import asyncio
import json
import os
import time
from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Optional

import httpx
import psycopg
from loguru import logger
from fastapi import APIRouter, WebSocketDisconnect, WebSocket, Query, HTTPException

from workflows.core import MESSAGE_TYPE_ERROR, MESSAGE_TYPE_END
from workflows.utils import parse_input
from workflows.models import AgentRequestModel
from workflows.core.settings import config_settings
from workflows.service import message_generator


router = APIRouter(prefix="/workflows", tags=["workflows", "agents"])


@router.websocket("/stream")
async def agent_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info(f"Step 1: {datetime.now()} socket accepted")

    reader_task = None
    heartbeat_task = None
    message_queue = None

    try:
        agent_graph = websocket.app.state.agent_graph

        if not agent_graph:
            logger.error("Agent graph is not available on app.state.")
            await websocket.send_json({"type": MESSAGE_TYPE_ERROR, "content_type": None, "message": "Agent not initialized."})
            await websocket.close()
            return

        first_message_json = None
        while first_message_json is None:
            first_message_text = await websocket.receive_text()
            try:
                candidate = json.loads(first_message_text)
            except json.JSONDecodeError:
                logger.error(f"First message is not valid JSON (length={len(first_message_text)})")
                await websocket.send_json({"type": MESSAGE_TYPE_ERROR, "content_type": None, "message": "Invalid message format."})
                await websocket.close()
                return
            if isinstance(candidate, dict) and candidate.get("type") in ("pong", "cancel"):
                continue
            first_message_json = candidate

        first_message_data = AgentRequestModel(**first_message_json)

        if first_message_data.graph_initialization:
            await websocket.send_text(json.dumps({
                "type": "ping",
                "message": "Graph initialized successfully"
            }))
            actual_message_text = await websocket.receive_text()
            try:
                first_message_json = json.loads(actual_message_text)
            except json.JSONDecodeError:
                logger.error(f"Message after graph init is not valid JSON")
                await websocket.send_json({"type": MESSAGE_TYPE_ERROR, "content_type": None, "message": "Invalid message format."})
                await websocket.close()
                return
            user_input = AgentRequestModel(**first_message_json)
        else:
            user_input = first_message_data

        cancel_event: asyncio.Event = asyncio.Event()
        message_queue: asyncio.Queue = asyncio.Queue()
        reader_closed = asyncio.Event()

        async def single_reader(ws: WebSocket):
            try:
                while True:
                    raw = await ws.receive_text()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning(f"[INPUT] Invalid JSON received (length={len(raw)})")
                        continue

                    if isinstance(msg, dict) and msg.get("type") == "cancel":
                        cancel_event.set()
                        logger.info("[CANCEL] Cancel signal received")
                    elif isinstance(msg, dict) and msg.get("type") == "pong":
                        continue
                    else:
                        await message_queue.put(msg)
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                reader_closed.set()
                cancel_event.set()

        async def heartbeat(ws: WebSocket):
            try:
                while not reader_closed.is_set():
                    await asyncio.sleep(config_settings.HEARTBEAT_INTERVAL_SECONDS)
                    await ws.send_json({"type": "ping"})
            except Exception:
                pass

        reader_task = asyncio.create_task(single_reader(websocket))
        heartbeat_task = asyncio.create_task(heartbeat(websocket))

        message_timestamps: deque = deque(maxlen=config_settings.RATE_LIMIT_MAX_MESSAGES)
        first_iteration = True
        last_message_time = time.time()

        while True:
            start_time = time.time()
            cancel_event.clear()

            if first_iteration:
                first_iteration = False
            else:
                logger.debug(f"Step 2: {datetime.now()} waiting for next user input")
                try:
                    parsed = await asyncio.wait_for(message_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if reader_closed.is_set():
                        break
                    if time.time() - last_message_time > config_settings.WS_IDLE_TIMEOUT_SECONDS:
                        logger.info(f"[IDLE] Connection idle for {config_settings.WS_IDLE_TIMEOUT_SECONDS}s — closing")
                        break
                    continue
                last_message_time = time.time()
                user_input = AgentRequestModel(**parsed)

            now = time.time()
            message_timestamps.append(now)
            if len(message_timestamps) >= config_settings.RATE_LIMIT_MAX_MESSAGES and (now - message_timestamps[0]) < config_settings.RATE_LIMIT_WINDOW_SECONDS:
                logger.warning(f"[RATE_LIMIT] Connection rate limited: {config_settings.RATE_LIMIT_MAX_MESSAGES} messages in {now - message_timestamps[0]:.1f}s")
                await websocket.send_json({
                    "type": MESSAGE_TYPE_ERROR,
                    "content_type": None,
                    "message": "Too many messages. Please wait a moment before sending more."
                })
                continue

            logger.info(f"Step 3: {datetime.now()} processing request")

            if user_input.graph_initialization:
                logger.info("Graph initialization request received, graph already initialized, sending ping.")
                await websocket.send_text(json.dumps({
                    "type": "ping",
                    "message": "Graph initialized successfully"
                }))
                continue

            kwargs, run_id = await parse_input(None, user_input, websocket)
            kwargs['config']['configurable']['websocket'] = websocket

            question = getattr(user_input, "question", "")
            if question and question.strip():
                await websocket.send_json({
                    "type": "stream",
                    "content_type": "processing",
                    "message": {
                        "status": "started",
                        "run_id": str(run_id),
                        "question": question[:config_settings.QUESTION_PREVIEW_LENGTH]
                    }
                })

            try:
                await message_generator(
                    user_input,
                    websocket,
                    run_id,
                    kwargs,
                    agent_graph,
                    cancel_event=cancel_event,
                    message_queue=message_queue,
                )
            except Exception as msg_gen_error:
                logger.error(f"Error in message_generator: {msg_gen_error}", exc_info=True)
                try:
                    await websocket.send_json({
                        "type": MESSAGE_TYPE_ERROR,
                        "content_type": None,
                        "message": "An error occurred while processing your request. Please try again."
                    })
                except RuntimeError as ws_err:
                    logger.warning(f"Could not send error message (WebSocket may be closed): {ws_err}")

            end_time = time.time()
            logger.info(f"Request execution time: {end_time - start_time:.2f} seconds")

            try:
                await websocket.send_text(json.dumps({
                    "type": MESSAGE_TYPE_END,
                    "content_type": None,
                    "message": ""
                }))
            except RuntimeError as ws_err:
                logger.warning(f"Could not send end message (WebSocket may be closed): {ws_err}")

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")

    except RuntimeError as e:
        if "not connected" in str(e).lower() or "closed" in str(e).lower():
            logger.info(f"WebSocket connection closed: {e}")
        else:
            logger.exception(f"RuntimeError in WebSocket processing loop: {e}")

    except Exception as e:
        logger.exception(f"Error in WebSocket processing loop: {e}")
        try:
            await websocket.send_json({
                "type": MESSAGE_TYPE_ERROR,
                "content_type": None,
                "message": "An error occurred while processing your request. Please try again."
            })
        except Exception:
            pass

    finally:
        if reader_task:
            reader_task.cancel()
            try:
                await reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass

        if message_queue:
            while not message_queue.empty():
                try:
                    message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        logger.info("Exiting WebSocket processing loop — all resources released.")


# ── Admin REST endpoint ────────────────────────────────────────────────────────
# Uses direct psycopg connection — completely separate from the master agent
# LLM pipeline. Queries refund_requests JOIN customers JOIN orders directly.

@router.get("/refunds/decisions")
async def get_refund_decisions(limit: int = Query(100, ge=1, le=500)):
    """Return all refund decisions for the admin dashboard.
    Visible to all logged-in users — no role gate (per assessment requirement).
    Uses direct psycopg query — does NOT go through the LLM/execute_query_from_text pipeline.
    """
    host = os.environ.get("POSTGRES_HOST", "")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    db = os.environ.get("POSTGRES_DATABASE", "test")
    sslmode = os.environ.get("POSTGRES_SSLMODE", "require")

    if not host or not user:
        raise HTTPException(status_code=503, detail="Database credentials not configured")

    sql = """
        SELECT
            rr.id,
            rr.decision,
            rr.denial_reason,
            rr.agent_reasoning,
            rr.amount_requested,
            rr.amount_approved,
            rr.requested_at,
            rr.decided_at,
            rr.reason AS refund_reason,
            c.name  AS customer_name,
            c.email AS customer_email,
            c.account_tier,
            o.order_number,
            o.product_name,
            o.amount      AS order_amount,
            o.status      AS order_status
        FROM refund_requests rr
        JOIN customers c ON c.id = rr.customer_id
        JOIN orders    o ON o.id = rr.order_id
        ORDER BY rr.requested_at DESC
        LIMIT %s
    """

    try:
        conn = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: psycopg.connect(
                f"host={host} port={port} dbname={db} user={user} password={password} sslmode={sslmode}"
            ),
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                cols = [desc.name for desc in cur.description]
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Admin decisions query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch refund decisions")

    decisions = []
    for row in rows:
        d = dict(zip(cols, row))
        for k in ("amount_requested", "amount_approved", "order_amount"):
            if isinstance(d.get(k), Decimal):
                d[k] = float(d[k])
        for k in ("requested_at", "decided_at"):
            if isinstance(d.get(k), datetime):
                d[k] = d[k].isoformat()
        decisions.append(d)

    return {"decisions": decisions, "count": len(decisions)}


@router.get("/traces")
async def get_langsmith_traces(limit: int = Query(20, ge=1, le=100)):
    """Proxy LangSmith traces for the admin dashboard.
    Calls LangSmith API server-side — keeps API key out of the browser.
    Returns recent runs from the WorkPodd project with name, type, status,
    latency, token counts, and a direct link to the trace in LangSmith.
    """
    api_key = config_settings.LANGSMITH_API_KEY
    endpoint = config_settings.LANGSMITH_ENDPOINT
    project = config_settings.LANGSMITH_PROJECT

    if not api_key:
        raise HTTPException(status_code=503, detail="LangSmith not configured")

    headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15) as client:
        # Step 1 — resolve session id from project name
        r = await client.get(
            f"{endpoint}/api/v1/sessions",
            headers=headers,
            params={"name": project, "limit": 1},
        )
        if not r.is_success or not r.json():
            raise HTTPException(status_code=503, detail="LangSmith project not found")
        session_id = r.json()[0]["id"]

        # Step 2 — fetch recent top-level runs (parent_run_id is None = root runs)
        r2 = await client.post(
            f"{endpoint}/api/v1/runs/query",
            headers=headers,
            json={
                "session": [session_id],
                "limit": limit,
                "order": "desc",
                "is_root": True,
            },
        )
        if not r2.is_success:
            raise HTTPException(status_code=503, detail="Failed to fetch LangSmith traces")

        raw = r2.json()
        runs = raw.get("runs", raw) if isinstance(raw, dict) else raw

        # Step 3 — fetch child runs for each root trace to show reasoning steps
        child_runs_by_parent: dict[str, list] = {}
        root_ids = [r.get("id") or r.get("trace_id", "") for r in runs if r.get("id") or r.get("trace_id")]
        if root_ids:
            r3 = await client.post(
                f"{endpoint}/api/v1/runs/query",
                headers=headers,
                json={
                    "trace": root_ids,
                    "limit": limit * 20,
                    "order": "asc",
                    "is_root": False,
                },
            )
            if r3.is_success:
                child_raw = r3.json()
                child_list = child_raw.get("runs", child_raw) if isinstance(child_raw, dict) else child_raw
                for child in child_list:
                    trace_id = child.get("trace_id", "")
                    if trace_id not in child_runs_by_parent:
                        child_runs_by_parent[trace_id] = []
                    child_runs_by_parent[trace_id].append(child)

    traces = []
    base_ui = "https://aws.smith.langchain.com"
    org_path = "/o/70092e4d-eee7-4ed4-b6e7-9ce5d3a51560"

    def _format_content(obj) -> str:
        if obj is None:
            return ""
        if isinstance(obj, str):
            return obj[:3000]
        try:
            return json.dumps(obj, indent=2, default=str)[:3000]
        except Exception:
            return str(obj)[:3000]

    for run in runs:
        run_id = run.get("id") or run.get("trace_id", "")
        app_path = run.get("app_path", "")
        trace_url = f"{base_ui}{app_path}" if app_path else f"{base_ui}{org_path}/projects/p/{session_id}/r/{run_id}"

        latency_s = None
        if run.get("start_time") and run.get("end_time"):
            try:
                s = datetime.fromisoformat(run["start_time"].replace("Z", "+00:00"))
                e = datetime.fromisoformat(run["end_time"].replace("Z", "+00:00"))
                latency_s = round((e - s).total_seconds(), 2)
            except Exception:
                pass

        children = child_runs_by_parent.get(run_id, [])
        steps = []
        for child in children:
            step_latency = None
            if child.get("start_time") and child.get("end_time"):
                try:
                    cs = datetime.fromisoformat(child["start_time"].replace("Z", "+00:00"))
                    ce = datetime.fromisoformat(child["end_time"].replace("Z", "+00:00"))
                    step_latency = round((ce - cs).total_seconds(), 2)
                except Exception:
                    pass
            steps.append({
                "name": child.get("name", ""),
                "run_type": child.get("run_type", ""),
                "status": child.get("status", ""),
                "latency_s": step_latency,
                "input": _format_content(child.get("inputs")),
                "output": _format_content(child.get("outputs")),
                "error": child.get("error"),
            })

        traces.append({
            "id": run_id,
            "name": run.get("name", ""),
            "run_type": run.get("run_type", ""),
            "status": run.get("status", ""),
            "start_time": run.get("start_time", ""),
            "end_time": run.get("end_time", ""),
            "latency_s": latency_s,
            "total_tokens": run.get("total_tokens"),
            "prompt_tokens": run.get("prompt_tokens"),
            "completion_tokens": run.get("completion_tokens"),
            "total_cost": run.get("total_cost"),
            "error": run.get("error"),
            "inputs": _format_content(run.get("inputs")),
            "outputs": _format_content(run.get("outputs")),
            "trace_url": trace_url,
            "steps": steps,
        })

    return {"traces": traces, "count": len(traces), "project": project}

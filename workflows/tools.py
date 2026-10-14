import time
import json
import asyncio
from decimal import Decimal
from datetime import datetime, date

from loguru import logger
from typing import Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool, ToolException

from workflows.core.settings import config_settings
from workflows.core import db_connector, StreamingLLMCallbackHandler
from workflows.core.db.client import _get_db_thread_pool
from workflows.core.db.prompts import build_sql_prompt
from workflows.core.vector_db.retrieval import get_relevant_documents


def _serialise(rows: list, max_rows: int) -> tuple[list, bool]:
    truncated = len(rows) > max_rows
    raw = rows[:max_rows] if truncated else rows
    data = [
        {
            k: v.isoformat() if isinstance(v, (datetime, date))
            else float(v) if isinstance(v, Decimal)
            else v
            for k, v in r.items()
        } if isinstance(r, dict) else r
        for r in raw
    ]
    return data, truncated


async def search_knowledge_base(
    query: str,
    top_k: int = 10,
    config: RunnableConfig = None,
) -> dict:
    """
    Search the knowledge base for relevant policy documents and guidelines.

    Use this tool to retrieve refund policy rules, return window information,
    eligibility criteria, and any other policy documentation needed to evaluate
    a refund request. Always call this before making approval/denial decisions.

    Args:
        query: Natural language search query describing what policy information is needed.
        top_k: Number of relevant documents to retrieve (default: 10).
    """
    section = "search_knowledge_base"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not query or not query.strip():
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": "No query provided for knowledge base search.",
                        "data": None,
                        "metadata": {
                            "error": "empty query",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        resolved_top_k = max(1, min(top_k, 50))
        index_name = config_settings.POLICY_OPENSEARCH_INDEX_NAME

        result = await asyncio.wait_for(
            get_relevant_documents(
                request_id=id(query),
                query=query.strip(),
                top_k=resolved_top_k,
                index_name=index_name,
                namespace=config_settings.POLICY_OPENSEARCH_NAMESPACE,
            ),
            timeout=30.0
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        if result.get("error"):
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": f"Knowledge base error: {result['error']}",
                        "data": None,
                        "metadata": {
                            "error": result["error"],
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": execution_time_ms,
                            "namespace": namespace,
                            "thread_id": thread_id,
                        }
                    },
                    default=str,
                )
            )

        doc_chunks = result.get("document_chunks", []) or []

        if not doc_chunks:
            return {
                "success": True,
                "message": "No relevant policy documents found for this query.",
                "data": [],
                "metadata": {
                    "section": section,
                    "row_count": 0,
                    "execution_time_ms": execution_time_ms,
                    "namespace": namespace,
                    "thread_id": thread_id,
                },
            }

        data = []
        for doc in doc_chunks:
            text = doc.page_content if hasattr(doc, 'page_content') else str(doc)
            metadata = getattr(doc, 'metadata', {}) or {}
            data.append({
                "content": text,
                "rule_key": metadata.get("rule_key", ""),
                "source": metadata.get("source", ""),
                "score": metadata.get("score"),
            })

        return {
            "success": True,
            "message": f"Retrieved {len(data)} relevant policy documents",
            "data": data,
            "metadata": {
                "section": section,
                "row_count": len(data),
                "execution_time_ms": execution_time_ms,
                "namespace": namespace,
                "thread_id": thread_id,
            },
        }

    except asyncio.TimeoutError:
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": "Knowledge base search timed out.",
                    "data": None,
                    "metadata": {
                        "error": "timeout",
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )
    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": f"Unexpected error: {str(e)}",
                    "data": None,
                    "metadata": {
                        "error": str(e),
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )



async def lookup_customer(
    identifier: str,
    config: RunnableConfig = None,
) -> dict:
    """
    Look up a customer profile by email address or numeric customer ID.

    Call this first for every refund request. Returns account tier
    (standard/premium/vip), flag status, and order history summary.

    Args:
        identifier: Customer email address (e.g. alice.johnson@shopmail.com) or numeric ID (e.g. 1).
    """
    section = "lookup_customer"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": "Database connection not available",
                        "data": None,
                        "metadata": {
                            "error": "no db",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        ident = identifier.strip()
        if not ident:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": "Customer identifier is required.",
                        "data": None,
                        "metadata": {
                            "error": "empty identifier",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        db_manager = db_connector.connection
        if ident.isdigit():
            prebuilt_section = "refund_lookup_customer_by_id"
            params = {
                "customer_id": str(int(ident)),
            }
        else:
            safe = ident.replace("'", "''")
            prebuilt_section = "refund_lookup_customer_by_email"
            params = {
                "customer_email": f"'{safe}'",
            }

        result = await db_manager.execute_prebuilt_sql_with_params(prebuilt_section, params)
        execution_time_ms = int((time.time() - start_time) * 1000)

        if result.success:
            rows = result.rows or []
            if not rows:
                raise ToolException(
                    json.dumps(
                        {
                            "success": False,
                            "message": f"No customer found for '{identifier}'. Verify the email address or ID.",
                            "data": None,
                            "metadata": {
                                "section": section,
                                "row_count": 0,
                                "execution_time_ms": execution_time_ms,
                                "namespace": namespace,
                                "thread_id": thread_id,
                            },
                        },
                        default=str,
                    )
                )
            data, truncated = _serialise(rows, config_settings.TOOL_RESPONSE_MAX_ROWS)
            return {
                "success": True,
                "message": "Customer found",
                "data": data,
                "metadata": {
                    "section": section,
                    "row_count": len(rows),
                    "truncated": truncated,
                    "execution_time_ms": execution_time_ms,
                    "namespace": namespace,
                    "thread_id": thread_id,
                },
            }

        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": result.message or "Query failed",
                    "data": None,
                    "metadata": {
                        "error": result.message,
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": execution_time_ms,
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": f"Unexpected error: {str(e)}",
                    "data": None,
                    "metadata": {
                        "error": str(e),
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )


async def lookup_order(
    identifier: str,
    config: RunnableConfig = None,
) -> dict:
    """
    Look up an order by order number or numeric order ID.

    Returns product name, category, amount, delivery date, order status, digital flag,
    and customer_id. Always call this before evaluating refund eligibility.

    Args:
        identifier: Order number (e.g. ORD-2026-10001) or numeric order ID (e.g. 1).
    """
    section = "lookup_order"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": "Database connection not available",
                        "data": None,
                        "metadata": {
                            "error": "no db",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        ident = identifier.strip()
        db_manager = db_connector.connection
        if ident.isdigit():
            prebuilt_section = "refund_lookup_order_by_id"
            params = {
                "order_id": str(int(ident)),
            }
        else:
            safe = ident.upper().replace("'", "''")
            prebuilt_section = "refund_lookup_order_by_number"
            params = {
                "order_number": f"'{safe}'",
            }

        result = await db_manager.execute_prebuilt_sql_with_params(prebuilt_section, params)
        execution_time_ms = int((time.time() - start_time) * 1000)

        if result.success:
            rows = result.rows or []
            if not rows:
                raise ToolException(
                    json.dumps(
                        {
                            "success": False,
                            "message": f"No order found for '{identifier}'. Verify the order number.",
                            "data": None,
                            "metadata": {
                                "section": section,
                                "row_count": 0,
                                "execution_time_ms": execution_time_ms,
                                "namespace": namespace,
                                "thread_id": thread_id,
                            },
                        },
                        default=str,
                    )
                )
            data, _ = _serialise(rows, config_settings.TOOL_RESPONSE_MAX_ROWS)
            return {
                "success": True,
                "message": "Order found",
                "data": data,
                "metadata": {
                    "section": section,
                    "row_count": len(rows),
                    "execution_time_ms": execution_time_ms,
                    "namespace": namespace,
                    "thread_id": thread_id,
                },
            }

        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": result.message or "Query failed",
                    "data": None,
                    "metadata": {
                        "error": result.message,
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": execution_time_ms,
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": f"Unexpected error: {str(e)}",
                    "data": None,
                    "metadata": {
                        "error": str(e),
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )


async def get_customer_orders(
    customer_id: int,
    config: RunnableConfig = None,
) -> dict:
    """Retrieve all recent orders for a customer by their numeric customer ID.

    Use when the customer has not specified a particular order number and you
    need to identify which order they are referring to.

    Args:
        customer_id: Numeric customer ID from the customers table.
    """
    section = "get_customer_orders"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": "Database connection not available",
                        "data": None,
                        "metadata": {
                            "error": "no db",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        result = await db_connector.connection.execute_prebuilt_sql_with_params(
            "refund_get_customer_orders",
            {
                "customer_id": str(int(customer_id)),
            },
        )
        execution_time_ms = int((time.time() - start_time) * 1000)

        if result.success:
            rows = result.rows or []
            max_rows = config_settings.TOOL_RESPONSE_MAX_ROWS
            data, truncated = _serialise(rows, max_rows)
            return {
                "success": True,
                "message": f"Returned {len(rows)} orders",
                "data": data,
                "metadata": {
                    "section": section,
                    "row_count": len(rows),
                    "truncated": truncated,
                    "execution_time_ms": execution_time_ms,
                    "namespace": namespace,
                    "thread_id": thread_id,
                },
            }

        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": result.message or "Query failed",
                    "data": None,
                    "metadata": {
                        "error": result.message,
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": execution_time_ms,
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": f"Unexpected error: {str(e)}",
                    "data": None,
                    "metadata": {
                        "error": str(e),
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )


async def check_refund_history(
    order_id: int,
    config: RunnableConfig = None,
) -> dict:
    """Check whether a refund request has already been made for this order.

    Always call this before approving or denying. Returns prior request count,
    prior approved count, and the decision history.

    Args:
        order_id: Numeric order ID from the orders table.
    """
    section = "check_refund_history"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": "Database connection not available",
                        "data": None,
                        "metadata": {
                            "error": "no db",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        result = await db_connector.connection.execute_prebuilt_sql_with_params(
            "refund_check_history",
            {
                "order_id": str(int(order_id)),
            },
        )
        execution_time_ms = int((time.time() - start_time) * 1000)

        if result.success:
            rows = result.rows or []
            max_rows = config_settings.TOOL_RESPONSE_MAX_ROWS
            data, _ = _serialise(rows, max_rows)
            prior_approved = [r for r in data if r.get("decision") == "approved"]
            return {
                "success": True,
                "message": f"Returned {len(rows)} prior refund request(s)",
                "data": data,
                "metadata": {
                    "section": section,
                    "prior_requests": len(rows),
                    "prior_approved_count": len(prior_approved),
                    "row_count": len(rows),
                    "execution_time_ms": execution_time_ms,
                    "namespace": namespace,
                    "thread_id": thread_id,
                },
            }

        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": result.message or "Query failed",
                    "data": None,
                    "metadata": {
                        "error": result.message,
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": execution_time_ms,
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": f"Unexpected error: {str(e)}",
                    "data": None,
                    "metadata": {
                        "error": str(e),
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )




async def approve_refund(
    customer_id: int,
    order_id: int,
    refund_reason: str,
    agent_reasoning: str,
    amount: Optional[float] = None,
    config: RunnableConfig = None,
) -> dict:
    """Record an approved refund decision in the database.

    Only call this after completing ALL mandatory workflow steps:
    1. lookup_customer — confirmed customer and account tier
    2. lookup_order — confirmed delivery date, amount, status, is_digital, customer_id ownership
    3. check_refund_history — confirmed no prior approved refund on this order
    4. search_knowledge_base — loaded and all applicable rules evaluated
    5. Eligibility confirmed under a specific policy rule

    Args:
        customer_id: Numeric customer ID.
        order_id: Numeric order ID.
        refund_reason: The customer's stated reason for the refund request.
        agent_reasoning: Complete step-by-step reasoning — every rule checked, facts applied, final determination.
        amount: Refund amount in USD. If None, the full order amount is used.
    """
    section = "approve_refund"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": "Database connection not available",
                        "data": None,
                        "metadata": {
                            "error": "no db",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        # Fetch order to get amount and verify ownership (uses prebuilt validated SQL)
        order_result = await db_connector.connection.execute_prebuilt_sql_with_params(
            "refund_lookup_order_by_id",
            {
                "order_id": str(int(order_id)),
            },
        )
        if not order_result.success or not order_result.rows:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": f"Order ID {order_id} not found.",
                        "data": None,
                        "metadata": {
                            "error": "order not found",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        order = order_result.rows[0]
        order_amount = float(order.get("amount", 0))
        order_number = order.get("order_number", str(order_id))

        # Guard: ownership
        if int(order.get("customer_id", -1)) != int(customer_id):
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": f"Order {order_number} does not belong to customer {customer_id}.",
                        "data": None,
                        "metadata": {
                            "error": "ownership mismatch",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        # Guard: amount cannot exceed order amount
        approved_amount = amount if amount is not None else order_amount
        if approved_amount > order_amount:
            approved_amount = order_amount
            logger.warning(f"approve_refund: requested {amount} exceeds order amount {order_amount}, capped")
        if approved_amount <= 0:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": "Approved amount must be greater than zero.",
                        "data": None,
                        "metadata": {
                            "error": "invalid amount",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        # Guard: block duplicate approval
        dup_result = await asyncio.get_running_loop().run_in_executor(
            _get_db_thread_pool(), db_connector.connection.execute,
            f"SELECT id, decision FROM refund_requests WHERE order_id = {int(order_id)} AND decision = 'approved';"
        )
        if dup_result.success and dup_result.rows:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": f"A refund has already been approved for order {order_number}.",
                        "data": None,
                        "metadata": {
                            "error": "duplicate approval",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        now_str = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        reason_safe = refund_reason.replace("'", "''")
        reasoning_safe = agent_reasoning.replace("'", "''")

        insert_sql = (
            f"INSERT INTO refund_requests "
            f"(customer_id, order_id, reason, decision, denial_reason, agent_reasoning, "
            f"amount_requested, amount_approved, requested_at, decided_at) "
            f"VALUES ({int(customer_id)}, {int(order_id)}, '{reason_safe}', 'approved', NULL, "
            f"'{reasoning_safe}', {order_amount}, {approved_amount}, "
            f"'{now_str}', '{now_str}') RETURNING id;"
        )

        insert_result = await asyncio.get_running_loop().run_in_executor(
            _get_db_thread_pool(), db_connector.connection.execute_write, insert_sql
        )
        execution_time_ms = int((time.time() - start_time) * 1000)

        if insert_result.success:
            rows = insert_result.rows or []
            request_id = rows[0].get("id", 0) if rows else 0
            logger.info(f"Refund APPROVED: request_id={request_id} order={order_number} amount={approved_amount}")
            return {
                "success": True,
                "message": (f"Refund of ${approved_amount:.2f} approved for order {order_number}. "
                            "Funds will be returned to the original payment method within 5-7 business days."),
                "data": [
                    {
                        "refund_request_id": request_id,
                        "decision": "approved",
                        "amount_approved": approved_amount,
                    },
                ],
                "metadata": {
                    "section": section,
                    "row_count": 1,
                    "execution_time_ms": execution_time_ms,
                    "namespace": namespace,
                    "thread_id": thread_id,
                },
            }

        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": insert_result.message or "Insert failed",
                    "data": None,
                    "metadata": {
                        "error": insert_result.message,
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": execution_time_ms,
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": f"Unexpected error: {str(e)}",
                    "data": None,
                    "metadata": {
                        "error": str(e),
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )


async def deny_refund(
    customer_id: int,
    order_id: int,
    refund_reason: str,
    denial_reason: str,
    agent_reasoning: str,
    config: RunnableConfig = None,
) -> dict:
    """Record a denied refund decision in the database.

    Only call this after verifying through policy rules that the request does not qualify.
    The denial_reason is shown to the customer — cite the specific policy rule name.

    Args:
        customer_id: Numeric customer ID.
        order_id: Numeric order ID.
        refund_reason: The customer's stated reason for the refund request.
        denial_reason: Customer-facing explanation citing the specific policy rule name.
        agent_reasoning: Complete internal reasoning — every rule checked and why it fails.
    """
    section = "deny_refund"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": "Database connection not available",
                        "data": None,
                        "metadata": {
                            "error": "no db",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        order_result = await db_connector.connection.execute_prebuilt_sql_with_params(
            "refund_lookup_order_by_id",
            {
                "order_id": str(int(order_id)),
            },
        )
        if not order_result.success or not order_result.rows:
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": f"Order ID {order_id} not found.",
                        "data": None,
                        "metadata": {
                            "error": "order not found",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        order = order_result.rows[0]
        order_amount = float(order.get("amount", 0))
        order_number = order.get("order_number", str(order_id))

        # Guard: ownership
        if int(order.get("customer_id", -1)) != int(customer_id):
            raise ToolException(
                json.dumps(
                    {
                        "success": False,
                        "message": f"Order {order_number} does not belong to customer {customer_id}.",
                        "data": None,
                        "metadata": {
                            "error": "ownership mismatch",
                            "section": section,
                            "row_count": 0,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "namespace": namespace,
                            "thread_id": thread_id,
                        },
                    },
                    default=str,
                )
            )

        now_str = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        reason_safe = refund_reason.replace("'", "''")
        denial_safe = denial_reason.replace("'", "''")
        reasoning_safe = agent_reasoning.replace("'", "''")

        insert_sql = (
            f"INSERT INTO refund_requests "
            f"(customer_id, order_id, reason, decision, denial_reason, agent_reasoning, "
            f"amount_requested, amount_approved, requested_at, decided_at) "
            f"VALUES ({int(customer_id)}, {int(order_id)}, '{reason_safe}', 'denied', "
            f"'{denial_safe}', '{reasoning_safe}', {order_amount}, 0, "
            f"'{now_str}', '{now_str}') RETURNING id;"
        )

        insert_result = await asyncio.get_running_loop().run_in_executor(
            _get_db_thread_pool(), db_connector.connection.execute_write, insert_sql
        )
        execution_time_ms = int((time.time() - start_time) * 1000)

        if insert_result.success:
            rows = insert_result.rows or []
            request_id = rows[0].get("id", 0) if rows else 0
            logger.info(f"Refund DENIED: request_id={request_id} order={order_number} reason={denial_reason[:80]}")
            return {
                "success": True,
                "message": denial_reason,
                "data": [
                    {
                        "refund_request_id": request_id,
                        "decision": "denied",
                        "denial_reason": denial_reason,
                    },
                ],
                "metadata": {
                    "section": section,
                    "row_count": 1,
                    "execution_time_ms": execution_time_ms,
                    "namespace": namespace,
                    "thread_id": thread_id,
                },
            }

        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": insert_result.message or "Insert failed",
                    "data": None,
                    "metadata": {
                        "error": insert_result.message,
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": execution_time_ms,
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": f"Unexpected error: {str(e)}",
                    "data": None,
                    "metadata": {
                        "error": str(e),
                        "section": section,
                        "row_count": 0,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )

async def text_to_sql(
        query: str,
        config: RunnableConfig = None
) -> dict:
    """Query the ecommerce returns database for analytics questions not covered by the refund workflow tools.

    Use this tool when the user asks quantitative questions about return trends, product categories,
    return rates, customer tiers, payment methods, shipping methods, return costs, or any aggregation
    over the ecommerce_returns dataset. Do NOT use this for individual customer refund decisions —
    use lookup_customer / lookup_order / approve_refund / deny_refund for those.

    Pass the user's question as-is. Do not add date filters the user did not mention.
    Do not pre-compute or guess values — let the database compute all aggregations.

    Args:
        query: The user's natural language analytics question. Pass it as-is without rephrasing or adding filters the user did not mention.
    """
    start_time = time.time()

    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    def raise_tool_error(error_msg, sql_query="", execution_time_ms=0):
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": error_msg,
                    "data": None,
                    "metadata": {
                        "error": error_msg,
                        "sql_query": sql_query,
                        "row_count": 0,
                        "execution_time_ms": execution_time_ms,
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )

    websocket = configurable.get("websocket")
    tool_key = configurable.get("current_tool_key", "0")
    tool_display_name = "Database Query Agent"

    try:
        logger.info(f"Text-to-SQL Tool started: query={query[:80]}, namespace={namespace}, thread_id={thread_id}")

        if not query or not query.strip():
            raise_tool_error("No query provided. Please pass the user's natural language question as the 'query' argument.")

        if not db_connector or not db_connector.status or not db_connector.connection:
            raise_tool_error("Database connection not available. Cannot execute queries at this time.")

        db_manager = db_connector.connection

        if not db_manager.is_ready():
            missing = [k for k, v in [("schema", db_manager.schema), ("schema description", db_manager.schema_prompt), ("few-shot examples", db_manager.few_shot_prompt)] if not v]
            raise_tool_error(f"Database pipeline not ready — missing: {', '.join(missing)}.")

        prompt_template = build_sql_prompt(user_context="")
        temperature = getattr(config_settings, 'TEXT_TO_SQL_BEDROCK_TEMPERATURE', 0.0)

        progress_callback = None
        if websocket or config:
            progress_callback = StreamingLLMCallbackHandler(
                websocket_internal=websocket,
                tool_key=tool_key,
                tool_name=tool_display_name,
                user_query=query,
                config=config,
                token_type='sql_generation'
            )

        try:
            result = await asyncio.wait_for(
                db_manager.execute_query_from_text(
                    user_query=query,
                    prompt_template=prompt_template,
                    temperature=temperature,
                    callbacks=[progress_callback] if progress_callback else None
                ),
                timeout=config_settings.TEXT_TO_SQL_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            raise_tool_error(f"Query timed out after {int(config_settings.TEXT_TO_SQL_TIMEOUT_SECONDS)}s — try a simpler question.", execution_time_ms=int((time.time() - start_time) * 1000))

        if result.success:
            execution_time_ms = int((time.time() - start_time) * 1000)
            rows = result.rows or []
            row_count = len(rows)
            max_rows = config_settings.TOOL_RESPONSE_MAX_ROWS
            truncated = row_count > max_rows
            raw = rows[:max_rows] if truncated else rows
            data = [
                {
                    k: v.isoformat() if isinstance(v, (datetime, date))
                    else float(v) if isinstance(v, Decimal)
                    else v
                    for k, v in r.items()
                } if isinstance(r, dict) else r
                for r in raw
            ]

            generated_sql = result.metadata.get("generated_sql", "")

            return {
                "success": True,
                "message": f"Query executed successfully, returned {row_count} rows",
                "data": data,
                "metadata": {
                    "sql_query": generated_sql,
                    "row_count": row_count,
                    "execution_time_ms": execution_time_ms,
                    "truncated": truncated,
                    "namespace": namespace,
                    "thread_id": thread_id,
                },
            }

        first_error_msg = result.message or "Query execution failed"
        first_generated_sql = result.metadata.get("generated_sql", "")
        logger.warning(f"First attempt failed: {first_error_msg}. Retrying...")

        retry_prompt = build_sql_prompt(user_context="", previous_sql=first_generated_sql, error_message=first_error_msg)

        try:
            retry_result = await asyncio.wait_for(
                db_manager.execute_query_from_text(
                    user_query=query,
                    prompt_template=retry_prompt,
                    temperature=temperature
                ),
                timeout=config_settings.TEXT_TO_SQL_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            raise_tool_error(
                f"Retry also timed out after {int(config_settings.TEXT_TO_SQL_TIMEOUT_SECONDS)}s.",
                sql_query=first_generated_sql,
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

        execution_time_ms = int((time.time() - start_time) * 1000)

        if retry_result.success:
            rows = retry_result.rows or []
            row_count = len(rows)
            max_rows = config_settings.TOOL_RESPONSE_MAX_ROWS
            truncated = row_count > max_rows
            raw = rows[:max_rows] if truncated else rows
            data = [
                {
                    k: v.isoformat() if isinstance(v, (datetime, date))
                    else float(v) if isinstance(v, Decimal)
                    else v
                    for k, v in r.items()
                } if isinstance(r, dict) else r
                for r in raw
            ]
            return {
                "success": True,
                "message": f"Query executed successfully after retry, returned {row_count} rows",
                "data": data,
                "metadata": {
                    "sql_query": retry_result.metadata.get("generated_sql", ""),
                    "row_count": row_count,
                    "execution_time_ms": execution_time_ms,
                    "truncated": truncated,
                    "namespace": namespace,
                    "thread_id": thread_id,
                },
            }

        retry_error_msg = retry_result.message or "Query execution failed after retry"
        raise ToolException(
            json.dumps(
                {
                    "success": False,
                    "message": retry_error_msg,
                    "data": None,
                    "metadata": {
                        "error": retry_error_msg,
                        "sql_query": retry_result.metadata.get("generated_sql", ""),
                        "row_count": 0,
                        "execution_time_ms": execution_time_ms,
                        "namespace": namespace,
                        "thread_id": thread_id,
                    },
                },
                default=str,
            )
        )

    except ToolException:
        raise
    except asyncio.CancelledError:
        logger.warning("Text-to-SQL execution was cancelled")
        raise
    except Exception as e:
        logger.error(f"Error in text_to_sql: {str(e)}", exc_info=True)
        raise_tool_error(f"Unexpected execution error: {str(e)}", execution_time_ms=int((time.time() - start_time) * 1000))


async def check_order_status(
    order_number: str,
    config: RunnableConfig = None,
) -> dict:
    """Check the current delivery/shipping status of an order by order number.

    Use this when the customer asks about their order status, delivery tracking,
    or wants to know if their package has arrived. Does NOT require prior customer lookup.

    Args:
        order_number: Order number (e.g. ORD-2026-10001).
    """
    section = "check_order_status"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps({
                    "success": False, "message": "Database connection not available",
                    "data": None, "metadata": {"error": "no db", "section": section,
                    "row_count": 0, "execution_time_ms": int((time.time() - start_time) * 1000),
                    "namespace": namespace, "thread_id": thread_id}
                }, default=str)
            )

        safe = order_number.strip().upper().replace("'", "''")
        result = await db_connector.connection.execute_prebuilt_sql_with_params(
            "refund_check_order_status",
            {"order_number": f"'{safe}'"},
        )
        execution_time_ms = int((time.time() - start_time) * 1000)

        if result.success:
            rows = result.rows or []
            if not rows:
                raise ToolException(
                    json.dumps({
                        "success": False, "message": f"No order found for '{order_number}'.",
                        "data": None, "metadata": {"section": section, "row_count": 0,
                        "execution_time_ms": execution_time_ms, "namespace": namespace, "thread_id": thread_id}
                    }, default=str)
                )
            data, _ = _serialise(rows, config_settings.TOOL_RESPONSE_MAX_ROWS)
            return {
                "success": True, "message": "Order status retrieved",
                "data": data, "metadata": {"section": section, "row_count": len(rows),
                "execution_time_ms": execution_time_ms, "namespace": namespace, "thread_id": thread_id}
            }

        raise ToolException(
            json.dumps({
                "success": False, "message": result.message or "Query failed",
                "data": None, "metadata": {"error": result.message, "section": section,
                "row_count": 0, "execution_time_ms": execution_time_ms, "namespace": namespace, "thread_id": thread_id}
            }, default=str)
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps({
                "success": False, "message": f"Unexpected error: {str(e)}",
                "data": None, "metadata": {"error": str(e), "section": section,
                "row_count": 0, "execution_time_ms": int((time.time() - start_time) * 1000),
                "namespace": namespace, "thread_id": thread_id}
            }, default=str)
        )


async def escalate_to_human(
    customer_id: int,
    order_id: int,
    reason: str,
    escalation_summary: str,
    config: RunnableConfig = None,
) -> dict:
    """Escalate a complex case to a human support agent.

    Use this when:
    - Safety hazard reported and customer wants immediate help beyond refund
    - Customer is extremely dissatisfied and requests a supervisor
    - Case involves legal/compliance concerns
    - Technical issue that requires hands-on investigation
    - Any situation where automated processing cannot adequately resolve the customer's need

    This records the escalation in the system and informs the customer that a human agent will follow up.

    Args:
        customer_id: Numeric customer ID.
        order_id: Numeric order ID (0 if no specific order).
        reason: Brief category (safety, supervisor_request, compliance, technical, other).
        escalation_summary: Detailed context for the human agent including what was already attempted.
    """
    section = "escalate_to_human"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps({
                    "success": False, "message": "Database connection not available",
                    "data": None, "metadata": {"error": "no db", "section": section,
                    "row_count": 0, "execution_time_ms": int((time.time() - start_time) * 1000),
                    "namespace": namespace, "thread_id": thread_id}
                }, default=str)
            )

        now_str = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        reason_safe = reason.replace("'", "''")
        summary_safe = escalation_summary.replace("'", "''")

        insert_sql = (
            f"INSERT INTO refund_requests "
            f"(customer_id, order_id, reason, decision, denial_reason, agent_reasoning, "
            f"amount_requested, amount_approved, requested_at, decided_at) "
            f"VALUES ({int(customer_id)}, {int(order_id)}, 'ESCALATED: {reason_safe}', 'pending', "
            f"NULL, '{summary_safe}', 0, 0, '{now_str}', NULL) RETURNING id;"
        )

        insert_result = await asyncio.get_running_loop().run_in_executor(
            _get_db_thread_pool(), db_connector.connection.execute_write, insert_sql
        )
        execution_time_ms = int((time.time() - start_time) * 1000)

        if insert_result.success:
            rows = insert_result.rows or []
            request_id = rows[0].get("id", 0) if rows else 0
            logger.info(f"Case ESCALATED: request_id={request_id} customer={customer_id} reason={reason}")
            return {
                "success": True,
                "message": f"Case escalated to human support (reference #{request_id}). A support agent will follow up within 24 hours.",
                "data": [{"escalation_id": request_id, "status": "pending_human_review"}],
                "metadata": {"section": section, "row_count": 1, "execution_time_ms": execution_time_ms,
                "namespace": namespace, "thread_id": thread_id}
            }

        raise ToolException(
            json.dumps({
                "success": False, "message": insert_result.message or "Escalation failed",
                "data": None, "metadata": {"error": insert_result.message, "section": section,
                "row_count": 0, "execution_time_ms": execution_time_ms, "namespace": namespace, "thread_id": thread_id}
            }, default=str)
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps({
                "success": False, "message": f"Unexpected error: {str(e)}",
                "data": None, "metadata": {"error": str(e), "section": section,
                "row_count": 0, "execution_time_ms": int((time.time() - start_time) * 1000),
                "namespace": namespace, "thread_id": thread_id}
            }, default=str)
        )


async def get_refund_summary(
    customer_id: int,
    config: RunnableConfig = None,
) -> dict:
    """Get a customer's overall refund history summary — total requests, approved count, denied count, total amount refunded.

    Use this to understand a customer's refund pattern before making decisions, or when
    the customer asks about their refund history.

    Args:
        customer_id: Numeric customer ID.
    """
    section = "get_refund_summary"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps({
                    "success": False, "message": "Database connection not available",
                    "data": None, "metadata": {"error": "no db", "section": section,
                    "row_count": 0, "execution_time_ms": int((time.time() - start_time) * 1000),
                    "namespace": namespace, "thread_id": thread_id}
                }, default=str)
            )

        result = await db_connector.connection.execute_prebuilt_sql_with_params(
            "refund_get_summary",
            {"customer_id": str(int(customer_id))},
        )
        execution_time_ms = int((time.time() - start_time) * 1000)

        if result.success:
            rows = result.rows or []
            data, _ = _serialise(rows, config_settings.TOOL_RESPONSE_MAX_ROWS)
            return {
                "success": True, "message": "Refund summary retrieved",
                "data": data, "metadata": {"section": section, "row_count": len(rows),
                "execution_time_ms": execution_time_ms, "namespace": namespace, "thread_id": thread_id}
            }

        raise ToolException(
            json.dumps({
                "success": False, "message": result.message or "Query failed",
                "data": None, "metadata": {"error": result.message, "section": section,
                "row_count": 0, "execution_time_ms": execution_time_ms, "namespace": namespace, "thread_id": thread_id}
            }, default=str)
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps({
                "success": False, "message": f"Unexpected error: {str(e)}",
                "data": None, "metadata": {"error": str(e), "section": section,
                "row_count": 0, "execution_time_ms": int((time.time() - start_time) * 1000),
                "namespace": namespace, "thread_id": thread_id}
            }, default=str)
        )


async def update_order_status(
    order_id: int,
    new_status: str,
    config: RunnableConfig = None,
) -> dict:
    """Update an order's status after a refund decision.

    Call this after approve_refund to mark the order as 'returned'.
    Valid status transitions: delivered → returned.

    Args:
        order_id: Numeric order ID.
        new_status: New status value (must be one of: returned, cancelled).
    """
    section = "update_order_status"
    start_time = time.time()
    configurable = {}
    if config:
        if hasattr(config, "get"):
            configurable = config.get("configurable", {})
        elif isinstance(config, dict):
            configurable = config.get("configurable", {})
    namespace = configurable.get("namespace")
    thread_id = configurable.get("thread_id")

    try:
        if not db_connector or not db_connector.status or not db_connector.connection:
            raise ToolException(
                json.dumps({
                    "success": False, "message": "Database connection not available",
                    "data": None, "metadata": {"error": "no db", "section": section,
                    "row_count": 0, "execution_time_ms": int((time.time() - start_time) * 1000),
                    "namespace": namespace, "thread_id": thread_id}
                }, default=str)
            )

        valid_statuses = ("returned", "cancelled")
        status_val = new_status.strip().lower()
        if status_val not in valid_statuses:
            raise ToolException(
                json.dumps({
                    "success": False, "message": f"Invalid status '{new_status}'. Must be one of: {', '.join(valid_statuses)}",
                    "data": None, "metadata": {"error": "invalid status", "section": section,
                    "row_count": 0, "execution_time_ms": int((time.time() - start_time) * 1000),
                    "namespace": namespace, "thread_id": thread_id}
                }, default=str)
            )

        update_sql = f"UPDATE orders SET status = '{status_val}' WHERE id = {int(order_id)} RETURNING id, order_number, status;"

        result = await asyncio.get_running_loop().run_in_executor(
            _get_db_thread_pool(), db_connector.connection.execute_write, update_sql
        )
        execution_time_ms = int((time.time() - start_time) * 1000)

        if result.success:
            rows = result.rows or []
            if not rows:
                raise ToolException(
                    json.dumps({
                        "success": False, "message": f"Order ID {order_id} not found.",
                        "data": None, "metadata": {"error": "order not found", "section": section,
                        "row_count": 0, "execution_time_ms": execution_time_ms, "namespace": namespace, "thread_id": thread_id}
                    }, default=str)
                )
            data, _ = _serialise(rows, config_settings.TOOL_RESPONSE_MAX_ROWS)
            logger.info(f"Order status updated: order_id={order_id} new_status={status_val}")
            return {
                "success": True, "message": f"Order status updated to '{status_val}'",
                "data": data, "metadata": {"section": section, "row_count": len(rows),
                "execution_time_ms": execution_time_ms, "namespace": namespace, "thread_id": thread_id}
            }

        raise ToolException(
            json.dumps({
                "success": False, "message": result.message or "Update failed",
                "data": None, "metadata": {"error": result.message, "section": section,
                "row_count": 0, "execution_time_ms": execution_time_ms, "namespace": namespace, "thread_id": thread_id}
            }, default=str)
        )

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"Error in {section}: {str(e)}", exc_info=True)
        raise ToolException(
            json.dumps({
                "success": False, "message": f"Unexpected error: {str(e)}",
                "data": None, "metadata": {"error": str(e), "section": section,
                "row_count": 0, "execution_time_ms": int((time.time() - start_time) * 1000),
                "namespace": namespace, "thread_id": thread_id}
            }, default=str)
        )


lookup_customer_tool: BaseTool = tool(lookup_customer, parse_docstring=True)
lookup_customer_tool.name = "lookup_customer"
lookup_customer_tool.handle_tool_error = True

lookup_order_tool: BaseTool = tool(lookup_order, parse_docstring=True)
lookup_order_tool.name = "lookup_order"
lookup_order_tool.handle_tool_error = True

get_customer_orders_tool: BaseTool = tool(get_customer_orders, parse_docstring=True)
get_customer_orders_tool.name = "get_customer_orders"
get_customer_orders_tool.handle_tool_error = True

check_refund_history_tool: BaseTool = tool(check_refund_history, parse_docstring=True)
check_refund_history_tool.name = "check_refund_history"
check_refund_history_tool.handle_tool_error = True

search_knowledge_base_tool: BaseTool = tool(search_knowledge_base, parse_docstring=True)
search_knowledge_base_tool.name = "search_knowledge_base"
search_knowledge_base_tool.handle_tool_error = True

approve_refund_tool: BaseTool = tool(approve_refund, parse_docstring=True)
approve_refund_tool.name = "approve_refund"
approve_refund_tool.handle_tool_error = True

deny_refund_tool: BaseTool = tool(deny_refund, parse_docstring=True)
deny_refund_tool.name = "deny_refund"
deny_refund_tool.handle_tool_error = True

text_to_sql_tool: BaseTool = tool(text_to_sql, parse_docstring=True)
text_to_sql_tool.name = "text_to_sql"
text_to_sql_tool.handle_tool_error = True

check_order_status_tool: BaseTool = tool(check_order_status, parse_docstring=True)
check_order_status_tool.name = "check_order_status"
check_order_status_tool.handle_tool_error = True

escalate_to_human_tool: BaseTool = tool(escalate_to_human, parse_docstring=True)
escalate_to_human_tool.name = "escalate_to_human"
escalate_to_human_tool.handle_tool_error = True

get_refund_summary_tool: BaseTool = tool(get_refund_summary, parse_docstring=True)
get_refund_summary_tool.name = "get_refund_summary"
get_refund_summary_tool.handle_tool_error = True

update_order_status_tool: BaseTool = tool(update_order_status, parse_docstring=True)
update_order_status_tool.name = "update_order_status"
update_order_status_tool.handle_tool_error = True

ALL_TOOLS = [
    lookup_customer_tool,
    lookup_order_tool,
    get_customer_orders_tool,
    check_refund_history_tool,
    check_order_status_tool,
    get_refund_summary_tool,
    search_knowledge_base_tool,
    approve_refund_tool,
    deny_refund_tool,
    update_order_status_tool,
    escalate_to_human_tool,
    text_to_sql_tool,
]

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import warnings

import uvicorn
import webbrowser
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from workflows.auth.db import close_auth_db, init_auth_db
from workflows.auth.routes import router as auth_router
from workflows.core import db_connector
from workflows.core.db.client import initialize_pools
from workflows.core.ingestion.routes import router as ingestion_router
from workflows.core.settings import config_settings
from workflows.graphs import create_graph
from workflows.routes import router as workflows_router


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger.remove()
logger.add(sys.stderr, diagnose=False, backtrace=True, level="INFO")

warnings.filterwarnings("ignore", category=ResourceWarning)
sys.path.insert(0, str(Path(__file__).parent))



def _is_docker() -> bool:
    return Path("/.dockerenv").exists()


def _build_react_app() -> None:
    """Build the React app (outputs directly to webapp-build/ via vite config).
    Only runs when not inside Docker (Docker images are pre-built)."""
    if _is_docker():
        return

    root = Path(__file__).parent
    react_dir = root / "webapp-react"
    target_dir = root / "webapp-build"

    if not react_dir.exists():
        logger.warning(f"React source not found at {react_dir}, skipping build")
        return

    logger.info("Not running in Docker — building React app...")
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(react_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"React build failed:\n{result.stderr}")
        return

    logger.info(f"React build output at {target_dir}")


def find_available_port(start_port: int, max_attempts: int = 100) -> int:
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("0.0.0.0", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_attempts}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ShopAssist AI Application")

    if not db_connector or not db_connector.status:
        logger.error("Database connector not initialized or connection failed")
        raise RuntimeError("Cannot start application: Database connection is required but failed to initialize")

    logger.info(
        f"Database connector ready with {len(db_connector.table_names) if db_connector.table_names else 0} tables"
    )

    await initialize_pools()
    logger.info("Async pools (checkpointer, store) initialized in server event loop")

    checkpointer = db_connector.checkpointer
    checkpoint_pool = db_connector.checkpoint_pool
    store = db_connector.store

    if not checkpointer:
        logger.error("Checkpointer not initialized in db_connector")
        raise RuntimeError("Cannot start application: Checkpointer initialization failed")

    try:
        agent_graph = await create_graph(checkpointer, store=store)
        logger.info("Agent graph compiled as singleton")
    except Exception as graph_err:
        logger.error(f"Failed to compile agent graph: {graph_err}", exc_info=True)
        raise RuntimeError(f"Cannot start application: agent graph compilation failed — {graph_err}")

    app.state.agent_graph = agent_graph
    logger.info("Agent graph stored on app.state")

    try:
        await init_auth_db()
    except Exception as auth_err:
        logger.warning(f"Auth DB (MongoDB) unavailable — auth endpoints disabled: {auth_err}")

    yield

    if db_connector.store_ctx is not None:
        try:
            await db_connector.store_ctx.__aexit__(None, None, None)
            logger.info("Agent store singleton closed")
        except Exception as e:
            logger.warning(f"Error closing agent store: {e}")

    checkpointer_type = config_settings.CHECKPOINT_TYPE.lower()
    if checkpointer_type == "sqlite" and hasattr(checkpointer, '__aexit__'):
        try:
            await checkpointer.__aexit__(None, None, None)
            logger.info("SQLite checkpointer closed")
        except Exception as e:
            logger.warning(f"Error closing SQLite checkpointer: {e}")

    if checkpoint_pool:
        try:
            await checkpoint_pool.close()
            logger.info("Checkpoint pool closed")
        except Exception as e:
            logger.warning(f"Error closing checkpoint pool: {e}")

    await close_auth_db()
    logger.info("Shutting down Text-to-SQL Agent Application")


_build_react_app()

app = FastAPI(title="ShopAssist AI", version="1.0.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(workflows_router)
app.include_router(ingestion_router)


@app.post("/tts")
async def text_to_speech(request: dict):
    """Stream edge-tts audio for the given text. Returns MP3 audio stream."""
    import edge_tts
    from edge_tts.exceptions import NoAudioReceived
    from fastapi import Response
    from fastapi.responses import StreamingResponse

    text = request.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")
    if len(text) > 5000:
        text = text[:5000]

    if not any(ch.isalnum() for ch in text):
        return Response(status_code=204)

    voice = config_settings.TTS_VOICE

    communicate = edge_tts.Communicate(text, voice)
    audio = bytearray()
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
    except NoAudioReceived:
        return Response(status_code=204)
    except Exception as exc:
        logger.error(f"TTS generation failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="TTS generation failed")

    if not audio:
        return Response(status_code=204)

    return Response(content=bytes(audio), media_type="audio/mpeg")


@app.post("/presigned-url")
async def generate_presigned_upload_url(filename: str):
    """Generate pre-signed S3 URLs for direct browser upload + ingest pipeline download."""
    import boto3

    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    bucket = config_settings.POLICY_S3_BUCKET
    prefix = config_settings.POLICY_S3_PREFIX
    s3_key = f"{prefix}{filename}"

    try:
        s3 = boto3.client("s3", region_name="us-east-1")
        upload_url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": s3_key, "ContentType": "application/pdf"},
            ExpiresIn=300,
        )
        download_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": s3_key},
            ExpiresIn=600,
        )
        return {
            "upload_url": upload_url,
            "download_url": download_url,
            "s3_key": s3_key,
            "filename": filename,
        }
    except Exception as e:
        logger.error(f"[PRESIGN] URL generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")

# Prefer the ShopAssist build at webapp-build/ (root), fall back to ai_module/webapp-build/
_root_build = Path(__file__).parent / "webapp-build"
_legacy_build = Path(__file__).parent / "ai_module" / "webapp-build"
webapp_build_dir = _root_build if _root_build.exists() else _legacy_build
webapp_dir = Path(__file__).parent / "webapp"

if webapp_build_dir.exists():
    logger.info(f"Serving React app from {webapp_build_dir}")
    app.mount("/assets", StaticFiles(directory=str(webapp_build_dir / "assets")), name="assets")

    @app.get("/")
    async def root():
        response = FileResponse(str(webapp_build_dir / "index.html"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Never intercept API or WebSocket paths
        if full_path.startswith(("workflows/", "auth/", "ingestion/", "presigned-url")):
            raise HTTPException(status_code=404)
        file_path = webapp_build_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        # For paths with a file extension that weren't found, return 404
        if "." in Path(full_path).name:
            raise HTTPException(status_code=404, detail=f"Static file not found: {full_path}")
        # SPA fallback for client-side routes
        response = FileResponse(str(webapp_build_dir / "index.html"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

elif webapp_dir.exists():
    logger.info(f"Serving old webapp from {webapp_dir}")
    app.mount("/ui", StaticFiles(directory=str(webapp_dir)), name="ui")

    @app.get("/login")
    async def login():
        response = FileResponse(str(webapp_dir / "login.html"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/")
    async def root():
        response = FileResponse(str(webapp_dir / "index.html"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
else:
    logger.warning(f"No webapp found. Tried {webapp_build_dir} and {webapp_dir}")


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    preferred_port = int(os.getenv("PORT", 8000))

    port = find_available_port(preferred_port)
    if port != preferred_port:
        logger.warning(f"Port {preferred_port} is in use, using port {port} instead")

    logger.info(f"Starting server on {host}:{port}")
    logger.info(f"Open http://localhost:{port} in your browser")

    timer = threading.Timer(2.0, lambda: webbrowser.open(f"http://localhost:{port}"))
    timer.start()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        ws="websockets",
        ws_ping_interval=config_settings.WS_PING_INTERVAL,
        ws_ping_timeout=config_settings.WS_PING_TIMEOUT,
        backlog=2048,
        timeout_keep_alive=75,
    )

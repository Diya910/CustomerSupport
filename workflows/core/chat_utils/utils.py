import fastapi
from loguru import logger
from starlette.websockets import WebSocketDisconnect

from typing import Literal

from workflows.core.chat_utils.models import ChatResponse


async def send_message_over_websocket(
    websocket: fastapi.WebSocket,
    message: str,
    message_type: Literal["start", "stream", "end", "blob", "error", "info"] = "stream",
    content_type: (
        Literal[
            "optimised_question",
            "answer",
            "summary",
            "retrieval",
            "agent_interrupt",
            "intermittent_steps",
        ]
        | None
    ) = None,
):
    try:
        resp = ChatResponse(
            message=message, type=message_type, content_type=content_type
        )
        await websocket.send_json(resp.model_dump())

    except WebSocketDisconnect:
        pass

    except RuntimeError as e:
        if "close" in str(e).lower():
            pass
        else:
            logger.warning(f"Error sending message over WebSocket: {e}")
    except Exception as e:
        logger.warning(f"Error sending message over WebSocket: {e}")

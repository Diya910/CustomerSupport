import uuid
import typing

from loguru import logger
from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableConfig

from workflows.core.chat_utils.models import ChatResponse


async def dispatch_tool_progress(
    config: RunnableConfig,
    tool_name: str,
    message: str,
    step_type: str = 'progress',
    metadata: dict = None
):
    if not config:
        logger.warning("No config provided for dispatch_tool_progress, skipping event")
        return

    try:
        event_data = {
            "tool_name": tool_name,
            "message": message,
            "step_type": step_type,
            "metadata": metadata or {}
        }
        await adispatch_custom_event(
            name="tool_progress",
            data=event_data,
            config=config
        )
        logger.debug(f"Dispatched tool_progress event: {tool_name} - {message}")
    except Exception as e:
        logger.error(f"Error dispatching tool_progress event: {e}")


class StreamingLLMCallbackHandler(AsyncCallbackHandler):
    __slots__ = ('websocket', 'tool_key', 'tool_name', 'user_query', 'config',
                 'token_type', 'generated_content', 'token_buffer', 'has_tool_context')

    def __init__(
        self,
        websocket_internal,
        tool_key: str = None,
        tool_name: str = None,
        user_query: str = None,
        config: RunnableConfig = None,
        token_type: str = 'generation'
    ):
        self.websocket = websocket_internal
        self.tool_key = tool_key
        self.tool_name = tool_name
        self.user_query = user_query
        self.config = config
        self.token_type = token_type
        self.generated_content = None
        self.token_buffer = []
        self.has_tool_context = bool(tool_key and tool_name)

    async def emit_tool_step(self, message: str, step_type: str = 'progress'):
        if not self.has_tool_context:
            return
        if self.config:
            try:
                await adispatch_custom_event(
                    name="tool_progress",
                    data={
                        "tool_name": self.tool_name,
                        "message": message,
                        "step_type": step_type,
                        "metadata": {"tool_key": self.tool_key}
                    },
                    config=self.config
                )
            except Exception as e:
                logger.warning(f"Failed to dispatch tool_progress event: {e}")
        elif self.websocket:
            await self.websocket.send_json({
                "type": "stream",
                "content_type": "tool_step",
                "message": {
                    'tool_key': self.tool_key,
                    'tool_name': self.tool_name,
                    'step_content': message,
                    'step_type': step_type,
                }
            })
        logger.debug(f"Tool step [{self.tool_name}]: {message}")

    async def emit_tool_token(self, token: str):
        if self.has_tool_context and self.config:
            try:
                await adispatch_custom_event(
                    name="tool_llm_token",
                    data={
                        "tool_key": self.tool_key,
                        "tool_name": self.tool_name,
                        "token": token,
                        "token_type": self.token_type
                    },
                    config=self.config
                )
            except Exception:
                pass

    async def handle_llm_start(self, run_id: uuid.UUID, log_prefix: str):
        logger.info(f"{log_prefix} | run_id={run_id}")
        if self.has_tool_context and self.config:
            try:
                await adispatch_custom_event(
                    name="tool_llm_start",
                    data={
                        "tool_key": self.tool_key,
                        "tool_name": self.tool_name,
                        "llm_type": self.token_type
                    },
                    config=self.config
                )
            except Exception:
                pass

    async def on_chat_model_start(
            self,
            serialized: typing.Dict[str, typing.Any],
            messages: typing.List[typing.List[BaseMessage]],
            *,
            run_id: uuid.UUID,
            parent_run_id: uuid.UUID | None = None,
            tags: typing.List[str] | None = None,
            metadata: typing.Dict[str, typing.Any] | None = None,
            **kwargs: typing.Any,
    ) -> typing.Any:
        await self.handle_llm_start(run_id, "LLM chat model start")

    async def on_llm_start(
            self,
            serialized: typing.Dict[str, typing.Any],
            prompts: typing.List[str],
            *,
            run_id: uuid.UUID,
            parent_run_id: typing.Optional[uuid.UUID] = None,
            tags: typing.Optional[typing.List[str]] = None,
            metadata: typing.Optional[typing.Dict[str, typing.Any]] = None,
            **kwargs: typing.Any
    ) -> None:
        await self.handle_llm_start(run_id, "LLM chain start")

    async def on_llm_new_token(self, token: str, **kwargs: typing.Any) -> None:
        if self.has_tool_context:
            self.token_buffer.append(token)
            await self.emit_tool_token(token)
        elif self.websocket:
            await self.websocket.send_json(ChatResponse(message=token, type="stream").model_dump())

    async def on_llm_end(
            self,
            response: LLMResult,
            *,
            run_id: uuid.UUID,
            parent_run_id: typing.Optional[uuid.UUID] = None,
            tags: typing.Optional[typing.List[str]] = None,
            **kwargs: typing.Any
    ) -> None:
        logger.info(f"LLM chain end | run_id={run_id}")

        if response.generations and response.generations[0]:
            gen = response.generations[0][0]
            self.generated_content = (
                getattr(gen, 'text', None) or
                getattr(getattr(gen, 'message', None), 'content', None)
            )
            if self.generated_content:
                logger.info(f"LLM generated content (first 200 chars): {self.generated_content[:200]}")

        if self.has_tool_context and self.config:
            try:
                await adispatch_custom_event(
                    name="tool_llm_end",
                    data={
                        "tool_key": self.tool_key,
                        "tool_name": self.tool_name,
                        "content": self.generated_content
                    },
                    config=self.config
                )
            except Exception:
                pass

    async def on_llm_error(
            self,
            error: Exception,
            *,
            run_id: uuid.UUID,
            parent_run_id: typing.Optional[uuid.UUID] = None,
            tags: typing.Optional[typing.List[str]] = None,
            **kwargs: typing.Any
    ) -> None:
        logger.error(f"LLM error: {error}")
        if self.has_tool_context:
            await self.emit_tool_step(f"Error: {str(error)[:100]}", step_type='error')

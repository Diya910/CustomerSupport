from workflows.core.db import db_connector
from workflows.core.settings import config_settings
from workflows.core.chat_utils.handler import StreamingLLMCallbackHandler
from workflows.core.llm import get_chat_model, get_streaming_chat_model, get_embeddings_model

from loguru import logger

logger.info("initializing module core")

CONTENT_TYPE_OPTIMISED_QUESTION = "optimised_question"
CONTENT_TYPE_ANSWER = "answer"
CONTENT_TYPE_SUMMARY = "summary"
CONTENT_TYPE_RETRIEVAL = "retrieval"
CONTENT_TYPE_AGENT_INTERRUPT = "agent_interrupt"
CONTENT_TYPE_INTERMITTENT_STEPS = "intermittent_steps"

MESSAGE_TYPE_START = "start"
MESSAGE_TYPE_END = "end"
MESSAGE_TYPE_BLOB = "blob"
MESSAGE_TYPE_ERROR = "error"
MESSAGE_TYPE_INFO = "info"

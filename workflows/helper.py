from loguru import logger
from typing import Literal

from workflows.core import config_settings
from workflows.utils import SENSITIVE_TOOLS

from workflows.state_schema import AgentState

from langchain_core.messages import (
    ToolMessage,
    HumanMessage
)
from langchain_core.messages import AIMessage, AnyMessage


def should_trigger_summarization(state: AgentState) -> bool:
    messages = state["messages"]
    message_count = len(messages)
    if message_count >= config_settings.THRESHOLD_MESSAGE_TO_SUMMARIZE:
        logger.info(f"Summarization triggered: message count {message_count} >= {config_settings.THRESHOLD_MESSAGE_TO_SUMMARIZE}")
        return True

    fraction_threshold = int(config_settings.MODEL_CONTEXT_WINDOW * config_settings.SUMMARIZATION_TRIGGER_FRACTION)
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            usage = getattr(msg, 'usage_metadata', None)
            if usage:
                input_tokens = usage.get('input_tokens', 0) if isinstance(usage, dict) else getattr(usage, 'input_tokens', 0)
                output_tokens = usage.get('output_tokens', 0) if isinstance(usage, dict) else getattr(usage, 'output_tokens', 0)
                total_tokens = input_tokens + output_tokens
                if total_tokens >= fraction_threshold:
                    logger.info(
                        f"Summarization triggered: usage_metadata tokens {total_tokens} "
                        f"(input={input_tokens}, output={output_tokens}) >= "
                        f"{config_settings.SUMMARIZATION_TRIGGER_FRACTION*100:.0f}% of context window ({fraction_threshold})"
                    )
                    return True
            break

    return False


def pending_tool_calls(state: AgentState) -> Literal["human", "tools", "summarize_conversation", "done"]:
    messages = state["messages"]
    if not messages:
        return "done"

    last_message = messages[-1]

    logger.info(f"Pending Tool Calls check. Last message: {type(last_message)}.")

    if not isinstance(last_message, AIMessage):
        logger.warning(
            f"pending_tool_calls: Expected AIMessage as last_message, "
            f"got {type(last_message)}. Content: {getattr(last_message, 'content', 'N/A')}"
        )
        return "done"

    logger.info(f"AIMessage tool_calls: {last_message.tool_calls}")
    logger.info(f"AIMessage content: {last_message.content[:200] if last_message.content else 'None'}")

    if last_message.additional_kwargs.get("requires_human_review"):
        return "human"

    if last_message.tool_calls:
        tool_name = last_message.tool_calls[0]["name"]
        is_sensitive = tool_name in SENSITIVE_TOOLS

        if is_sensitive:
            logger.info(f"Sensitive tool call detected ({tool_name}), routing to human.")
            return "human"

        logger.info(f"Tool call detected ({tool_name}), routing to tools.")
        return "tools"

    if should_trigger_summarization(state):
        return "summarize_conversation"

    logger.info("No tool calls. Routing to done.")
    return "done"


def collect_attempt_counts(messages: list[AnyMessage]) -> dict[str, int]:
    """Count tool execution attempts (success or failure) per tool name for the current query only."""
    by_name: dict[str, int] = {}

    # Find the last user message to determine the start of current query
    last_user_message_index = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_user_message_index = i
            break

    # Only count tool calls from the current query (after the last user message)
    query_messages = messages[last_user_message_index + 1:] if last_user_message_index >= 0 else messages

    # Count attempts directly from AIMessage tool_calls (not responses) in current query only
    for msg in query_messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tool_name = tc.get("name")
                if tool_name:
                    current_attempt = by_name.get(tool_name, 0) + 1
                    by_name[tool_name] = current_attempt
                    logger.debug(f"Tool attempt count: {tool_name} = {current_attempt}")

    return by_name


async def retry_guard(state: AgentState):
    messages: list[AnyMessage] = state.get("messages", [])
    if not messages:
        return {}

    last_message = messages[-1]
    if not isinstance(last_message, AIMessage) or not getattr(last_message, "tool_calls", None):
        return {}

    attempts_by_name = collect_attempt_counts(messages)

    modified_tool_calls = []
    injected_messages: list[AnyMessage] = []

    for tc in last_message.tool_calls:
        tool_name = tc.get("name") or ""
        current_attempts = attempts_by_name.get(tool_name, 0)

        if current_attempts > config_settings.TOOL_MAX_RETRIES_LIMIT:
            failure_text = (
                f"No answer generated after {current_attempts} attempts for tool '{tool_name}'. "
                "Proceeding to the next available tool to continue resolving your request."
            )
            injected_messages.append(
                ToolMessage(content=failure_text, tool_call_id=tc.get("id"))
            )
        else:
            modified_tool_calls.append(tc)

    if len(modified_tool_calls) == len(last_message.tool_calls):
        return {}

    delta_messages: list[AnyMessage] = []

    if modified_tool_calls:
        delta_messages.append(
            AIMessage(
                content=last_message.content,
                tool_calls=modified_tool_calls,
                id=last_message.id,
                name=getattr(last_message, 'name', None),
                additional_kwargs=(
                    last_message.additional_kwargs.copy() if hasattr(last_message, 'additional_kwargs') else {})
            )
        )
    else:
        delta_messages.append(
            AIMessage(
                content=last_message.content or "All tools have exceeded retry limits.",
                id=last_message.id,
                name=getattr(last_message, 'name', None),
                additional_kwargs=(last_message.additional_kwargs.copy()
                                   if hasattr(last_message, 'additional_kwargs') else {})
            )
        )
    delta_messages.extend(injected_messages)

    return {"messages": delta_messages}

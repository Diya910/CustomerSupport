import asyncio
import json
import re
from loguru import logger
from typing import Literal
from datetime import datetime

from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.graph import END, StateGraph
from langchain_core.runnables import RunnableConfig

from botocore.exceptions import ClientError

from langchain.agents.middleware.summarization import SummarizationMiddleware

from workflows.core import get_chat_model as initialize_chat_model

from workflows.state_schema import should_continue, AgentState
from workflows.prompts.agent_prompts import get_agent_prompt
from workflows.utils import wrap_model

from workflows.helper import pending_tool_calls, retry_guard

from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    ToolMessage,
    RemoveMessage
)

from workflows.tools import ALL_TOOLS
from workflows.core import config_settings


async def create_graph(checkpointer, store=None):
    tools = ALL_TOOLS
    logger.info(f"Create Graph Called with {len(tools)} tools")
    agent = StateGraph(AgentState)

    def format_tool_error(e: Exception) -> str:
        error_type = type(e).__name__
        message = str(e)[:500]
        return f"Tool execution failed ({error_type}): {message}"

    async def summarize_conversation_node(state: AgentState) -> dict:
        try:
            model = initialize_chat_model(model_key=config_settings.SUMMARIZATION_MODEL)

            summarization_middleware = SummarizationMiddleware(
                model=model,
                trigger=[
                    ("tokens", config_settings.THRESHOLD_TOKENS_TO_SUMMARIZE),
                    ("messages", config_settings.THRESHOLD_MESSAGE_TO_SUMMARIZE),
                ],
                keep=("messages", config_settings.SUMMARIZATION_KEEP_MESSAGES),
                trim_tokens_to_summarize=config_settings.SUMMARIZATION_MIN_TOKENS_TO_SUMMARIZE,
            )

            result = await summarization_middleware.abefore_model(state, None)
            if result:
                logger.info(f"SummarizationMiddleware pruned messages: {len(state['messages'])} → {len(result.get('messages', []))}")
                return result
        except Exception as e:
            logger.error(f"SummarizationMiddleware error: {e}", exc_info=True)
        return {}

    async def ainvoke_model(state: AgentState, config: RunnableConfig) -> AgentState:
        logger.info("ainvoke_model Calling")
        return await acall_model(state, tools, config)

    agent.add_node("model", ainvoke_model)
    agent.add_node("tools", ToolNode(tools, handle_tool_errors=format_tool_error))
    agent.add_node("retry_guard", retry_guard)
    agent.add_node("summarize_conversation", summarize_conversation_node)

    agent.set_entry_point("model")
    agent.add_conditional_edges("tools", should_continue)

    agent.add_conditional_edges(
        "model",
        pending_tool_calls,
        {
            "tools": "retry_guard",
            "summarize_conversation": "summarize_conversation",
            "human": END,
            "done": END
        }
    )

    def retry_router(state: AgentState) -> Literal["tools", "model"]:
        messages = state.get("messages", [])
        if not messages:
            return "model"
        last = messages[-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return "model"

    agent.add_conditional_edges(
        "retry_guard", retry_router, {"tools": "tools", "model": "model"}
    )

    agent.add_edge("summarize_conversation", END)

    research_assistant = agent.compile(checkpointer=checkpointer, store=store)

    logger.info(f"Step: {datetime.now()} seconds got graph created END")
    return research_assistant


async def acall_model(state: AgentState, tools: list[tool], config: RunnableConfig) -> AgentState:
    logger.info(f"Step 4: {datetime.now()} seconds acall_model")

    model = initialize_chat_model(model_key="CHAT_MODEL_NAME", temperature=config_settings.DEEP_AGENT_TEMPERATURE)

    summary = state.get("summary", "")
    messages = await filter_messages_async(state.get("messages", []))
    current_state = {"messages": messages, "summary": summary}

    agent_instructions = get_agent_prompt(datetime.now().strftime("%Y-%m-%d"))

    dynamic_parts = []
    use_case = config["configurable"].get("use_case", "default")
    if use_case == "reason":
        dynamic_parts.append("You must not answer using your own knowledge. Only respond if tool outputs are available.")
    if summary:
        dynamic_parts.append(f"Summary of conversation earlier: {summary}")

    system_prompt = agent_instructions or ""
    dynamic_context = "\n\n".join(dynamic_parts) if dynamic_parts else ""
    model_runnable = wrap_model(model, tools, system_prompt, dynamic_context)

    max_retries = 2
    response = None
    invoke_timeout = config_settings.MODEL_INVOCATION_TIMEOUT_SECONDS
    for attempt in range(max_retries + 1):
        try:
            response = await asyncio.wait_for(
                model_runnable.ainvoke(current_state, config),
                timeout=invoke_timeout,
            )
            break
        except asyncio.TimeoutError:
            logger.error(f"Model invocation hard-timeout after {invoke_timeout}s (attempt {attempt+1})")
            if attempt < max_retries:
                continue
            response = AIMessage(content="I apologize, but the response is taking too long. Please try again or rephrase your question.")
            break
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', '')

            is_tool_validation_error = (
                error_code.lower() == 'validationexception' and
                ('tool_use' in error_message.lower() or 'tool_result' in error_message.lower())
            )
            is_context_error = (
                error_code == 'ValidationException' and
                'input is too long' in error_message.lower()
            )

            if is_tool_validation_error:
                logger.error(f"Tool validation error detected: {error_message}")
                current_state["messages"] = await filter_messages_async(current_state["messages"])
                if attempt < max_retries:
                    continue
                else:
                    response = AIMessage(content="I apologize, there was an error processing the tool calls. Please try rephrasing your question.")
                    break

            if is_context_error and attempt < max_retries:
                logger.warning(f"Context limit exceeded (attempt {attempt + 1}). Dropping old messages...")
                current_state["messages"] = truncate_for_context_limit(current_state["messages"])
                continue
            else:
                logger.error(f"Model invocation error: {e}")
                response = AIMessage(content="I apologize, but I don't have any information available to answer your question based on the available data.")
                break
        except Exception as e:
            logger.error(f"Unexpected error during model invocation: {e}")
            response = AIMessage(content="I apologize, but I don't have any information available to answer your question based on the available data.")
            break

    if not response:
        response = AIMessage(content="I apologize, but I don't have any information available to answer your question based on the available data.")

    if config_settings.ENABLE_PROMPT_CACHING and hasattr(response, 'usage_metadata') and response.usage_metadata:
        usage = response.usage_metadata
        cache_read = usage.get("input_token_details", {}).get("cache_read", 0)
        cache_creation = usage.get("input_token_details", {}).get("cache_creation", 0)
        if cache_read or cache_creation:
            logger.info(f"Prompt cache: read={cache_read} tokens, creation={cache_creation} tokens")

    return process_response(response, state)


def truncate_for_context_limit(messages: list) -> list:
    if not messages or len(messages) <= 2:
        return messages

    logger.info(f"Truncating {len(messages)} messages to fit context limit")

    tool_call_to_response = {}
    response_to_call = {}

    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and getattr(msg, 'tool_calls', None):
            for tc in msg.tool_calls:
                tool_call_to_response[tc["id"]] = i
        elif isinstance(msg, ToolMessage) and msg.tool_call_id:
            response_to_call[i] = msg.tool_call_id

    keep_count = max(len(messages) // 2, 3)

    result = []
    start_idx = 0
    if messages and isinstance(messages[0], SystemMessage):
        result.append(messages[0])
        start_idx = 1

    msg_indices_to_keep = set(range(max(start_idx, len(messages) - keep_count), len(messages)))

    for i in msg_indices_to_keep.copy():
        msg = messages[i]
        if isinstance(msg, ToolMessage) and msg.tool_call_id:
            if msg.tool_call_id in tool_call_to_response:
                call_idx = tool_call_to_response[msg.tool_call_id]
                msg_indices_to_keep.add(call_idx)
        if isinstance(msg, AIMessage) and getattr(msg, 'tool_calls', None):
            for tc in msg.tool_calls:
                for resp_idx, call_id in response_to_call.items():
                    if call_id == tc["id"]:
                        msg_indices_to_keep.add(resp_idx)

    for i in sorted(msg_indices_to_keep):
        result.append(messages[i])

    logger.info(f"Truncated messages: {len(messages)} → {len(result)}")
    return result


async def filter_messages_async(messages):
    def validate_and_clean_tool_calls(msg: AIMessage) -> AIMessage:
        if not isinstance(msg, AIMessage) or not getattr(msg, 'tool_calls', None):
            return msg

        valid_tool_calls = []
        for tc in msg.tool_calls:
            if isinstance(tc.get('args'), dict) or tc.get('args') is None:
                valid_tool_calls.append(tc)
            else:
                logger.warning(f"Removing tool call '{tc.get('name')}' with invalid input type: {type(tc.get('args'))}")

        if not valid_tool_calls and msg.tool_calls:
            logger.warning("All tool calls in message were invalid. Cleaning message.")
            return AIMessage(
                content=msg.content if msg.content else "I need to use a tool to answer this.",
                id=msg.id if hasattr(msg, 'id') else None
            )

        if len(valid_tool_calls) != len(msg.tool_calls):
            msg.tool_calls = valid_tool_calls

        return msg

    def limit_sql_rows(msg: ToolMessage) -> ToolMessage:
        try:
            if not isinstance(msg.content, str):
                return msg

            stripped = msg.content.strip()
            if not stripped or stripped[0] not in ("{", "["):
                return msg

            try:
                tool_output_data = json.loads(stripped)
            except json.JSONDecodeError:
                return msg

            if not isinstance(tool_output_data, dict) or not tool_output_data.get("success"):
                return msg

            original_row_count = tool_output_data.get("row_count", 0)
            rows = tool_output_data.get("data", [])

            if original_row_count <= config_settings.MAX_ROWS_FOR_LLM_CONTEXT:
                return msg

            if not isinstance(rows, list):
                return msg

            limited_rows = rows[:config_settings.MAX_ROWS_FOR_LLM_CONTEXT]

            new_content_dict = {
                "success": True,
                "data": limited_rows,
                "row_count": len(limited_rows),
                "metadata": tool_output_data.get("metadata", {}),
                "_context_note": f"Showing {len(limited_rows)} of {original_row_count} rows"
            }

            return ToolMessage(
                content=json.dumps(new_content_dict),
                name=msg.name,
                tool_call_id=msg.tool_call_id,
                id=msg.id,
            )
        except Exception as e:
            logger.error(f"Error limiting SQL rows: {e}")
            return msg

    tool_response_ids = set()
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.tool_call_id:
            tool_response_ids.add(msg.tool_call_id)

    max_chars = config_settings.MAX_TOOL_OUTPUT_CHARS

    def cap_tool_content(msg: ToolMessage) -> ToolMessage:
        content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
        if len(content_str) <= max_chars:
            return msg
        logger.warning(f"Tool '{msg.name}' output exceeded {max_chars} chars ({len(content_str)}), capping")
        return ToolMessage(
            content=content_str[:max_chars],
            name=msg.name,
            tool_call_id=msg.tool_call_id,
            id=msg.id,
        )

    def strip_orphaned_tool_use_from_content(content, valid_ids: set):
        if not isinstance(content, list):
            return content
        cleaned = [
            block for block in content
            if not (isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") not in valid_ids)
        ]
        return cleaned if cleaned else ""

    surviving_tool_use_ids = set()

    pass1_messages = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            continue
        elif isinstance(msg, AIMessage):
            msg = validate_and_clean_tool_calls(msg)
            has_tool_use = (
                bool(msg.tool_calls) or
                (isinstance(msg.content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_use" for b in msg.content
                ))
            )
            if not has_tool_use:
                pass1_messages.append(msg)
            else:
                valid_tool_calls = [
                    tc for tc in (msg.tool_calls or [])
                    if tc["id"] in tool_response_ids
                ]
                valid_ids = {tc["id"] for tc in valid_tool_calls}
                if isinstance(msg.content, list):
                    for block in msg.content:
                        if (isinstance(block, dict) and block.get("type") == "tool_use"
                                and block.get("id") and block["id"] in tool_response_ids):
                            valid_ids.add(block["id"])
                content = strip_orphaned_tool_use_from_content(msg.content, valid_ids)
                if valid_ids:
                    new_msg = AIMessage(
                        content=content if content else "",
                        tool_calls=valid_tool_calls,
                        additional_kwargs=msg.additional_kwargs if valid_tool_calls else {k: v for k, v in msg.additional_kwargs.items() if k != "tool_calls"},
                        id=msg.id
                    )
                    pass1_messages.append(new_msg)
                    surviving_tool_use_ids.update(valid_ids)
                elif content:
                    new_msg = AIMessage(
                        content=content,
                        additional_kwargs={k: v for k, v in msg.additional_kwargs.items() if k != "tool_calls"},
                        id=msg.id
                    )
                    pass1_messages.append(new_msg)
        elif isinstance(msg, ToolMessage):
            pass1_messages.append(msg)
        elif not isinstance(msg, RemoveMessage):
            pass1_messages.append(msg)

    filtered_messages = []
    for msg in pass1_messages:
        if isinstance(msg, ToolMessage):
            if msg.tool_call_id in surviving_tool_use_ids:
                if msg.name == "text_to_sql":
                    filtered_messages.append(cap_tool_content(limit_sql_rows(msg)))
                else:
                    filtered_messages.append(cap_tool_content(msg))
            else:
                logger.debug(f"Dropping orphaned ToolMessage: {msg.tool_call_id}")
        else:
            filtered_messages.append(msg)

    STREAMING_ONLY_FIELDS = ("index", "partial_json")

    def strip_streaming_fields(msg):
        if not isinstance(msg, AIMessage):
            return msg
        if not isinstance(msg.content, list):
            return msg
        cleaned = False
        new_content = []
        for block in msg.content:
            if isinstance(block, dict) and any(k in block for k in STREAMING_ONLY_FIELDS):
                stripped = {k: v for k, v in block.items() if k not in STREAMING_ONLY_FIELDS}
                new_content.append(stripped)
                cleaned = True
            else:
                new_content.append(block)
        if not cleaned:
            return msg
        return AIMessage(
            content=new_content,
            tool_calls=msg.tool_calls if msg.tool_calls else [],
            additional_kwargs=msg.additional_kwargs,
            id=msg.id,
        )

    validated_messages = []
    for msg in filtered_messages:
        if isinstance(msg, AIMessage):
            validated_messages.append(strip_streaming_fields(msg))
        else:
            validated_messages.append(msg)

    return validated_messages


def process_response(response, state):
    if state.get("is_last_step", False) and hasattr(response, 'tool_calls') and response.tool_calls:
        return {
            "messages": [
                AIMessage(
                    id=response.id,
                    content="Sorry, need more steps to process this request."
                )
            ]
        }

    if hasattr(response, 'content') and isinstance(response.content, str):
        cleaned_content = re.sub(r'<thinking>.*?</thinking>', '', response.content, flags=re.DOTALL)
        cleaned_content = cleaned_content.strip()

        if cleaned_content != response.content:
            response = AIMessage(
                id=response.id if hasattr(response, 'id') else None,
                content=cleaned_content,
                tool_calls=response.tool_calls if hasattr(response, 'tool_calls') else None,
                additional_kwargs=response.additional_kwargs if hasattr(response, 'additional_kwargs') else {}
            )

    return {"messages": [response]}

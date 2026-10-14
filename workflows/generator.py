import json
import asyncio

from loguru import logger
from fastapi import WebSocket

from workflows.state_schema import ChatMessage
from workflows.utils import tools_name, tool_output
from workflows.state_schema import StreamInput

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Overwrite

from langchain_core.messages import RemoveMessage, SystemMessage
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)

from workflows.core import (
    CONTENT_TYPE_ANSWER,
    MESSAGE_TYPE_START,
    MESSAGE_TYPE_END,
    MESSAGE_TYPE_ERROR,
)
from workflows.core.settings import config_settings


async def process_stream(
        websocket: WebSocket,
        agent: CompiledStateGraph,
        user_input: StreamInput,
        run_id: str,
        kwargs,
        human_feedback=None,
        cancel_event: asyncio.Event = None,
):
    start = False
    tool_sequence_num = -1
    tool_io_message = {}
    pending_agent_text = ""
    last_tool_name = None
    last_usage_stats: dict | None = None
    tool_call_count_per_name = {}
    tools_have_executed = False
    final_answer_started = False
    pre_tool_streamed_text = ""
    pre_tool_streamed_len = 0
    post_tool_buffer = ""
    in_thinking = False
    thinking_buffer = ""
    thinking_ack_sent = False
    initial_ack_cleared = False

    tool_retry_counts = {}
    max_tool_retries = config_settings.TOOL_MAX_RETRIES_LIMIT
    answer_end_sent = False

    await websocket.send_json({
        "type": MESSAGE_TYPE_START,
        "content_type": CONTENT_TYPE_ANSWER,
        "message": ""
    })
    start = True
    logger.info(f"Sent start signal for run_id: {run_id}")

    await websocket.send_json({
        "type": "stream",
        "content_type": "agent_thinking",
        "message": "..."
    })

    event_stream = agent.astream_events(**kwargs, version="v2")

    try:
        async for event in event_stream:
            if cancel_event and cancel_event.is_set():
                logger.info(f"[CANCEL] Generation cancelled by user for run_id: {run_id}")
                try:
                    await websocket.send_json({
                        "type": "stream",
                        "content_type": CONTENT_TYPE_ANSWER,
                        "message": "\n\n*Generation stopped.*"
                    })
                except Exception:
                    pass
                try:
                    await event_stream.aclose()
                except Exception as close_err:
                    logger.warning(f"Error closing event stream on cancel: {close_err}")
                return False

            if not event:
                continue

            if event["event"] == "on_custom_event":
                custom_data = event.get('data', {})
                custom_name = event.get('name', '')

                if custom_name == "tool_progress":
                    tool_name_from_event = custom_data.get('tool_name', '')
                    message = custom_data.get('message', '')
                    step_type = custom_data.get('step_type', 'progress')
                    metadata = custom_data.get('metadata', {})

                    if tool_name_from_event and tool_name_from_event not in tools_name:
                        logger.debug(f"Skipping tool_progress for non-whitelisted tool: {tool_name_from_event}")
                        continue

                    current_tool_key = metadata.get('tool_key') or tool_io_message.get(
                        tool_name_from_event, str(tool_sequence_num)
                    )
                    tool_display_name = tools_name.get(tool_name_from_event, tool_name_from_event)

                    if message:
                        await websocket.send_json({
                            "type": "stream",
                            "content_type": "tool_step",
                            "message": {
                                'tool_key': current_tool_key,
                                'tool_name': tool_display_name,
                                'step_content': message,
                                'step_type': step_type,
                            }
                        })
                        logger.debug(f"Custom event [{tool_name_from_event}]: {message}")

                elif custom_name == "tool_llm_start":
                    tool_key = custom_data.get('tool_key', str(tool_sequence_num))
                    tool_name_from_event = custom_data.get('tool_name', '')
                    llm_type = custom_data.get('llm_type', 'generation')
                    tool_display_name = tools_name.get(tool_name_from_event, tool_name_from_event)

                    await websocket.send_json({
                        "type": "stream",
                        "content_type": "tool_llm_start",
                        "message": {
                            "tool_key": tool_key,
                            "tool_name": tool_display_name,
                            "llm_type": llm_type
                        }
                    })

                elif custom_name == "tool_llm_token":
                    tool_key = custom_data.get('tool_key', str(tool_sequence_num))
                    token = custom_data.get('token', '')
                    token_type = custom_data.get('token_type', 'generation')

                    if token:
                        await websocket.send_json({
                            "type": "stream",
                            "content_type": "tool_llm_token",
                            "message": {
                                "tool_key": tool_key,
                                "token": token,
                                "token_type": token_type
                            }
                        })

                elif custom_name == "tool_llm_end":
                    tool_key = custom_data.get('tool_key', str(tool_sequence_num))
                    tool_name_from_event = custom_data.get('tool_name', '')
                    content = custom_data.get('content', '')
                    tool_display_name = tools_name.get(tool_name_from_event, tool_name_from_event)

                    await websocket.send_json({
                        "type": "stream",
                        "content_type": "tool_llm_end",
                        "message": {
                            "tool_key": tool_key,
                            "tool_name": tool_display_name,
                            "content": content
                        }
                    })

                elif custom_name == "tool_status_start":
                    tool_name_from_event = custom_data.get('tool_name', '')
                    milestone = custom_data.get('milestone', '')
                    current_tool_key = tool_io_message.get(tool_name_from_event, str(tool_sequence_num))
                    tool_display_name = tools_name.get(tool_name_from_event, tool_name_from_event)

                    await websocket.send_json({
                        "type": "stream",
                        "content_type": "tool_status_start",
                        "message": {
                            "tool_key": current_tool_key,
                            "tool_name": tool_display_name,
                            "milestone": milestone
                        }
                    })

                elif custom_name == "tool_status_token":
                    tool_name_from_event = custom_data.get('tool_name', '')
                    token = custom_data.get('token', '')
                    current_tool_key = tool_io_message.get(tool_name_from_event, str(tool_sequence_num))

                    if token:
                        await websocket.send_json({
                            "type": "stream",
                            "content_type": "tool_status_token",
                            "message": {
                                "tool_key": current_tool_key,
                                "token": token
                            }
                        })

                elif custom_name == "tool_status_end":
                    tool_name_from_event = custom_data.get('tool_name', '')
                    current_tool_key = tool_io_message.get(tool_name_from_event, str(tool_sequence_num))

                    await websocket.send_json({
                        "type": "stream",
                        "content_type": "tool_status_end",
                        "message": {
                            "tool_key": current_tool_key
                        }
                    })

            if event["event"] == "on_tool_start":
                tool_name = event['name']
                event_data = event.get('data', {})
                if not isinstance(event_data, dict):
                    event_data = {}
                input_data = event_data.get('input', {})

                if tool_name not in tools_name:
                    logger.debug(f"Skipping non-UI tool from display: {tool_name}")
                    continue

                tool_retry_counts[tool_name] = tool_retry_counts.get(tool_name, 0) + 1
                if tool_retry_counts[tool_name] > max_tool_retries:
                    logger.warning(
                        f"[RETRY_GUARD] Tool '{tool_name}' exceeded retry limit "
                        f"({tool_retry_counts[tool_name]}/{max_tool_retries}). Sending warning to UI."
                    )
                    await websocket.send_json({
                        "type": "stream",
                        "content_type": None,
                        "message": f"I've attempted this operation {max_tool_retries} times without success. "
                                   "Let me provide you with what I have so far."
                    })
                    continue

                tools_have_executed = True
                final_answer_started = False

                streamed_pre_tool = pre_tool_streamed_len > 0

                if post_tool_buffer:
                    logger.info(
                        f"Discarding post-tool buffer before data tool ({len(post_tool_buffer)} chars): {post_tool_buffer[:80]}"
                    )
                    post_tool_buffer = ""

                tool_display_name = tools_name.get(tool_name, tool_name)

                if tool_name == last_tool_name and tool_name in tool_io_message:
                    current_tool_key = tool_io_message[tool_name]
                    tool_call_count_per_name[tool_name] = tool_call_count_per_name.get(tool_name, 1) + 1
                    logger.info(
                        f"Reusing tool_key {current_tool_key} for consecutive "
                        f"{tool_name} call (call #{tool_call_count_per_name[tool_name]})"
                    )
                else:
                    tool_sequence_num += 1
                    current_tool_key = str(tool_sequence_num)
                    tool_io_message[tool_name] = current_tool_key
                    tool_call_count_per_name[tool_name] = 1
                    last_tool_name = tool_name

                kwargs['config']['configurable']['current_tool_key'] = current_tool_key

                tool_query = None
                if isinstance(input_data, dict):
                    tool_query = input_data.get('query', '')
                elif isinstance(input_data, str):
                    tool_query = input_data
                kwargs['config']['configurable']['tool_query'] = tool_query

                combined_parts = []
                if pre_tool_streamed_text.strip():
                    combined_parts.append(pre_tool_streamed_text.strip())
                if pending_agent_text.strip():
                    combined_parts.append(pending_agent_text.strip())
                combined_pre_tool_text = " ".join(combined_parts) if combined_parts else ""

                if streamed_pre_tool:
                    fallback_status = combined_pre_tool_text or f"Using {tool_display_name}"
                    await websocket.send_json({
                        "type": "stream",
                        "content_type": "agent_thinking",
                        "message": fallback_status
                    })
                    if not combined_pre_tool_text:
                        combined_pre_tool_text = fallback_status

                if combined_pre_tool_text:
                    await websocket.send_json({
                        "type": "stream",
                        "content_type": "status_before",
                        "message": {
                            "tool_key": current_tool_key,
                            "tool_name": tool_display_name,
                            "status_message": combined_pre_tool_text
                        }
                    })
                    logger.info(f"Emitted LLM status_before: {combined_pre_tool_text[:50]}...")
                    pre_tool_streamed_text = ""
                    pre_tool_streamed_len = 0
                    pending_agent_text = ""

                if tool_call_count_per_name.get(tool_name, 1) == 1:
                    description = (
                        tool_query.strip()
                        if tool_query and tool_query.strip()
                        else tool_output.get(tool_name, '')
                    )
                    tool_start_payload = {
                        "type": "stream",
                        "content_type": "tool_start",
                        "message": {
                            'tool_key': current_tool_key,
                            'tool_name': tool_display_name,
                            'tool_id': tool_name,
                            'tool_description': description,
                        }
                    }
                    logger.info(f"SENDING tool_start: {tool_name} #{tool_sequence_num}")
                    await websocket.send_json(tool_start_payload)
                else:
                    logger.info(f"Skipping tool_start for consecutive {tool_name} call (reusing existing card)")



            if event["event"] == "on_llm_start":
                metadata = event.get('metadata', {})
                parent_ids = event.get('parent_ids', [])
                tags = event.get('tags', [])

                is_nested_in_tool = any('tool' in str(pid).lower() for pid in parent_ids) or \
                                   any('tool' in str(tag).lower() for tag in tags) or \
                                   metadata.get('langgraph_node') == 'tools'

                if is_nested_in_tool and tool_io_message:
                    last_tool = list(tool_io_message.keys())[-1] if tool_io_message else None
                    if last_tool:
                        logger.debug(f"Nested LLM started for tool: {last_tool}")

            if event["event"] == "on_chat_model_end":
                metadata = event.get('metadata', {})
                parent_ids = event.get('parent_ids', [])
                tags = event.get('tags', [])

                is_nested_in_tool = any('tool' in str(pid).lower() for pid in parent_ids) or \
                                   any('tool' in str(tag).lower() for tag in tags) or \
                                   metadata.get('langgraph_node') == 'tools'

                if not is_nested_in_tool and config_settings.ENABLE_PROMPT_CACHING:
                    try:
                        msg = event.get('data', {}).get('output')
                        usage = getattr(msg, 'usage_metadata', None)
                        if usage is not None:
                            token_details = usage.get('input_token_details', {}) if isinstance(usage, dict) else getattr(usage, 'input_token_details', {})
                            cache_read = (token_details or {}).get('cache_read', 0) if isinstance(token_details, dict) else getattr(token_details, 'cache_read', 0)
                            cache_creation = (token_details or {}).get('cache_creation', 0) if isinstance(token_details, dict) else getattr(token_details, 'cache_creation', 0)
                            input_tokens = usage.get('input_tokens', 0) if isinstance(usage, dict) else getattr(usage, 'input_tokens', 0)
                            output_tokens = usage.get('output_tokens', 0) if isinstance(usage, dict) else getattr(usage, 'output_tokens', 0)
                            logger.info(f"LLM usage: input={input_tokens}, output={output_tokens}, cache_read={cache_read}, cache_creation={cache_creation}")
                            last_usage_stats = {
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "cache_read": cache_read,
                                "cache_creation": cache_creation,
                            }
                    except Exception as e:
                        logger.debug(f"Could not extract usage from on_chat_model_end: {e}")

                if not is_nested_in_tool and final_answer_started and start and not answer_end_sent:
                    answer_end_sent = True
                    logger.info("Ending answer stream (eager, on_chat_model_end)")
                    if last_usage_stats:
                        await websocket.send_json({
                            "type": "stream",
                            "content_type": "usage_stats",
                            "message": last_usage_stats,
                        })
                    await websocket.send_json({
                        "type": MESSAGE_TYPE_END,
                        "content_type": CONTENT_TYPE_ANSWER,
                        "message": ""
                    })

            if event["event"] == "on_tool_end":
                tool_name_end = event.get('name', 'unknown')

                if tool_name_end not in tools_name:
                    logger.debug(f"Skipping non-UI tool end: {tool_name_end}")
                    continue

                final_answer_started = False

                output_data = event.get('data', {}).get('output', {})

                if hasattr(output_data, 'content'):
                    output_str = str(output_data.content)
                elif isinstance(output_data, dict):
                    output_str = json.dumps(output_data, default=str)
                else:
                    output_str = str(output_data)

                logger.info(f"Tool {tool_name_end} completed. Output: {output_str[:300]}")

                current_tool_key_end = tool_io_message.get(tool_name_end, str(tool_sequence_num))

                await websocket.send_json({
                    "type": "stream",
                    "content_type": "tool_end",
                    "message": {
                        'tool_key': current_tool_key_end,
                    }
                })
                logger.info(f"Sent tool_end for {tool_name_end} with key {current_tool_key_end}")


            if (
                event["event"] == "on_chain_end"
                and any(t.startswith("graph:step:") for t in event.get("tags", []))
                and (
                    (
                            isinstance(event["data"]["output"], dict) and "messages" in event["data"]["output"])
                    or (
                            hasattr(event["data"]["output"], 'update') and isinstance(event["data"]["output"].update, dict) and
                        "messages" in event["data"]["output"].update
                    )
                )
            ):
                if isinstance(event["data"]["output"], dict):
                    new_messages = event["data"]["output"]["messages"]
                else:
                    new_messages = event["data"]["output"].update["messages"]

                if isinstance(new_messages, Overwrite):
                    new_messages = new_messages.value

                if not isinstance(new_messages, (list, tuple)):
                    logger.warning(f"new_messages is not iterable: {type(new_messages)}")
                    continue

                for message in new_messages:
                    if message is None or isinstance(message, (RemoveMessage, dict)):
                        continue

                    if hasattr(message, 'type') and message.type == 'remove':
                        continue

                    try:
                        if not isinstance(message, (AIMessage, HumanMessage, SystemMessage, ToolMessage)):
                            logger.warning(f"Skipping unsupported message type: {type(message)}")
                            continue

                        chat_message = ChatMessage.from_langchain(message)
                        chat_message.run_id = str(run_id)
                    except Exception as e:
                        await websocket.send_json({
                            "type": MESSAGE_TYPE_ERROR,
                            "content_type": None,
                            "message": f"Error parsing message: {e}"
                        })
                        continue

                    if chat_message.type == "human" and chat_message.content == user_input.question:
                        continue

            if event["event"] == "on_chat_model_stream":
                metadata = event.get('metadata', {})
                langgraph_node = metadata.get('langgraph_node', '')
                chunk = event.get("data", {}).get("chunk")
                chunk_content = chunk.content if chunk and hasattr(chunk, 'content') else None

                if langgraph_node != 'model':
                    continue

                if not chunk_content:
                    continue

                raw_content = chunk_content
                content = ""

                if isinstance(raw_content, list):
                    text_parts = []
                    for block in raw_content:
                        if isinstance(block, dict):
                            if "text" in block:
                                text_parts.append(block["text"])
                            elif block.get("type") == "text" and "text" in block:
                                text_parts.append(block["text"])
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = "".join(text_parts)
                elif isinstance(raw_content, str):
                    content = raw_content
                else:
                    try:
                        content = str(raw_content)
                    except Exception:
                        continue

                if not in_thinking and '<thinking' in content:
                    before = content.split('<thinking', 1)[0]
                    in_thinking = True
                    thinking_buffer = content[len(before):]
                    content = before
                    if not thinking_ack_sent:
                        thinking_ack_sent = True
                        try:
                            await websocket.send_json({
                                "type": "stream",
                                "content_type": "agent_thinking",
                                "message": "..."
                            })
                        except Exception:
                            pass
                elif in_thinking:
                    thinking_buffer += content
                    if '</thinking>' in thinking_buffer:
                        after = thinking_buffer.split('</thinking>', 1)[1]
                        in_thinking = False
                        thinking_buffer = ""
                        content = after
                        try:
                            await websocket.send_json({
                                "type": "stream",
                                "content_type": "agent_thinking",
                                "message": ""
                            })
                        except Exception:
                            pass
                    else:
                        content = ""

                if not content:
                    continue

                has_tool_calls = len(
                    event["data"]["chunk"].tool_calls
                ) > 0 if hasattr(event["data"]["chunk"], 'tool_calls') and event["data"]["chunk"].tool_calls else False

                has_tool_call_chunks = hasattr(
                    event["data"]["chunk"], 'tool_call_chunks'
                ) and event["data"]["chunk"].tool_call_chunks and len(event["data"]["chunk"].tool_call_chunks) > 0

                if has_tool_calls or has_tool_call_chunks:
                    if content:
                        if not tools_have_executed:
                            pending_agent_text += content
                            if pending_agent_text.strip():
                                try:
                                    await websocket.send_json({
                                        "type": "stream",
                                        "content_type": "agent_thinking",
                                        "message": pending_agent_text.strip()
                                    })
                                except Exception:
                                    pass
                        else:
                            post_tool_buffer += content
                    final_answer_started = False
                    continue

                if not tools_have_executed:
                    if content:
                        if not initial_ack_cleared:
                            initial_ack_cleared = True
                            try:
                                await websocket.send_json({
                                    "type": "stream",
                                    "content_type": "agent_thinking",
                                    "message": ""
                                })
                            except Exception:
                                pass
                        pre_tool_streamed_text += content
                        pre_tool_streamed_len += len(content)
                        await websocket.send_json({
                            "type": "stream",
                            "content_type": None,
                            "message": content
                        })
                    continue

                if not final_answer_started:
                    final_answer_started = True
                    if not initial_ack_cleared:
                        initial_ack_cleared = True
                        try:
                            await websocket.send_json({
                                "type": "stream",
                                "content_type": "agent_thinking",
                                "message": ""
                            })
                        except Exception:
                            pass
                    if post_tool_buffer:
                        logger.info(
                            f"Flushing post-tool buffer as answer start ({len(post_tool_buffer)} chars): {post_tool_buffer[:80]}.."
                        )
                        if not start:
                            await websocket.send_json({
                                "type": MESSAGE_TYPE_START,
                                "content_type": CONTENT_TYPE_ANSWER,
                                "message": ""
                            })
                            start = True
                        await websocket.send_json({
                            "type": "stream",
                            "content_type": None,
                            "message": post_tool_buffer
                        })
                        post_tool_buffer = ""
                    logger.info("Final answer streaming started")

                if not start:
                    await websocket.send_json({
                        "type": MESSAGE_TYPE_START,
                        "content_type": CONTENT_TYPE_ANSWER,
                        "message": ""
                    })
                    start = True

                if content:
                    await websocket.send_json({
                        "type": "stream",
                        "content_type": None,
                        "message": content
                    })

                continue

    except Exception as e:
        logger.error(f"Error in event stream processing: {type(e).__name__}: {str(e)}", exc_info=True)
        try:
            if start:
                await websocket.send_json({
                    "type": MESSAGE_TYPE_END,
                    "content_type": CONTENT_TYPE_ANSWER,
                    "message": ""
                })
        except Exception as send_err:
            logger.error(f"Failed to send end message after error: {send_err}")
        try:
            await event_stream.aclose()
        except Exception as close_err:
            logger.warning(f"Error closing event stream on exception: {close_err}")
        raise
    finally:
        if cancel_event and cancel_event.is_set():
            try:
                await event_stream.aclose()
            except Exception:
                pass

    if not tools_have_executed:
        flush_text = ""
        if pre_tool_streamed_text.strip():
            unstreamed_pre = pre_tool_streamed_text[pre_tool_streamed_len:]
            if pre_tool_streamed_len > 0:
                logger.info(
                    f"Pre-tool text already streamed ({pre_tool_streamed_len} chars). "
                    f"Unstreamed remainder: {len(unstreamed_pre)} chars"
                )
                await websocket.send_json({
                    "type": "stream",
                    "content_type": "agent_thinking",
                    "message": ""
                })
                if unstreamed_pre.strip():
                    await websocket.send_json({
                        "type": "stream",
                        "content_type": None,
                        "message": unstreamed_pre
                    })
            else:
                flush_text = pre_tool_streamed_text.strip()
                logger.info(f"Flushing pre-tool text as final response ({len(flush_text)} chars): {flush_text[:80]}...")
        elif pending_agent_text.strip():
            flush_text = pending_agent_text.strip()
            logger.info(f"Flushing pending text as final response ({len(flush_text)} chars): {flush_text[:80]}...")

        if flush_text:
            if not start:
                await websocket.send_json({
                    "type": MESSAGE_TYPE_START,
                    "content_type": CONTENT_TYPE_ANSWER,
                    "message": ""
                })
                start = True

            await websocket.send_json({
                "type": "stream",
                "content_type": "agent_thinking",
                "message": ""
            })
            await websocket.send_json({
                "type": "stream",
                "content_type": None,
                "message": flush_text
            })

    elif tools_have_executed and post_tool_buffer.strip() and not final_answer_started:
        flush_text = post_tool_buffer.strip()
        logger.info(f"Flushing post-tool buffer as final answer ({len(flush_text)} chars): {flush_text[:80]}...")
        if not start:
            await websocket.send_json({
                "type": MESSAGE_TYPE_START,
                "content_type": CONTENT_TYPE_ANSWER,
                "message": ""
            })
            start = True
        await websocket.send_json({
            "type": "stream",
            "content_type": None,
            "message": flush_text
        })
        post_tool_buffer = ""

    if start and not answer_end_sent:
        if last_usage_stats:
            await websocket.send_json({
                "type": "stream",
                "content_type": "usage_stats",
                "message": last_usage_stats,
            })
        logger.info("Ending answer stream")
        await websocket.send_json({
            "type": MESSAGE_TYPE_END,
            "content_type": CONTENT_TYPE_ANSWER,
            "message": ""
        })

    state = await agent.aget_state({
        "configurable": {
            "thread_id": kwargs["config"]["configurable"]["thread_id"],
            "run_id": kwargs["config"]["run_id"],
        }
    })

    if state.tasks and len(state.tasks) > 0:
        task = state.tasks[0]
        if task and task.interrupts:
            logger.info(f"Interrupts: {task.interrupts}")
            return True
        else:
            return False

    return False

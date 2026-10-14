import asyncio
import time
import json

from loguru import logger
from fastapi import WebSocket

from langgraph.graph.state import CompiledStateGraph
from langgraph.errors import GraphRecursionError

from workflows.models import HumanFeedback
from workflows.state_schema import StreamInput
from workflows.generator import process_stream
from workflows.utils import tools_name

from workflows.core import MESSAGE_TYPE_START, MESSAGE_TYPE_END, CONTENT_TYPE_ANSWER
from workflows.core.chat_utils.utils import send_message_over_websocket


async def message_generator(
        user_input: StreamInput,
        websocket: WebSocket,
        run_id: str,
        kwargs,
        agent: CompiledStateGraph,
        cancel_event: asyncio.Event = None,
        message_queue: asyncio.Queue = None,
):
    logger.info(
        f"message_generator called: thread_id={kwargs.get('config', {}).get('configurable', {}).get('thread_id')}"
    )

    process_start_time = time.time()

    try:
        stream_start_time = time.time()
        graph_invoke = await process_stream(
            websocket,
            agent,
            user_input,
            run_id,
            kwargs,
            human_feedback=None,

            cancel_event=cancel_event
        )
        stream_time = time.time() - stream_start_time
        logger.info(f"Initial stream processing time: {stream_time:.2f} seconds")

    except GraphRecursionError as e:
        logger.error(f"GraphRecursionError: Query required too many steps. {str(e)}")
        await send_message_over_websocket(
            websocket,
            "I wasn't able to find the data you requested. "
            "This could mean the information doesn't exist for the given criteria, or I need you to be more specific. "
            "Could you try rephrasing your question?",
            message_type="stream",
            content_type=CONTENT_TYPE_ANSWER
        )
        await send_message_over_websocket(websocket, "", MESSAGE_TYPE_END, content_type=CONTENT_TYPE_ANSWER)
        return

    except Exception as e:
        logger.error(f"Error in initial stream processing: {str(e)}", exc_info=True)
        await send_message_over_websocket(
            websocket,
            "I apologize, but an error occurred while processing your request. Please try again.",
            message_type="stream",
            content_type=CONTENT_TYPE_ANSWER
        )
        await send_message_over_websocket(websocket, "", MESSAGE_TYPE_END, content_type=CONTENT_TYPE_ANSWER)
        return

    while graph_invoke:
        snapshot = await agent.aget_state({
            "configurable": {
                "thread_id": kwargs["config"]["configurable"]["thread_id"],
                "run_id": kwargs["config"]["run_id"],
            }
        })

        logger.info(f"Snapshot: {snapshot}")

        if snapshot.tasks and len(snapshot.tasks) > 0:
            task = snapshot.tasks[0]
            if task and task.interrupts:
                logger.info(f"Interrupts: {task.interrupts}")

                interrupt_value = task.interrupts[0].value
                summary_message = interrupt_value.get("summary")
                tools = task.interrupts[0].value.get("tool_call")

                if summary_message:
                    if tools and isinstance(tools, list) and len(tools) > 0:
                        tool_name = tools[0].get("name")
                        if tool_name:
                            await websocket.send_json({
                                "type": "stream",
                                "content_type": "tools",
                                "message": {
                                    'type': "tool",
                                    'tool_key': tool_name,
                                    'tool_name': tools_name.get(tool_name, tool_name),
                                    'tool_content': "Requires confirmation to proceed.",
                                    'tool_input': None,
                                }
                            })

                        await websocket.send_json({
                            "type": MESSAGE_TYPE_START,
                            "content_type": CONTENT_TYPE_ANSWER,
                            "message": ""
                        })
                        await websocket.send_json({
                            "type": "stream",
                            "content_type": None,
                            "message": summary_message
                        })

                    else:
                        logger.warning("Interrupt occurred but no summary found in payload. Using fallback.")

                        if isinstance(tools, str):
                            tool_names_str = tools
                            tool_display_names = [
                                tools_name.get(name.strip(), name.strip()) for name in
                                tool_names_str.split(',')
                                if name.strip()
                            ] if tool_names_str else []

                            formatted_tools = ", ".join(list(set(tool_display_names))) if tool_display_names else None

                            await websocket.send_json({
                                "type": "stream",
                                "content_type": "tools",
                                "message": {
                                    'type': "tool",
                                    'tool_key': tool_names_str,
                                    'tool_name': formatted_tools,
                                    'tool_content': "There seems to be missing or invalid information."
                                                    " Please provide the information properly.",
                                    'tool_input': None,
                                }
                            })
                            await websocket.send_json({
                                "type": MESSAGE_TYPE_START,
                                "content_type": CONTENT_TYPE_ANSWER,
                                "message": ""
                            })
                            await websocket.send_json({
                                "type": "stream",
                                "content_type": None,
                                "message": interrupt_value.get("task", "Please provide the required information.")
                            })
                        else:
                            await websocket.send_json(
                                {"type": MESSAGE_TYPE_START, "content_type": CONTENT_TYPE_ANSWER, "message": ""}
                            )
                            await websocket.send_json({
                                "type": "stream",
                                "content_type": None,
                                "message": "Please confirm if I should proceed with the requested action."
                            })

                    await websocket.send_text(json.dumps({
                        "type": MESSAGE_TYPE_END,
                        "content_type": None,
                        "message": ""
                    }))

                    if message_queue:
                        raw_feedback = await message_queue.get()
                        input_message = json.dumps(raw_feedback) if isinstance(raw_feedback, dict) else raw_feedback
                    else:
                        input_message = await websocket.receive_text()
                    human_feedback = HumanFeedback(**json.loads(input_message))

                    await send_message_over_websocket(websocket, "", MESSAGE_TYPE_START)

                    try:
                        additional_stream_start = time.time()
                        graph_invoke = await process_stream(
                            websocket,
                            agent,
                            user_input,
                            run_id,
                            kwargs,
                            human_feedback=human_feedback,
                            cancel_event=cancel_event,
                        )
                        additional_stream_time = time.time() - additional_stream_start
                        logger.info(
                            f"Additional stream processing time after human feedback: {additional_stream_time:.2f} seconds"
                        )

                    except GraphRecursionError as e:
                        logger.error(f"GraphRecursionError after feedback: {str(e)}")
                        await send_message_over_websocket(
                            websocket,
                            "I wasn't able to complete the request. Could you try rephrasing or simplifying your question?",
                            message_type="stream",
                            content_type=CONTENT_TYPE_ANSWER
                        )
                        await send_message_over_websocket(websocket, "", MESSAGE_TYPE_END, content_type=CONTENT_TYPE_ANSWER)
                        break

                    except Exception as e:
                        logger.error(f"Error in additional stream processing: {str(e)}", exc_info=True)
                        await send_message_over_websocket(
                            websocket,
                            "I apologize, but an error occurred while processing your feedback. Please try again.",
                            message_type="stream",
                            content_type=CONTENT_TYPE_ANSWER
                        )
                        await send_message_over_websocket(websocket, "", MESSAGE_TYPE_END, content_type=CONTENT_TYPE_ANSWER)
                        break

                total_process_time = time.time() - process_start_time
                logger.info(f"Total message generation time: {total_process_time:.2f} seconds")

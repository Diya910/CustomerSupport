from uuid import uuid4
from typing import Any

from loguru import logger
from fastapi.websockets import WebSocket

from workflows.core.settings import config_settings
from workflows.state_schema import ChatMessage, UserInput, AgentState

from workflows.tools import ALL_TOOLS
from langchain_core.tools import tool
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import (
    RunnableLambda,
    RunnableSerializable,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    SystemMessage,
)


tools_name = {
    "lookup_customer":      "Customer Lookup",
    "lookup_order":         "Order Lookup",
    "get_customer_orders":  "Order History",
    "check_refund_history": "Refund History Check",
    "search_knowledge_base": "Policy Search",
    "approve_refund":       "Refund Approved",
    "deny_refund":          "Refund Denied",
    "text_to_sql":          "Returns Analytics",
}


tool_output = {
    "lookup_customer":      "Looking up customer profile and account status",
    "lookup_order":         "Retrieving order details and delivery information",
    "get_customer_orders":  "Loading order history for this customer",
    "check_refund_history": "Checking for prior refund requests on this order",
    "search_knowledge_base": "Searching knowledge base for policy rules",
    "approve_refund":       "Recording approved refund decision",
    "deny_refund":          "Recording denied refund decision",
    "text_to_sql":          "Querying ecommerce returns data for analytics",
}


SAFE_TOOLS = [t.name for t in ALL_TOOLS]
SENSITIVE_TOOLS = []


async def parse_input(
        token,
        user_input: UserInput,
        websocket: WebSocket,
        run_id: str = ""
) -> tuple[dict[str, Any], str]:
    run_id = run_id or str(uuid4())
    thread_id = user_input.thread_id or str(uuid4())

    input_message = ChatMessage(type="human", content=user_input.question)

    config_dict = {
        "thread_id": thread_id,
        "chat_context": user_input.chat_context,
        "language": user_input.language,
        "stored_language": "",
        "namespace": user_input.namespace,
        "original_question": user_input.question,
    }

    kwargs = {
        "input": {"messages": [input_message.to_langchain()]},
        "stream_mode": ["updates", "messages"],
        "config": {
            "configurable": config_dict,
            "run_id": run_id,
            "recursion_limit": config_settings.DEEP_AGENT_RECURSION_LIMIT,
        }
    }

    return kwargs, run_id


def _bind_tools_with_cache(model: BaseChatModel, tools: list) -> BaseChatModel:
    bound = model.bind_tools(tools)
    tool_defs = bound.kwargs.get("tools", [])
    if tool_defs:
        tool_defs[-1] = {**tool_defs[-1], "cache_control": {"type": "ephemeral"}}
    return bound


def wrap_model(
        model: BaseChatModel,
        tools: list[tool],
        system_prompt: str = "",
        dynamic_context: str = ""
) -> RunnableSerializable[AgentState, AIMessage]:
    if config_settings.ENABLE_PROMPT_CACHING and tools:
        model = _bind_tools_with_cache(model, tools)
    else:
        model = model.bind_tools(tools)
    logger.info(f"Model bound with {len(tools)} tools (cache={'enabled' if config_settings.ENABLE_PROMPT_CACHING else 'disabled'})")

    if system_prompt:
        if config_settings.ENABLE_PROMPT_CACHING:
            system_content = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                },
            ]
            if dynamic_context:
                system_content.append({"type": "text", "text": dynamic_context})
            system_msg = SystemMessage(content=system_content)
        else:
            full_prompt = f"{system_prompt}\n\n{dynamic_context}" if dynamic_context else system_prompt
            system_msg = SystemMessage(content=full_prompt)

        preprocessor = RunnableLambda(
            lambda state: [system_msg] + state["messages"],
            name="StateModifier",
        )
    else:
        preprocessor = RunnableLambda(
            lambda state: state["messages"],
            name="StateModifier",
        )

    return preprocessor | model



def initialise_pre_grounding_prompt_template():
    prompt_template = """
You are a helpful query preprocessor. Given a user query and optional chat history, produce TWO outputs:

1. **ACKNOWLEDGEMENT**: A brief, natural, first-person response that signals the assistant is working on the user's request. Keep it to ONE short sentence maximum.
   - For QA/performance analytics requests: briefly describe what you're about to look up (e.g., "Let me check your QA score.").
   - For anything outside QA/performance analytics (coding, jokes, general knowledge, opinions, etc.): do NOT promise to do the task. Keep it neutral and brief — the main agent decides what to do.
   - For conversational messages (greetings, thanks, small talk, farewell): keep it extremely brief — a few words at most. The main agent handles the full response.

2. **QUERY**: The reformulated standalone query. Rules:
   - Reformulate to be grammatically correct and self-contained using chat history context if needed.
   - **CRITICAL: Preserve the original intent exactly.** If the user's message is conversational (greeting, thanks, small talk, farewell), output it as-is — do NOT transform it into a question about capabilities or features. "Hi" stays "Hi", "Thanks" stays "Thanks".
   - Keep compound questions as a SINGLE sentence (e.g. "What is my QA score and how can I improve?" stays as one query — do NOT split into numbered bullets or separate questions).
   - Do NOT add information beyond what the user asked. Do NOT optimize for specific tools.
   - Do NOT inflate the user's intent — if they didn't ask a question, don't create one.

**Language**: If target_language is "auto", match the user's language. Otherwise translate to target_language.

**Chat History**:
{chat_history}

**User Question**:
{question}

**Target Language**:
{target_language}

**Output** (use EXACTLY this format):
ACKNOWLEDGEMENT: <your brief acknowledgement>
QUERY: <reformulated query>
"""

    return PromptTemplate(
        template=prompt_template,
        input_variables=["question", "chat_history", "target_language"],
    )

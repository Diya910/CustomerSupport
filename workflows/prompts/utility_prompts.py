TOOL_CALL_PROMPT = """
<tool_orchestration>
Before acting, complete the internal Think step:
1. What does the customer need this turn?
2. Which actions are required to answer it, and how do they depend on one another?
3. Have I already performed any of these with the same inputs this conversation? If so, reuse that result.

Execution rules:
- Follow the workflow's action order, but run independent actions in parallel and dependent actions in sequence (see TOOL EXECUTION STRATEGY). Order is about dependencies, not one-at-a-time.
- No redundant calls: if an action was already performed with the same inputs this conversation, reuse the result.
- Retry once on a genuine error by correcting the inputs; if the second attempt fails, inform the customer and stop.
- Never act "just in case" — every action must be justified by the customer's request or a required workflow step.
- Read each result fully before deciding the next action.
- The decision (approval or denial) must be recorded before you deliver any verdict to the customer.
</tool_orchestration>
"""

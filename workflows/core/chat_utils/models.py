from typing import Literal

from pydantic import BaseModel


class ChatResponse(BaseModel):
    """Chat response schema."""

    message: str
    type: Literal["start", "stream", "end", "blob", "error", "info"]
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
    ) = None
import re
import unicodedata

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union

from workflows.core.settings import config_settings


CONTROL_CHAR_RE = re.compile(
    r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f'
    r'​-‏ - ⁠-⁯﻿￹-￼]'
)


class HumanFeedback(BaseModel):
    question: Union[str, dict]


class Message(BaseModel):
    type: str
    content: str


class AgentRequestModel(BaseModel):
    question: Optional[str] = Field(None, max_length=config_settings.QUESTION_MAX_LENGTH)
    language: str = "English"
    chat_context: Optional[List[Message]] = None
    namespace: Optional[str] = None
    thread_id: Optional[str] = None
    graph_initialization: Optional[bool] = False

    @field_validator('question', mode='before')
    @classmethod
    def sanitize_question(cls, v):
        if v is None:
            return v
        if not isinstance(v, str):
            v = str(v)
        v = unicodedata.normalize('NFC', v)
        v = CONTROL_CHAR_RE.sub('', v)
        v = v.strip()
        if len(v) > config_settings.QUESTION_MAX_LENGTH:
            v = v[:config_settings.QUESTION_MAX_LENGTH]
        return v

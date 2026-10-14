from enum import Enum
from pydantic import BaseModel

from typing import Union, Optional, List


class Message(BaseModel):
    type: str
    content: str


class ProcessStatusEnum(str, Enum):
    """Enumeration of possible process statuses."""
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

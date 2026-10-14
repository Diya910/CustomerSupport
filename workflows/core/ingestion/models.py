from typing import Any, Dict, Optional
from pydantic import BaseModel

from workflows.core.models import ProcessStatusEnum


class IngestionRequestDto(BaseModel):
    request_id: Optional[str] = None
    pre_signed_url: Optional[str] = None
    file_name: Optional[str] = None
    file_type: str = "txt"
    index_name: Optional[str] = None
    namespace_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class IngestionResponseDto(BaseModel):
    request_id: Optional[str] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    chunk_count: Optional[int] = None
    status: ProcessStatusEnum = ProcessStatusEnum.PROCESSING
    error_detail: Optional[str] = None

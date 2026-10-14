from pydantic import BaseModel

from typing import Any, List, Optional
from langchain_core.documents import Document


class ClientResponseDto(BaseModel):
    status_code: bool
    client: Optional[Any] = None


class ConnectionResponseDto(BaseModel):
    status: bool = False
    client: object = None
    manager: Optional[object] = None
    message: Optional[str] = None


class RetrievalRequest(BaseModel):
    request_id: int = None
    query: str
    top_k: int = 10
    index_name: Optional[str] = None
    namespace: Optional[str] = None


class RetrievalResponse(BaseModel):
    request_id: str
    user_query: str
    document_chunks: List[Document] = None
    total_images: int = 0
    total_chunks: int = 0
    error: Optional[str] = None


class WeaviateConfig(BaseModel):
    index_name: str = None
    namespace: str = None


class DeleteResponseDto(BaseModel):
    status: bool = False
    index: Optional[str] = None
    namespace: Optional[str] = None
    filename: Optional[str] = None
    timestamp: Optional[str] = None
    error: Optional[str] = None


class PushToDatabaseResponseDto(BaseModel):
    status: bool = False
    document_ids: List[str] = []
    index: Optional[str] = None
    namespace: Optional[str] = None
    timestamp: Optional[str] = None
    error: Optional[str] = None


class FileDeleteRequestDto(BaseModel):
    filename: str
    index_name: Optional[str] = None
    namespace: Optional[str] = None


class NamespaceDeleteRequestDto(BaseModel):
    namespace: str
    index_name: Optional[str] = None


class IndexDeleteRequestDto(BaseModel):
    index_name: str

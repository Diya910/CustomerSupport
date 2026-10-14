import asyncio
import os
import ssl
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List
from urllib.parse import urlparse
from urllib.request import urlopen

from loguru import logger

from workflows.core.vector_db.date_filter_utils import get_current_timestamp_ms
from workflows.core.models import ProcessStatusEnum
from workflows.core.settings import config_settings
from workflows.core.loader.file_loader import FileLoader
from workflows.core.loader.utils import split_text
from workflows.core.vector_db.utils import push_to_vectordb
from workflows.core.ingestion.models import IngestionRequestDto, IngestionResponseDto


async def load_file_push_to_db(
        request: IngestionRequestDto | List[IngestionRequestDto]
) -> IngestionResponseDto | List[IngestionResponseDto]:
    if isinstance(request, list):
        tasks = [ process_single_request(req) for req in request ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        responses: List[IngestionResponseDto] = []
        for req, result in zip(request, results):
            if isinstance(result, Exception):
                logger.error(f"Ingestion failed for request_id={req.request_id}: {result}")
                responses.append(
                    IngestionResponseDto(
                        request_id=req.request_id,
                        file_path=req.pre_signed_url,
                        file_name=req.file_name,
                        chunk_count=0,
                        status=ProcessStatusEnum.FAILED,
                        error_detail=str(result),
                    )
                )
            else:
                responses.append(result)
        return responses
    return await process_single_request(request)


async def process_single_request(request: IngestionRequestDto) -> IngestionResponseDto:
    if not request:
        return IngestionResponseDto(
            request_id=None,
            file_path=None,
            file_name=None,
            chunk_count=0,
            status=ProcessStatusEnum.FAILED,
            error_detail="Ingestion request payload is empty",
        )

    if not request.pre_signed_url:
        return IngestionResponseDto(
            request_id=request.request_id,
            file_path=None,
            file_name=request.file_name,
            chunk_count=0,
            status=ProcessStatusEnum.FAILED,
            error_detail="pre_signed_url is required for ingestion",
        )

    agent_namespace = request.namespace_name or config_settings.DEFAULT_NAMESPACE
    if not agent_namespace:
        return IngestionResponseDto(
            request_id=request.request_id,
            file_path=request.pre_signed_url,
            file_name=request.file_name,
            chunk_count=0,
            status=ProcessStatusEnum.FAILED,
            error_detail="Unable to resolve namespace for ingestion",
        )

    cleanup_paths: List[str] = []
    try:
        local_path, should_cleanup, derived_name = await asyncio.to_thread(
            prepare_presigned_entry, request.pre_signed_url
        )
        if should_cleanup:
            cleanup_paths.append(local_path)
    except Exception as exc:
        logger.error(f"Failed to prepare ingestion input: {exc}")
        return IngestionResponseDto(
            request_id=request.request_id,
            file_path=request.pre_signed_url,
            file_name=request.file_name,
            chunk_count=0,
            status=ProcessStatusEnum.FAILED,
            error_detail=str(exc),
        )

    resolved_name = request.file_name or derived_name

    metadata_payload: Dict[str, Any] = {}
    if isinstance(request.metadata, dict):
        metadata_payload.update(request.metadata)
    metadata_payload.setdefault("agent_id", agent_namespace)
    metadata_payload.setdefault("namespace", agent_namespace)
    metadata_payload.setdefault("file_name", resolved_name)
    metadata_payload.setdefault("ingestion_datetime", get_current_timestamp_ms())

    try:
        loader = FileLoader(local_path, process_type=request.file_type)
        raw_docs = await asyncio.to_thread(loader.load)

        chunks = split_text(
            raw_docs,
            chunk_size=config_settings.CHUNK_SIZE,
            chunk_overlap=config_settings.CHUNK_OVERLAP,
        )

        for doc in chunks:
            doc.metadata.update(metadata_payload)

        documents = chunks

        ingestion_result = await push_to_vectordb(
            documents,
            request.index_name,
            agent_namespace,
            resolved_name,
        )

        vector_count = ingestion_result.get("vector_count", 0) if isinstance(ingestion_result, dict) else 0
        status = ProcessStatusEnum.COMPLETED if vector_count > 0 else ProcessStatusEnum.FAILED
        error_detail = ingestion_result.get("error") if isinstance(ingestion_result, dict) else None

        return IngestionResponseDto(
            request_id=request.request_id,
            file_path=request.pre_signed_url,
            file_name=resolved_name,
            chunk_count=vector_count,
            status=status,
            error_detail=error_detail,
        )

    except Exception as exc:
        logger.error(f"Ingestion pipeline failed for file {resolved_name}: {exc}")
        return IngestionResponseDto(
            request_id=request.request_id,
            file_path=request.pre_signed_url,
            file_name=resolved_name,
            chunk_count=0,
            status=ProcessStatusEnum.FAILED,
            error_detail=str(exc),
        )
    finally:
        cleanup_paths_if_needed(cleanup_paths)


def cleanup_paths_if_needed(paths: List[str]) -> None:
    for entry in paths:
        try:
            if entry and os.path.exists(entry):
                os.remove(entry)
        except Exception as exc:
            logger.warning(f"Failed to cleanup temporary file {entry}: {exc}")


def prepare_presigned_entry(value: str) -> tuple[str, bool, str]:
    if os.path.exists(value):
        return value, False, os.path.basename(value)
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        local_path = download_http_file(value)
        file_name = os.path.basename(parsed.path) or "document.txt"
        return local_path, True, file_name
    raise FileNotFoundError("File path does not exist")


def download_http_file(url: str) -> str:
    suffix = suffix_from_url(url)
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urlopen(url, context=ctx) as response, NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        data = response.read()
        handle.write(data)
        return handle.name


def suffix_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = os.path.basename(parsed.path)
    if "." in name:
        return name[name.rfind("."):]
    return ".txt"

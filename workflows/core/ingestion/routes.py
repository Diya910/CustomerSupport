import asyncio
import os
from pathlib import Path
from typing import List, Union

import boto3
from loguru import logger
from fastapi import APIRouter, HTTPException

from workflows.core.models import ProcessStatusEnum
from workflows.core.settings import config_settings
from workflows.core.ingestion.utils import load_file_push_to_db
from workflows.core.ingestion.models import IngestionRequestDto, IngestionResponseDto


router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post(
    "/ingest",
    response_model=
    Union[
        IngestionResponseDto,
        List[IngestionResponseDto]
    ])
async def ingest_doc(
        request: Union[IngestionRequestDto, List[IngestionRequestDto]]
) -> Union[IngestionResponseDto, List[IngestionResponseDto]]:
    try:
        requests: List[IngestionRequestDto] = request if isinstance(request, list) else [request]

        initial_responses: List[IngestionResponseDto] = [
            IngestionResponseDto(
                request_id=req.request_id,
                file_name=req.file_name,
                status=ProcessStatusEnum.PROCESSING,
            )
            for req in requests
        ]

        result = await load_file_push_to_db(requests if isinstance(request, list) else requests[0])

        if isinstance(request, list):
            if not isinstance(result, list):
                result = [result]

            merged: List[IngestionResponseDto] = []
            for idx, res in enumerate(result):
                try:
                    if isinstance(res, IngestionResponseDto):
                        merged.append(res)
                    else:
                        merged.append(
                            IngestionResponseDto(
                                request_id=initial_responses[idx].request_id,
                                file_name=initial_responses[idx].file_name,
                                status=ProcessStatusEnum.FAILED,
                                error_detail="Invalid response payload"
                            )
                        )
                except Exception as e:
                    merged.append(
                        IngestionResponseDto(
                            request_id=initial_responses[idx].request_id,
                            file_name=initial_responses[idx].file_name,
                            status=ProcessStatusEnum.FAILED,
                            error_detail=str(e),
                        )
                    )
            return merged
        else:
            if isinstance(result, IngestionResponseDto):
                return result
            # Coerce non-conforming result
            return IngestionResponseDto(
                request_id=initial_responses[0].request_id,
                file_name=initial_responses[0].file_name,
                status=ProcessStatusEnum.FAILED,
                error_detail="Invalid response payload",
            )

    except HTTPException:
        raise

    except Exception as exc:
        if not isinstance(request, list):
            return IngestionResponseDto(
                request_id=getattr(request, "request_id", None),
                file_name=getattr(request, "file_name", None),
                status=ProcessStatusEnum.FAILED,
                error_detail=str(exc),
            )
        failed_list: List[IngestionResponseDto] = [
            IngestionResponseDto(
                request_id=getattr(req, "request_id", None),
                file_name=getattr(req, "file_name", None),
                status=ProcessStatusEnum.FAILED,
                error_detail=str(exc),
            )
            for req in request
        ]
        return failed_list




@router.get("/documents")
async def list_ingested_documents():
    """List documents stored in the policy S3 bucket."""
    bucket = config_settings.POLICY_S3_BUCKET
    prefix = config_settings.POLICY_S3_PREFIX

    try:
        s3 = boto3.client("s3", region_name="us-east-1")
        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        contents = response.get("Contents", [])

        documents = []
        for obj in contents:
            key = obj["Key"]
            if key == prefix:
                continue
            documents.append({
                "filename": key.replace(prefix, ""),
                "s3_key": key,
                "size_bytes": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
            })

        return {"documents": documents, "count": len(documents), "bucket": bucket}

    except Exception as e:
        logger.error(f"[ADMIN] Error listing documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")


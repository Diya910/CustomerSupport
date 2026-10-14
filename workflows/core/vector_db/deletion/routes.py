from fastapi import APIRouter, HTTPException
from loguru import logger

from workflows.core.vector_db.models import FileDeleteRequestDto, NamespaceDeleteRequestDto, IndexDeleteRequestDto
from workflows.core.vector_db.models import DeleteResponseDto
from workflows.core.vector_db.deletion.deletion_utils import delete_by_filename, delete_namespace, delete_index
from workflows.core.settings import config_settings


router = APIRouter(prefix="/deletion", tags=["deletion"])


@router.post("/file", response_model=DeleteResponseDto)
async def delete_chunks_by_filename(
    request: FileDeleteRequestDto
) -> DeleteResponseDto:
    try:
        logger.info(f"Received request to delete chunks with filename '{request.filename}'")

        index_name = request.index_name or config_settings.INDEX_NAME
        namespace = request.namespace or config_settings.DEFAULT_NAMESPACE

        response = await delete_by_filename(
            index_name=index_name,
            namespace=namespace,
            filename=request.filename,
        )

        if not response.status:
            logger.error(f"Failed to delete chunks: {response.error}")

        return response

    except Exception as e:
        error_msg = f"Error processing deletion request: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/namespace", response_model=DeleteResponseDto)
async def delete_namespace_endpoint(
    request: NamespaceDeleteRequestDto
) -> DeleteResponseDto:
    try:
        logger.info(f"Received request to delete namespace '{request.namespace}'")

        index_name = request.index_name or config_settings.INDEX_NAME

        response = await delete_namespace(
            index_name=index_name,
            namespace=request.namespace,
        )

        if not response.status:
            logger.error(f"Failed to delete namespace: {response.error}")

        return response

    except Exception as e:
        error_msg = f"Error processing namespace deletion request: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/index", response_model=DeleteResponseDto)
async def delete_index_endpoint(
    request: IndexDeleteRequestDto
) -> DeleteResponseDto:
    try:
        logger.info(f"Received request to delete index '{request.index_name}'")

        response = await delete_index(
            index_name=request.index_name,
        )

        if not response.status:
            logger.error(f"Failed to delete index: {response.error}")

        return response

    except Exception as e:
        error_msg = f"Error processing index deletion request: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

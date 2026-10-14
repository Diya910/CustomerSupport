from datetime import datetime
from loguru import logger
from typing import Optional

from workflows.core.settings import config_settings, VectorDBServiceType
from workflows.core.vector_db.models import DeleteResponseDto
from workflows.core.vector_db.sanitization import sanitize_index_name
from workflows.core.vector_db.deletion.utils import delete_by_filename_opensearch
from workflows.core.vector_db.opensearch_utils.client import OpenSearchFactory


async def delete_namespace(
        index_name: str,
        namespace: str,
) -> Optional[DeleteResponseDto]:
    try:
        logger.info(f"Deleting namespace '{namespace}' from index '{index_name}'")

        if config_settings.VECTOR_DATABASE_TO_USE != VectorDBServiceType.OPENSEARCH.value:
            error_msg = f"Unsupported database type: {config_settings.VECTOR_DATABASE_TO_USE}. Only opensearch is supported."
            logger.error(error_msg)
            return DeleteResponseDto(
                status=False,
                index=index_name,
                namespace=namespace,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                error=error_msg,
                filename=None
            )

        return await delete_namespace_opensearch(index_name, namespace)

    except Exception as e:
        error_msg = f"Error deleting namespace '{namespace}' from index '{index_name}': {str(e)}"
        logger.error(error_msg)
        return DeleteResponseDto(
            status=False,
            index=index_name,
            namespace=namespace,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=error_msg,
            filename=None
        )


async def delete_namespace_opensearch(
        index_name: str,
        namespace: str,
) -> DeleteResponseDto:
    try:
        sanitized_index_name = sanitize_index_name(index_name, db_type="opensearch")

        factory = OpenSearchFactory(index_name=sanitized_index_name)
        success = factory.delete_namespace(namespace)

        if success:
            logger.info(f"Successfully deleted namespace '{namespace}' from OpenSearch")
            return DeleteResponseDto(
                status=True,
                index=index_name,
                namespace=namespace,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                filename=None
            )
        else:
            error_msg = f"Failed to delete namespace '{namespace}' from OpenSearch"
            logger.error(error_msg)
            return DeleteResponseDto(
                status=False,
                index=index_name,
                namespace=namespace,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                error=error_msg,
                filename=None
            )

    except Exception as e:
        error_msg = f"Error deleting namespace '{namespace}' from OpenSearch: {str(e)}"
        logger.error(error_msg)
        return DeleteResponseDto(
            status=False,
            index=index_name,
            namespace=namespace,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=error_msg,
            filename=None
        )


async def delete_by_filename(
        index_name: str,
        namespace: str,
        filename: str,
) -> DeleteResponseDto:
    if config_settings.VECTOR_DATABASE_TO_USE != VectorDBServiceType.OPENSEARCH.value:
        error_msg = f"Unsupported database type: {config_settings.VECTOR_DATABASE_TO_USE}. Only opensearch is supported."
        logger.error(error_msg)
        return DeleteResponseDto(
            status=False,
            index=index_name,
            namespace=namespace,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=error_msg,
            filename=filename
        )

    return await delete_by_filename_opensearch(index_name, namespace, filename)


async def delete_index(
        index_name: str,
) -> DeleteResponseDto:
    try:
        logger.info(f"Deleting index '{index_name}'")

        if config_settings.VECTOR_DATABASE_TO_USE != VectorDBServiceType.OPENSEARCH.value:
            error_msg = f"Unsupported database type: {config_settings.VECTOR_DATABASE_TO_USE}. Only opensearch is supported."
            logger.error(error_msg)
            return DeleteResponseDto(
                status=False,
                index=index_name,
                namespace=None,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                error=error_msg,
                filename=None
            )

        return await delete_index_opensearch(index_name)

    except Exception as e:
        error_msg = f"Error deleting index '{index_name}': {str(e)}"
        logger.error(error_msg)
        return DeleteResponseDto(
            status=False,
            index=index_name,
            namespace=None,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=error_msg,
            filename=None
        )


async def delete_index_opensearch(
        index_name: str,
) -> DeleteResponseDto:
    try:
        sanitized_index_name = sanitize_index_name(index_name, db_type="opensearch")

        factory = OpenSearchFactory(index_name=sanitized_index_name)
        success = factory.delete_index()

        if success:
            logger.info(f"Successfully deleted index '{index_name}' from OpenSearch")
            return DeleteResponseDto(
                status=True,
                index=index_name,
                namespace=None,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                filename=None
            )
        else:
            error_msg = f"Index '{index_name}' does not exist or failed to delete from OpenSearch"
            logger.error(error_msg)
            return DeleteResponseDto(
                status=False,
                index=index_name,
                namespace=None,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                error=error_msg,
                filename=None
            )

    except Exception as e:
        error_msg = f"Error deleting index '{index_name}' from OpenSearch: {str(e)}"
        logger.error(error_msg)
        return DeleteResponseDto(
            status=False,
            index=index_name,
            namespace=None,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=error_msg,
            filename=None
        )

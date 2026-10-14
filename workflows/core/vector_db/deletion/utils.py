from datetime import datetime

from loguru import logger

from workflows.core.vector_db.models import DeleteResponseDto
from workflows.core.vector_db.sanitization import sanitize_index_name
from workflows.core.vector_db.opensearch_utils.client import OpenSearchFactory


async def delete_by_filename_opensearch(
        index_name: str,
        namespace: str,
        filename: str,
) -> DeleteResponseDto:
    try:
        logger.info(
            f"Deleting chunks with filename '{filename}' from OpenSearch index '{index_name}', namespace '{namespace}'")

        sanitized_index_name = sanitize_index_name(index_name, db_type="opensearch")

        factory = OpenSearchFactory(index_name=sanitized_index_name)
        deleted_count = factory.delete_by_filename(namespace, filename)

        logger.info(f"Successfully deleted {deleted_count} documents for file '{filename}' from OpenSearch")

        return DeleteResponseDto(
            status=True,
            index=index_name,
            namespace=namespace,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            filename=filename
        )

    except Exception as e:
        error_msg = f"Error deleting from OpenSearch: {str(e)}"
        logger.error(error_msg)
        return DeleteResponseDto(
            status=False,
            index=index_name,
            namespace=namespace,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=error_msg,
            filename=filename
        )

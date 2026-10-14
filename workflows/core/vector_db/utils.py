import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger
from langchain_core.documents import Document

from workflows.core.settings import config_settings, VectorDBServiceType
from workflows.core.handler import retry_with_custom_backoff
from workflows.core.vector_db.opensearch_utils.client import OpenSearchFactory
from workflows.core.vector_db.deletion.deletion_utils import delete_by_filename


@retry_with_custom_backoff(
    max_retries=config_settings.BEDROCK_MAX_RETRY_ATTEMPTS,
    initial_delay=config_settings.BEDROCK_RETRY_BASE_DELAY_SEC,
    backoff_factor=2.0,
    max_delay=15.0,
)
async def push_to_vectordb(
        documents: List[Document],
        index_name: Optional[str] = None,
        namespace: Optional[str] = None,
        file_name: Optional[str] = None,
) -> Dict[str, Any]:
    if not documents:
        return {"vector_count": 0, "message": "No documents provided"}

    resolved_namespace = namespace or config_settings.DEFAULT_NAMESPACE

    if config_settings.VECTOR_DATABASE_TO_USE != VectorDBServiceType.OPENSEARCH.value:
        raise ValueError(f"Unsupported vector database backend: {config_settings.VECTOR_DATABASE_TO_USE}")

    resolved_index = index_name or config_settings.OPENSEARCH_INDEX_NAME
    factory = OpenSearchFactory(index_name=resolved_index)
    try:
        if file_name:
            logger.info(f"Checking for existing file '{file_name}' in namespace '{resolved_namespace}' before ingestion")

            await asyncio.to_thread(factory.ensure_index)

            client = await asyncio.to_thread(factory.get_client)

            delete_result = await asyncio.to_thread(
                factory.delete_existing,
                client,
                resolved_namespace,
                file_name,
            )
            if delete_result:
                logger.info(f"Deleted existing chunks for file '{file_name}' in namespace '{resolved_namespace}'")
            else:
                logger.info(f"No chunks found for file '{file_name}' in namespace '{resolved_namespace}' to be deleted")

        result = await asyncio.to_thread(
            factory.ingest_documents,
            documents,
            resolved_namespace,
            file_name,
        )
        return result

    except Exception as exc:
        error_message = str(exc)
        if "AuthenticationException" in error_message or "401" in error_message:
            logger.error(f"OpenSearch authentication failed. Please check OPENSEARCH_USERNAME and OPENSEARCH_PASSWORD in .env file: {exc}")

        elif "ConnectionError" in error_message:
            logger.error(f"OpenSearch connection failed. Please check OPENSEARCH_URL and network connectivity: {exc}")

        else:
            logger.error(f"OpenSearch ingestion failed: {exc}")
        return {"error": str(exc), "vector_count": 0}

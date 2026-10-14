import asyncio
from loguru import logger
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from workflows.core.settings import config_settings, VectorDBServiceType
from workflows.core.vector_db.sanitization import sanitize_index_name, sanitize_namespace
from workflows.core.vector_db.opensearch_utils.client import OpenSearchFactory


class DocumentSearchError(Exception):
    pass


async def get_related_docs_with_score(
    index_name: str = None,
    namespace: str = None,
    question: str = "",
    total_docs_to_retrieve: int = None,
    filter_value: Optional[str] = None,
    metadata_filters: Optional[Dict[str, Any]] = None,
    agent_id: Optional[str] = None,
) -> List[Tuple[Document, float]]:
    index_name = index_name or config_settings.INDEX_NAME
    namespace = namespace or config_settings.DEFAULT_NAMESPACE
    total_docs_to_retrieve = total_docs_to_retrieve or int(config_settings.NUMBER_OF_RETRIEVAL_RESULTS)

    try:
        sanitized_index_name = sanitize_index_name(index_name, db_type=config_settings.VECTOR_DATABASE_TO_USE)
        sanitized_namespace = sanitize_namespace(namespace, db_type=config_settings.VECTOR_DATABASE_TO_USE)

        logger.debug(
            f"Starting document search: index={sanitized_index_name}, "
            f"namespace={sanitized_namespace}, query_length={len(question)}, "
            f"top_k={total_docs_to_retrieve}, filter_value={filter_value}, "
            f"has_metadata_filters={bool(metadata_filters)}"
        )

        filters: Dict[str, Any] = {}
        if metadata_filters:
            filters.update(metadata_filters)
        if filter_value:
            filters["file_name"] = filter_value

        if config_settings.VECTOR_DATABASE_TO_USE != VectorDBServiceType.OPENSEARCH.value:
            logger.error(f"Unsupported database type: {config_settings.VECTOR_DATABASE_TO_USE}")
            return []

        factory = OpenSearchFactory(index_name=sanitized_index_name)
        documents = await factory.hybrid_search(
            question,
            sanitized_namespace,
            total_docs_to_retrieve,
            filters or None,
            agent_id=agent_id,
        )

        if not documents:
            logger.debug("Search returned no documents")
            return []

        doc_tuples = [(doc, doc.metadata.get("score", 1.0)) for doc in documents]
        logger.info(f"Search returned {len(doc_tuples)} candidate documents")
        return doc_tuples

    except asyncio.CancelledError:
        logger.warning("Document search was cancelled")
        raise

    except Exception as e:
        logger.error(f"Failed to get related docs: {e}", exc_info=True)
        return []


async def get_related_docs_without_context(
        index_name: str = None,
        namespace: str = None,
        question: str = "",
        total_docs_to_retrieve: int = 10
) -> List[Document]:
    try:
        results = await get_related_docs_with_score(
            index_name=index_name,
            namespace=namespace,
            question=question,
            total_docs_to_retrieve=total_docs_to_retrieve,
        )
        return [doc for doc, _ in results]

    except asyncio.CancelledError:
        logger.warning("Document retrieval was cancelled")
        raise

    except Exception as e:
        logger.error(f"Error in get_related_docs_without_context: {str(e)}", exc_info=True)
        return []


async def cleanup_factories() -> None:
    await OpenSearchFactory.cleanup()
    logger.debug("All vector database factories cleaned up")

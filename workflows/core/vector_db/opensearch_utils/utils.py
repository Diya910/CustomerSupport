from typing import Any, Dict, List, Optional

from loguru import logger
from langchain_core.documents import Document

from workflows.core.settings import config_settings
from workflows.core.vector_db.opensearch_utils.client import OpenSearchFactory


async def handle_opensearch_push(
        documents: List[Document],
        index_name: Optional[str] = None,
        namespace: Optional[str] = None,
        file_name: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        idx = index_name or config_settings.OPENSEARCH_INDEX_NAME
        ns = namespace or config_settings.DEFAULT_NAMESPACE
        logger.info(f"Starting OpenSearch ingestion to index: {idx}, namespace: {ns}")

        factory = OpenSearchFactory(index_name=idx)
        factory.ensure_index()

        if file_name:
            deleted_count = factory.delete_by_filename(ns, file_name)
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} existing documents for file '{file_name}'")

        if not documents:
            return {"vector_count": 0, "message": "No documents provided"}

        result = factory.ingest_documents(
            documents=documents,
            namespace=ns,
            file_name=file_name,
        )

        logger.info(f"Successfully ingested {result.get('vector_count', 0)} vectors to OpenSearch")
        return result

    except Exception as e:
        logger.error(f"Error in OpenSearch ingestion: {str(e)}")
        return {"error": str(e), "vector_count": 0}


async def query_opensearch(
        query: str,
        top_k: int = 10,
        index_name: Optional[str] = None,
        namespace: Optional[str] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        idx = index_name or config_settings.OPENSEARCH_INDEX_NAME
        ns = namespace or config_settings.DEFAULT_NAMESPACE

        factory = OpenSearchFactory(index_name=idx)

        documents = await factory.hybrid_search(
            query=query,
            namespace=ns,
            top_k=top_k,
            metadata_filters=metadata_filters,
        )

        logger.info(f"Retrieved {len(documents)} documents from OpenSearch")
        return {
            "documents": documents,
            "total_chunks": len(documents),
            "query_info": {
                "top_k": top_k,
                "namespace": ns,
                "metadata_filters": metadata_filters,
            },
        }

    except Exception as exc:
        logger.error(f"Error querying OpenSearch: {exc}")
        return {
            "documents": [],
            "total_chunks": 0,
            "error": str(exc),
            "query_info": {
                "top_k": top_k,
                "namespace": namespace,
                "metadata_filters": metadata_filters,
            },
        }


async def delete_by_filename_opensearch(
        index_name: str,
        namespace: str,
        filename: str,
) -> Dict[str, Any]:
    try:
        logger.info(f"Deleting documents with filename '{filename}' from OpenSearch index '{index_name}', namespace '{namespace}'")

        factory = OpenSearchFactory(index_name=index_name)
        deleted_count = factory.delete_by_filename(namespace, filename)

        return {
            "status": True,
            "deleted_count": deleted_count,
            "index": index_name,
            "namespace": namespace,
            "filename": filename,
        }

    except Exception as e:
        logger.error(f"Error deleting from OpenSearch: {str(e)}")
        return {
            "status": False,
            "deleted_count": 0,
            "error": str(e),
            "index": index_name,
            "namespace": namespace,
            "filename": filename,
        }

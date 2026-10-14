import asyncio
from loguru import logger
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig

from workflows.core.settings import config_settings, VectorDBServiceType
from workflows.core.vector_db.doc_search import get_related_docs_with_score
from workflows.core.vector_db.reranker import rerank_documents


class RetrievalError(Exception):
    pass


async def get_relevant_documents(
        request_id: int,
        query: str,
        top_k: Optional[int] = None,
        index_name: Optional[str] = None,
        file_filter: Optional[str] = None,
        namespace: Optional[str] = None,
        agent_id: Optional[str] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        config: Optional[RunnableConfig] = None,
) -> Dict[str, Any]:
    if config_settings.VECTOR_DATABASE_TO_USE == VectorDBServiceType.OPENSEARCH.value:
        resolved_index = index_name or config_settings.OPENSEARCH_INDEX_NAME
    elif config_settings.VECTOR_DATABASE_TO_USE == VectorDBServiceType.WEAVIATE.value:
        resolved_index = index_name or config_settings.INDEX_NAME
    else:
        resolved_index = index_name or config_settings.INDEX_NAME

    resolved_top_k = top_k or config_settings.NUMBER_OF_RETRIEVAL_RESULTS
    resolved_namespace = namespace or config_settings.DEFAULT_NAMESPACE
    resolved_timeout = timeout or config_settings.RETRIEVAL_TIMEOUT

    candidate_k = max(resolved_top_k * config_settings.RERANKER_TOP_K_CANDIDATES, 10)

    query_info = {
        "top_k": resolved_top_k,
        "candidate_k": candidate_k,
        "file_filter": file_filter,
        "namespace": resolved_namespace,
        "backend": config_settings.VECTOR_DATABASE_TO_USE,
        "metadata_filters_applied": bool(metadata_filters),
        "reranker_enabled": config_settings.RERANKER_ENABLED,
    }

    try:
        logger.info(
            f"Starting retrieval for request_id={request_id}, "
            f"query='{query[:100]}...', top_k={resolved_top_k}, candidate_k={candidate_k}, "
            f"namespace={resolved_namespace}, metadata_filters={bool(metadata_filters)}"
        )

        try:
            scored_docs = await asyncio.wait_for(
                get_related_docs_with_score(
                    index_name=resolved_index,
                    namespace=resolved_namespace,
                    question=query,
                    total_docs_to_retrieve=candidate_k,
                    filter_value=file_filter,
                    metadata_filters=metadata_filters,
                    agent_id=agent_id,
                ),
                timeout=resolved_timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Retrieval timed out after {resolved_timeout} seconds for request_id={request_id}")
            return {
                "request_id": request_id,
                "user_query": query,
                "error": f"Retrieval timed out after {resolved_timeout} seconds",
                "document_chunks": [],
                "total_chunks": 0,
                "candidate_count": 0,
                "matches": [],
                "query_info": query_info,
            }

        candidate_count = len(scored_docs) if scored_docs else 0
        logger.info(f"Vector search returned {candidate_count} candidate documents for request_id={request_id}")

        if not scored_docs:
            return {
                "request_id": request_id,
                "user_query": query,
                "document_chunks": [],
                "total_chunks": 0,
                "candidate_count": 0,
                "matches": [],
                "query_info": query_info,
            }

        try:
            reranked_docs = await rerank_documents(
                query=query,
                documents=scored_docs,
                top_k=resolved_top_k
            )
            logger.info(
                f"Reranking completed: {candidate_count} candidates -> {len(reranked_docs)} final documents "
                f"for request_id={request_id}"
            )
        except Exception as e:
            logger.warning(f"Reranking failed, using top candidates: {e}")
            reranked_docs = scored_docs[:resolved_top_k]

        documents: List[Document] = [doc for doc, _score in reranked_docs]
        total_chunks = len(documents)

        result = {
            "request_id": request_id,
            "user_query": query,
            "document_chunks": documents,
            "total_chunks": total_chunks,
            "candidate_count": candidate_count,
            "matches": documents,
            "query_info": query_info,
        }

        logger.info(f"Retrieval completed successfully with {total_chunks} documents for request_id={request_id}")
        return result

    except asyncio.CancelledError:
        logger.warning(f"Retrieval was cancelled for request_id={request_id}")
        raise

    except Exception as exc:
        logger.error(f"Retrieval failed for request_id={request_id}: {exc}", exc_info=True)
        return {
            "request_id": request_id,
            "user_query": query,
            "error": f"Retrieval failed: {str(exc)}",
            "document_chunks": [],
            "total_chunks": 0,
            "candidate_count": 0,
            "matches": [],
            "query_info": query_info,
        }


async def get_relevant_documents_batch(
        queries: List[Dict[str, Any]],
        concurrency_limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if not queries:
        return []

    limit = concurrency_limit or config_settings.RETRIEVAL_BATCH_CONCURRENCY
    semaphore = asyncio.Semaphore(limit)

    async def bounded_retrieval(params: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            return await get_relevant_documents(**params)

    tasks = [bounded_retrieval(q) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            params = queries[i]
            processed_results.append({
                "request_id": params.get("request_id"),
                "user_query": params.get("query", ""),
                "error": f"Batch retrieval failed: {str(result)}",
                "document_chunks": [],
                "total_chunks": 0,
                "matches": [],
                "query_info": {},
            })
        else:
            processed_results.append(result)

    return processed_results

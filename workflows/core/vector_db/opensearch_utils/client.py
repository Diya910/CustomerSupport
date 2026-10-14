from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from typing import Any, Dict, Iterable, List, Optional, Sequence

import boto3
from loguru import logger
from opensearchpy import OpenSearch, AsyncOpenSearch, helpers, exceptions as opensearch_exceptions
from opensearchpy import RequestsHttpConnection, AsyncHttpConnection, AWSV4SignerAsyncAuth
from requests_aws4auth import AWS4Auth

from langchain_core.documents import Document

from workflows.core.settings import config_settings
from workflows.core.llm import get_embeddings_model
from workflows.core.handler import retry_with_custom_backoff


class OpenSearchFactory:
    client_instance: Optional[OpenSearch] = None
    async_client_instance: Optional[AsyncOpenSearch] = None

    def __init__(self, index_name: Optional[str] = None) -> None:
        self.host = config_settings.OPENSEARCH_URL
        self.port = config_settings.OPENSEARCH_PORT
        self.username = config_settings.OPENSEARCH_USERNAME or None
        self.password = config_settings.OPENSEARCH_PASSWORD or None
        self.use_ssl = config_settings.OPENSEARCH_USE_SSL
        self.verify_certs = config_settings.OPENSEARCH_VERIFY_CERTS
        self.index = index_name or config_settings.OPENSEARCH_INDEX_NAME
        self.vector_field = config_settings.OPENSEARCH_VECTOR_FIELD
        self.text_field = config_settings.OPENSEARCH_TEXT_FIELD
        self.timeout = config_settings.OPENSEARCH_TIMEOUT
        self.max_retries = config_settings.OPENSEARCH_MAX_RETRIES
        self.retry_on_timeout = config_settings.OPENSEARCH_RETRY_ON_TIMEOUT
        self.search_timeout = config_settings.OPENSEARCH_SEARCH_TIMEOUT
        self.vector_weight = config_settings.OPENSEARCH_VECTOR_WEIGHT
        self.lexical_weight = config_settings.OPENSEARCH_LEXICAL_WEIGHT
        self.search_multiplier = config_settings.OPENSEARCH_SEARCH_MULTIPLIER

    def _get_aws_auth(self) -> AWS4Auth:
        region = config_settings.AWS_REGION_NAME
        service = "aoss" if ".aoss." in self.host else "es"
        credentials = boto3.Session().get_credentials().get_frozen_credentials()
        return AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            region,
            service,
            session_token=credentials.token,
        )

    def _get_aws_async_auth(self) -> AWSV4SignerAsyncAuth:
        region = config_settings.AWS_REGION_NAME
        service = "aoss" if ".aoss." in self.host else "es"
        credentials = boto3.Session().get_credentials()
        return AWSV4SignerAsyncAuth(credentials, region, service)

    def get_client(self) -> OpenSearch:
        if OpenSearchFactory.client_instance is not None:
            return OpenSearchFactory.client_instance

        if config_settings.OPENSEARCH_AUTH_METHOD == "aws_sigv4":
            OpenSearchFactory.client_instance = OpenSearch(
                hosts=[{"host": self.host, "port": self.port}],
                http_auth=self._get_aws_auth(),
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                timeout=self.timeout,
                max_retries=self.max_retries,
                retry_on_timeout=self.retry_on_timeout,
            )
        else:
            auth = (self.username, self.password) if self.username else None
            OpenSearchFactory.client_instance = OpenSearch(
                hosts=[{"host": self.host, "port": self.port}],
                http_auth=auth,
                use_ssl=self.use_ssl,
                verify_certs=self.verify_certs,
                ssl_show_warn=False,
                timeout=self.timeout,
                max_retries=self.max_retries,
                retry_on_timeout=self.retry_on_timeout,
            )
        logger.debug("OpenSearch client singleton created")
        return OpenSearchFactory.client_instance

    async def get_async_client(self) -> AsyncOpenSearch:
        if OpenSearchFactory.async_client_instance is not None:
            return OpenSearchFactory.async_client_instance

        if config_settings.OPENSEARCH_AUTH_METHOD == "aws_sigv4":
            OpenSearchFactory.async_client_instance = AsyncOpenSearch(
                hosts=[{"host": self.host, "port": self.port}],
                http_auth=self._get_aws_async_auth(),
                use_ssl=True,
                verify_certs=True,
                connection_class=AsyncHttpConnection,
                timeout=self.timeout,
                max_retries=self.max_retries,
                retry_on_timeout=self.retry_on_timeout,
            )
        else:
            auth = (self.username, self.password) if self.username else None
            OpenSearchFactory.async_client_instance = AsyncOpenSearch(
                hosts=[{"host": self.host, "port": self.port}],
                http_auth=auth,
                use_ssl=self.use_ssl,
                verify_certs=self.verify_certs,
                ssl_show_warn=False,
                connection_class=AsyncHttpConnection,
                timeout=self.timeout,
                max_retries=self.max_retries,
                retry_on_timeout=self.retry_on_timeout,
            )
        logger.debug("AsyncOpenSearch client singleton created")
        return OpenSearchFactory.async_client_instance

    def get_embeddings(self):
        embeddings = get_embeddings_model(model_key="EMBEDDING_MODEL_NAME")
        if embeddings is None:
            raise RuntimeError("Embedding model is not configured for OpenSearch ingestion")
        return embeddings

    def resolve_vector_dimension(self) -> int:
        try:
            embeddings = self.get_embeddings()
            probe_text = config_settings.CHECK_EMBEDDING_LEN_STRING or "hello"
            vector = embeddings.embed_query(probe_text)
            return len(vector)

        except Exception as exc:
            logger.warning(f"Falling back to configured OpenSearch dimension: {exc}")
            return config_settings.OPENSEARCH_EMBED_DIMENSION

    def _is_serverless(self) -> bool:
        return ".aoss." in self.host

    def ensure_index(self) -> None:
        client = self.get_client()
        if client.indices.exists(index=self.index):
            logger.info(f"Index '{self.index}' already exists")
            return
        else:
            logger.info(f"Index '{self.index}' does not exist. Creating new index.")

        dimension = self.resolve_vector_dimension()

        if self._is_serverless():
            serverless_engine = config_settings.OPENSEARCH_VECTOR_ENGINE
            if serverless_engine == "lucene":
                serverless_engine = "faiss"
            body = {
                "settings": {"index": {"knn": True}},
                "mappings": {
                    "properties": {
                        self.text_field: {"type": "text"},
                        self.vector_field: {
                            "type": "knn_vector",
                            "dimension": dimension,
                            "method": {
                                "name": config_settings.OPENSEARCH_VECTOR_METHOD_NAME,
                                "space_type": config_settings.OPENSEARCH_VECTOR_SPACE_TYPE,
                                "engine": serverless_engine,
                            },
                        },
                        "metadata": {"type": "object", "enabled": True},
                        "namespace": {"type": "keyword"},
                        "file_name": {"type": "keyword"},
                        "agent_id": {"type": "keyword"},
                        "created_at": {"type": "date", "format": "epoch_millis"},
                    }
                },
            }
        else:
            body = {
                "settings": {
                    "index": {
                        "knn": True,
                        "number_of_shards": config_settings.OPENSEARCH_NUMBER_OF_SHARDS,
                        "number_of_replicas": config_settings.OPENSEARCH_NUMBER_OF_REPLICAS,
                    }
                },
                "mappings": {
                    "properties": {
                        self.text_field: {"type": "text"},
                        self.vector_field: {
                            "type": "knn_vector",
                            "dimension": dimension,
                            "method": {
                                "name": config_settings.OPENSEARCH_VECTOR_METHOD_NAME,
                                "space_type": config_settings.OPENSEARCH_VECTOR_SPACE_TYPE,
                                "engine": config_settings.OPENSEARCH_VECTOR_ENGINE,
                            },
                        },
                        "metadata": {
                            "type": "object",
                            "enabled": True,
                            "properties": {
                                "ingestion_datetime": {"type": "date", "format": "epoch_millis"}
                            }
                        },
                        "namespace": {"type": "keyword"},
                        "file_name": {"type": "keyword"},
                        "agent_id": {"type": "keyword"},
                        "created_at": {"type": "date", "format": "epoch_millis"},
                    }
                },
            }

        try:
            client.indices.create(index=self.index, body=body)
            logger.info(f"Created OpenSearch index {self.index}")
        except opensearch_exceptions.RequestError as exc:
            if exc.error == "resource_already_exists_exception":
                logger.info(f"OpenSearch index {self.index} already exists")
                return
            raise

    def ingest_documents(
            self,
            documents: Sequence[Document],
            namespace: str,
            file_name: Optional[str],
    ) -> Dict[str, Any]:
        if not documents:
            return {"vector_count": 0, "message": "No documents provided"}

        embeddings = self.get_embeddings()
        client = self.get_client()

        texts = [doc.page_content or "" for doc in documents]
        vectors = embeddings.embed_documents(texts)

        actions = []
        timestamp_ms = int(time.time() * 1000)

        for doc, vector in zip(documents, vectors):
            metadata = dict(doc.metadata or {})
            metadata.setdefault("namespace", namespace)
            metadata.setdefault("file_name", file_name)
            agent_id = metadata.get("agent_id")
            if not agent_id and namespace:
                metadata["agent_id"] = namespace
                agent_id = namespace

            source_doc = {
                self.text_field: doc.page_content or "",
                self.vector_field: vector,
                "metadata": metadata,
                "namespace": metadata.get("namespace"),
                "file_name": metadata.get("file_name"),
                "agent_id": agent_id,
                "created_at": timestamp_ms,
            }

            action = {
                "_op_type": "index",
                "_index": self.index,
                "_source": source_doc,
            }
            if not self._is_serverless():
                action["_id"] = metadata.get("document_id") or str(uuid4())

            actions.append(action)

        if not actions:
            return {"vector_count": 0, "message": "No valid documents to ingest"}

        chunk_size = max(1, config_settings.OPENSEARCH_BULK_BATCH_SIZE)
        try:
            helpers.bulk(client, actions, chunk_size=chunk_size, refresh=(not self._is_serverless()))
            logger.info(f"Ingested {len(actions)} documents into index {self.index}")
            return {"vector_count": len(actions), "index": self.index}

        except Exception as exc:
            logger.error(f"OpenSearch bulk ingest failed: {exc}")
            return {"error": str(exc), "vector_count": 0}

    async def hybrid_search(
            self,
            query: str,
            namespace: Optional[str],
            top_k: int,
            metadata_filters: Optional[Dict[str, Any]] = None,
            agent_id: Optional[str] = None,
    ) -> List[Document]:
        if not query:
            return []

        namespace_value = namespace or config_settings.DEFAULT_NAMESPACE
        if agent_id:
            namespace_value = None
        client = await self.get_async_client()
        embeddings = self.get_embeddings()

        query_vector = await asyncio.to_thread(embeddings.embed_query, query)
        filters = self.build_filter(namespace_value, metadata_filters, agent_id=agent_id)

        vector_hits, lexical_hits = await self.parallel_search(client, query, query_vector, filters, top_k)
        combined_hits = self.combine_hits(vector_hits, lexical_hits)

        documents: List[Document] = []
        for hit in combined_hits[:top_k]:
            source = hit.get("_source", {})
            page_content = source.get(self.text_field, "")
            metadata = dict(source.get("metadata") or {})
            metadata["score"] = hit.get("_score")
            metadata.setdefault("namespace", source.get("namespace"))
            metadata.setdefault("file_name", source.get("file_name"))
            metadata.setdefault("agent_id", source.get("agent_id"))
            documents.append(Document(page_content=page_content, metadata=metadata))

        return documents

    async def parallel_search(
            self,
            client: AsyncOpenSearch,
            query: str,
            query_vector: List[float],
            filters: Optional[List[Dict[str, Any]]],
            top_k: int,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        vector_task = asyncio.create_task(
            self.vector_search(client, query_vector, filters, top_k)
        )
        lexical_task = asyncio.create_task(
            self.lexical_search(client, query, filters, top_k)
        )

        vector_hits, lexical_hits = await asyncio.gather(vector_task, lexical_task)
        return vector_hits, lexical_hits

    async def vector_search(
            self,
            client: AsyncOpenSearch,
            query_vector: List[float],
            filters: Optional[List[Dict[str, Any]]],
            top_k: int,
    ) -> List[Dict[str, Any]]:
        size = max(top_k * self.search_multiplier, 10)

        body: Dict[str, Any] = {
            "size": size,
            "query": {
                "knn": {
                    self.vector_field: {
                        "vector": query_vector,
                        "k": size,
                    }
                }
            }
        }

        if filters:
            body["query"] = {
                "bool": {
                    "must": [
                        {
                            "knn": {
                                self.vector_field: {
                                    "vector": query_vector,
                                    "k": size,
                                }
                            }
                        }
                    ],
                    "filter": filters,
                }
            }

        try:
            response = await client.search(index=self.index, body=body)
            return response.get("hits", {}).get("hits", [])

        except Exception as exc:
            logger.error(f"Vector search failed: {exc}")
            return []

    async def lexical_search(
            self,
            client: AsyncOpenSearch,
            query: str,
            filters: Optional[List[Dict[str, Any]]],
            top_k: int,
    ) -> List[Dict[str, Any]]:
        size = max(top_k * self.search_multiplier, 10)

        bool_query: Dict[str, Any] = {
            "must": [
                {
                    "match": {
                        self.text_field: {
                            "query": query, "fuzziness": "AUTO"}
                    }
                }
            ]
        }
        if filters:
            bool_query["filter"] = filters

        body = {
            "size": size,
            "query": {"bool": bool_query}
        }

        try:
            response = await client.search(index=self.index, body=body)
            return response.get("hits", {}).get("hits", [])
        except Exception as exc:
            logger.error(f"Lexical search failed: {exc}")
            return []

    def combine_hits(
            self,
            vector_hits: Iterable[Dict[str, Any]],
            lexical_hits: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        def normalize_scores(hits: Iterable[Dict[str, Any]]) -> Dict[str, float]:
            scores = {
                hit.get("_id"): hit.get(
                    "_score", 0.0) for hit in hits if hit.get("_id")
            }
            if not scores:
                return {}

            max_score = max(scores.values()) or 1.0
            return {
                doc_id: score / max_score for doc_id, score in scores.items()
            }

        vector_scores = normalize_scores(vector_hits)
        lexical_scores = normalize_scores(lexical_hits)

        combined: Dict[str, Dict[str, Any]] = {}

        def upsert(hit: Dict[str, Any], source: str) -> None:
            doc_id = hit.get("_id")
            if not doc_id:
                return
            record = combined.setdefault(
                doc_id, {
                    "_id": doc_id,
                    "_source": hit.get("_source", {})
                }
            )
            record[source] = hit

        for entry in vector_hits:
            upsert(entry, "vector")
        for entry in lexical_hits:
            upsert(entry, "lexical")

        merged: List[Dict[str, Any]] = []
        for doc_id, payload in combined.items():
            vector_score = vector_scores.get(doc_id, 0.0)
            lexical_score = lexical_scores.get(doc_id, 0.0)
            score = self.vector_weight * vector_score + self.lexical_weight * lexical_score

            base_hit = payload.get("vector") or payload.get("lexical") or {
                "_id": doc_id, "_source": payload.get("_source", {})
            }

            base_hit = dict(base_hit)
            base_hit["_score"] = score
            merged.append(base_hit)

        merged.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
        return merged

    def delete_existing(self, client: OpenSearch, namespace: str, file_name: str) -> int:
        if self._is_serverless():
            logger.debug(f"AOSS: skipping delete_by_query for {file_name} (not supported)")
            return 0

        query = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"namespace": namespace}},
                        {"term": {"file_name": file_name}},
                    ]
                }
            }
        }
        try:
            response = client.delete_by_query(
                index=self.index,
                body=query,
                refresh=True,
                conflicts="proceed"
            )
            deleted = 0
            if isinstance(response, dict):
                deleted = int(response.get("deleted", 0) or 0)

            if deleted:
                logger.info(f"Deleted {deleted} existing documents for file {file_name} in namespace {namespace}")
            else:
                logger.debug(f"No existing documents deleted for file {file_name} in namespace {namespace}")

            return deleted

        except Exception as exc:
            logger.error(f"Failed to delete existing documents for {file_name}: {exc}")
            return 0

    def delete_by_filename(self, namespace: str, file_name: str) -> int:
        client = self.get_client()
        return self.delete_existing(client, namespace, file_name)

    def delete_namespace(self, namespace: str) -> bool:
        client = self.get_client()
        query = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"namespace": namespace}}
                    ]
                }
            }
        }

        try:
            response = client.delete_by_query(
                index=self.index,
                body=query,
                refresh=True,
                conflicts="proceed"
            )
            deleted = response.get(
                "deleted", 0
            ) if isinstance(response, dict) else 0

            logger.info(f"Deleted {deleted} documents from namespace '{namespace}'")
            return True

        except Exception as exc:
            logger.error(f"Failed to delete namespace {namespace}: {exc}")
            return False

    def delete_index(self) -> bool:
        client = self.get_client()
        try:
            if not client.indices.exists(index=self.index):
                logger.error(f"Index '{self.index}' does not exist")
                return False

            client.indices.delete(index=self.index)
            logger.info(f"Deleted index '{self.index}'")
            return True
        except Exception as exc:
            logger.error(f"Failed to delete index {self.index}: {exc}")
            return False

    @staticmethod
    def build_filter(
            namespace: Optional[str],
            metadata_filters: Optional[Dict[str, Any]],
            agent_id: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        filters: List[Dict[str, Any]] = []
        if agent_id:
            filters.append({"term": {"agent_id": agent_id}})
        if namespace:
            filters.append({"term": {"namespace": namespace}})
        if metadata_filters:
            for key, value in metadata_filters.items():
                if value is None:
                    continue
                if isinstance(value, dict) and any(k in value for k in ['gte', 'lte', 'gt', 'lt']):
                    filters.append({"range": {f"metadata.{key}": value}})
                elif isinstance(value, str):
                    filters.append({"term": {f"metadata.{key}": value}})
                else:
                    filters.append({"term": {f"metadata.{key}": value}})

        return filters or None

    @classmethod
    async def cleanup(cls) -> None:
        if cls.client_instance is not None:
            try:
                cls.client_instance.close()
            except Exception:
                pass
            cls.client_instance = None

        if cls.async_client_instance is not None:
            try:
                await cls.async_client_instance.close()
            except Exception:
                pass
            cls.async_client_instance = None

        logger.debug("OpenSearch factory cleanup completed")

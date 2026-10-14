from __future__ import annotations

import json
import asyncio
from typing import List, Optional, Tuple

import boto3
from loguru import logger
from langchain_core.documents import Document

from workflows.core.settings import config_settings


class Reranker:

    class_instance: Optional['Reranker'] = None
    class_lock: Optional[asyncio.Lock] = None

    def __init__(self):
        self._client = None
        self.class_initialized = False
        self.instance_lock = asyncio.Lock()

    @classmethod
    async def get_class_lock(cls) -> asyncio.Lock:
        if cls.class_lock is None:
            cls.class_lock = asyncio.Lock()
        return cls.class_lock

    @classmethod
    async def get_instance(cls) -> 'Reranker':
        if cls.class_instance is None:
            lock = await cls.get_class_lock()
            async with lock:
                if cls.class_instance is None:
                    cls.class_instance = cls()
        return cls.class_instance

    async def initialize(self, force: bool = False):
        if self.class_initialized and not force:
            return

        async with self.instance_lock:
            if self.class_initialized and not force:
                return

            try:
                self._client = boto3.client(
                    "bedrock-agent-runtime",
                    region_name=config_settings.AWS_REGION_NAME,
                    aws_access_key_id=config_settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=config_settings.AWS_SECRET_ACCESS_KEY,
                )
                self.class_initialized = True
                logger.info(f"Bedrock Reranker initialized (model: {config_settings.RERANKER_MODEL_ID})")

            except Exception as exc:
                logger.error(f"Failed to initialize Bedrock reranker client: {exc}")
                self.class_initialized = False
                self._client = None
                raise

    async def rerank_documents(
        self,
        query: str,
        documents: List[Tuple[Document, float]],
        top_k: Optional[int] = None,
    ) -> List[Tuple[Document, float]]:
        try:
            if not documents:
                return []

            if not config_settings.RERANKER_ENABLED:
                return self._apply_top_k(documents, top_k)

            if not query or not query.strip():
                return self._apply_top_k(documents, top_k)

            validated = self._validate_documents(documents)
            if not validated:
                return []

            if not self.class_initialized:
                await self.initialize()

            if not self._client:
                logger.warning("Bedrock reranker client unavailable, returning original order")
                return self._apply_top_k(validated, top_k)

            actual_top_k = top_k if top_k and top_k > 0 else len(validated)
            candidate_multiplier = config_settings.RERANKER_TOP_K_CANDIDATES or 3
            candidate_count = min(len(validated), max(actual_top_k * candidate_multiplier, 10))
            candidates = validated[:candidate_count]

            text_sources = [
                {"type": "INLINE", "inlineDocumentSource": {
                    "type": "TEXT",
                    "textDocument": {"text": doc.page_content[:2048]}
                }}
                for doc, _ in candidates
            ]

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.rerank(
                    queries=[{"type": "TEXT", "textQuery": {"text": query}}],
                    sources=text_sources,
                    rerankingConfiguration={
                        "type": "BEDROCK_RERANKING_MODEL",
                        "bedrockRerankingConfiguration": {
                            "modelConfiguration": {
                                "modelArn": f"arn:aws:bedrock:{config_settings.AWS_REGION_NAME}::foundation-model/{config_settings.RERANKER_MODEL_ID}"
                            },
                            "numberOfResults": actual_top_k,
                        }
                    },
                )
            )

            results = response.get("results", [])
            score_weight = config_settings.RERANKER_SCORE_WEIGHT

            reranked = []
            for result in results:
                idx = result["index"]
                rerank_score = result["relevanceScore"]
                doc, orig_score = candidates[idx]

                orig_max = max(s for _, s in candidates) if candidates else 1.0
                norm_orig = orig_score / orig_max if orig_max > 0 else 0.0
                final_score = (1 - score_weight) * norm_orig + score_weight * rerank_score

                updated_metadata = dict(doc.metadata) if doc.metadata else {}
                updated_metadata["original_score"] = orig_score
                updated_metadata["rerank_score"] = rerank_score
                updated_metadata["final_score"] = final_score

                updated_doc = Document(
                    page_content=doc.page_content,
                    metadata=updated_metadata
                )
                reranked.append((updated_doc, final_score))

            reranked.sort(key=lambda x: x[1], reverse=True)
            logger.info(f"Reranked {len(candidates)} documents via Bedrock, returning {len(reranked)}")
            return reranked

        except Exception as exc:
            logger.error(f"Bedrock reranking failed: {exc}", exc_info=True)
            return self._apply_top_k(documents, top_k) if documents else []

    @staticmethod
    def _validate_documents(
        documents: List[Tuple[Document, float]]
    ) -> List[Tuple[Document, float]]:
        validated = []
        for item in documents:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            doc, score = item
            if not isinstance(doc, Document):
                continue
            if not doc.page_content or not isinstance(doc.page_content, str):
                continue
            if not doc.page_content.strip():
                continue
            try:
                score = float(score)
            except (ValueError, TypeError):
                score = 0.0
            validated.append((doc, score))
        return validated

    @staticmethod
    def _apply_top_k(
        documents: List[Tuple[Document, float]],
        top_k: Optional[int]
    ) -> List[Tuple[Document, float]]:
        if not documents:
            return []
        if top_k is None or top_k <= 0:
            return documents
        return documents[:top_k]


async def initialize_reranker(force: bool = False):
    reranker = await Reranker.get_instance()
    await reranker.initialize(force=force)
    logger.info("Bedrock Reranker ready for use")


async def rerank_documents(
    query: str,
    documents: List[Tuple[Document, float]],
    top_k: Optional[int] = None,
) -> List[Tuple[Document, float]]:
    reranker = await Reranker.get_instance()
    return await reranker.rerank_documents(query, documents, top_k)

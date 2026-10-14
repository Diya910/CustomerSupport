from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import asyncio
from typing import List
from loguru import logger

from workflows.core.settings import config_settings
from workflows.core.handler import retry_with_custom_backoff
from .prompts import PROMPT_SUMMARIZE_DOCUMENT
from workflows.core.llm import get_chat_model


def split_text(text: List[Document], chunk_size: int, chunk_overlap: int) -> List[Document]:
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
    return text_splitter.split_documents(text)


@retry_with_custom_backoff(
    max_retries=config_settings.BEDROCK_MAX_RETRY_ATTEMPTS,
    initial_delay=config_settings.BEDROCK_RETRY_BASE_DELAY_SEC,
    backoff_factor=2.0,
    max_delay=30.0,
)
async def summarize_text(doc_text: str) -> str:

    llm = get_chat_model("SUMMARIZE_MODEL_NAME", temperature=0.0)

    full_prompt = PROMPT_SUMMARIZE_DOCUMENT.replace("{text}", doc_text)
    response = await llm.ainvoke(full_prompt)

    return response.content if hasattr(response, "content") else str(response)


async def summarize_documents(documents: List[Document]) -> List[str]:
    """
    Summarize multiple documents concurrently with throttle handling.
    Returns summaries in the same order as input documents.
    """
    concurrency = max(1, int(config_settings.SUMMARY_MAX_CONCURRENCY))
    sem = asyncio.Semaphore(concurrency)

    async def summarize_single(doc: Document, idx: int):
        async with sem:
            text = doc.page_content or ""
            try:
                summary = await summarize_text(text)
                return idx, summary
            except Exception as e:
                logger.error(f"Failed to summarize document {idx}: {e}")
                return idx, ""

    tasks = [summarize_single(doc, i) for i, doc in enumerate(documents)]
    results = await asyncio.gather(*tasks)
    results_sorted = sorted(results, key=lambda x: x[0])

    return [summary for _, summary in results_sorted]

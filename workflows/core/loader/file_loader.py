import pprint
import asyncio
import os
from pathlib import Path

from loguru import logger
from os import path, remove
from urllib.parse import urlparse
from os.path import expanduser, isfile
from tempfile import NamedTemporaryFile
from typing import Any, IO, Dict, List, Optional, Tuple

from langchain_community.document_loaders import TextLoader, PyPDFLoader

from langchain_core.documents import Document
from langchain_core.document_loaders import BaseLoader

from workflows.core.settings import config_settings
from workflows.core.loader.utils import split_text, summarize_documents


class URLDownloaderMixin:
    @staticmethod
    def is_valid_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            return bool(parsed.netloc) and bool(parsed.scheme)
        except Exception:
            return False

    def __init__(self, file_path: Optional[str] = None, *args: Any, **kwargs: Any) -> None:
        self.temp_file: Optional[IO[bytes]] = None
        self.file_path = str(file_path) if file_path else ""

        if "~" in self.file_path:
            self.file_path = expanduser(self.file_path)

        if isfile(self.file_path):
            return

        if self.is_valid_url(self.file_path):
            self.temp_file = NamedTemporaryFile(delete=False)
            self.file_path = self.temp_file.name
            return

        raise ValueError(f"Invalid file path or URL: {self.file_path}")

    def __del__(self) -> None:
        if hasattr(self, '_temp_file') and self.temp_file:
            try:
                self.temp_file.close()
                remove(self.temp_file.name)
            except Exception as e:
                logger.error(f"Error cleaning up temporary file: {e}")


class FileLoader(BaseLoader):
    LOADER_MAP = {
        "txt": TextLoader,
        "pdf": PyPDFLoader,
    }

    def __init__(self, file_path: str, process_type: str = "txt") -> None:
        self.file_path = file_path
        self.process_type = process_type.lower()
        self.validate_process_type()

    def validate_process_type(self) -> None:
        if self.process_type not in config_settings.ALLOWED_FILE_EXTENSIONS:
            raise ValueError(f"Unsupported process type: {self.process_type}. Allowed: {config_settings.ALLOWED_FILE_EXTENSIONS}")

    def validate_file_path(self) -> None:
        if not path.isfile(self.file_path):
            raise FileNotFoundError(f"File not found: {self.file_path}")

    def load(self) -> List[Document]:
        try:
            self.validate_file_path()
            loader_cls = self.LOADER_MAP.get(self.process_type)
            if not loader_cls:
                raise ValueError(f"Unsupported process type: {self.process_type}")

            loader = loader_cls(file_path=self.file_path)
            file_contents = loader.load()

            logger.info(
                f"Successfully loaded {self.process_type} file: {self.file_path} ({len(file_contents)} documents)")
            return file_contents

        except Exception as e:
            logger.error(f"Error loading file {self.file_path}: {str(e)}")
            raise

async def file_loader(
        pre_signed_url: str,
        file_name: str,
        file_type: str,
        namespace: str,
        metadata: Optional[List[Dict[str, str]]] = None
) -> Tuple[List[Document], Document]:
    """
    Load and process a file from a pre-signed URL.
    Generate summaries and split into chunks.
    Enrich documents with metadata.
    """
    try:
        if file_type not in config_settings.ALLOWED_FILE_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {file_type}")

        loader = FileLoader(pre_signed_url, process_type=file_type)
        loaded_documents = loader.load()

        logger.debug(f"Loaded {len(loaded_documents)} documents before chunking")

        try:
            summary = await summarize_documents(loaded_documents)
        except Exception as e:
            logger.error(f"Error during summarization: {e}")
            summary = [""] * len(loaded_documents)

        chunks_documents = split_text(
            text=loaded_documents,
            chunk_size=config_settings.CHUNK_SIZE,
            chunk_overlap=config_settings.CHUNK_OVERLAP
        )

        logger.info(f"Document processing complete: {len(chunks_documents)} chunks created")

        base_metadata = {
            "file_name": file_name,
            "file_type": file_type,
            "namespace": namespace,
        }
        if metadata:
            for meta in metadata:
                base_metadata.update(meta)

        for document in chunks_documents:
            document.metadata.update(base_metadata)

        summary_text = "\n\n".join(
            s.strip() for s in summary if isinstance(s, str) and s.strip()
        )
        if not summary_text and loaded_documents:
            summary_text = (loaded_documents[0].page_content or "").strip()
        summary_metadata = base_metadata.copy()
        summary_metadata["chunk_type"] = "summary"
        summary_document = Document(
            page_content=summary_text,
            metadata=summary_metadata
        )
        return chunks_documents, summary_document

    except Exception as e:
        logger.error(f"Error in file_loader: {str(e)}")
        raise

if __name__ == "__main__":
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    test_url = os.environ.get(
        "TEST_FILE_PATH",
        str(project_root / "data" / "sample.txt")
    )
    test_file_name = Path(test_url).name
    test_file_type = "txt"
    test_namespace = "test"

    if not Path(test_url).exists():
        print(f"Test file not found: {test_url}")
        print("Please set TEST_FILE_PATH environment variable or create the file.")
        exit(1)

    chunks, summary = asyncio.run(
        file_loader(
            pre_signed_url=test_url,
            file_name=test_file_name,
            file_type=test_file_type,
            namespace=test_namespace
        )
    )
    pprint.pprint(summary.metadata)
    pprint.pprint(summary.page_content)
    print(f"Total chunks created: {len(chunks)}")

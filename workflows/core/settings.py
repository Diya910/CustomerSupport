import os

from enum import Enum
from pydantic import ConfigDict

from dotenv import load_dotenv
from typing import ClassVar, List
from pydantic_settings import BaseSettings


load_dotenv()


class VectorDBServiceType(str, Enum):
    OPENSEARCH = "opensearch"


class LLMServiceType(str, Enum):
    AWS = "aws-bedrock"


class DatabaseType(str, Enum):
    SQLITE = "sqlite"
    ATHENA = "athena"
    REDSHIFT = "redshift"
    POSTGRES = "postgres"


class StoreType(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    MONGODB = "mongodb"


class CheckpointType(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class Settings(BaseSettings):
    # AWS Configuration
    AWS_ACCESS_KEY_ID: str = os.environ.get("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    AWS_REGION_NAME: str = os.environ.get("AWS_REGION_NAME", "us-east-1")
    AWS_PROFILE_NAME: str = os.environ.get("AWS_PROFILE_NAME", "default")

    # File Processing Configuration
    ALLOWED_FILE_EXTENSIONS: List[str] = ["txt", "pdf"]

    # Chunking Configuration
    CHUNK_SIZE: int = int(os.environ.get("CHUNK_SIZE", 2000))
    CHUNK_OVERLAP: int = int(os.environ.get("CHUNK_OVERLAP", 800))

    # Summary Configuration
    SUMMARY_MAX_CONCURRENCY: int = int(os.environ.get("SUMMARY_MAX_CONCURRENCY", 3))
    THRESHOLD_MESSAGE_TO_SUMMARIZE: int = int(os.environ.get("THRESHOLD_MESSAGE_TO_SUMMARIZE", 40))
    THRESHOLD_TOKENS_TO_SUMMARIZE: int = int(os.environ.get("THRESHOLD_TOKENS_TO_SUMMARIZE", 80000))
    SUMMARIZATION_MODEL: str = os.environ.get("SUMMARIZATION_MODEL", "SUMMARIZATION_MODEL_NAME")
    SUMMARIZATION_TRIGGER_FRACTION: float = float(os.environ.get("SUMMARIZATION_TRIGGER_FRACTION", 0.70))
    SUMMARIZATION_KEEP_MESSAGES: int = int(os.environ.get("SUMMARIZATION_KEEP_MESSAGES", 20))
    SUMMARIZATION_MIN_TOKENS_TO_SUMMARIZE: int = int(os.environ.get("SUMMARIZATION_MIN_TOKENS_TO_SUMMARIZE", 8000))

    # Tool Configuration
    TOOLS_TO_CALL_FOR_NON_SENSITIVE_DATA: List[str] = [
        "text_to_sql",
    ]

    # Vector Database Configuration
    DELETE_PARTITION_STATUS: bool = os.environ.get("DELETE_PARTITION_STATUS", False)
    INDEX_NAME: str = os.environ.get("INDEX_NAME", "testing-data")
    DEFAULT_NAMESPACE: str = os.environ.get("DEFAULT_NAMESPACE", "default")
    DROP_INDEX_NAME_STATUS: bool = os.environ.get("DROP_INDEX_NAME_STATUS", False)
    DELETE_NAMESPACE_STATUS: bool = os.environ.get("DELETE_NAMESPACE_STATUS", False)
    TOTAL_DOCS_TO_RETRIEVE: int = os.environ.get("TOTAL_DOCS_TO_RETRIEVE", 10)
    CHECK_EMBEDDING_LEN_STRING: str = os.environ.get("CHECK_EMBEDDING_LEN_STRING", "hello")
    NUMBER_OF_RETRIEVAL_RESULTS: int = int(os.environ.get("NUMBER_OF_RETRIEVAL_RESULTS", 10))

    # Weaviate Vector Database Configuration
    WEAVIATE_VECTOR_DATABASE_SERVICE_TYPE: str = os.environ.get("WEAVIATE_VECTOR_DATABASE_SERVICE_TYPE", "local")
    WEAVIATE_API_KEY: str = os.environ.get("WEAVIATE_API_KEY", "")
    WEAVIATE_CLUSTER_URL: str = os.environ.get("WEAVIATE_CLUSTER_URL", "")
    WEAVIATE_AUTH_CREDENTIALS: str = os.environ.get("WEAVIATE_AUTH_CREDENTIALS", "")
    WEAVIATE_HOST: str = os.environ.get("WEAVIATE_HOST", "localhost")
    WEAVIATE_HOST_PORT: int = int(os.environ.get("WEAVIATE_HOST_PORT", 8080))
    WEAVIATE_GRPC_PORT: int = int(os.environ.get("WEAVIATE_GRPC_PORT", 50051))
    WEAVIATE_HYPERPARAMETER_HYBRID_SEARCH: float = float(os.environ.get("WEAVIATE_HYPERPARAMETER_HYBRID_SEARCH", 0.5))
    WEAVIATE_MULTI_TENANCY_STATUS: bool = os.environ.get("WEAVIATE_MULTI_TENANCY_STATUS", True)
    WEAVIATE_TEXT_KEY: str = os.environ.get("WEAVIATE_TEXT_KEY", "text")
    WEAVIATE_FILTER_RESULTS_PARAMETER: str = os.environ.get("WEAVIATE_FILTER_RESULTS_PARAMETER", "file_name")

    # OpenSearch Vector Database Configuration
    OPENSEARCH_URL: str = os.environ.get(
        "OPENSEARCH_URL",
        "search-chatbot-qeval-kkyosyuxanotmtrtu4mlgojm44.us-east-1.es.amazonaws.com"
    )
    OPENSEARCH_PORT: int = int(os.environ.get("OPENSEARCH_PORT", 443))
    OPENSEARCH_USERNAME: str = os.environ.get("OPENSEARCH_USERNAME", "chatbot-qeval")
    OPENSEARCH_PASSWORD: str = os.environ.get("OPENSEARCH_PASSWORD", "")
    OPENSEARCH_USE_SSL: bool = str(os.environ.get("OPENSEARCH_USE_SSL", "true")).lower() not in {"false", "0", "no"}
    OPENSEARCH_VERIFY_CERTS: bool = str(os.environ.get("OPENSEARCH_VERIFY_CERTS", "false")).lower() in {"true", "1", "yes"}
    OPENSEARCH_INDEX_NAME: str = os.environ.get("OPENSEARCH_INDEX_NAME", "testing-data")
    OPENSEARCH_VECTOR_FIELD: str = os.environ.get("OPENSEARCH_VECTOR_FIELD", "vector")
    OPENSEARCH_TEXT_FIELD: str = os.environ.get("OPENSEARCH_TEXT_FIELD", "text")
    OPENSEARCH_BULK_BATCH_SIZE: int = int(os.environ.get("OPENSEARCH_BULK_BATCH_SIZE", 100))
    OPENSEARCH_EMBED_DIMENSION: int = int(os.environ.get("OPENSEARCH_EMBED_DIMENSION", 1536))
    OPENSEARCH_AUTH_METHOD: str = os.environ.get("OPENSEARCH_AUTH_METHOD", "basic").lower()
    OPENSEARCH_TIMEOUT: int = int(os.environ.get("OPENSEARCH_TIMEOUT", 60))
    OPENSEARCH_MAX_RETRIES: int = int(os.environ.get("OPENSEARCH_MAX_RETRIES", 3))
    OPENSEARCH_RETRY_ON_TIMEOUT: bool = str(os.environ.get("OPENSEARCH_RETRY_ON_TIMEOUT", "true")).lower() in {"true", "1", "yes"}
    OPENSEARCH_SEARCH_TIMEOUT: int = int(os.environ.get("OPENSEARCH_SEARCH_TIMEOUT", 30))
    OPENSEARCH_VECTOR_WEIGHT: float = float(os.environ.get("OPENSEARCH_VECTOR_WEIGHT", 0.6))
    OPENSEARCH_LEXICAL_WEIGHT: float = float(os.environ.get("OPENSEARCH_LEXICAL_WEIGHT", 0.4))
    OPENSEARCH_SEARCH_MULTIPLIER: int = int(os.environ.get("OPENSEARCH_SEARCH_MULTIPLIER", 3))
    OPENSEARCH_THREAD_POOL_SIZE: int = int(os.environ.get("OPENSEARCH_THREAD_POOL_SIZE", 4))
    OPENSEARCH_NUMBER_OF_SHARDS: int = int(os.environ.get("OPENSEARCH_NUMBER_OF_SHARDS", 1))
    OPENSEARCH_NUMBER_OF_REPLICAS: int = int(os.environ.get("OPENSEARCH_NUMBER_OF_REPLICAS", 1))
    OPENSEARCH_VECTOR_METHOD_NAME: str = os.environ.get("OPENSEARCH_VECTOR_METHOD_NAME", "hnsw")
    OPENSEARCH_VECTOR_SPACE_TYPE: str = os.environ.get("OPENSEARCH_VECTOR_SPACE_TYPE", "cosinesimil")
    OPENSEARCH_VECTOR_ENGINE: str = os.environ.get("OPENSEARCH_VECTOR_ENGINE", "lucene")

    # Reranker Configuration (AWS Bedrock Rerank API)
    RERANKER_MODEL_ID: str = os.environ.get("RERANKER_MODEL_ID", "cohere.rerank-v3-5:0")
    RERANKER_ENABLED: bool = str(os.environ.get("RERANKER_ENABLED", "true")).lower() in {"true", "1", "yes"}
    RERANKER_TOP_K_CANDIDATES: int = int(os.environ.get("RERANKER_TOP_K_CANDIDATES", 3))
    RERANKER_SCORE_WEIGHT: float = float(os.environ.get("RERANKER_SCORE_WEIGHT", 0.5))

    # Retrieval Configuration
    RETRIEVAL_TIMEOUT: float = float(os.environ.get("RETRIEVAL_TIMEOUT", 60.0))
    RETRIEVAL_BATCH_CONCURRENCY: int = int(os.environ.get("RETRIEVAL_BATCH_CONCURRENCY", 5))

    # RAG Agent Summarization Configuration
    RAG_AGENT_SUMMARIZE_THRESHOLD: int = int(os.environ.get("RAG_AGENT_SUMMARIZE_THRESHOLD", 5))

    # Session Management Configuration
    SESSION_TTL_SECONDS: int = int(os.environ.get("SESSION_TTL_SECONDS", 3600))

    # LLM Service Configuration
    VECTOR_DATABASE_TO_USE: str = os.environ.get("VECTOR_DATABASE_TO_USE", VectorDBServiceType.OPENSEARCH.value)
    DATABASE_SERVICE_TYPE: str = os.environ.get("DATABASE_SERVICE_TYPE", DatabaseType.REDSHIFT.value)
    LLM_SERVICE_TYPE: str = os.environ.get("LLM_SERVICE_TYPE", LLMServiceType.AWS.value)

    CHECKPOINT_TYPE: str = os.environ.get("CHECKPOINT_TYPE", CheckpointType.SQLITE.value)
    CHECKPOINT_POSTGRES_HOST: str = os.environ.get("CHECKPOINT_POSTGRES_HOST", "localhost")
    CHECKPOINT_POSTGRES_PORT: int = int(os.environ.get("CHECKPOINT_POSTGRES_PORT", 5432))
    CHECKPOINT_POSTGRES_USER: str = os.environ.get("CHECKPOINT_POSTGRES_USER", "")
    CHECKPOINT_POSTGRES_PASSWORD: str = os.environ.get("CHECKPOINT_POSTGRES_PASSWORD", "")
    CHECKPOINT_POSTGRES_DATABASE: str = os.environ.get("CHECKPOINT_POSTGRES_DATABASE", "langgraph_checkpoints")
    CHECKPOINT_POSTGRES_SSLMODE: str = os.environ.get("CHECKPOINT_POSTGRES_SSLMODE", "disable")
    CHECKPOINT_DB_PATH: str = os.environ.get("CHECKPOINT_DB_PATH", "")
    CHECKPOINT_POOL_MIN_SIZE: int = int(os.environ.get("CHECKPOINT_POOL_MIN_SIZE", 2))
    CHECKPOINT_POOL_MAX_SIZE: int = int(os.environ.get("CHECKPOINT_POOL_MAX_SIZE", 50))
    CHECKPOINT_POOL_MAX_IDLE: int = int(os.environ.get("CHECKPOINT_POOL_MAX_IDLE", 300))
    CHECKPOINT_POOL_MAX_LIFETIME: int = int(os.environ.get("CHECKPOINT_POOL_MAX_LIFETIME", 600))
    CHECKPOINT_POOL_RECONNECT_TIMEOUT: int = int(os.environ.get("CHECKPOINT_POOL_RECONNECT_TIMEOUT", 10))
    CHECKPOINT_POOL_TIMEOUT: float = float(os.environ.get("CHECKPOINT_POOL_TIMEOUT", 60.0))

    # Store Configuration (cross-thread long-term memory)
    STORE_TYPE: str = os.environ.get("STORE_TYPE", StoreType.SQLITE.value)
    STORE_SQLITE_PATH: str = os.environ.get("STORE_SQLITE_PATH", "store.db")
    STORE_POSTGRES_URI: str = os.environ.get("STORE_POSTGRES_URI", "")

    # MongoDB Auth Configuration
    MONGO_AUTH_URI: str = os.environ.get("MONGO_AUTH_URI", "mongodb://localhost:27017")
    MONGO_AUTH_DATABASE: str = os.environ.get("MONGO_AUTH_DATABASE", "kpichatbot_auth")
    MONGO_AUTH_COLLECTION: str = os.environ.get("MONGO_AUTH_COLLECTION", "users")

    # JWT Configuration
    JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 60))

    # TTS Configuration (edge-tts, no API key required)
    TTS_VOICE: str = os.environ.get("TTS_VOICE", "en-US-AriaNeural")

    # Auth Configuration
    AUTH_PASSWORD_MIN_LENGTH: int = int(os.environ.get("AUTH_PASSWORD_MIN_LENGTH", 8))

    def get_checkpoint_postgres_uri(self) -> str:
        if not self.CHECKPOINT_POSTGRES_USER or not self.CHECKPOINT_POSTGRES_PASSWORD:
            raise ValueError(
                "CHECKPOINT_POSTGRES_USER and CHECKPOINT_POSTGRES_PASSWORD must be set "
                "when using postgres checkpoint"
            )
        return (
            f"postgresql://{self.CHECKPOINT_POSTGRES_USER}:{self.CHECKPOINT_POSTGRES_PASSWORD}"
            f"@{self.CHECKPOINT_POSTGRES_HOST}:{self.CHECKPOINT_POSTGRES_PORT}"
            f"/{self.CHECKPOINT_POSTGRES_DATABASE}?sslmode={self.CHECKPOINT_POSTGRES_SSLMODE}"
        )

    BEDROCK_MAX_RETRY_ATTEMPTS: int = int(os.environ.get("BEDROCK_MAX_RETRY_ATTEMPTS", 5))
    BEDROCK_RETRY_BASE_DELAY_SEC: float = float(os.environ.get("BEDROCK_RETRY_BASE_DELAY_SEC", 1.0))

    # Boto/AWS Client Configuration
    BOTO_CONNECT_TIMEOUT: int = int(os.environ.get("BOTO_CONNECT_TIMEOUT", 60))
    BOTO_READ_TIMEOUT: int = int(os.environ.get("BOTO_READ_TIMEOUT", 60))
    BOTO_MAX_RETRY_ATTEMPTS: int = int(os.environ.get("BOTO_MAX_RETRY_ATTEMPTS", 3))
    BOTO_MAX_POOL_CONNECTIONS: int = int(os.environ.get("BOTO_MAX_POOL_CONNECTIONS", 10))
    BOTO_TCP_KEEPALIVE: bool = str(os.environ.get("BOTO_TCP_KEEPALIVE", "true")).lower() in {"true", "1", "yes"}

    # AWS Bedrock Model Providers Configuration
    AWS_BEDROCK_MODEL_PROVIDERS: ClassVar[dict] = {
        "CHAT_MODEL_NAME": os.environ.get("CHAT_MODEL_PROVIDER", "anthropic"),
        "SUMMARIZATION_MODEL_NAME": os.environ.get("SUMMARIZATION_MODEL_PROVIDER", "anthropic"),
        "EMBEDDING_MODEL_NAME": os.environ.get("EMBEDDING_MODEL_PROVIDER", "amazon"),
        "LLM_MODEL_NAME": os.environ.get("LLM_MODEL_PROVIDER", "meta"),
        "CLASSIFICATION_MODEL_NAME": os.environ.get("CLASSIFICATION_MODEL_PROVIDER", "meta"),
        "TABLE_SUMMARIZER_MODEL": os.environ.get("TABLE_SUMMARIZER_PROVIDER", "meta"),
        "VISION_MODEL": os.environ.get("VISION_MODEL_PROVIDER", "anthropic"),
        "OPTIMIZED_QUESTION_MODEL": os.environ.get("OPTIMIZED_QUESTION_PROVIDER", "meta"),
        "LANGUAGE_DETECTION_MODEL": os.environ.get("LANGUAGE_DETECTION_PROVIDER", "meta"),
        "CHAT_STREAMING_MODEL": os.environ.get("CHAT_STREAMING_PROVIDER", "meta"),
        "TRANSFORM_QUERY_MODEL_NAME": os.environ.get("TRANSFORM_QUERY_MODEL_NAME", "meta"),
        "VISUALIZATION_MODEL_NAME": os.environ.get("VISUALIZATION_MODEL_PROVIDER", "anthropic"),
        "TEXT_TO_SQL_MODEL": os.environ.get("TEXT_TO_SQL_MODEL_PROVIDER", "anthropic")
    }

    AWS_BEDROCK_MODEL_SETTINGS: ClassVar[dict] = {
        "CHAT_MODEL_NAME": os.environ.get("CHAT_MODEL_NAME", "us.anthropic.claude-sonnet-4-6"),
        "SUMMARIZATION_MODEL_NAME": os.environ.get("SUMMARIZATION_MODEL_NAME", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
        "EMBEDDING_MODEL_NAME": os.environ.get("EMBEDDING_MODEL_NAME", "amazon.titan-embed-text-v2:0"),
        "LLM_MODEL_NAME": os.environ.get("LLM_MODEL_NAME", "meta.llama3-3-70b-instruct-v1:0"),
        "CLASSIFICATION_MODEL_NAME": os.environ.get("CLASSIFICATION_MODEL_NAME", "meta.llama3-3-70b-instruct-v1:0"),
        "SUMMARIZE_MODEL_NAME": os.environ.get("SUMMARIZE_MODEL_NAME", "meta.llama3-3-70b-instruct-v1:0"),
        "TABLE_SUMMARIZER_MODEL": os.environ.get("TABLE_SUMMARIZER_MODEL", "meta.llama3-3-70b-instruct-v1:0"),
        "VISION_MODEL": os.environ.get("VISION_MODEL", "us.anthropic.claude-sonnet-4-6"),
        "OPTIMIZED_QUESTION_MODEL": os.environ.get("OPTIMIZED_QUESTION_MODEL", "meta.llama3-3-70b-instruct-v1:0"),
        "LANGUAGE_DETECTION_MODEL": os.environ.get("LANGUAGE_DETECTION_MODEL", "meta.llama3-3-70b-instruct-v1:0"),
        "CHAT_STREAMING_MODEL": os.environ.get("CHAT_STREAMING_MODEL", "meta.llama3-3-70b-instruct-v1:0"),
        "TRANSFORM_QUERY_MODEL_NAME": os.environ.get("TRANSFORM_QUERY_MODEL_NAME", "meta.llama3-3-70b-instruct-v1:0"),
        "VISUALIZATION_MODEL_NAME": os.environ.get("VISUALIZATION_MODEL_NAME", "us.anthropic.claude-sonnet-4-6"),
        "TEXT_TO_SQL_MODEL": os.environ.get("TEXT_TO_SQL_MODEL", "us.anthropic.claude-sonnet-4-6")
    }

    AWS_BEDROCK_MODEL_KWARGS: ClassVar[dict] = {
        "CHAT_MODEL_NAME": {
            "max_tokens": 8192,
        },
        "TEXT_TO_SQL_MODEL": {
            "max_tokens": 8192,
        }
    }

    # RAG Text Truncation Limits
    RAG_CONTENT_PREVIEW_LIMIT: int = int(os.environ.get("RAG_CONTENT_PREVIEW_LIMIT", 10000))
    RAG_SUMMARY_MIN_LENGTH: int = int(os.environ.get("RAG_SUMMARY_MIN_LENGTH", 100))
    RAG_SUMMARY_FALLBACK_LIMIT: int = int(os.environ.get("RAG_SUMMARY_FALLBACK_LIMIT", 500))
    DOCUMENT_PREVIEW_CHAR_LIMIT: int = int(os.environ.get("DOCUMENT_PREVIEW_CHAR_LIMIT", 800))

    # Text-to-SQL Database Configuration
    TEXT_TO_SQL_ATHENA_REGION: str = os.environ.get("TEXT_TO_SQL_ATHENA_REGION", "us-east-1")
    TEXT_TO_SQL_DATABASE_NAME: str = os.environ.get("TEXT_TO_SQL_DATABASE_NAME", "default")
    TEXT_TO_SQL_SQLITE_PATH: str = os.environ.get("TEXT_TO_SQL_SQLITE_PATH", "")
    TEXT_TO_SQL_EXTRACT_ALL_TABLES: bool = True
    TEXT_TO_SQL_TABLES_NAME: List[str] = []
    TOOL_SQL_TABLES_NAME: List[str] = []

    POLICY_OPENSEARCH_INDEX_NAME: str = os.environ.get("POLICY_OPENSEARCH_INDEX_NAME", "test_wp")
    POLICY_OPENSEARCH_NAMESPACE: str = os.environ.get("POLICY_OPENSEARCH_NAMESPACE", "shopassist")
    POLICY_S3_BUCKET: str = os.environ.get("POLICY_S3_BUCKET", "diya-temp")
    POLICY_S3_PREFIX: str = os.environ.get("POLICY_S3_PREFIX", "policy-documents/")

    # Redshift AWS Credentials (separate from Bedrock)
    REDSHIFT_AWS_ACCESS_KEY_ID: str = os.environ.get("REDSHIFT_AWS_ACCESS_KEY_ID", "")
    REDSHIFT_AWS_SECRET_ACCESS_KEY: str = os.environ.get("REDSHIFT_AWS_SECRET_ACCESS_KEY", "")
    REDSHIFT_AWS_REGION_NAME: str = os.environ.get("REDSHIFT_AWS_REGION_NAME", "")
    REDSHIFT_WORKGROUP: str = os.environ.get("REDSHIFT_WORKGROUP", "")

    # Redshift Database Configuration
    REDSHIFT_CLUSTER_ID: str = os.environ.get("REDSHIFT_CLUSTER_ID", "")
    REDSHIFT_DATABASE: str = os.environ.get("REDSHIFT_DATABASE", "")
    REDSHIFT_SECRET_ARN: str = os.environ.get("REDSHIFT_SECRET_ARN", "")
    REDSHIFT_HOST: str = os.environ.get("REDSHIFT_HOST", "")
    REDSHIFT_PORT: int = int(os.environ.get("REDSHIFT_PORT", 5439))
    REDSHIFT_USER: str = os.environ.get("REDSHIFT_USER", "")
    REDSHIFT_PASSWORD: str = os.environ.get("REDSHIFT_PASSWORD", "")
    REDSHIFT_SCHEMA: str = os.environ.get("REDSHIFT_SCHEMA", "public")

    # PostgreSQL Database Configuration
    POSTGRES_HOST: str = os.environ.get("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.environ.get("POSTGRES_PORT", 5432))
    POSTGRES_USER: str = os.environ.get("POSTGRES_USER", "")
    POSTGRES_PASSWORD: str = os.environ.get("POSTGRES_PASSWORD", "")
    POSTGRES_DATABASE: str = os.environ.get("POSTGRES_DATABASE", "")
    POSTGRES_SCHEMA: str = os.environ.get("POSTGRES_SCHEMA", "public")
    POSTGRES_SSLMODE: str = os.environ.get("POSTGRES_SSLMODE", "prefer")

    # Text-to-SQL Query Configuration
    TEXT_TO_SQL_QUERY_ALLOWED_OPERATIONS: List[str] = [
        op.strip()
        for op in os.environ.get("TEXT_TO_SQL_QUERY_ALLOWED_OPERATIONS", "SELECT, JOIN, AGGREGATION, WITH").split(",")
        if op.strip()
    ]
    TEXT_TO_SQL_QUERY_FORBIDDEN_OPERATIONS: List[str] = [
        op.strip()
        for op in os.environ.get(
            "TEXT_TO_SQL_QUERY_FORBIDDEN_OPERATIONS",
            "INSERT,UPDATE,DELETE,DROP,CREATE,ALTER,TRUNCATE,EXEC,EXECUTE,CALL,GRANT,REVOKE"
        ).split(",")
        if op.strip()
    ]
    TEXT_TO_SQL_QUERY_MAX_RESULTS: int = int(os.environ.get("TEXT_TO_SQL_QUERY_MAX_RESULTS", 200))
    TEXT_TO_SQL_OUTPUT_FORMAT: str = os.environ.get("TEXT_TO_SQL_OUTPUT_FORMAT", "dataframe")
    TEXT_TO_SQL_OUTPUT_INCLUDE_METADATA: bool = os.environ.get("TEXT_TO_SQL_OUTPUT_INCLUDE_METADATA", True)
    TEXT_TO_SQL_BEDROCK_TEMPERATURE: float = float(os.environ.get("TEXT_TO_SQL_BEDROCK_TEMPERATURE", 0.0))

    TOOL_MAX_RETRIES_LIMIT: int = int(os.environ.get("TOOL_MAX_RETRIES_LIMIT", 3))
    HEARTBEAT_INTERVAL_SECONDS: int = int(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", 15))
    WS_IDLE_TIMEOUT_SECONDS: int = int(os.environ.get("WS_IDLE_TIMEOUT_SECONDS", 300))
    TEXT_TO_SQL_TIMEOUT_SECONDS: float = float(os.environ.get("TEXT_TO_SQL_TIMEOUT_SECONDS", 90.0))
    MODEL_INVOCATION_TIMEOUT_SECONDS: float = float(os.environ.get("MODEL_INVOCATION_TIMEOUT_SECONDS", 180.0))
    RAG_TOOL_TIMEOUT_SECONDS: float = float(os.environ.get("RAG_TOOL_TIMEOUT_SECONDS", 60.0))

    # Rate Limiting Configuration
    RATE_LIMIT_MAX_MESSAGES: int = int(os.environ.get("RATE_LIMIT_MAX_MESSAGES", 15))
    RATE_LIMIT_WINDOW_SECONDS: int = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", 60))

    # Input Validation Configuration
    QUESTION_MAX_LENGTH: int = int(os.environ.get("QUESTION_MAX_LENGTH", 2000))
    QUESTION_PREVIEW_LENGTH: int = int(os.environ.get("QUESTION_PREVIEW_LENGTH", 100))

    # Chat History Configuration
    CHAT_HISTORY_RECENT_MESSAGES: int = int(os.environ.get("CHAT_HISTORY_RECENT_MESSAGES", 10))
    CHAT_HISTORY_CONTENT_MAX_LENGTH: int = int(os.environ.get("CHAT_HISTORY_CONTENT_MAX_LENGTH", 1500))

    # Agent Configuration
    DEEP_AGENT_TEMPERATURE: float = float(os.environ.get("DEEP_AGENT_TEMPERATURE", 0.2))
    DEEP_AGENT_RECURSION_LIMIT: int = int(os.environ.get("DEEP_AGENT_RECURSION_LIMIT", 50))

    # Workflow Configuration
    TOOL_RESPONSE_MAX_ROWS: int = int(os.environ.get("TOOL_RESPONSE_MAX_ROWS", 200))
    MAX_ROWS_FOR_LLM_CONTEXT: int = int(os.environ.get("MAX_ROWS_FOR_LLM_CONTEXT", 200))
    MAX_TOOL_OUTPUT_CHARS: int = int(os.environ.get("MAX_TOOL_OUTPUT_CHARS", 100000))
    MODEL_CONTEXT_WINDOW: int = int(os.environ.get("MODEL_CONTEXT_WINDOW", 200000))

    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

    # LangSmith Observability Configuration
    LANGSMITH_TRACING: str = os.environ.get("LANGSMITH_TRACING", "false")
    LANGSMITH_ENDPOINT: str = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    LANGSMITH_API_KEY: str = os.environ.get("LANGSMITH_API_KEY", "")
    LANGSMITH_PROJECT: str = os.environ.get("LANGSMITH_PROJECT", "default")

    # Prompt Caching Configuration
    ENABLE_PROMPT_CACHING: bool = str(os.environ.get("ENABLE_PROMPT_CACHING", "true")).lower() in {"true", "1", "yes"}

    # SQLAlchemy Connection Pool Configuration
    DB_POOL_SIZE: int = int(os.environ.get("DB_POOL_SIZE", 20))
    DB_MAX_OVERFLOW: int = int(os.environ.get("DB_MAX_OVERFLOW", 30))
    DB_POOL_PRE_PING: bool = str(os.environ.get("DB_POOL_PRE_PING", "true")).lower() in {"true", "1", "yes"}
    DB_POOL_RECYCLE: int = int(os.environ.get("DB_POOL_RECYCLE", 1800))
    DB_POOL_TIMEOUT: int = int(os.environ.get("DB_POOL_TIMEOUT", 30))
    DB_THREAD_POOL_WORKERS: int = int(os.environ.get("DB_THREAD_POOL_WORKERS", 50))

    # WebSocket Server Configuration
    WS_PING_INTERVAL: int = int(os.environ.get("WS_PING_INTERVAL", 20))
    WS_PING_TIMEOUT: int = int(os.environ.get("WS_PING_TIMEOUT", 20))
    PROMPT_CACHE_TTL: str = os.environ.get("PROMPT_CACHE_TTL", "5m")

    def validate_api_keys(self) -> None:
        if self.LLM_SERVICE_TYPE == LLMServiceType.AWS.value and not (
                self.AWS_ACCESS_KEY_ID and self.AWS_SECRET_ACCESS_KEY):
            raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required when using AWS service")

    def validate_vector_db_config(self) -> None:
        if self.VECTOR_DATABASE_TO_USE not in [e.value for e in VectorDBServiceType]:
            raise ValueError(f"Unsupported vector database: {self.VECTOR_DATABASE_TO_USE}")

    def validate_text_to_sql_config(self) -> None:
        if self.DATABASE_SERVICE_TYPE not in ["athena", "sqlite", "redshift", "postgres"]:
            raise ValueError(f"Unsupported database type: {self.DATABASE_SERVICE_TYPE}")

        if self.DATABASE_SERVICE_TYPE == DatabaseType.SQLITE.value and not self.TEXT_TO_SQL_SQLITE_PATH:
            raise ValueError("TEXT_TO_SQL_SQLITE_PATH must be set when DATABASE_SERVICE_TYPE is sqlite")

        if self.DATABASE_SERVICE_TYPE == DatabaseType.POSTGRES.value:
            if not self.POSTGRES_HOST or not self.POSTGRES_USER or not self.POSTGRES_DATABASE:
                raise ValueError(
                    "POSTGRES_HOST, POSTGRES_USER, and POSTGRES_DATABASE must be set "
                    "when DATABASE_SERVICE_TYPE is postgres"
                )

    def validate_checkpoint_config(self) -> None:
        if self.CHECKPOINT_TYPE.lower() == CheckpointType.SQLITE.value and not self.CHECKPOINT_DB_PATH:
            raise ValueError("CHECKPOINT_DB_PATH must be set when CHECKPOINT_TYPE is sqlite")

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        validate_assignment=True,
        extra="ignore",
        customise_sources=lambda init_s, env_s, file_s: (
            init_s,
            env_s,
            file_s,
        )
    )


try:
    config_settings = Settings()
    config_settings.validate_api_keys()
    config_settings.validate_vector_db_config()
    config_settings.validate_text_to_sql_config()
    config_settings.validate_checkpoint_config()
except Exception as e:
    raise RuntimeError(f"Failed to initialize application settings: {str(e)}")

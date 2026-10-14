import atexit
import json
import asyncio
import concurrent.futures
import re
import threading
import boto3
from urllib.parse import quote as url_quote

from pathlib import Path
from loguru import logger
from typing import Dict, Any, Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, text, inspect
from workflows.core.settings import config_settings, DatabaseType, StoreType, CheckpointType
from workflows.core.db.models import (
    QueryExecutionResult,
    DBConnectionOutputModel
)

from psycopg_pool import AsyncConnectionPool
from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.store.sqlite.aio import AsyncSqliteStore
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.memory import MemorySaver

from workflows.core.llm import get_chat_model, get_streaming_chat_model
from .utils import validate_query_text, truncate_rows, QueryValidationError
from workflows.core.db.prompts import (
    get_schema_description_prompt,
    get_few_shot_examples_prompt,
    get_business_guidelines,
    get_few_shot_example_validation_prompt,
    get_few_shot_regeneration_prompt,
    get_text_to_sql_prompt,
    TOOL_SQL_GENERATION_PROMPT,
    TOOL_SQL_SAMPLE_PARAMS,
)


_db_thread_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
_db_thread_pool_lock = threading.Lock()


def _get_db_thread_pool() -> concurrent.futures.ThreadPoolExecutor:
    global _db_thread_pool
    if _db_thread_pool is None:
        with _db_thread_pool_lock:
            if _db_thread_pool is None:
                workers = config_settings.DB_THREAD_POOL_WORKERS
                _db_thread_pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=workers,
                    thread_name_prefix="db_exec"
                )
                logger.info(f"DB thread pool created with {workers} workers")
    return _db_thread_pool


class DatabaseManager:
    class_instance: Optional['DatabaseManager'] = None
    class_initialized: bool = False
    class_lock = threading.Lock()

    def __new__(cls):
        if cls.class_instance is None:
            with cls.class_lock:
                if cls.class_instance is None:
                    cls.class_instance = super().__new__(cls)
        return cls.class_instance

    def __init__(self):
        if DatabaseManager.class_initialized:
            return
        self.database_name = config_settings.TEXT_TO_SQL_DATABASE_NAME
        self.sqlite_path = config_settings.TEXT_TO_SQL_SQLITE_PATH
        self.region = config_settings.TEXT_TO_SQL_ATHENA_REGION
        self.extract_all_tables = config_settings.TEXT_TO_SQL_EXTRACT_ALL_TABLES
        self.table_names_filter = config_settings.TEXT_TO_SQL_TABLES_NAME
        self.connection_string = None
        self.redshift_host = config_settings.REDSHIFT_HOST
        self.redshift_port = config_settings.REDSHIFT_PORT
        self.redshift_username = config_settings.REDSHIFT_USER
        self.redshift_password = config_settings.REDSHIFT_PASSWORD
        self.postgres_host = config_settings.POSTGRES_HOST
        self.postgres_port = config_settings.POSTGRES_PORT
        self.postgres_username = config_settings.POSTGRES_USER
        self.postgres_password = config_settings.POSTGRES_PASSWORD

        self.engine: Optional[Engine] = None
        self.connected = False
        self.schema: Dict[str, Any] = {}
        self.table_names: list = []
        self.session_local = None
        self.schema_prompt: Optional[str] = None
        self.few_shot_prompt: Optional[str] = None
        self.prebuilt_sql: Dict[str, str] = {}

        if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.REDSHIFT.value:
            self.db_schema_name = config_settings.REDSHIFT_SCHEMA
        elif config_settings.DATABASE_SERVICE_TYPE == DatabaseType.POSTGRES.value:
            self.db_schema_name = config_settings.POSTGRES_SCHEMA
        else:
            self.db_schema_name = None

        atexit.register(self.close)
        DatabaseManager.class_initialized = True

    async def connect(self):
        try:
            if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.SQLITE.value:
                path = Path(self.sqlite_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.touch()
                self.engine = self.create_engine()
                self.session_local = sessionmaker(bind=self.engine, expire_on_commit=False)

            elif config_settings.DATABASE_SERVICE_TYPE == DatabaseType.ATHENA.value:
                self.engine = self.create_engine()
                self.session_local = sessionmaker(bind=self.engine, expire_on_commit=False)

            elif config_settings.DATABASE_SERVICE_TYPE == DatabaseType.REDSHIFT.value:
                self.engine = self.create_engine()
                self.session_local = sessionmaker(bind=self.engine, expire_on_commit=False)

            elif config_settings.DATABASE_SERVICE_TYPE == DatabaseType.POSTGRES.value:
                self.engine = self.create_engine()
                self.session_local = sessionmaker(bind=self.engine, expire_on_commit=False)

            else:
                raise ValueError(
                    f"unsupported database type: {config_settings.DATABASE_SERVICE_TYPE}"
                )
            self.connected = True

            logger.info(f"Connected to {config_settings.DATABASE_SERVICE_TYPE} database")
            self.extract_and_store_schema()

            if not self.schema or not self.table_names:
                logger.error("Schema extraction failed. No schema or tables found.")
                raise RuntimeError("Schema extraction failed. Database schema is required for service initialization.")

            await self.generate_prompts()

            if not self.schema_prompt or not self.few_shot_prompt:
                logger.warning("Prompt generation failed or incomplete. Basic database operations will work, but advanced text-to-SQL features may be limited.")

            if self.few_shot_prompt:
                await self.validate_few_shot_examples()

            await self.build_refund_sql()

        except Exception as e:
            logger.error(f"Failed to connect to {config_settings.DATABASE_SERVICE_TYPE}: {str(e)}")
            raise

    def create_engine(self) -> Engine:
        connection_string = self.get_connection_string()
        try:
            engine_kwargs = {"pool_pre_ping": config_settings.DB_POOL_PRE_PING}

            if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.REDSHIFT.value:
                sslmode = "require" if config_settings.REDSHIFT_WORKGROUP else "prefer"
                engine_kwargs["connect_args"] = {"sslmode": sslmode}
                engine_kwargs["isolation_level"] = "AUTOCOMMIT"

            elif config_settings.DATABASE_SERVICE_TYPE == DatabaseType.POSTGRES.value:
                engine_kwargs["connect_args"] = {"sslmode": config_settings.POSTGRES_SSLMODE}
                engine_kwargs["pool_size"] = config_settings.DB_POOL_SIZE
                engine_kwargs["max_overflow"] = config_settings.DB_MAX_OVERFLOW
                engine_kwargs["pool_recycle"] = config_settings.DB_POOL_RECYCLE
                engine_kwargs["pool_timeout"] = config_settings.DB_POOL_TIMEOUT
                engine_kwargs["pool_reset_on_return"] = "rollback"
                engine_kwargs["pool_use_lifo"] = True

            engine = create_engine(connection_string, **engine_kwargs)

            if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.REDSHIFT.value:
                engine.dialect._set_backslash_escapes = lambda connection: setattr(
                    engine.dialect, "_backslash_escapes", False
                )

            logger.info(f"Engine created for {config_settings.DATABASE_SERVICE_TYPE} database successfully.")
            return engine
        except Exception as e:
            logger.error(f"Failed to create engine: {str(e)}", exc_info=True)
            raise e

    def get_connection_string(self) -> str:
        if self.connection_string:
            return self.connection_string

        if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.SQLITE.value:
            return f"sqlite:///{self.sqlite_path}"

        elif config_settings.DATABASE_SERVICE_TYPE == DatabaseType.REDSHIFT.value:
            redshift_aws_key = config_settings.REDSHIFT_AWS_ACCESS_KEY_ID or config_settings.AWS_ACCESS_KEY_ID
            redshift_aws_secret = config_settings.REDSHIFT_AWS_SECRET_ACCESS_KEY or config_settings.AWS_SECRET_ACCESS_KEY
            redshift_region = config_settings.REDSHIFT_AWS_REGION_NAME or config_settings.AWS_REGION_NAME

            if config_settings.REDSHIFT_WORKGROUP:
                try:
                    logger.info("Attempting IAM auth for Redshift Serverless...")
                    iam_user, iam_pass = self.get_redshift_serverless_credentials(
                        redshift_aws_key, redshift_aws_secret, redshift_region
                    )
                    username = url_quote(iam_user, safe='')
                    password = url_quote(iam_pass, safe='')
                    return f"postgresql+psycopg://{username}:{password}@{self.redshift_host}:{self.redshift_port}/{self.database_name}"
                except Exception as e:
                    logger.warning(f"IAM auth failed, falling back to direct credentials: {e}")

            if self.redshift_host and self.redshift_username:
                username = url_quote(self.redshift_username, safe='')
                password = url_quote(self.redshift_password, safe='')
                return f"postgresql+psycopg://{username}:{password}@{self.redshift_host}:{self.redshift_port}/{self.database_name}"

            elif self.redshift_host:
                access_key = url_quote(redshift_aws_key, safe='')
                secret_key = url_quote(redshift_aws_secret, safe='')
                return f"postgresql+psycopg://{access_key}:{secret_key}@{self.redshift_host}:{self.redshift_port}/{self.database_name}"

            else:
                access_key = url_quote(redshift_aws_key, safe='')
                secret_key = url_quote(redshift_aws_secret, safe='')
                return (
                    f"postgresql+psycopg://{access_key}:{secret_key}"
                    f"@{config_settings.REDSHIFT_CLUSTER_ID}.{self.region}"
                    f".redshift.amazonaws.com:{self.redshift_port}/{self.database_name}"
                )

        elif config_settings.DATABASE_SERVICE_TYPE == DatabaseType.ATHENA.value:
            access_key = url_quote(config_settings.AWS_ACCESS_KEY_ID, safe='')
            secret_key = url_quote(config_settings.AWS_SECRET_ACCESS_KEY, safe='')
            return f"awsathena+rest://{access_key}:{secret_key}@athena.{self.region}.amazonaws.com:443/{self.database_name}"

        elif config_settings.DATABASE_SERVICE_TYPE == DatabaseType.POSTGRES.value:
            username = url_quote(self.postgres_username, safe='')
            password = url_quote(self.postgres_password, safe='')
            return (
                f"postgresql+psycopg://{username}:{password}"
                f"@{self.postgres_host}:{self.postgres_port}"
                f"/{config_settings.POSTGRES_DATABASE}"
            )

        raise ValueError("Unsupported or unspecified database type.")

    def get_store_uri(self) -> str:
        if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.POSTGRES.value:
            username = url_quote(self.postgres_username, safe='')
            password = url_quote(self.postgres_password, safe='')
            return (
                f"postgresql://{username}:{password}"
                f"@{self.postgres_host}:{self.postgres_port}"
                f"/{config_settings.POSTGRES_DATABASE}"
                f"?sslmode={config_settings.POSTGRES_SSLMODE}"
            )
        raise ValueError(f"get_store_uri() not supported for database type: {config_settings.DATABASE_SERVICE_TYPE}")

    def get_redshift_serverless_credentials(self, aws_key, aws_secret, region):
        client = boto3.client(
            "redshift-serverless",
            region_name=region,
            aws_access_key_id=aws_key,
            aws_secret_access_key=aws_secret,
        )
        creds = client.get_credentials(
            workgroupName=config_settings.REDSHIFT_WORKGROUP,
            dbName=self.database_name,
        )
        logger.info(f"IAM temp credentials obtained for user: {creds['dbUser']}")
        return creds["dbUser"], creds["dbPassword"]

    def extract_and_store_schema(self):
        try:
            logger.debug("Extracting database schema")
            schema: Dict[str, Any] = {}

            if not self.engine:
                logger.warning("Engine not available for schema extraction")
                return

            if config_settings.DATABASE_SERVICE_TYPE in (
                DatabaseType.REDSHIFT.value, DatabaseType.POSTGRES.value
            ):
                db_label = "Redshift" if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.REDSHIFT.value else "PostgreSQL"
                excluded_schemas = (
                    "'information_schema', 'pg_catalog', 'pg_internal', 'pg_toast'"
                    if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.REDSHIFT.value
                    else "'information_schema', 'pg_catalog', 'pg_toast'"
                )
                with self.engine.connect() as conn:
                    logger.debug(f"Extracting {db_label} schema via information_schema")

                    schema_filter = "AND table_schema = :schema_name" if self.db_schema_name else ""
                    schema_params = {"schema_name": self.db_schema_name} if self.db_schema_name else {}

                    table_result = conn.execute(text(f"""
                        SELECT table_schema, table_name
                        FROM information_schema.tables
                        WHERE table_type = 'BASE TABLE'
                        AND table_schema NOT IN ({excluded_schemas})
                        {schema_filter}
                        ORDER BY table_schema, table_name
                    """), schema_params)

                    table_data = [(row[0], row[1]) for row in table_result]

                    if self.extract_all_tables:
                        tables_to_extract = table_data
                    else:
                        tables_to_extract = [
                            (s, t) for s, t in table_data if t in self.table_names_filter
                        ] if self.table_names_filter else []

                    logger.debug(f"{db_label}: found {len(table_data)} tables, extracting {len(tables_to_extract)}")

                    for schema_name, table_name in tables_to_extract:
                        col_result = conn.execute(text("""
                            SELECT column_name, data_type, is_nullable, column_default
                            FROM information_schema.columns
                            WHERE table_schema = :schema_name AND table_name = :table_name
                            ORDER BY ordinal_position
                        """), {"schema_name": schema_name, "table_name": table_name})

                        schema[table_name] = [
                            {
                                "name": row[0],
                                "type": row[1],
                                "nullable": row[2] == "YES",
                                "default": row[3]
                            }
                            for row in col_result
                        ]
            else:
                inspector = inspect(self.engine)
                all_tables = inspector.get_table_names()

                if self.extract_all_tables:
                    tables_to_extract = all_tables
                else:
                    tables_to_extract = [
                        t for t in all_tables if t in self.table_names_filter
                    ] if self.table_names_filter else []

                for t in tables_to_extract:
                    cols = inspector.get_columns(t)
                    schema[t] = [
                        {
                            "name": c["name"],
                            "type": str(c["type"]),
                            "nullable": c.get("nullable"),
                            "default": c.get("default")
                        }
                        for c in cols
                    ]

            self.schema = schema
            self.table_names = list(schema.keys())
            logger.info(f"Schema extracted successfully. Tables: {self.table_names}")

        except Exception as e:
            logger.error(f"Error extracting schema: {str(e)}", exc_info=True)
            self.schema = {}
            self.table_names = []

    def get_qualified_schema_for_prompts(self) -> Dict[str, Any]:
        if not self.db_schema_name:
            return self.schema
        qualified = {}
        for table_name, columns in self.schema.items():
            qualified_name = f"{self.db_schema_name}.{table_name}"
            qualified[qualified_name] = columns
        return qualified

    def get_qualified_table(self, table_name: str) -> str:
        if self.db_schema_name:
            return f"{self.db_schema_name}.{table_name}"
        return table_name

    async def generate_prompts(self):
        try:
            if not self.schema:
                logger.warning("No schema available for prompt generation")
                return None

            llm = get_chat_model("TEXT_TO_SQL_MODEL", temperature=0.0)
            if llm is None:
                logger.error("LLM unavailable for prompt generation")
                return None

            schema_json = json.dumps(self.get_qualified_schema_for_prompts())
            business_guidelines = get_business_guidelines()

            schema_prompt_template = get_schema_description_prompt()
            if schema_prompt_template is None:
                logger.error("Schema description prompt template unavailable")
                return None

            schema_rendered = schema_prompt_template.format(
                database_type=config_settings.DATABASE_SERVICE_TYPE,
                schema=schema_json,
                business_guidelines=business_guidelines,
            )
            schema_res = await llm.ainvoke(schema_rendered)
            schema_content = getattr(schema_res, "content", None)
            if not isinstance(schema_content, str):
                schema_content = str(schema_content)
            self.schema_prompt = schema_content.strip()

            few_shot_prompt_template = get_few_shot_examples_prompt()
            if few_shot_prompt_template is None:
                logger.error("Few-shot examples prompt template unavailable")
                return None

            few_shot_rendered = few_shot_prompt_template.format(
                database_type=config_settings.DATABASE_SERVICE_TYPE,
                schema=schema_json,
                business_guidelines=business_guidelines,
            )
            few_shot_res = await llm.ainvoke(few_shot_rendered)
            few_shot_content = getattr(few_shot_res, "content", None)
            if not isinstance(few_shot_content, str):
                few_shot_content = str(few_shot_content)
            self.few_shot_prompt = few_shot_content.strip()

            logger.info(f"Schema prompt generated: {bool(self.schema_prompt)}")
            logger.info(f"Few-shot prompt generated: {bool(self.few_shot_prompt)}")

        except Exception as e:
            logger.error(f"Error generating prompts: {str(e)}", exc_info=True)

    def extract_examples_from_few_shot(self, prompt_text: str) -> list:
        examples = []
        blocks = re.split(r'### Example\s+\d+', prompt_text)
        for i, block in enumerate(blocks[1:], 1):
            question_match = re.search(
                r'-- Natural-Language Request:\s*\n(.+?)(?=\n\s*\n|-- SQL:)',
                block, re.DOTALL
            )
            sql_match = re.search(
                r'-- SQL:\s*\n(.*?)(?=\n### Example|\Z)',
                block, re.DOTALL
            )
            question = question_match.group(1).strip() if question_match else ""
            sql = sql_match.group(1).strip().rstrip(';').strip() if sql_match else ""
            if sql:
                examples.append({"number": i, "question": question, "sql": sql})
        return examples

    def execute_few_shot_example(self, sql: str) -> dict:
        sql_clean = sql.rstrip(';').strip()
        if not sql_clean or sql_clean.endswith(('>', '<', '=', 'AND', 'OR', 'WHERE', 'BY', 'ON', 'FROM', ',')):
            return {
                "success": False,
                "row_count": 0,
                "data": None,
                "error": f"Truncated or incomplete SQL: ...{sql_clean[-50:]}"
            }
        sql_with_limit = sql_clean + " LIMIT 5;" if "LIMIT" not in sql_clean.upper() else sql_clean + ";"
        try:
            result = self.execute(sql_with_limit)
            if result.success:
                rows = result.rows[:5] if result.rows else []
                return {
                    "success": True,
                    "row_count": result.metadata.get("row_count", len(rows)),
                    "data": rows,
                    "error": None
                }
            return {
                "success": False,
                "row_count": 0,
                "data": None,
                "error": result.message
            }
        except Exception as e:
            return {
                "success": False,
                "row_count": 0,
                "data": None,
                "error": str(e)
            }

    async def validate_few_shot_examples(self):
        if not self.few_shot_prompt:
            return

        max_retries = 2

        for attempt in range(max_retries):
            examples = self.extract_examples_from_few_shot(self.few_shot_prompt)
            if not examples:
                logger.warning("No SQL examples found in few-shot prompt to validate")
                return

            logger.info(f"Validating {len(examples)} few-shot examples (attempt {attempt + 1}/{max_retries})...")

            execution_failed = []
            for ex in examples:
                exec_result = self.execute_few_shot_example(ex["sql"])
                ex["exec_result"] = exec_result
                if exec_result["success"]:
                    logger.info(f"  Example {ex['number']}: Executed OK ({exec_result['row_count']} rows)")
                else:
                    logger.warning(f"  Example {ex['number']}: FAILED - {exec_result['error']}")
                    execution_failed.append(ex)

            if not execution_failed:
                logger.info(f"All {len(examples)} few-shot examples passed execution validation")
                break

            logger.warning(
                f"{len(execution_failed)}/{len(examples)} few-shot examples failed execution. "
                f"Regenerating (attempt {attempt + 1})..."
            )
            await self.regenerate_few_shot_examples(execution_failed)

        await self.semantic_validate_few_shot_examples()

    async def semantic_validate_few_shot_examples(self):
        llm = get_chat_model("TEXT_TO_SQL_MODEL", temperature=0.0)
        if not llm:
            logger.warning("LLM unavailable for few-shot semantic validation")
            return

        db_type = config_settings.DATABASE_SERVICE_TYPE
        schema_json = json.dumps(self.get_qualified_schema_for_prompts())
        business_guidelines = get_business_guidelines()

        examples = self.extract_examples_from_few_shot(self.few_shot_prompt)
        if not examples:
            logger.warning("No examples to semantically validate")
            return

        logger.info(f"Running per-example LLM semantic validation on {len(examples)} examples...")
        invalid_examples = []

        for ex in examples:
            exec_result = self.execute_few_shot_example(ex["sql"])
            execution_status = "SUCCESS" if exec_result["success"] else f"FAILED: {exec_result['error']}"
            execution_results = json.dumps(exec_result["data"][:5], default=str) if exec_result["data"] else "No results"

            prompt = get_few_shot_example_validation_prompt(
                database_type=db_type,
                schema_json=schema_json,
                business_guidelines=business_guidelines,
                example_number=ex["number"],
                question=ex["question"],
                sql_query=ex["sql"],
                execution_status=execution_status,
                execution_results=execution_results
            )

            try:
                response = await llm.ainvoke(prompt)
                content = response.content if hasattr(response, 'content') else str(response)
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()

                result = json.loads(content)
                is_valid = result.get("is_valid", False)
                issues = result.get("issues", [])

                if is_valid:
                    logger.info(f"  Example {ex['number']}: LLM validation PASSED")
                else:
                    logger.warning(f"  Example {ex['number']}: LLM validation FAILED - {issues}")
                    invalid_examples.append({
                        "number": ex["number"],
                        "question": ex["question"],
                        "sql": ex["sql"],
                        "issues": issues,
                        "fixed_sql": result.get("fixed_sql")
                    })

            except json.JSONDecodeError as e:
                logger.warning(f"  Example {ex['number']}: Failed to parse LLM response: {e}")
            except Exception as e:
                logger.warning(f"  Example {ex['number']}: LLM validation error: {e}")

        if not invalid_examples:
            logger.success(f"All {len(examples)} few-shot examples passed LLM semantic validation")
            return

        logger.warning(f"{len(invalid_examples)}/{len(examples)} examples failed LLM validation. Regenerating...")
        await self.regenerate_few_shot_examples(invalid_examples)

        final_examples = self.extract_examples_from_few_shot(self.few_shot_prompt)
        all_pass = True
        for ex in final_examples:
            exec_result = self.execute_few_shot_example(ex["sql"])
            if not exec_result["success"]:
                logger.warning(f"  Example {ex['number']}: Still failing after regeneration - {exec_result['error']}")
                all_pass = False
            else:
                logger.info(f"  Example {ex['number']}: Post-regeneration execution OK")

        if all_pass:
            logger.success("All few-shot examples pass after regeneration")
        else:
            logger.warning("Some few-shot examples still have issues after regeneration")

    async def regenerate_few_shot_examples(self, failed_examples: list):
        try:
            llm = get_chat_model("TEXT_TO_SQL_MODEL", temperature=0.0)
            if not llm:
                return

            db_type = config_settings.DATABASE_SERVICE_TYPE
            schema_json = json.dumps(self.get_qualified_schema_for_prompts())
            business_guidelines = get_business_guidelines()

            issues_text = "\n".join(
                f"Example {ex.get('number', '?')}: Question='{ex.get('question', '')[:80]}' "
                f"Issues={ex.get('issues', ex.get('exec_result', {}).get('error', 'unknown'))}"
                for ex in failed_examples
            )

            prompt = get_few_shot_regeneration_prompt(
                database_type=db_type,
                schema_json=schema_json,
                business_guidelines=business_guidelines,
                few_shot_examples=self.few_shot_prompt,
                validation_issues=issues_text
            )

            response = await llm.ainvoke(prompt)
            content = getattr(response, "content", None)

            if isinstance(content, str) and content.strip():
                self.few_shot_prompt = content.strip()
                logger.info("Few-shot examples regenerated with issue context")

        except Exception as e:
            logger.warning(f"Failed to regenerate few-shot examples: {e}")

    def execute(self, sql: str) -> QueryExecutionResult:
        if not self.connected:
            raise RuntimeError("Database not connected. Connection must be established at startup.")

        try:
            validate_query_text(sql)

            if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.SQLITE.value:
                session = self.session_local()
                try:
                    result = session.execute(text(sql))
                    cols = result.keys()
                    data = result.fetchall()
                    rows = [dict(zip(cols, r)) for r in data]
                    session.commit()
                    rows = truncate_rows(rows, config_settings.TEXT_TO_SQL_QUERY_MAX_RESULTS)
                    metadata = {"row_count": len(rows)}
                    return QueryExecutionResult(success=True, rows=rows, metadata=metadata, message="")
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error executing SQLite query: {str(e)}", exc_info=True)
                    return QueryExecutionResult(success=False, rows=None, metadata={}, message=str(e))
                finally:
                    session.close()

            elif config_settings.DATABASE_SERVICE_TYPE == DatabaseType.ATHENA.value:
                return QueryExecutionResult(
                    success=False, rows=None, metadata={},
                    message="athena execution not implemented"
                )

            elif config_settings.DATABASE_SERVICE_TYPE in (
                DatabaseType.REDSHIFT.value, DatabaseType.POSTGRES.value
            ):
                db_label = "Redshift" if config_settings.DATABASE_SERVICE_TYPE == DatabaseType.REDSHIFT.value else "PostgreSQL"
                try:
                    with self.engine.connect() as conn:
                        result = conn.execute(text(sql))
                        cols = result.keys()
                        data = result.fetchall()
                        rows = [dict(zip(cols, r)) for r in data]
                    rows = truncate_rows(rows, config_settings.TEXT_TO_SQL_QUERY_MAX_RESULTS)
                    metadata = {"row_count": len(rows)}
                    return QueryExecutionResult(success=True, rows=rows, metadata=metadata, message="")
                except Exception as e:
                    logger.error(f"Error executing {db_label} query: {str(e)}", exc_info=True)
                    return QueryExecutionResult(success=False, rows=None, metadata={}, message=str(e))

            else:
                return QueryExecutionResult(
                    success=False, rows=None, metadata={},
                    message="unsupported database type"
                )

        except Exception as e:
            return QueryExecutionResult(success=False, rows=None, metadata={}, message=str(e))

    async def generate_sql_from_query(
        self,
        user_query: str,
        prompt_template: Optional[str] = None,
        temperature: float = 0.0,
        callbacks: Optional[list] = None
    ) -> str:
        if not self.connected:
            raise RuntimeError("Database not connected. Connection must be established at startup.")

        try:
            logger.info(f"Generating SQL for query: {user_query[:100]}...")

            if callbacks:
                llm = get_streaming_chat_model("TEXT_TO_SQL_MODEL", temperature=temperature, callbacks=callbacks)
            else:
                llm = get_chat_model("TEXT_TO_SQL_MODEL", temperature=temperature)

            if not llm:
                logger.error("Failed to initialize LLM model for SQL generation")
                raise ValueError("LLM model not available for SQL generation")

            if not self.schema:
                logger.error("No schema available for SQL generation")
                raise ValueError("Database schema is required for SQL generation")

            business_guidelines = get_business_guidelines()

            if prompt_template:
                prompt = prompt_template.format(
                    user_query=user_query,
                    schema=json.dumps(self.get_qualified_schema_for_prompts()),
                    schema_description=self.schema_prompt if self.schema_prompt else 'Not available',
                    few_shot_examples=self.few_shot_prompt if self.few_shot_prompt else 'Not available',
                    business_guidelines=business_guidelines,
                    database_type=config_settings.DATABASE_SERVICE_TYPE,
                    allowed_operations=', '.join(config_settings.TEXT_TO_SQL_QUERY_ALLOWED_OPERATIONS),
                    forbidden_operations=', '.join(config_settings.TEXT_TO_SQL_QUERY_FORBIDDEN_OPERATIONS),
                    max_results=config_settings.TEXT_TO_SQL_QUERY_MAX_RESULTS
                )
            else:
                prompt = get_text_to_sql_prompt(
                    schema=json.dumps(self.get_qualified_schema_for_prompts()),
                    schema_description=self.schema_prompt,
                    business_guidelines=business_guidelines,
                    few_shot_examples=self.few_shot_prompt,
                    user_query=user_query,
                    database_type=config_settings.DATABASE_SERVICE_TYPE,
                    max_results=config_settings.TEXT_TO_SQL_QUERY_MAX_RESULTS,
                    allowed_operations=', '.join(config_settings.TEXT_TO_SQL_QUERY_ALLOWED_OPERATIONS),
                    forbidden_operations=', '.join(config_settings.TEXT_TO_SQL_QUERY_FORBIDDEN_OPERATIONS)
                )

            response = await llm.ainvoke(prompt)
            raw_sql = response.content if hasattr(response, 'content') else str(response)

            sql_query = self.extract_sql_from_response(raw_sql)

            logger.info(f"Generated SQL query: {sql_query}")
            return sql_query

        except Exception as e:
            logger.error(f"SQL generation failed: {str(e)}")
            raise

    def extract_sql_from_response(self, response: str) -> str:
        response = response.strip()

        if response.startswith("```sql"):
            response = response[6:]
        elif response.startswith("```"):
            response = response[3:]

        if response.endswith("```"):
            response = response[:-3]

        sql_query = response.strip()
        lines = sql_query.split('\n')
        sql_lines = []

        for line in lines:
            line = line.strip()
            if not line or line.startswith('--') or line.startswith('#'):
                continue
            if any(word in line.lower() for word in ['query:', 'sql:', 'answer:', 'result:']):
                continue
            sql_lines.append(line)

        sql_query = ' '.join(sql_lines)

        if sql_query and not sql_query.endswith(';'):
            sql_query += ';'

        return sql_query

    async def execute_query_from_text(
        self,
        user_query: str,
        prompt_template: Optional[str] = None,
        temperature: float = 0.0,
        callbacks: Optional[list] = None
    ) -> QueryExecutionResult:
        try:
            sql_query = await self.generate_sql_from_query(user_query, prompt_template, temperature, callbacks)

            if sql_query.strip().upper().startswith("UNMAPPABLE:"):
                unmappable_msg = sql_query.strip()
                logger.warning(f"Text-to-SQL returned unmappable: {unmappable_msg}")
                return QueryExecutionResult(
                    success=False,
                    rows=None,
                    metadata={"user_query": user_query, "error": unmappable_msg, "generated_sql": ""},
                    message=unmappable_msg
                )

            try:
                validate_query_text(sql_query, reject_select_star=True)
            except QueryValidationError as ve:
                return QueryExecutionResult(
                    success=False,
                    rows=None,
                    metadata={"user_query": user_query, "error": str(ve), "generated_sql": sql_query},
                    message=f"Query blocked: {ve}"
                )
            result = await asyncio.get_running_loop().run_in_executor(_get_db_thread_pool(), self.execute, sql_query)

            if result.success:
                result.metadata["generated_sql"] = sql_query
                result.metadata["user_query"] = user_query

            return result

        except Exception as e:
            logger.error(f"Execute query from text failed: {str(e)}")
            return QueryExecutionResult(
                success=False,
                rows=None,
                metadata={"user_query": user_query, "error": str(e)},
                message=f"Failed to execute query: {str(e)}"
            )

    async def execute_prebuilt_sql_with_params(
        self,
        section_name: str,
        params: Dict[str, str],
    ) -> "QueryExecutionResult":
        """Execute a refund SQL template substituting {param_name} placeholders.

        params: dict mapping placeholder name → safe literal value already escaped by caller.
        """
        sql = self.prebuilt_sql.get(section_name)
        if not sql:
            return QueryExecutionResult(
                success=False,
                rows=None,
                metadata={"section": section_name},
                message=f"No prebuilt SQL found for section '{section_name}'. Run build_refund_sql() first.",
            )
        try:
            sql_ready = sql
            for key, val in params.items():
                sql_ready = sql_ready.replace("{" + key + "}", val)
        except Exception as e:
            return QueryExecutionResult(
                success=False,
                rows=None,
                metadata={"section": section_name},
                message=f"Parameter substitution failed: {e}",
            )

        logger.info(f"[execute_prebuilt_sql_with_params] section={section_name} params={list(params.keys())} sql={sql_ready[:300]}")

        return await asyncio.get_running_loop().run_in_executor(_get_db_thread_pool(), self.execute, sql_ready)

    def extract_tables_schema(self, table_names: list) -> Dict[str, Any]:
        schema = {}
        if not self.engine:
            return schema
        with self.engine.connect() as conn:
            for table_name in table_names:
                col_result = conn.execute(text("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = :schema_name AND table_name = :table_name
                    ORDER BY ordinal_position
                """), {
                    "schema_name": self.db_schema_name or "public",
                    "table_name": table_name
                })
                cols = [
                    {"name": row[0], "type": row[1], "nullable": row[2] == "YES", "default": row[3]}
                    for row in col_result
                ]
                if cols:
                    qualified = f"{self.db_schema_name or 'public'}.{table_name}"
                    schema[qualified] = cols
        return schema

    async def build_refund_sql(self) -> None:
        if not self.connected:
            logger.warning("Cannot build tool SQL — DB not ready")
            return

        tool_tables = config_settings.TOOL_SQL_TABLES_NAME
        if not tool_tables:
            logger.info("TOOL_SQL_TABLES_NAME not configured — skipping tool SQL generation")
            return

        llm = get_chat_model("TEXT_TO_SQL_MODEL", temperature=0.0)
        if not llm:
            logger.error("LLM unavailable for tool SQL generation")
            return

        tool_schema = self.extract_tables_schema(tool_tables)
        if not tool_schema:
            logger.error(f"Failed to extract tool table schema for: {tool_tables}")
            return
        schema_json = json.dumps(tool_schema)
        business_guidelines = get_business_guidelines()

        max_retries = 3
        previous_attempt_block = ""

        for attempt in range(max_retries):
            prompt = TOOL_SQL_GENERATION_PROMPT.format(
                database_type=config_settings.DATABASE_SERVICE_TYPE,
                schema=schema_json,
                business_guidelines=business_guidelines,
                previous_attempt_block=previous_attempt_block,
            )

            logger.info(f"Tool SQL generation attempt {attempt+1}/{max_retries}...")
            response = await llm.ainvoke(prompt)
            raw_content = (getattr(response, "content", "") or "").strip()

            if raw_content.startswith("```"):
                raw_content = raw_content.split("```")[1]
                if raw_content.startswith("json"):
                    raw_content = raw_content[4:]
                raw_content = raw_content.strip()

            try:
                generated = json.loads(raw_content)
            except json.JSONDecodeError as e:
                logger.warning(f"  attempt {attempt+1}: JSON parse failed — {e}")
                previous_attempt_block = (
                    f"PREVIOUS ATTEMPT FAILED:\nOUTPUT: {raw_content[:500]}\n"
                    f"ERROR: Invalid JSON — {e}\nReturn valid JSON only.\n"
                )
                continue

            if not isinstance(generated, dict):
                previous_attempt_block = "PREVIOUS ATTEMPT FAILED:\nERROR: Output was not a JSON object.\n"
                continue

            if not generated:
                previous_attempt_block = "PREVIOUS ATTEMPT FAILED:\nERROR: Empty JSON object returned.\n"
                continue

            failed_sections = []
            for section_name, sql_raw in generated.items():
                sql_template = sql_raw.strip().rstrip(";") + ";"

                sample_sql = sql_template
                for param, val in TOOL_SQL_SAMPLE_PARAMS.items():
                    sample_sql = sample_sql.replace("{" + param + "}", val)

                result = await asyncio.get_running_loop().run_in_executor(
                    _get_db_thread_pool(), self.execute, sample_sql
                )
                if result.success:
                    self.prebuilt_sql[section_name] = sql_template
                    logger.info(f"  [{section_name}] PASSED — {len(result.rows or [])} rows")
                else:
                    failed_sections.append((section_name, result.message))
                    logger.warning(f"  [{section_name}] FAILED — {result.message}")

            if not failed_sections:
                logger.info(f"All {len(generated)} tool SQL sections validated successfully")
                return

            errors_text = "\n".join(
                f"- {name}: {err}" for name, err in failed_sections
            )
            previous_attempt_block = (
                f"PREVIOUS ATTEMPT FAILED:\nThese sections had execution errors:\n{errors_text}\n"
                "Regenerate ALL sections with corrections for the failed ones.\n"
            )

        logger.error(
            f"Tool SQL generation failed after {max_retries} attempts. "
            f"Sections ready: {len(self.prebuilt_sql)}"
        )

    def execute_write(self, sql: str) -> QueryExecutionResult:
        """Execute a write statement (INSERT/UPDATE) on the refund tables.

        Bypasses validate_query_text which blocks write operations.
        Only used by approve_refund and deny_refund tools.
        """
        if not self.connected:
            raise RuntimeError("Database not connected.")
        try:
            if config_settings.DATABASE_SERVICE_TYPE in (
                DatabaseType.REDSHIFT.value, DatabaseType.POSTGRES.value
            ):
                with self.engine.connect() as conn:
                    result = conn.execute(text(sql))
                    conn.commit()
                    cols = result.keys() if result.returns_rows else []
                    rows = [dict(zip(cols, r)) for r in result.fetchall()] if result.returns_rows else []
                return QueryExecutionResult(success=True, rows=rows, metadata={"row_count": len(rows)}, message="")
            return QueryExecutionResult(success=False, rows=None, metadata={}, message="unsupported database type for write")
        except Exception as e:
            logger.error(f"execute_write error: {str(e)}", exc_info=True)
            return QueryExecutionResult(success=False, rows=None, metadata={}, message=str(e))

    def close(self):
        if self.engine:
            self.engine.dispose()
            logger.info(f"Connection to {config_settings.DATABASE_SERVICE_TYPE} database closed successfully.")
        self.connected = False
        self.schema = {}
        self.table_names = []
        self.schema_prompt = None
        self.few_shot_prompt = None
        self.prebuilt_sql = {}

        global _db_thread_pool

        if _db_thread_pool is not None:
            _db_thread_pool.shutdown(wait=False)
            _db_thread_pool = None

    def is_ready(self) -> bool:
        return self.connected and bool(self.schema) and bool(self.schema_prompt) and bool(self.few_shot_prompt)


db_connector = None


async def initialize_connection_to_db() -> DBConnectionOutputModel:
    connection_status = False
    try:
        db_type = config_settings.DATABASE_SERVICE_TYPE
        logger.info(f"Connecting to the database: {db_type}")

        if db_type in ["sqlite", "athena", "redshift", "postgres"]:
            logger.debug("Database manager initialization started.")

            db_manager = DatabaseManager()
            await db_manager.connect()
            logger.debug("Database manager initialized successfully.")

            if db_manager and db_manager.connected:
                connection_uri = None
                if db_manager.engine:
                    connection_uri = str(db_manager.engine.url)

                logger.info("Database connection established successfully.")
                connection_status = True

                return DBConnectionOutputModel(
                    status=connection_status,
                    message="Connected to the database successfully.",
                    connection=db_manager,
                    uri_connection=connection_uri,
                    database_schema=db_manager.schema,
                    table_names=db_manager.table_names,
                    schema_prompt=db_manager.schema_prompt,
                    few_shot_prompt=db_manager.few_shot_prompt,
                    store=None,
                    store_ctx=None,
                    checkpointer=None,
                    checkpoint_pool=None,
                )
            else:
                logger.warning("Database connection attempt failed.")
                return DBConnectionOutputModel(
                    status=False,
                    message="Failed to connect to the database.",
                    connection=None,
                    uri_connection=None,
                    database_schema=None,
                    table_names=None,
                    schema_prompt=None,
                    few_shot_prompt=None,
                )
        else:
            logger.error(f"Unsupported database type: {db_type}")
            return DBConnectionOutputModel(
                status=False,
                message=f"Unsupported database type {db_type}",
                connection=None,
                uri_connection=None,
                database_schema=None,
                table_names=None,
                schema_prompt=None,
                few_shot_prompt=None,
            )

    except Exception as e:
        logger.error(f"Failed to initialize database connection: {str(e)}", exc_info=True)
        return DBConnectionOutputModel(
            status=False,
            message=f"Database connection initialization failed: {str(e)}",
            connection=None,
            uri_connection=None,
            database_schema=None,
            table_names=None,
            schema_prompt=None,
            few_shot_prompt=None,
        )

    finally:
        if not connection_status:
            logger.info("Database connection process completed with failures.")
        else:
            logger.info("Database connection process completed successfully.")


async def initialize_pools() -> None:
    global db_connector
    if db_connector is None or not db_connector.status:
        raise RuntimeError("Cannot initialize async pools: db_connector not ready")

    if db_connector.checkpointer is not None:
        logger.info("Async pools already initialized — skipping")
        return

    db_manager = db_connector.connection

    store = None
    store_ctx = None
    store_type = config_settings.STORE_TYPE.lower()

    if store_type == StoreType.POSTGRES.value:
        uri = config_settings.STORE_POSTGRES_URI or db_manager.get_store_uri()
        _store_ctx = AsyncPostgresStore.from_conn_string(uri)
        store = await _store_ctx.__aenter__()
        await store.setup()
        store_ctx = _store_ctx
        logger.info("PostgreSQL agent store singleton initialized")

    elif store_type == StoreType.SQLITE.value:
        path = config_settings.STORE_SQLITE_PATH or "store.db"
        _store_ctx = AsyncSqliteStore.from_conn_string(path)
        store = await _store_ctx.__aenter__()
        await store.setup()
        store_ctx = _store_ctx
        logger.info(f"SQLite agent store singleton initialized at {path}")

    else:
        logger.info("No agent store configured — running without store")

    checkpoint_pool = None
    checkpointer = None
    checkpointer_type = config_settings.CHECKPOINT_TYPE.lower()

    try:
        if checkpointer_type == CheckpointType.POSTGRES.value:
            postgres_uri = config_settings.get_checkpoint_postgres_uri()
            _checkpoint_pool = AsyncConnectionPool(
                conninfo=postgres_uri,
                min_size=config_settings.CHECKPOINT_POOL_MIN_SIZE,
                max_size=config_settings.CHECKPOINT_POOL_MAX_SIZE,
                max_idle=config_settings.CHECKPOINT_POOL_MAX_IDLE,
                max_lifetime=config_settings.CHECKPOINT_POOL_MAX_LIFETIME,
                reconnect_timeout=config_settings.CHECKPOINT_POOL_RECONNECT_TIMEOUT,
                timeout=config_settings.CHECKPOINT_POOL_TIMEOUT,
                check=AsyncConnectionPool.check_connection,
                kwargs={"autocommit": True, "prepare_threshold": 0},
                open=False,
            )
            await _checkpoint_pool.open(wait=True, timeout=30.0)
            logger.info(f"Checkpoint pool opened: min_size={config_settings.CHECKPOINT_POOL_MIN_SIZE}, max_size={config_settings.CHECKPOINT_POOL_MAX_SIZE}")
            async with _checkpoint_pool.connection() as conn:
                setup_saver = AsyncPostgresSaver(conn=conn)
                await setup_saver.setup()
            checkpointer = AsyncPostgresSaver(_checkpoint_pool)
            checkpoint_pool = _checkpoint_pool
            logger.info("PostgreSQL checkpoint pool initialized (in server event loop)")

        elif checkpointer_type == CheckpointType.SQLITE.value:
            checkpoint_path = (
                Path(config_settings.CHECKPOINT_DB_PATH).resolve()
                if config_settings.CHECKPOINT_DB_PATH
                else Path("checkpoints.db").resolve()
            )
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpointer = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
            await checkpointer.__aenter__()
            logger.info(f"SQLite checkpointer initialized at {checkpoint_path}")

        else:
            checkpointer = MemorySaver()
            logger.info("Using in-memory checkpointer")

    except Exception:
        if store_ctx is not None:
            try:
                await store_ctx.__aexit__(None, None, None)
            except Exception as cleanup_err:
                logger.warning(f"Failed to clean up store after checkpoint init failure: {cleanup_err}")
        raise

    db_connector.store = store
    db_connector.store_ctx = store_ctx
    db_connector.checkpointer = checkpointer
    db_connector.checkpoint_pool = checkpoint_pool


def initialize_db_connector():
    global db_connector

    if db_connector is None:
        logger.info("Initializing database connector for the first time...")
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is None:
                db_connector = asyncio.run(initialize_connection_to_db())
            else:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, initialize_connection_to_db())
                    db_connector = future.result()
        except Exception as e:
            logger.error(f"Failed to initialize db connector: {e}")
            raise
        logger.info(f"Database connector initialized. Status: {db_connector.status}")

    return db_connector



if __name__ == "__main__":
    db_conn = asyncio.run(initialize_connection_to_db())
    if db_conn.status:
        logger.info("Database connection initialized successfully.")
    else:
        logger.error("Database connection initialization failed.")

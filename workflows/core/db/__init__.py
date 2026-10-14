from loguru import logger
from workflows.core.db.client import initialize_db_connector
from .client import DatabaseManager


logger.info("=" * 80)
logger.info("DB startup: creating singleton and building text-to-SQL pipeline...")
logger.info("=" * 80)

try:
    db_connector = initialize_db_connector()

    if db_connector and db_connector.status:
        db_mgr: DatabaseManager = db_connector.connection
        table_count = len(db_connector.table_names) if db_connector.table_names else 0
        logger.success(f"DB connected  │ type={db_connector.uri_connection.split('://')[0] if db_connector.uri_connection else 'unknown'}")
        logger.info(   f"Schema        │ {table_count} table(s) extracted: {', '.join(db_connector.table_names or [])}")
        logger.info(   f"Schema prompt │ {'✓ generated' if db_connector.schema_prompt else '✗ missing'}")
        logger.info(   f"Few-shot      │ {'✓ generated' if db_connector.few_shot_prompt else '✗ missing'}")
        logger.info(   f"Refund SQL    │ {len(db_mgr.prebuilt_sql)} sections generated")
        logger.info(   f"Pipeline      │ {'READY — all tools fully operational' if db_mgr.is_ready() else 'PARTIAL — some tools may degrade'}")
    else:
        logger.error("DB connection failed — text_to_sql tool will not work")
        logger.error("Check DATABASE_SERVICE_TYPE and credentials in .env")
        raise RuntimeError("Database connection failed. Cannot start application without database connectivity.")

except RuntimeError:
    raise
except Exception as e:
    logger.error(f"DB startup failed: {str(e)}")
    raise RuntimeError(f"Failed to initialize database connector: {str(e)}")

logger.info("=" * 80)

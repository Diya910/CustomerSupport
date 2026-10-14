import re
from typing import List, Dict, Any
from workflows.core.settings import config_settings

FORBIDDEN = set(op.lower() for op in config_settings.TEXT_TO_SQL_QUERY_FORBIDDEN_OPERATIONS)
ALLOWED = set(op.lower() for op in config_settings.TEXT_TO_SQL_QUERY_ALLOWED_OPERATIONS)

operation_regex = re.compile(r"^\s*([a-zA-Z]+)", re.IGNORECASE)
sql_line_comment = re.compile(r'--[^\n]*')
sql_block_comment = re.compile(r'/\*.*?\*/', re.DOTALL)


class QueryValidationError(Exception):
    pass


def extract_operation(sql: str) -> str:
    m = operation_regex.match(sql)
    return m.group(1).lower() if m else ""


def strip_sql_comments(sql: str) -> str:
    sql = sql_block_comment.sub(' ', sql)
    sql = sql_line_comment.sub(' ', sql)
    return sql.strip()


def validate_query_text(sql: str, reject_select_star: bool = False) -> None:
    cleaned = strip_sql_comments(sql)
    op = extract_operation(cleaned)
    if not op:
        raise QueryValidationError("missing operation")
    if op in FORBIDDEN:
        raise QueryValidationError("forbidden operation")
    if ALLOWED and op not in ALLOWED:
        raise QueryValidationError("operation not allowed")
    if ";" in cleaned.strip().rstrip(";"):
        raise QueryValidationError("multiple statements forbidden")
    if reject_select_star:
        cte_names = set(m.group(1).lower() for m in re.finditer(r'\b(\w+)\s+AS\s*\(', cleaned, re.IGNORECASE))
        for m in re.finditer(r'\bSELECT\s+\*\s+FROM\s+(\S+)', cleaned, re.IGNORECASE):
            table_ref = m.group(1).lower().rstrip(",;)")
            if table_ref not in cte_names:
                raise QueryValidationError("SELECT * is not allowed; specify column names explicitly")


def truncate_rows(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    if limit and len(rows) > limit:
        return rows[:limit]
    return rows

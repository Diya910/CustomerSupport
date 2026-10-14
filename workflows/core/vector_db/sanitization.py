import re

from loguru import logger


def sanitize_index_name(name: str, db_type: str = "opensearch") -> str:
    if db_type.lower() == "opensearch":
        index_name = name.lower()
        index_name = index_name.replace(" ", "_")

        index_name = re.sub(r'[^a-z0-9_-]', '-', index_name)

        if index_name and not index_name[0].isalpha():
            index_name = 'p' + index_name

        if index_name and not (index_name[-1].isalnum()):
            index_name = index_name + '0'

        if len(index_name) > 45:
            index_name = index_name[:45]

        return index_name

    logger.warning(f"Unknown database type: {db_type}. Returning original name.")
    return name


def sanitize_namespace(namespace: str, db_type: str = "opensearch") -> str:
    if db_type in ("elasticsearch", "opensearch"):
        ns = namespace.lower()
        ns = ns.replace(" ", "_")
        return ns

    logger.warning(f"Unknown database type: {db_type}. Returning original namespace.")
    return namespace

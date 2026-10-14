from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from loguru import logger


class DateFilterError(Exception):
    """Custom exception for date filter parsing errors."""
    pass


def get_current_timestamp_ms() -> int:
    """
    Get current timestamp in epoch milliseconds.

    Returns:
        Current timestamp in milliseconds
    """
    return int(datetime.now().timestamp() * 1000)


def date_string_to_epoch_ms(date_str: str, end_of_day: bool = False) -> int:
    if not date_str or not isinstance(date_str, str):
        raise DateFilterError(f"Invalid date string: {date_str}")

    date_str = date_str.strip()

    try:
        # Try parsing YYYY-MM-DD format
        dt = datetime.strptime(date_str, "%Y-%m-%d")

        if end_of_day:
            # Set to end of day: 23:59:59.999
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            # Set to start of day: 00:00:00.000
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)

        return int(dt.timestamp() * 1000)

    except ValueError as e:
        # Try other common formats
        alternative_formats = [
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
        ]

        for fmt in alternative_formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if end_of_day:
                    dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                else:
                    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                return int(dt.timestamp() * 1000)
            except ValueError:
                continue

        raise DateFilterError(
            f"Unable to parse date string '{date_str}'. Expected format: YYYY-MM-DD"
        ) from e


def build_date_range_filter(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Optional[Dict[str, int]]:
    """
    Build a date range filter dict for OpenSearch queries.

    The filter is compatible with OpenSearch range queries and uses epoch milliseconds.
    If only start_date is provided, end_date defaults to current time.
    If only end_date is provided, returns filter with just 'lte'.
    If both are provided, returns filter with both 'gte' and 'lte'.

    Args:
        start_date: Start date string (YYYY-MM-DD format). Documents from this date onwards.
        end_date: End date string (YYYY-MM-DD format). Documents up to and including this date.

    Returns:
        Dict with 'gte' and/or 'lte' keys containing epoch milliseconds,
        or None if no valid dates provided.

    Raises:
        DateFilterError: If date strings are invalid or start_date > end_date

    Examples:
        build_date_range_filter("2024-01-01", "2024-06-30")
        {'gte': 1704067200000, 'lte': 1719791999999}

        build_date_range_filter("2024-01-01")  # end_date defaults to now
        {'gte': 1704067200000, 'lte': <current_timestamp>}

        build_date_range_filter(None, "2024-06-30")
        {'lte': 1719791999999}
    """
    if not start_date and not end_date:
        logger.debug("No date filters provided")
        return None

    result: Dict[str, int] = {}

    try:
        if start_date:
            start_ts = date_string_to_epoch_ms(start_date, end_of_day=False)
            result["gte"] = start_ts
            logger.debug(f"Start date '{start_date}' converted to epoch ms: {start_ts}")

        if end_date:
            end_ts = date_string_to_epoch_ms(end_date, end_of_day=True)
            result["lte"] = end_ts
            logger.debug(f"End date '{end_date}' converted to epoch ms: {end_ts}")
        elif start_date:
            # If start_date provided but no end_date, default to current time
            end_ts = get_current_timestamp_ms()
            result["lte"] = end_ts
            logger.debug(f"No end date provided, using current timestamp: {end_ts}")

        # Validate that start <= end
        if "gte" in result and "lte" in result:
            if result["gte"] > result["lte"]:
                raise DateFilterError(
                    f"Start date ({start_date}) cannot be after end date ({end_date})"
                )

        # Additional validation
        current_ts = get_current_timestamp_ms()
        ten_years_ms = 10 * 365 * 24 * 60 * 60 * 1000
        one_year_ms = 365 * 24 * 60 * 60 * 1000

        if "gte" in result:
            if current_ts - result["gte"] > ten_years_ms:
                logger.warning(f"Start date is more than 10 years in the past")

        if "lte" in result:
            if result["lte"] > current_ts + one_year_ms:
                logger.warning(f"End date is more than 1 year in the future")

        logger.info(f"Built date range filter: {result}")
        return result

    except DateFilterError:
        raise

    except Exception as e:
        logger.error(f"Unexpected error building date range filter: {e}", exc_info=True)
        raise DateFilterError(f"Failed to build date range filter: {e}") from e


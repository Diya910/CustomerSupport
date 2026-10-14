import asyncio
import time
from typing import Optional, Callable, Type
from loguru import logger
from functools import wraps


def retry_with_custom_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 20.0,
    exception: tuple[Type[Exception],...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    def calculate_delay(attempt: int) -> float:
        delay = min(initial_delay * (backoff_factor ** attempt), max_delay)
        return delay

    def decorator(func : Callable) -> Callable:

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            attempts = 0
            last_exception = None
            while attempts < max_retries:
                try:
                    return await func(*args, **kwargs)
                except exception as e:
                    attempts += 1
                    last_exception = e

                    if attempts == max_retries:
                        logger.error(
                            f"Failed to execute {func.__name__} after {max_retries} attempts. Last exception: {last_exception}"
                        )
                        raise last_exception

                    delay = calculate_delay(attempts)
                    if on_retry:
                        on_retry(last_exception, attempts)

                    logger.warning(
                        f"Retrying {func.__name__} in {delay} seconds. "
                        f"Attempt {attempts}/{max_retries}. Last exception: {last_exception}"
                    )

                    await asyncio.sleep(delay)

            if last_exception:
                logger.error(
                    f"Failed to execute {func.__name__} after {max_retries} attempts. Last exception: {last_exception}"
                )
                raise last_exception

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            attempts = 0
            last_exception = None
            while attempts < max_retries:
                try:
                    return func(*args, **kwargs)
                except exception as e:
                    attempts += 1
                    last_exception = e

                    if attempts == max_retries:
                        logger.error(
                            f"Failed to execute {func.__name__} after {max_retries} attempts. Last exception: {last_exception}"
                        )
                        raise last_exception

                    delay = calculate_delay(attempts)
                    if on_retry:
                        on_retry(last_exception, attempts)

                    logger.warning(
                        f"Retrying {func.__name__} in {delay} seconds. "
                        f"Attempt {attempts}/{max_retries}. Last exception: {last_exception}"
                    )

                    time.sleep(delay)

            if last_exception:
                logger.error(
                    f"Failed to execute {func.__name__} after {max_retries} attempts. Last exception: {last_exception}"
                )
                raise last_exception


        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator
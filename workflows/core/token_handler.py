import json
import boto3
from typing import Optional, List, Any

from loguru import logger
from langchain_core.messages import BaseMessage, trim_messages

from workflows.core.settings import config_settings


token_handler_instance = None


def initialize_token_handler():
    global token_handler_instance

    if token_handler_instance is None:
        try:
            if config_settings.ENABLE_TOKEN_TRUNCATION:
                token_handler_instance = TokenHandler()
                logger.info("TokenHandler initialized at startup (Bedrock CountTokens API)")
            else:
                logger.info("TokenHandler initialization skipped (truncation disabled in settings)")
        except Exception as e:
            logger.warning(f"Failed to initialize TokenHandler at startup: {e}")
            logger.warning("TokenHandler will be initialized lazily on first use")
            token_handler_instance = None


def get_token_handler(encoding_name: str = None) -> Optional['TokenHandler']:
    global token_handler_instance

    if token_handler_instance is None:
        try:
            token_handler_instance = TokenHandler()
            logger.info("TokenHandler lazy initialized (Bedrock CountTokens API)")
        except Exception as e:
            logger.error(f"Failed to initialize TokenHandler: {e}")
            return None

    return token_handler_instance


class TokenHandler:

    class_instance = None
    class_initialized = False

    def __new__(cls):
        if cls.class_instance is None:
            cls.class_instance = super(TokenHandler, cls).__new__(cls)
        return cls.class_instance

    def __init__(self):
        if TokenHandler.class_initialized:
            return

        try:
            self._model_id = config_settings.AWS_BEDROCK_MODEL_SETTINGS.get(
                "CHAT_MODEL_NAME", "us.anthropic.claude-sonnet-4-6"
            )
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=config_settings.AWS_REGION_NAME,
                aws_access_key_id=config_settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=config_settings.AWS_SECRET_ACCESS_KEY,
            )
            self._chars_per_token = 3.5
            TokenHandler.class_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client for token counting: {e}")
            raise

    def num_tokens_from_string(self, string: str) -> int:
        if not string:
            return 0
        try:
            response = self._client.count_tokens(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": string}]}],
            )
            return response.get("totalTokens", 0)
        except Exception:
            return int(len(string) / self._chars_per_token)

    def truncate_string_to_tokens(
        self,
        string: str,
        max_tokens: int,
        add_ellipsis: bool = True
    ) -> str:
        if not string:
            return string

        try:
            current_tokens = self.num_tokens_from_string(string)
            if current_tokens <= max_tokens:
                return string

            ratio = max_tokens / max(current_tokens, 1)
            char_limit = int(len(string) * ratio * 0.95)
            truncated = string[:char_limit]

            actual_tokens = self.num_tokens_from_string(truncated)
            if actual_tokens > max_tokens:
                further_ratio = max_tokens / max(actual_tokens, 1)
                char_limit = int(len(truncated) * further_ratio * 0.95)
                truncated = truncated[:char_limit]

            if add_ellipsis:
                truncated += "..."

            return truncated
        except Exception as e:
            logger.error(f"Error truncating string to tokens: {e}")
            char_limit = int(max_tokens * self._chars_per_token)
            return string[:char_limit] + ("..." if add_ellipsis else "")

    def count_message_tokens(self, messages: List[BaseMessage]) -> int:
        total_tokens = 0
        for message in messages:
            try:
                if hasattr(message, 'content'):
                    content = message.content
                    if isinstance(content, str):
                        total_tokens += self.num_tokens_from_string(content)
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and 'text' in item:
                                total_tokens += self.num_tokens_from_string(item['text'])
                            elif isinstance(item, str):
                                total_tokens += self.num_tokens_from_string(item)
            except Exception as e:
                logger.warning(f"Error counting tokens for message: {e}")

        return total_tokens

    def trim_messages_to_token_limit(
        self,
        messages: List[BaseMessage],
        max_tokens: int,
        strategy: str = "last",
        include_system: bool = True
    ) -> List[BaseMessage]:
        try:
            trimmed = trim_messages(
                messages,
                max_tokens=max_tokens,
                token_counter=self.count_message_tokens,
                strategy=strategy,
                include_system=include_system,
                allow_partial=False
            )

            original_count = self.count_message_tokens(messages)
            trimmed_count = self.count_message_tokens(trimmed)

            if original_count > trimmed_count:
                logger.info(
                    f"Trimmed messages from {original_count} to {trimmed_count} tokens "
                    f"(removed {len(messages) - len(trimmed)} messages)"
                )

            return trimmed
        except Exception as e:
            logger.error(f"Error trimming messages: {e}. Returning original messages.")
            return messages

    def truncate_tool_output(
        self,
        output: Any,
        max_tokens: int,
        preserve_structure: bool = True
    ) -> str:
        try:
            if isinstance(output, (dict, list)):
                output_str = str(output)
            else:
                output_str = str(output)

            token_count = self.num_tokens_from_string(output_str)

            if token_count <= max_tokens:
                return output_str

            if preserve_structure and isinstance(output, dict):
                return self._truncate_dict(output, max_tokens)
            elif preserve_structure and isinstance(output, list):
                return self._truncate_list(output, max_tokens)
            else:
                return self.truncate_string_to_tokens(output_str, max_tokens, add_ellipsis=True)

        except Exception as e:
            logger.error(f"Error truncating tool output: {e}")
            return str(output)[:1000] + "..."

    def _truncate_dict(self, data: dict, max_tokens: int) -> str:
        try:
            result = {}
            current_tokens = 0

            for key, value in data.items():
                key_str = f'"{key}": '
                key_tokens = self.num_tokens_from_string(key_str)
                value_str = str(value)
                value_tokens = self.num_tokens_from_string(value_str)
                total_tokens = key_tokens + value_tokens

                if current_tokens + total_tokens > max_tokens:
                    remaining_tokens = max_tokens - current_tokens - key_tokens
                    if remaining_tokens > 50:
                        truncated_value = self.truncate_string_to_tokens(
                            value_str, remaining_tokens, add_ellipsis=True
                        )
                        result[key] = truncated_value
                    result["_truncated"] = True
                    break

                result[key] = value
                current_tokens += total_tokens

            return str(result)
        except Exception as e:
            logger.error(f"Error in _truncate_dict: {e}")
            return self.truncate_string_to_tokens(str(data), max_tokens)

    def _truncate_list(self, data: list, max_tokens: int) -> str:
        try:
            result = []
            current_tokens = 0

            for item in data:
                item_str = str(item)
                item_tokens = self.num_tokens_from_string(item_str)

                if current_tokens + item_tokens > max_tokens:
                    result.append(f"... ({len(data) - len(result)} more items truncated)")
                    break

                result.append(item)
                current_tokens += item_tokens

            return str(result)
        except Exception as e:
            logger.error(f"Error in _truncate_list: {e}")
            return self.truncate_string_to_tokens(str(data), max_tokens)


initialize_token_handler()

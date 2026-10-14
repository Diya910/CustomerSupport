from typing import Union
from loguru import logger

from langchain_aws import ChatBedrock, BedrockEmbeddings
from workflows.core.settings import config_settings, LLMServiceType
from botocore.config import Config


def get_chat_model(
        model_key: str,
        temperature: float = 0.0,
):
    # Resolves model ID and provider; instantiates configured ChatBedrock client with retry policy
    if config_settings.LLM_SERVICE_TYPE == LLMServiceType.AWS.value:
        model_id = config_settings.AWS_BEDROCK_MODEL_SETTINGS.get(model_key, None)

        if model_id is None or model_id == "":
            logger.error(f"Model ID for {model_key} is None or empty. Check AWS_BEDROCK_MODEL_SETTINGS configuration.")
            return None

        is_arn = model_id.startswith("arn:")

        provider = None
        if is_arn:
            provider = config_settings.AWS_BEDROCK_MODEL_PROVIDERS.get(model_key, None)
            logger.info(f"Using ARN model ID for {model_key}: {model_id} with provider: {provider}")
        else:
            mid = model_id.lower()
            if any(p in mid for p in ["anthropic", "claude-"]):
                provider = "anthropic"
            elif "mistral" in mid:
                provider = "mistral"
            elif "cohere" in mid:
                provider = "cohere"
            elif "meta" in mid or "llama" in mid:
                provider = "meta"
            elif mid.startswith("amazon.") or "titan" in mid or "nova" in mid:
                provider = "amazon"
            else:
                provider = config_settings.AWS_BEDROCK_MODEL_PROVIDERS.get(model_key, None)
            logger.info(f"Using regular model ID for {model_key}: {model_id}")

        try:
            try:
                bedrock_kwargs_map = config_settings.AWS_BEDROCK_MODEL_KWARGS
                model_kwargs = bedrock_kwargs_map.get(model_key, {}) if isinstance(bedrock_kwargs_map, dict) else {}
            except Exception:
                model_kwargs = {}

            boto_config = Config(
                connect_timeout=config_settings.BOTO_CONNECT_TIMEOUT,
                read_timeout=config_settings.BOTO_READ_TIMEOUT,
                retries={'max_attempts': config_settings.BOTO_MAX_RETRY_ATTEMPTS, 'mode': 'standard'},
                max_pool_connections=config_settings.BOTO_MAX_POOL_CONNECTIONS,
                tcp_keepalive=config_settings.BOTO_TCP_KEEPALIVE,
            )

            return ChatBedrock(
                model_id=model_id,
                provider=provider,
                temperature=temperature,
                aws_access_key_id=config_settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=config_settings.AWS_SECRET_ACCESS_KEY,
                region=config_settings.AWS_REGION_NAME,
                model_kwargs=model_kwargs,
                config=boto_config,
            )

        except Exception as e:
            logger.error(f"Failed to create ChatBedrock instance for {model_key}: {str(e)}")
            return None

    return None


def get_streaming_chat_model(
        model_key: str,
        temperature: float = 0.0,
        callbacks=None,
):
    if config_settings.LLM_SERVICE_TYPE == LLMServiceType.AWS.value:
        model_id = config_settings.AWS_BEDROCK_MODEL_SETTINGS.get(model_key, None)

        if model_id is None or model_id == "":
            logger.error(f"Model ID for {model_key} is None or empty.")
            return None

        is_arn = model_id.startswith("arn:")

        provider = None
        if is_arn:
            provider = config_settings.AWS_BEDROCK_MODEL_PROVIDERS.get(model_key, None)
            logger.info(f"Using ARN model ID for {model_key}: {model_id} with provider: {provider}")
        else:
            mid = model_id.lower()
            if any(p in mid for p in ["anthropic", "claude-"]):
                provider = "anthropic"
            elif "mistral" in mid:
                provider = "mistral"
            elif "cohere" in mid:
                provider = "cohere"
            elif "meta" in mid or "llama" in mid:
                provider = "meta"
            elif mid.startswith("amazon.") or "titan" in mid or "nova" in mid:
                provider = "amazon"
            else:
                provider = config_settings.AWS_BEDROCK_MODEL_PROVIDERS.get(model_key, None)
            logger.info(f"Using regular model ID for {model_key}: {model_id}")

        try:
            try:
                bedrock_kwargs_map = config_settings.AWS_BEDROCK_MODEL_KWARGS
                model_kwargs = bedrock_kwargs_map.get(
                    model_key, {}
                ) if isinstance(bedrock_kwargs_map, dict) else {}

            except Exception:
                model_kwargs = {}

            boto_config = Config(
                connect_timeout=config_settings.BOTO_CONNECT_TIMEOUT,
                read_timeout=config_settings.BOTO_READ_TIMEOUT,
                retries={'max_attempts': config_settings.BOTO_MAX_RETRY_ATTEMPTS, 'mode': 'standard'},
                max_pool_connections=config_settings.BOTO_MAX_POOL_CONNECTIONS,
                tcp_keepalive=config_settings.BOTO_TCP_KEEPALIVE,
            )

            logger.info(f"Creating streaming LLM for {model_key} with {len(callbacks) if callbacks else 0} callbacks")
            return ChatBedrock(
                model_id=model_id,
                provider=provider,
                temperature=temperature,
                streaming=True,
                callbacks=callbacks or [],
                aws_access_key_id=config_settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=config_settings.AWS_SECRET_ACCESS_KEY,
                region=config_settings.AWS_REGION_NAME,
                model_kwargs=model_kwargs,
                config=boto_config,
            )

        except Exception as e:
            logger.error(f"Failed to create streaming ChatBedrock for {model_key}: {str(e)}")
            return None

    return None


def get_embeddings_model(
        model_key: str = "EMBEDDING_MODEL_NAME",
) -> Union[BedrockEmbeddings] | None:
    try:
        if config_settings.LLM_SERVICE_TYPE == LLMServiceType.AWS.value:
            model_id = config_settings.AWS_BEDROCK_MODEL_SETTINGS.get(model_key, None)

            boto_config = Config(
                connect_timeout=config_settings.BOTO_CONNECT_TIMEOUT,
                read_timeout=config_settings.BOTO_READ_TIMEOUT,
                retries={'max_attempts': config_settings.BOTO_MAX_RETRY_ATTEMPTS, 'mode': 'standard'},
                max_pool_connections=config_settings.BOTO_MAX_POOL_CONNECTIONS,
                tcp_keepalive=config_settings.BOTO_TCP_KEEPALIVE,
            )

            embeddings = BedrockEmbeddings(
                model_id=model_id,
                aws_access_key_id=config_settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=config_settings.AWS_SECRET_ACCESS_KEY,
                region_name=config_settings.AWS_REGION_NAME,
                config=boto_config,
            )

            return embeddings

        return None

    except Exception as e:
        logger.error(f"Error initializing embeddings model: {e}")
        return None

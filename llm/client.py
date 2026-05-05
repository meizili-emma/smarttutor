import os
from typing import Type, TypeVar, Optional

from dotenv import load_dotenv
from openai import AzureOpenAI, BadRequestError, APIError, RateLimitError, APITimeoutError
from pydantic import BaseModel, ValidationError

from utils.json_utils import extract_json_object

load_dotenv()

T = TypeVar("T", bound=BaseModel)


class LLMClientError(Exception):
    """Base exception for controlled LLM client failures."""
    pass


class LLMContentFilterError(LLMClientError):
    """Raised when the provider blocks the request or response due to content filtering."""
    pass


class LLMJSONParseError(LLMClientError):
    """Raised when the model output cannot be parsed into the expected JSON schema."""
    pass


class LLMProviderError(LLMClientError):
    """Raised for non-content-filter provider/API failures."""
    pass


class LLMClient:
    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.model = model
        self.client = AzureOpenAI(
            api_key=api_key or os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=api_version or os.getenv("OPENAI_API_VERSION"),
            azure_endpoint=endpoint or os.getenv("AZURE_OPENAI_ENDPOINT"),
        )
        self.temperature = float(os.getenv("DEFAULT_TEMPERATURE", 0.1))

    def call_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
    ) -> T:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

        except BadRequestError as e:
            msg = str(e)
            lowered = msg.lower()

            if (
                "content management policy" in lowered
                or "content filter" in lowered
                or "filtered" in lowered
                or "responsible ai" in lowered
            ):
                raise LLMContentFilterError(msg) from e

            raise LLMProviderError(msg) from e

        except (RateLimitError, APITimeoutError, APIError) as e:
            raise LLMProviderError(str(e)) from e

        text = response.choices[0].message.content or ""

        try:
            data = extract_json_object(text)
            return response_model.model_validate(data)

        except (ValueError, TypeError, ValidationError) as e:
            raise LLMJSONParseError(
                f"Failed to parse/validate model JSON output. Raw output was:\n{text}"
            ) from e
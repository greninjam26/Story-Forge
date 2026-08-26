import json
from dataclasses import dataclass

import httpx
from anthropic import APIError, Anthropic

from app.services.cost_tracking import Usage


CLAUDE_STORY_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True, slots=True)
class StoryProviderRequest:
    system: str
    user: str
    schema: dict[str, object]


@dataclass(frozen=True, slots=True)
class StoryProviderResponse:
    payload: object | None
    provider: str
    model: str | None
    usage: tuple[Usage, ...] | None


class StoryProviderError(Exception):
    def __init__(
        self,
        *,
        message: str,
        provider: str,
        model: str | None,
        usage: tuple[Usage, ...] | None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.usage = usage


class StoryProviderRequestError(StoryProviderError):
    def __init__(
        self,
        *,
        provider: str,
        model: str | None,
        usage: tuple[Usage, ...] | None,
    ) -> None:
        super().__init__(
            message="Story provider request failed.",
            provider=provider,
            model=model,
            usage=usage,
        )


class InvalidStoryProviderResponse(StoryProviderError):
    def __init__(
        self,
        *,
        provider: str,
        model: str | None,
        usage: tuple[Usage, ...] | None,
    ) -> None:
        super().__init__(
            message="Story provider returned an invalid response.",
            provider=provider,
            model=model,
            usage=usage,
        )


class ClaudeStoryProvider:
    def __init__(self, *, api_key: str | None, model: str) -> None:
        if api_key is None or not api_key.strip():
            raise ValueError("Anthropic API key is required.")
        self._api_key = api_key
        self.model = model

    def generate(
        self,
        request: StoryProviderRequest,
    ) -> StoryProviderResponse:
        client = Anthropic(
            api_key=self._api_key,
            max_retries=0,
            timeout=CLAUDE_STORY_TIMEOUT_SECONDS,
        )
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=1536,
                system=request.system,
                tools=[
                    {
                        "name": "submit_story",
                        "description": "Submit the finished bedtime story.",
                        "input_schema": request.schema,
                    }
                ],
                tool_choice={"type": "tool", "name": "submit_story"},
                messages=[{"role": "user", "content": request.user}],
            )
        except APIError:
            raise StoryProviderRequestError(
                provider="claude",
                model=self.model,
                usage=None,
            ) from None
        tool_use = next(
            (
                block
                for block in response.content
                if block.type == "tool_use"
            ),
            None,
        )
        return StoryProviderResponse(
            payload=tool_use.input if tool_use is not None else None,
            provider="claude",
            model=self.model,
            usage=(
                Usage("input_token", response.usage.input_tokens),
                Usage("output_token", response.usage.output_tokens),
            ),
        )


class OllamaStoryProvider:
    def __init__(self, *, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = model

    def generate(
        self,
        request: StoryProviderRequest,
    ) -> StoryProviderResponse:
        try:
            response = httpx.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": request.system},
                        {"role": "user", "content": request.user},
                    ],
                    "format": request.schema,
                    "stream": False,
                    "options": {"temperature": 0.8},
                },
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=180.0,
                    write=10.0,
                    pool=10.0,
                ),
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise StoryProviderRequestError(
                provider="ollama",
                model=self.model,
                usage=(Usage("request", 1),),
            ) from None
        try:
            content = response.json()["message"]["content"]
            payload = json.loads(content)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise InvalidStoryProviderResponse(
                provider="ollama",
                model=self.model,
                usage=(Usage("request", 1),),
            ) from None
        return StoryProviderResponse(
            payload=payload,
            provider="ollama",
            model=self.model,
            usage=(Usage("request", 1),),
        )


class GroqStoryProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        if api_key is None or not api_key.strip():
            raise ValueError("Groq API key is required.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._timeout_seconds = timeout_seconds

    def generate(
        self,
        request: StoryProviderRequest,
    ) -> StoryProviderResponse:
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": request.system},
                        {"role": "user", "content": request.user},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "bedtime_story",
                            "strict": True,
                            "schema": request.schema,
                        },
                    },
                    "max_completion_tokens": 4096,
                    "temperature": 0.8,
                },
                timeout=httpx.Timeout(self._timeout_seconds),
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise StoryProviderRequestError(
                provider="groq",
                model=self.model,
                usage=None,
            ) from None

        usage: tuple[Usage, ...] | None = None
        try:
            body = response.json()
            usage_body = body["usage"]
            usage = (
                Usage("input_token", usage_body["prompt_tokens"]),
                Usage("output_token", usage_body["completion_tokens"]),
            )
            content = body["choices"][0]["message"]["content"]
            payload = json.loads(content)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            raise InvalidStoryProviderResponse(
                provider="groq",
                model=self.model,
                usage=usage,
            ) from None

        return StoryProviderResponse(
            payload=payload,
            provider="groq",
            model=self.model,
            usage=usage,
        )

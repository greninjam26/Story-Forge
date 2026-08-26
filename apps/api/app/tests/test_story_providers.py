import json
import traceback
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import httpx
from anthropic import APIConnectionError

from app.services import story_providers
from app.services.cost_tracking import Usage


def test_claude_provider_requires_an_api_key() -> None:
    from app.services.story_providers import ClaudeStoryProvider

    with pytest.raises(ValueError, match="API key"):
        ClaudeStoryProvider(api_key=None, model="claude-test")


def test_groq_provider_requires_an_api_key() -> None:
    with pytest.raises(ValueError, match="Groq API key"):
        story_providers.GroqStoryProvider(
            api_key=" ",
            base_url="https://api.groq.com/openai/v1",
            model="openai/gpt-oss-20b",
            timeout_seconds=60,
        )


def test_claude_provider_returns_structured_payload_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                input={"title": "A Gentle Night", "pages": ["Page one."]},
            )
        ],
        usage=SimpleNamespace(input_tokens=120, output_tokens=45),
    )
    client_options: dict[str, object] = {}

    def create_client(**options: object) -> MagicMock:
        client_options.update(options)
        return client

    monkeypatch.setattr(story_providers, "Anthropic", create_client)
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }
    provider = story_providers.ClaudeStoryProvider(
        api_key="test-key",
        model="claude-test",
    )

    result = provider.generate(
        story_providers.StoryProviderRequest(
            system="System instructions",
            user="Child context",
            schema=schema,
        )
    )

    assert result.payload == {
        "title": "A Gentle Night",
        "pages": ["Page one."],
    }
    assert result.provider == "claude"
    assert result.model == "claude-test"
    assert result.usage == (
        Usage("input_token", 120),
        Usage("output_token", 45),
    )
    assert client_options == {
        "api_key": "test-key",
        "max_retries": 0,
        "timeout": 600.0,
    }
    request = client.messages.create.call_args.kwargs
    assert request["model"] == "claude-test"
    assert request["system"] == "System instructions"
    assert request["messages"] == [
        {"role": "user", "content": "Child context"}
    ]
    assert request["tools"][0]["input_schema"] == schema
    assert request["tool_choice"] == {
        "type": "tool",
        "name": "submit_story",
    }


def test_ollama_provider_returns_structured_payload_and_zero_cost_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock()
    response.json.return_value = {
        "message": {
            "content": json.dumps(
                {"title": "A Local Night", "pages": ["Page one."]}
            )
        }
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(story_providers.httpx, "post", post)
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }
    provider = story_providers.OllamaStoryProvider(
        base_url="http://localhost:11434/",
        model="local-test",
    )

    result = provider.generate(
        story_providers.StoryProviderRequest(
            system="System instructions",
            user="Child context",
            schema=schema,
        )
    )

    assert result.payload == {
        "title": "A Local Night",
        "pages": ["Page one."],
    }
    assert result.provider == "ollama"
    assert result.model == "local-test"
    assert result.usage == (Usage("request", 1),)
    response.raise_for_status.assert_called_once_with()
    call = post.call_args
    assert call.args == ("http://localhost:11434/api/chat",)
    assert call.kwargs["json"] == {
        "model": "local-test",
        "messages": [
            {"role": "system", "content": "System instructions"},
            {"role": "user", "content": "Child context"},
        ],
        "format": schema,
        "stream": False,
        "options": {"temperature": 0.8},
    }


def test_groq_provider_returns_strict_structured_payload_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock()
    response.json.return_value = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1787712000,
        "model": "openai/gpt-oss-20b",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "title": "A Fast Gentle Night",
                            "pages": ["Page one."],
                        }
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 140,
            "completion_tokens": 52,
            "total_tokens": 192,
        },
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(story_providers.httpx, "post", post)
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    }
    provider = story_providers.GroqStoryProvider(
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1/",
        model="openai/gpt-oss-20b",
        timeout_seconds=60,
    )

    result = provider.generate(
        story_providers.StoryProviderRequest(
            system="System instructions",
            user="Child context",
            schema=schema,
        )
    )

    assert result.payload == {
        "title": "A Fast Gentle Night",
        "pages": ["Page one."],
    }
    assert result.provider == "groq"
    assert result.model == "openai/gpt-oss-20b"
    assert result.usage == (
        Usage("input_token", 140),
        Usage("output_token", 52),
    )
    response.raise_for_status.assert_called_once_with()
    call = post.call_args
    assert call.args == (
        "https://api.groq.com/openai/v1/chat/completions",
    )
    assert call.kwargs["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert call.kwargs["json"] == {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {"role": "system", "content": "System instructions"},
            {"role": "user", "content": "Child context"},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "bedtime_story",
                "strict": True,
                "schema": schema,
            },
        },
        "max_completion_tokens": 4096,
        "temperature": 0.8,
    }


def test_claude_provider_sanitizes_sdk_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.messages.create.side_effect = APIConnectionError(
        request=httpx.Request(
            "POST",
            "https://api.anthropic.com/v1/messages?secret=value",
        )
    )
    monkeypatch.setattr(
        story_providers,
        "Anthropic",
        lambda **_: client,
    )
    provider = story_providers.ClaudeStoryProvider(
        api_key="test-key",
        model="claude-test",
    )

    with pytest.raises(
        story_providers.StoryProviderRequestError
    ) as captured:
        provider.generate(
            story_providers.StoryProviderRequest(
                system="System instructions",
                user="Private child context",
                schema={"type": "object"},
            )
        )

    assert captured.value.provider == "claude"
    assert captured.value.model == "claude-test"
    assert captured.value.usage is None
    assert str(captured.value) == "Story provider request failed."
    rendered_error = "".join(traceback.format_exception(captured.value))
    assert "APIConnectionError" not in rendered_error
    assert "secret=value" not in rendered_error


def test_ollama_provider_preserves_zero_cost_usage_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        story_providers.httpx,
        "post",
        MagicMock(side_effect=httpx.ConnectError("local server unavailable")),
    )
    provider = story_providers.OllamaStoryProvider(
        base_url="http://localhost:11434",
        model="local-test",
    )

    with pytest.raises(
        story_providers.StoryProviderRequestError
    ) as captured:
        provider.generate(
            story_providers.StoryProviderRequest(
                system="System instructions",
                user="Child context",
                schema={"type": "object"},
            )
        )

    assert captured.value.provider == "ollama"
    assert captured.value.model == "local-test"
    assert captured.value.usage == (Usage("request", 1),)
    rendered_error = "".join(traceback.format_exception(captured.value))
    assert "ConnectError" not in rendered_error
    assert "local server unavailable" not in rendered_error


def test_ollama_provider_classifies_malformed_json_as_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock()
    response.json.return_value = {
        "message": {"content": "private child story is not json"}
    }
    monkeypatch.setattr(
        story_providers.httpx,
        "post",
        MagicMock(return_value=response),
    )
    provider = story_providers.OllamaStoryProvider(
        base_url="http://localhost:11434",
        model="local-test",
    )

    with pytest.raises(
        story_providers.InvalidStoryProviderResponse
    ) as captured:
        provider.generate(
            story_providers.StoryProviderRequest(
                system="System instructions",
                user="Child context",
                schema={"type": "object"},
            )
        )

    assert captured.value.provider == "ollama"
    assert captured.value.model == "local-test"
    assert captured.value.usage == (Usage("request", 1),)
    rendered_error = "".join(traceback.format_exception(captured.value))
    assert "JSONDecodeError" not in rendered_error
    assert "private child story" not in rendered_error


def test_groq_provider_sanitizes_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        story_providers.httpx,
        "post",
        MagicMock(side_effect=httpx.ConnectError("private Groq failure")),
    )
    provider = story_providers.GroqStoryProvider(
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-20b",
        timeout_seconds=60,
    )

    with pytest.raises(
        story_providers.StoryProviderRequestError
    ) as captured:
        provider.generate(
            story_providers.StoryProviderRequest(
                system="System instructions",
                user="Private child context",
                schema={"type": "object"},
            )
        )

    assert captured.value.provider == "groq"
    assert captured.value.model == "openai/gpt-oss-20b"
    assert captured.value.usage is None
    rendered_error = "".join(traceback.format_exception(captured.value))
    assert "ConnectError" not in rendered_error
    assert "private Groq failure" not in rendered_error


def test_groq_provider_classifies_malformed_payload_as_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock()
    response.json.return_value = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1787712000,
        "model": "openai/gpt-oss-20b",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "private child story is not json",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 140,
            "completion_tokens": 12,
            "total_tokens": 152,
        },
    }
    monkeypatch.setattr(
        story_providers.httpx,
        "post",
        MagicMock(return_value=response),
    )
    provider = story_providers.GroqStoryProvider(
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-20b",
        timeout_seconds=60,
    )

    with pytest.raises(
        story_providers.InvalidStoryProviderResponse
    ) as captured:
        provider.generate(
            story_providers.StoryProviderRequest(
                system="System instructions",
                user="Child context",
                schema={"type": "object"},
            )
        )

    assert captured.value.provider == "groq"
    assert captured.value.usage == (
        Usage("input_token", 140),
        Usage("output_token", 12),
    )
    rendered_error = "".join(traceback.format_exception(captured.value))
    assert "JSONDecodeError" not in rendered_error
    assert "private child story" not in rendered_error

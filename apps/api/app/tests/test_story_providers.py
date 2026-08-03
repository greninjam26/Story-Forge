import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import story_providers
from app.services.cost_tracking import Usage


def test_claude_provider_requires_an_api_key() -> None:
    from app.services.story_providers import ClaudeStoryProvider

    with pytest.raises(ValueError, match="API key"):
        ClaudeStoryProvider(api_key=None, model="claude-test")


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
    assert client_options == {"api_key": "test-key", "max_retries": 0}
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

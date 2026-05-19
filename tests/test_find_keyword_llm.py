import pytest
import logging
from types import SimpleNamespace

from app.llm.client import call_openai_compatible_chat
from app.llm.find_keyword_llm import FindKeywordLLM


class _FakeSettings:
    def __init__(self, api_key: str = "k", log_raw_output: bool = False):
        self.llm_model = "fake-model"
        self.llm_api_key = api_key
        self.llm_base_url = "https://example.invalid/v1"
        self.llm_reasoning_split = True
        self.llm_log_raw_output = log_raw_output


def test_invoke_returns_keyword_dict():
    llm = FindKeywordLLM(chat_caller=lambda **kwargs: '{"keyword":"沙丘2"}')

    result = llm.invoke("我想看沙丘2")

    assert result == {"keyword": "沙丘2"}


def test_invoke_logs_extracted_keyword(caplog):
    llm = FindKeywordLLM(chat_caller=lambda **kwargs: '{"keyword":"沙丘2"}')

    with caplog.at_level(logging.INFO, logger="app.llm.find_keyword_llm"):
        llm.invoke("我想看沙丘2")

    assert "LLM keyword extraction succeeded keyword=沙丘2" in caplog.text


def test_invoke_trims_keyword_whitespace():
    llm = FindKeywordLLM(chat_caller=lambda **kwargs: '{"keyword":"  沙丘2  "}')

    assert llm.invoke("我想看沙丘2") == {"keyword": "沙丘2"}


def test_invoke_accepts_json_wrapped_in_code_fence():
    llm = FindKeywordLLM(
        chat_caller=lambda **kwargs: '```json\n{"keyword":"沙丘2"}\n```'
    )

    assert llm.invoke("我想看沙丘2") == {"keyword": "沙丘2"}


def test_invoke_accepts_json_after_think_block():
    llm = FindKeywordLLM(
        chat_caller=lambda **kwargs: '<think>\ninner-reasoning\n</think>\n{"keyword":"沙丘2"}'
    )

    assert llm.invoke("我想看沙丘2") == {"keyword": "沙丘2"}


def test_invoke_raises_for_non_json_output():
    llm = FindKeywordLLM(chat_caller=lambda **kwargs: "not-json")

    with pytest.raises(ValueError, match="valid JSON"):
        llm.invoke("我想看沙丘2")


def test_invoke_raises_for_empty_keyword():
    llm = FindKeywordLLM(chat_caller=lambda **kwargs: '{"keyword":"   "}')

    with pytest.raises(ValueError, match="keyword"):
        llm.invoke("我想看沙丘2")


def test_invoke_forwards_message_to_chat_caller():
    captured: dict[str, str] = {}

    def fake_chat_caller(*, system_prompt: str, user_prompt: str) -> str:
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return '{"keyword":"沙丘2"}'

    llm = FindKeywordLLM(chat_caller=fake_chat_caller)
    llm.invoke("我想看沙丘2")

    assert "Media Librarian" in captured["system_prompt"]
    assert captured["user_prompt"] == "我想看沙丘2"


def _fake_sdk_response(content):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def test_chat_helper_raises_for_empty_choices(monkeypatch):
    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key="k"))

    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **create_kwargs: SimpleNamespace(choices=[]),
                )
            )

    monkeypatch.setattr("app.llm.client.OpenAI", FakeOpenAI, raising=False)

    with pytest.raises(ValueError, match="choices"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")


def test_chat_helper_uses_openai_sdk_with_configured_base_url_and_model(monkeypatch):
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return _fake_sdk_response('{"keyword":"沙丘2"}')

    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key="k"))
    monkeypatch.setattr("app.llm.client.OpenAI", FakeOpenAI, raising=False)

    result = call_openai_compatible_chat(system_prompt="s", user_prompt="u")

    assert result == '{"keyword":"沙丘2"}'
    assert captured["client_kwargs"] == {
        "api_key": "k",
        "base_url": "https://example.invalid/v1",
        "timeout": 30.0,
    }
    assert captured["create_kwargs"] == {
        "model": "fake-model",
        "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
        "extra_body": {"reasoning_split": True},
    }


def test_chat_helper_logs_metadata_without_secret_or_raw_output(monkeypatch, caplog):
    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        def create(self, **kwargs):
            _ = kwargs
            return _fake_sdk_response('{"keyword":"沙丘2"}')

    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key="secret-key"))
    monkeypatch.setattr("app.llm.client.OpenAI", FakeOpenAI, raising=False)

    with caplog.at_level(logging.INFO, logger="app.llm.client"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")

    assert "LLM chat completion started model=fake-model" in caplog.text
    assert "base_url=https://example.invalid/v1" in caplog.text
    assert "LLM chat completion succeeded model=fake-model" in caplog.text
    assert "secret-key" not in caplog.text
    assert '{"keyword":"沙丘2"}' not in caplog.text


def test_chat_helper_logs_raw_output_preview_when_enabled(monkeypatch, caplog):
    raw_output = '{"keyword":"' + ("沙" * 80) + '"}'

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        def create(self, **kwargs):
            _ = kwargs
            return _fake_sdk_response(raw_output)

    monkeypatch.setattr(
        "app.llm.client.get_settings",
        lambda: _FakeSettings(api_key="secret-key", log_raw_output=True),
    )
    monkeypatch.setattr("app.llm.client.OpenAI", FakeOpenAI, raising=False)

    with caplog.at_level(logging.DEBUG, logger="app.llm.client"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")

    assert "LLM raw output preview" in caplog.text
    assert "raw_preview=" in caplog.text
    assert "secret-key" not in caplog.text


def test_chat_helper_omits_reasoning_split_when_disabled(monkeypatch):
    captured: dict[str, object] = {}

    class _DisabledReasoningSettings(_FakeSettings):
        def __init__(self, api_key: str = "k"):
            super().__init__(api_key=api_key)
            self.llm_reasoning_split = False

    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return _fake_sdk_response('{"keyword":"沙丘2"}')

    monkeypatch.setattr("app.llm.client.get_settings", lambda: _DisabledReasoningSettings(api_key="k"))
    monkeypatch.setattr("app.llm.client.OpenAI", FakeOpenAI, raising=False)

    call_openai_compatible_chat(system_prompt="s", user_prompt="u")

    create_kwargs = captured.get("create_kwargs")
    assert isinstance(create_kwargs, dict)
    assert "extra_body" not in create_kwargs


def test_chat_helper_raises_for_missing_message(monkeypatch):
    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key="k"))

    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **create_kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(index=0)]
                    ),
                )
            )

    monkeypatch.setattr("app.llm.client.OpenAI", FakeOpenAI, raising=False)

    with pytest.raises(ValueError, match="message"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")


def test_chat_helper_raises_for_non_string_content(monkeypatch):
    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key="k"))

    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **create_kwargs: _fake_sdk_response({"keyword": "沙丘2"}),
                )
            )

    monkeypatch.setattr("app.llm.client.OpenAI", FakeOpenAI, raising=False)

    with pytest.raises(ValueError, match="content"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")


def test_chat_helper_raises_clearly_when_api_key_missing(monkeypatch):
    called = {"post": False}

    def fake_post(*args, **kwargs):
        called["post"] = True
        return _fake_sdk_response('{"keyword":"x"}')

    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key=""))
    monkeypatch.setattr("app.llm.client.OpenAI", fake_post, raising=False)

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")

    assert called["post"] is False

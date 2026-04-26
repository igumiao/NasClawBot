import pytest

from app.llm.client import call_openai_compatible_chat
from app.llm.find_keyword_llm import FindKeywordLLM


class _FakeSettings:
    def __init__(self, api_key: str = "k"):
        self.llm_model = "fake-model"
        self.llm_api_key = api_key
        self.llm_base_url = "https://example.invalid/v1"
        self.llm_reasoning_split = True


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_invoke_returns_keyword_dict():
    llm = FindKeywordLLM(chat_caller=lambda **kwargs: '{"keyword":"沙丘2"}')

    result = llm.invoke("我想看沙丘2")

    assert result == {"keyword": "沙丘2"}


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

    assert "Return STRICT JSON format" in captured["system_prompt"]
    assert captured["user_prompt"] == "我想看沙丘2"


def test_chat_helper_raises_for_empty_choices(monkeypatch):
    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key="k"))
    monkeypatch.setattr(
        "app.llm.client.httpx.post",
        lambda *args, **kwargs: _FakeResponse({"choices": []}),
    )

    with pytest.raises(ValueError, match="choices"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")


def test_chat_helper_includes_reasoning_split_from_settings(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse({"choices": [{"message": {"content": '{"keyword":"沙丘2"}'}}]})

    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key="k"))
    monkeypatch.setattr("app.llm.client.httpx.post", fake_post)

    call_openai_compatible_chat(system_prompt="s", user_prompt="u")

    body = captured.get("json")
    assert isinstance(body, dict)
    assert body["reasoning_split"] is True


def test_chat_helper_raises_for_missing_message(monkeypatch):
    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key="k"))
    monkeypatch.setattr(
        "app.llm.client.httpx.post",
        lambda *args, **kwargs: _FakeResponse({"choices": [{"index": 0}]}),
    )

    with pytest.raises(ValueError, match="message"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")


def test_chat_helper_raises_for_non_string_content(monkeypatch):
    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key="k"))
    monkeypatch.setattr(
        "app.llm.client.httpx.post",
        lambda *args, **kwargs: _FakeResponse(
            {"choices": [{"message": {"content": {"keyword": "沙丘2"}}}]}
        ),
    )

    with pytest.raises(ValueError, match="content"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")


def test_chat_helper_raises_clearly_when_api_key_missing(monkeypatch):
    called = {"post": False}

    def fake_post(*args, **kwargs):
        called["post"] = True
        return _FakeResponse({"choices": [{"message": {"content": '{"keyword":"x"}'}}]})

    monkeypatch.setattr("app.llm.client.get_settings", lambda: _FakeSettings(api_key=""))
    monkeypatch.setattr("app.llm.client.httpx.post", fake_post)

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        call_openai_compatible_chat(system_prompt="s", user_prompt="u")

    assert called["post"] is False

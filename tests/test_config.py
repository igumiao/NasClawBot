import app.config as config_module


def test_settings_parse_llm_reasoning_split_false_from_env(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_SPLIT", "false")
    config_module.get_settings.cache_clear()

    settings = config_module.get_settings()

    assert settings.llm_reasoning_split is False

    config_module.get_settings.cache_clear()

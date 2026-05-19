import app.config as config_module


def test_settings_default_to_deepseek_v4_pro(monkeypatch):
    monkeypatch.setattr(config_module, "_ENV_DEFAULTS", {})
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    config_module.get_settings.cache_clear()

    settings = config_module.get_settings()

    assert settings.llm_model == "deepseek-v4-pro"
    assert settings.llm_base_url == "https://api.deepseek.com"

    config_module.get_settings.cache_clear()


def test_settings_parse_llm_reasoning_split_false_from_env(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_SPLIT", "false")
    config_module.get_settings.cache_clear()

    settings = config_module.get_settings()

    assert settings.llm_reasoning_split is False

    config_module.get_settings.cache_clear()

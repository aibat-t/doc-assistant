from docs_assistant.config import Settings


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_TOP_K", "7")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert s.retrieval_top_k == 7
    assert s.anthropic_api_key.get_secret_value() == "sk-test"
    # секрет не утекает в repr и логи
    assert "sk-test" not in repr(s)

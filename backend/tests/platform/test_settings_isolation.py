"""Local deployment configuration must not change synthetic integration tests."""


def test_platform_settings_ignore_local_dotenv(monkeypatch, tmp_path, request):
    (tmp_path / ".env").write_text(
        'RAG_PIPELINE_ID="hybrid-llm-rerank-v1"\n'
        'PRICING_VERSION="deployment-pricing"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAG_PIPELINE_ID", raising=False)
    monkeypatch.delenv("PRICING_VERSION", raising=False)

    settings = request.getfixturevalue("platform_settings")

    assert settings.rag_pipeline_id == "dense-v1"
    assert settings.pricing_version == "unconfigured"

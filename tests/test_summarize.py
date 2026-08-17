import config
import summarize.generate as gen


def test_run_refuses_when_disabled(monkeypatch, capsys):
    monkeypatch.setattr(config, "LLM_SUMMARIES_ENABLED", False)
    result = gen.run(season=2026, week=1, game_id=None, publish=False, force=False)
    assert result == 1
    assert "refusing to run" in capsys.readouterr().err


def test_run_refuses_without_api_key(monkeypatch, capsys):
    monkeypatch.setattr(config, "LLM_SUMMARIES_ENABLED", True)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    result = gen.run(season=2026, week=1, game_id=None, publish=False, force=False)
    assert result == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_existing_summary_status_human(tmp_path):
    path = tmp_path / "42.md"
    path.write_text("---\ngame_id: 42\nauthor: Levi\nstatus: published\n---\n\nBody.\n")
    assert gen.existing_summary_status(path) == "human"


def test_existing_summary_status_llm(tmp_path):
    path = tmp_path / "7.md"
    path.write_text("---\ngame_id: 7\nauthor: Claude\ngenerated_by: llm\nstatus: draft\n---\n\nBody.\n")
    assert gen.existing_summary_status(path) == "llm"


def test_existing_summary_status_missing(tmp_path):
    assert gen.existing_summary_status(tmp_path / "missing.md") is None

import importlib.util
import io
import json
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).parent.parent / "hooks"
FINANCE_CONFIG = HOOKS_DIR / "configs" / "finance-agent.json"

spec = importlib.util.spec_from_file_location(
    "log_artifact_entry", HOOKS_DIR / "log_artifact_entry.py"
)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


# --- template engine ---


def test_render_plain_and_group_fields():
    assert hook.render("Verdict - {ticker}", {"ticker": "MSFT"}) == "Verdict - MSFT"
    assert hook.render("static text", {}) == "static text"


def test_render_dotted_paths_and_format_specs():
    ctx = {"content": {"price": 512.5, "verdict": {"winner": "bear"}}}
    assert hook.render("${content.price:,.2f}", ctx) == "$512.50"
    assert hook.render("{content.verdict.winner}", ctx) == "bear"


def test_render_list_index():
    ctx = {"content": {"articles": [{"title": "first"}]}}
    assert hook.render("{content.articles.0.title}", ctx) == "first"


def test_render_returns_none_for_missing_or_bad_fields():
    assert hook.render("{missing}", {}) is None
    assert hook.render("{content.nope}", {"content": {}}) is None
    assert hook.render("{content.price:,.2f}", {"content": {"price": "not a number"}}) is None
    assert hook.render("{ticker}", {"ticker": None}) is None


# --- finance-agent config, end to end through main() ---


@pytest.fixture
def project(tmp_path):
    """A finance-agent repo layout opted in with the shipped config."""
    root = tmp_path / "finance-agent"
    (root / "skills" / "trader" / "tmp").mkdir(parents=True)
    (root / ".ai-data-store.json").write_text(FINANCE_CONFIG.read_text())
    return root


def write_artifact(root, filename, content, skill="trader"):
    tmp_dir = root / "skills" / skill / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / filename
    path.write_text(json.dumps(content))
    return path


def run_main(monkeypatch, event):
    posted = []
    monkeypatch.setattr(hook, "load_ingest_config", lambda: ("http://test/entries", "tok"))
    monkeypatch.setattr(hook, "post_entry", lambda url, token, payload: posted.append(payload))
    monkeypatch.setattr(hook.sys, "stdin", io.StringIO(json.dumps(event)))
    hook.main()
    return posted


def bash_event(cwd, path):
    return {
        "cwd": str(cwd),
        "tool_name": "Bash",
        "tool_input": {"command": "python some_script.py"},
        "tool_response": {"stdout": f"{path}\n"},
    }


def test_verdict_artifact(monkeypatch, project):
    path = write_artifact(
        project,
        "verdict_MSFT_20260801_122634.json",
        {"symbol": "MSFT", "verdict": {"winner": "bear", "confidence": "medium"}},
    )

    posted = run_main(monkeypatch, bash_event(project, path))

    assert len(posted) == 1
    entry = posted[0]
    assert entry["source"] == "finance-agent"
    assert entry["description"] == "Verdict - MSFT (bear, medium confidence)"
    assert entry["keywords"] == ["MSFT", "trader", "verdict"]
    assert entry["data"]["artifact"]["symbol"] == "MSFT"
    assert entry["data"]["artifact_path"] == str(path)


def test_verdict_falls_back_when_content_is_sparse(monkeypatch, project):
    path = write_artifact(project, "verdict_MSFT_20260801.json", {"unexpected": "shape"})

    posted = run_main(monkeypatch, bash_event(project, path))

    assert posted[0]["description"] == "Verdict - MSFT"


def test_check_stock_with_and_without_price(monkeypatch, project):
    with_price = write_artifact(
        project,
        "check_stock_MSFT_20260801.json",
        {"name": "Microsoft", "symbol": "MSFT", "price": 512.5, "change_percent": -1.25},
        skill="check",
    )
    without_price = write_artifact(
        project,
        "check_stock_AAPL_20260801.json",
        {"name": "Apple", "symbol": "AAPL"},
        skill="check",
    )

    entry = run_main(monkeypatch, bash_event(project, with_price))[0]
    assert entry["description"] == "Microsoft (MSFT) - $512.50 (-1.25%)"
    assert entry["keywords"] == ["MSFT", "check", "check_stock"]

    entry = run_main(monkeypatch, bash_event(project, without_price))[0]
    assert entry["description"] == "Apple (AAPL) price check"


def test_portfolio_snapshot(monkeypatch, project):
    path = write_artifact(
        project,
        "portfolio_20260801.json",
        {"account_summary": {"totalValue": 12345.67, "currency": "GBP"}},
        skill="portfolio",
    )

    entry = run_main(monkeypatch, bash_event(project, path))[0]
    assert entry["description"] == "Portfolio snapshot - GBP 12,345.67"
    assert entry["keywords"] == ["portfolio"]


def test_history_includes_period_keyword(monkeypatch, project):
    path = write_artifact(project, "history_AAPL_1mo_20260801.json", [])

    entry = run_main(monkeypatch, bash_event(project, path))[0]
    assert entry["description"] == "Price history - AAPL"
    assert entry["keywords"] == ["AAPL", "trader", "history", "1mo"]


def test_news_results_counts_articles(monkeypatch, project):
    path = write_artifact(project, "news_results_20260801.json", [1, 2, 3], skill="news")

    entry = run_main(monkeypatch, bash_event(project, path))[0]
    assert entry["description"] == "News search - 3 articles"
    assert entry["keywords"] == ["news", "news_results"]


def test_source_defaults_to_project_dir_name(monkeypatch, project):
    config = json.loads((project / ".ai-data-store.json").read_text())
    del config["source"]
    (project / ".ai-data-store.json").write_text(json.dumps(config))
    path = write_artifact(project, "history_AAPL_1mo_20260801.json", [])

    entry = run_main(monkeypatch, bash_event(project, path))[0]
    assert entry["source"] == "finance-agent"


def test_config_found_from_subdirectory_cwd(monkeypatch, project):
    path = write_artifact(project, "history_AAPL_1mo_20260801.json", [])

    posted = run_main(monkeypatch, bash_event(project / "skills" / "trader", path))
    assert len(posted) == 1


# --- no-op paths ---


def test_ignores_projects_without_config(monkeypatch, tmp_path):
    root = tmp_path / "some-other-project"
    (root / "skills" / "trader" / "tmp").mkdir(parents=True)
    path = write_artifact(root, "verdict_MSFT_20260801.json", {"symbol": "MSFT"})

    assert run_main(monkeypatch, bash_event(root, path)) == []


def test_ignores_artifacts_outside_the_project(monkeypatch, project, tmp_path):
    outside = tmp_path / "elsewhere"
    (outside / "skills" / "trader" / "tmp").mkdir(parents=True)
    path = write_artifact(outside, "verdict_MSFT_20260801.json", {"symbol": "MSFT"})

    assert run_main(monkeypatch, bash_event(project, path)) == []


def test_ignores_non_bash_tools(monkeypatch, project):
    path = write_artifact(project, "verdict_MSFT_20260801.json", {"symbol": "MSFT"})
    event = {**bash_event(project, path), "tool_name": "Read"}

    assert run_main(monkeypatch, event) == []


def test_ignores_unmatched_filenames(monkeypatch, project):
    path = write_artifact(project, "random_output.json", {})

    assert run_main(monkeypatch, bash_event(project, path)) == []


def test_ignores_non_artifact_stdout(monkeypatch, project):
    event = bash_event(project, "")
    event["tool_response"] = {"stdout": "total 4\n-rw-r--r-- 1 user user 0 file.txt\n"}

    assert run_main(monkeypatch, event) == []


def test_ignores_missing_artifact_file(monkeypatch, project):
    path = write_artifact(project, "verdict_MSFT_20260801.json", {"symbol": "MSFT"})
    path.unlink()

    assert run_main(monkeypatch, bash_event(project, path)) == []


def test_ignores_invalid_artifact_json(monkeypatch, project):
    path = project / "skills" / "trader" / "tmp" / "verdict_MSFT_20260801.json"
    path.write_text("not json {")

    assert run_main(monkeypatch, bash_event(project, path)) == []


def test_relative_artifact_path_resolves_against_cwd(monkeypatch, project):
    write_artifact(project, "verdict_MSFT_20260801.json", {"symbol": "MSFT"})
    event = bash_event(project, "skills/trader/tmp/verdict_MSFT_20260801.json")

    posted = run_main(monkeypatch, event)
    assert len(posted) == 1
    assert posted[0]["description"] == "Verdict - MSFT"

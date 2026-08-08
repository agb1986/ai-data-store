import importlib.util
import io
import json
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "log_finance_entry.py"
spec = importlib.util.spec_from_file_location("log_finance_entry", HOOK_PATH)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def test_match_prefix_picks_longest_match():
    assert hook.match_prefix("check_stock_MSFT_20260801.json") == "check_stock"
    assert hook.match_prefix("check_crypto_BTC_20260801.json") == "check_crypto"
    assert hook.match_prefix("verdict_MSFT_20260801.json") == "verdict"
    assert hook.match_prefix("news_results_20260801.json") == "news_results"


def test_match_prefix_rejects_unknown():
    assert hook.match_prefix("random_file.json") is None
    assert hook.match_prefix("verdict.json") is None  # no underscore separator


def test_describe_verdict():
    content = {"symbol": "MSFT", "verdict": {"winner": "bear", "confidence": "medium"}}
    assert hook.describe("verdict", "MSFT", content) == "Verdict - MSFT (bear, medium confidence)"


def test_describe_check_stock_with_price():
    content = {"name": "Microsoft", "symbol": "MSFT", "price": 512.5, "change_percent": -1.25}
    assert hook.describe("check_stock", "MSFT", content) == "Microsoft (MSFT) - $512.50 (-1.25%)"


def test_describe_check_stock_without_price():
    content = {"name": "Microsoft", "symbol": "MSFT"}
    assert hook.describe("check_stock", "MSFT", content) == "Microsoft (MSFT) price check"


def test_describe_portfolio():
    content = {"account_summary": {"totalValue": 12345.67, "currency": "GBP"}}
    assert hook.describe("portfolio", None, content) == "Portfolio snapshot - GBP 12,345.67"


def test_describe_news_results():
    assert hook.describe("news_results", None, [1, 2, 3]) == "News search - 3 articles"
    assert hook.describe("news_results", None, {"odd": "shape"}) == "News search"


def test_build_keywords():
    assert hook.build_keywords("verdict", "trader", "MSFT", None) == ["MSFT", "trader", "verdict"]
    assert hook.build_keywords("history", "trader", "AAPL", "1mo") == [
        "AAPL",
        "trader",
        "history",
        "1mo",
    ]
    # prefix matching the skill dir is not duplicated
    assert hook.build_keywords("portfolio", "portfolio", None, None) == ["portfolio"]


@pytest.fixture
def artifact(tmp_path):
    """A finance-agent repo layout with one verdict artifact on disk."""
    cwd = tmp_path / "finance-agent"
    tmp_dir = cwd / "skills" / "trader" / "tmp"
    tmp_dir.mkdir(parents=True)
    path = tmp_dir / "verdict_MSFT_20260801_122634.json"
    path.write_text(
        json.dumps({"symbol": "MSFT", "verdict": {"winner": "bear", "confidence": "medium"}})
    )
    return cwd, path


def run_main(monkeypatch, event):
    posted = []
    monkeypatch.setattr(hook, "load_ingest_config", lambda: ("http://test/entries", "tok"))
    monkeypatch.setattr(hook, "post_entry", lambda url, token, payload: posted.append(payload))
    monkeypatch.setattr(hook.sys, "stdin", io.StringIO(json.dumps(event)))
    hook.main()
    return posted


def test_main_logs_verdict_artifact(monkeypatch, artifact):
    cwd, path = artifact
    event = {
        "cwd": str(cwd),
        "tool_name": "Bash",
        "tool_input": {"command": "python skills/trader/verdict.py MSFT"},
        "tool_response": {"stdout": f"{path}\n"},
    }

    posted = run_main(monkeypatch, event)

    assert len(posted) == 1
    entry = posted[0]
    assert entry["source"] == "finance-agent"
    assert entry["description"] == "Verdict - MSFT (bear, medium confidence)"
    assert entry["keywords"] == ["MSFT", "trader", "verdict"]
    assert entry["data"]["artifact"]["symbol"] == "MSFT"
    assert entry["data"]["artifact_path"] == str(path)


def test_main_ignores_other_projects(monkeypatch, artifact):
    _, path = artifact
    event = {
        "cwd": "/home/user/some-other-project",
        "tool_name": "Bash",
        "tool_response": {"stdout": f"{path}\n"},
    }
    assert run_main(monkeypatch, event) == []


def test_main_ignores_non_bash_tools(monkeypatch, artifact):
    cwd, path = artifact
    event = {"cwd": str(cwd), "tool_name": "Read", "tool_response": {"stdout": f"{path}\n"}}
    assert run_main(monkeypatch, event) == []


def test_main_ignores_non_artifact_stdout(monkeypatch, artifact):
    cwd, _ = artifact
    event = {
        "cwd": str(cwd),
        "tool_name": "Bash",
        "tool_response": {"stdout": "total 4\n-rw-r--r-- 1 user user 0 file.txt\n"},
    }
    assert run_main(monkeypatch, event) == []


def test_main_ignores_missing_artifact_file(monkeypatch, artifact):
    cwd, path = artifact
    path.unlink()
    event = {
        "cwd": str(cwd),
        "tool_name": "Bash",
        "tool_response": {"stdout": f"{path}\n"},
    }
    assert run_main(monkeypatch, event) == []

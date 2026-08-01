#!/usr/bin/env python3
"""PostToolUse hook: logs finance-agent artifacts to ai-data-store as they're produced.

Registered globally in ~/.claude/settings.json so it fires on every tool call
in every project, but it only acts on a Bash call inside finance-agent whose
stdout is the path to a known artifact under skills/*/tmp/ — every artifact
script in this repo follows the convention of printing just that path, so
this fires deterministically the moment an artifact is created, regardless
of whether the agent later reads it back into its own context. (An earlier
version hooked Read instead, which missed panel/debate stages entirely,
since the trader skill only re-reads the final verdict file.) Everything
else is a silent no-op, so it adds no noise to the store and negligible
latency to unrelated tool calls.
"""
import json
import os
import re
import sys
import urllib.request

TICKER_PREFIXES = {"verdict", "debate", "panel", "check_stock", "check_crypto", "history"}
NO_TICKER_PREFIXES = {"portfolio", "news_results", "analysis"}
ALL_PREFIXES = TICKER_PREFIXES | NO_TICKER_PREFIXES

ARTIFACT_RE = re.compile(r"/skills/(?P<skill_dir>[^/]+)/tmp/(?P<filename>[^/]+\.json)$")


def match_prefix(filename: str) -> str | None:
    for prefix in sorted(ALL_PREFIXES, key=len, reverse=True):
        if filename.startswith(prefix + "_"):
            return prefix
    return None


def describe(prefix: str, ticker: str | None, content) -> str:
    if prefix == "verdict":
        symbol = content.get("symbol", ticker)
        v = content.get("verdict", {})
        return f"Verdict - {symbol} ({v.get('winner', '?')}, {v.get('confidence', '?')} confidence)"
    if prefix == "debate":
        symbol = content.get("symbol", ticker)
        return f"Debate - {symbol} ({content.get('rounds', '?')} rounds)"
    if prefix == "panel":
        return f"Panel analysis - {content.get('symbol', ticker)}"
    if prefix == "check_stock":
        name, symbol = content.get("name", ticker), content.get("symbol", ticker)
        price, pct = content.get("price"), content.get("change_percent")
        if price is not None and pct is not None:
            return f"{name} ({symbol}) - ${price:,.2f} ({pct:+.2f}%)"
        return f"{name} ({symbol}) price check"
    if prefix == "check_crypto":
        name, symbol = content.get("name", ticker), content.get("symbol", ticker)
        price, pct = content.get("price"), content.get("change_percent_24h")
        if price is not None and pct is not None:
            return f"{name} ({symbol}) - ${price:,.2f} ({pct:+.2f}% 24h)"
        return f"{name} ({symbol}) price check"
    if prefix == "history":
        return f"Price history - {ticker}"
    if prefix == "portfolio":
        summary = content.get("account_summary", {})
        total = summary.get("totalValue")
        if total is not None:
            return f"Portfolio snapshot - {summary.get('currency', '')} {total:,.2f}"
        return "Portfolio snapshot"
    if prefix == "news_results":
        return f"News search - {len(content)} articles" if isinstance(content, list) else "News search"
    if prefix == "analysis":
        return f"News analysis - {len(content)} articles ranked" if isinstance(content, list) else "News analysis"
    return prefix


def build_keywords(prefix: str, skill_dir: str, ticker: str | None, period: str | None) -> list[str]:
    keywords = [ticker] if ticker else []
    keywords.append(skill_dir)
    if prefix != skill_dir:
        keywords.append(prefix)
    if period:
        keywords.append(period)
    return keywords


def load_ingest_config() -> tuple[str, str]:
    with open(os.path.expanduser("~/.claude.json")) as f:
        cfg = json.load(f)
    server = cfg["mcpServers"]["ai-data-store"]
    base_url = server["url"].rsplit("/sse", 1)[0]
    token = server["headers"]["Authorization"].split(" ", 1)[1]
    return f"{base_url}/entries", token


def post_entry(url: str, token: str, payload: dict) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def main() -> None:
    event = json.load(sys.stdin)

    if os.path.basename(event.get("cwd", "")) != "finance-agent":
        return
    if event.get("tool_name") != "Bash":
        return

    tool_response = event.get("tool_response") or {}
    if isinstance(tool_response, str):
        tool_response = json.loads(tool_response)
    stdout = (tool_response.get("stdout") or "").strip()
    if not stdout:
        return
    file_path = stdout.splitlines()[0].strip()

    match = ARTIFACT_RE.search(file_path)
    if not match:
        return
    skill_dir, filename = match["skill_dir"], match["filename"]

    prefix = match_prefix(filename)
    if not prefix:
        return

    rest = filename[len(prefix) + 1:].removesuffix(".json")
    parts = rest.split("_")
    ticker = parts[0] if prefix in TICKER_PREFIXES else None
    period = parts[1] if prefix == "history" and len(parts) > 1 else None

    try:
        with open(file_path) as f:
            content = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    entry = {
        "source": "finance-agent",
        "description": describe(prefix, ticker, content),
        "keywords": build_keywords(prefix, skill_dir, ticker, period),
        "data": {
            "tool_name": event.get("tool_name"),
            "tool_input": event.get("tool_input"),
            "artifact_path": file_path,
            "artifact": content,
        },
    }

    url, token = load_ingest_config()
    post_entry(url, token, entry)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"log_finance_entry hook failed: {e}", file=sys.stderr)

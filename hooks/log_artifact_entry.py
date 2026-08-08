#!/usr/bin/env python3
"""PostToolUse hook: logs JSON artifacts from any opted-in project to ai-data-store.

Generic successor to log_finance_entry.py. Registered globally in
~/.claude/settings.json so it fires on every tool call in every project, but
it only acts on Bash calls in projects that opt in by having a
.ai-data-store.json config at their root (searched upward from the session
cwd). The artifact convention is unchanged: a script that produces an
artifact prints just the path of the JSON file it wrote, and the hook picks
it up from stdout the moment it's created. Everything else is a silent
no-op, so it adds no noise to the store and negligible latency to unrelated
tool calls.

Config format — templates use str.format syntax, where dotted names traverse
into the artifact JSON ({content.verdict.winner}) and regex groups from the
rule's pattern are available by name ({ticker}):

    {
      "source": "finance-agent",   // optional, defaults to the project dir name
      "rules": [
        {
          "pattern": "/tmp/verdict_(?P<ticker>[^_]+)_[^/]*\\.json$",
          "description": [
            "Verdict - {content.symbol} ({content.verdict.winner} wins)",
            "Verdict - {ticker}"
          ],
          "keywords": ["{ticker}", "verdict"]
        }
      ]
    }

The first rule whose pattern matches the artifact path wins. "description"
is a template or a list of them — the first whose fields all resolve is
used, falling back to the artifact filename. Keyword templates that fail to
resolve are dropped, and duplicates are removed. {content_length} is
available when the artifact's top level is a list, {filename} always.
"""
from __future__ import annotations

import json
import os
import re
import string
import sys
import urllib.request

CONFIG_NAME = ".ai-data-store.json"


class _DotFormatter(string.Formatter):
    """str.format where {a.b.c} traverses nested dicts/lists and None counts as missing."""

    def get_field(self, field_name, args, kwargs):
        obj = kwargs
        for part in field_name.split("."):
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
                obj = obj[int(part)]
            else:
                raise KeyError(field_name)
        if obj is None:
            raise KeyError(field_name)
        return obj, field_name


_formatter = _DotFormatter()


def render(template: str, context: dict) -> str | None:
    """Render one template, or None if any field is missing or unformattable."""
    try:
        return _formatter.format(template, **context)
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def find_project_root(start: str) -> str | None:
    """Walk up from the session cwd to the nearest directory holding a config."""
    path = os.path.realpath(start)
    while True:
        if os.path.isfile(os.path.join(path, CONFIG_NAME)):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def build_entry(config: dict, source: str, file_path: str, content, event: dict) -> dict | None:
    for rule in config.get("rules", []):
        match = re.search(rule["pattern"], file_path)
        if match:
            break
    else:
        return None

    context = {k: v for k, v in match.groupdict().items() if v is not None}
    context["content"] = content
    context["filename"] = os.path.basename(file_path)
    if isinstance(content, list):
        context["content_length"] = len(content)

    templates = rule.get("description", [])
    if isinstance(templates, str):
        templates = [templates]
    description = next(
        (d for d in (render(t, context) for t in templates) if d is not None),
        os.path.basename(file_path),
    )

    keywords = []
    for template in rule.get("keywords", []):
        keyword = render(template, context)
        if keyword and keyword not in keywords:
            keywords.append(keyword)

    return {
        "source": source,
        "description": description,
        "keywords": keywords,
        "data": {
            "tool_name": event.get("tool_name"),
            "tool_input": event.get("tool_input"),
            "artifact_path": file_path,
            "artifact": content,
        },
    }


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

    if event.get("tool_name") != "Bash":
        return
    cwd = event.get("cwd") or ""
    if not cwd:
        return

    tool_response = event.get("tool_response") or {}
    if isinstance(tool_response, str):
        try:
            tool_response = json.loads(tool_response)
        except json.JSONDecodeError:
            return
    stdout = (tool_response.get("stdout") or "").strip()
    if not stdout:
        return
    raw_path = stdout.splitlines()[0].strip()
    if not raw_path.endswith(".json"):
        return
    file_path = os.path.realpath(raw_path if os.path.isabs(raw_path) else os.path.join(cwd, raw_path))

    root = find_project_root(cwd)
    if root is None:
        return
    # Only log artifacts that live inside the opted-in project
    if os.path.commonpath([root, file_path]) != root:
        return

    with open(os.path.join(root, CONFIG_NAME)) as f:
        config = json.load(f)

    try:
        with open(file_path) as f:
            content = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    source = config.get("source") or os.path.basename(root)
    entry = build_entry(config, source, file_path, content, event)
    if entry is None:
        return

    url, token = load_ingest_config()
    post_entry(url, token, entry)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"log_artifact_entry hook failed: {e}", file=sys.stderr)

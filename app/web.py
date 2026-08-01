import base64
import json
import secrets
from contextlib import asynccontextmanager
from html import escape
from math import ceil
from urllib.parse import urlencode

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from app.config import settings
from app.database import close_client, get_db
from app.formatting import format_doc, parse_id

PAGE_SIZE = 20

STYLE = """
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
  h1 { font-size: 1.4rem; }
  form.filters { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
  form.filters input { padding: 0.4rem 0.6rem; border: 1px solid #8888; border-radius: 6px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #8884; vertical-align: top; }
  tr:hover { background: #80808014; cursor: pointer; }
  a { color: #3b82f6; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .chip { display: inline-block; background: #80808022; border-radius: 999px; padding: 0.1rem 0.6rem; margin: 0 0.2rem 0.2rem 0; font-size: 0.85rem; }
  .muted { color: #888; font-size: 0.85rem; }
  pre { background: #80808014; padding: 1rem; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
  .pagination { margin-top: 1rem; display: flex; gap: 1rem; align-items: center; }
  .empty { color: #888; padding: 2rem 0; text-align: center; }
</style>
"""


def _check_auth(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode()
        username, _, password = decoded.partition(":")
    except Exception:
        return False
    return secrets.compare_digest(username, settings.ui_username) and secrets.compare_digest(
        password, settings.ui_password
    )


class BasicAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            if not _check_auth(Request(scope)):
                response = Response(
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="ai-data-store"'},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  {STYLE}
</head>
<body>
{body}
</body>
</html>"""


def _fmt_time(iso: str) -> str:
    return iso[:19].replace("T", " ")


async def index(request: Request) -> HTMLResponse:
    source = request.query_params.get("source", "").strip()
    keyword = request.query_params.get("keyword", "").strip()
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1

    query: dict = {}
    if source:
        query["source"] = source
    if keyword:
        query["keywords"] = keyword

    db = get_db()
    total = await db.entries.count_documents(query)
    cursor = (
        db.entries.find(query)
        .sort("created_at", -1)
        .skip((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    items = [format_doc(doc) async for doc in cursor]

    filter_qs = {k: v for k, v in {"source": source, "keyword": keyword}.items() if v}

    if items:
        rows = "".join(
            f"""<tr onclick="location.href='/entries/{item['id']}'">
              <td>{escape(item['source'])}</td>
              <td>{escape(item['description'])}</td>
              <td>{''.join(f'<span class="chip">{escape(k)}</span>' for k in item['keywords'])}</td>
              <td class="muted">{_fmt_time(item['created_at'])}</td>
            </tr>"""
            for item in items
        )
        table = f"""<table>
          <thead><tr><th>Source</th><th>Description</th><th>Keywords</th><th>Created</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""
    else:
        table = '<div class="empty">No entries found.</div>'

    total_pages = max(1, ceil(total / PAGE_SIZE))
    prev_link = (
        f'<a href="?{urlencode({**filter_qs, "page": page - 1})}">&larr; prev</a>' if page > 1 else ""
    )
    next_link = (
        f'<a href="?{urlencode({**filter_qs, "page": page + 1})}">next &rarr;</a>'
        if page < total_pages
        else ""
    )
    pagination = f"""<div class="pagination">
      <span class="muted">{total} entr{"y" if total == 1 else "ies"} &middot; page {page} of {total_pages}</span>
      {prev_link}
      {next_link}
    </div>"""

    body = f"""
    <h1>AI Data Store</h1>
    <form class="filters" method="get">
      <input type="text" name="source" placeholder="Filter by source" value="{escape(source)}">
      <input type="text" name="keyword" placeholder="Filter by keyword" value="{escape(keyword)}">
      <button type="submit">Filter</button>
    </form>
    {table}
    {pagination}
    """
    return HTMLResponse(_layout("AI Data Store", body))


async def detail(request: Request) -> HTMLResponse:
    entry_id = request.path_params["entry_id"]
    db = get_db()
    doc = None
    try:
        doc = await db.entries.find_one({"_id": parse_id(entry_id)})
    except ValueError:
        pass

    if not doc:
        body = '<p><a href="/">&larr; back</a></p><div class="empty">Entry not found.</div>'
        return HTMLResponse(_layout("Not found", body), status_code=404)

    item = format_doc(doc)
    chips = (
        "".join(f'<span class="chip">{escape(k)}</span>' for k in item["keywords"])
        or '<span class="muted">none</span>'
    )
    data_json = escape(json.dumps(item["data"], indent=2, default=str))

    body = f"""
    <p><a href="/">&larr; back</a></p>
    <h1>{escape(item['description'])}</h1>
    <p class="muted">
      <strong>{escape(item['source'])}</strong> &middot;
      created {_fmt_time(item['created_at'])} &middot;
      updated {_fmt_time(item['updated_at'])} &middot;
      id {escape(item['id'])}
    </p>
    <p>{chips}</p>
    <pre>{data_json}</pre>
    """
    return HTMLResponse(_layout(item["description"], body))


@asynccontextmanager
async def lifespan(app: Starlette):
    yield
    await close_client()


app = Starlette(
    routes=[
        Route("/", index),
        Route("/entries/{entry_id}", detail),
    ],
    lifespan=lifespan,
)
app.add_middleware(BasicAuthMiddleware)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8743)

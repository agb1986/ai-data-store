# ai-data-store

A persistent store for data produced by AI agents, hosted on a home CasaOS server. Agents running on a laptop connect to it remotely via MCP to save and retrieve results.

## Approach

- **MCP server** (FastMCP) over SSE transport on port `8742` — agents call named tools rather than constructing HTTP requests
- **MongoDB** for storage, running in Docker alongside the server
- **Bearer token auth** to protect the store on the local network

## Data schema

Each entry stores:

```json
{
  "id": "68571a2c...",
  "source": "finance-agent",
  "description": "SPCX trade analysis for June 2025",
  "keywords": ["trader", "SPCX"],
  "data": {},
  "created_at": "2025-06-21T14:32:00Z",
  "updated_at": "2025-06-21T14:32:00Z"
}
```

## Server setup (CasaOS)

```bash
git clone <repo-url>
cd ai-data-store
./setup.sh
```

The setup script generates an API key, writes `.env`, and starts the containers. The API key and server URL are printed at the end — save them for the laptop config.

To update after a code change:

```bash
git pull
docker compose up -d --build
```

## Laptop setup

Configure your MCP client with the server URL and API key printed during setup.

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "ai-data-store": {
      "url": "http://<casaos-ip>:8742/sse",
      "headers": {
        "Authorization": "Bearer <api-key>"
      }
    }
  }
}
```

**Claude API** (agent code):
```python
tools=[{
    "type": "mcp",
    "server_label": "ai-data-store",
    "server_url": "http://<casaos-ip>:8742/sse",
    "authorization_token": "<api-key>"
}]
```

## MCP tools

| Tool | Description |
|------|-------------|
| `create_entry` | Store a new agent result |
| `list_entries` | List entries, filter by `source` or `keywords` |
| `get_entry` | Fetch a single entry by ID |
| `update_entry` | Update fields on an existing entry |
| `delete_entry` | Remove an entry |

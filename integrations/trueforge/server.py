# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.20,<2", "httpx>=0.28,<1"]
# ///
"""Local read-only MCP tools for Conferge. Run with uv run this-file.py."""
import os

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

BASE = os.environ.get("CONFERGE_API_URL", "https://conferge-fx6pnv.spwt.app").rstrip("/")
mcp = FastMCP("Conferge", host="127.0.0.1", port=8792, stateless_http=True, json_response=True)
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)


async def request(path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.request("POST" if body is not None else "GET",
                                        BASE + "/api/v1/" + path, params=params, json=body)
        response.raise_for_status()
        return response.json()


@mcp.tool(annotations=READ)
async def search_connections(query: str, company: str = "", role: str = "", topic: str = "") -> dict:
    """Find people by meaning in Conferge. Returns sourced profiles, not confirmed attendance.

    Uses OpenAI and FalkorDB; may populate the embedding cache but never changes user records.
    """
    result = await request("connections/search", body=dict(query=query, company=company, role=role, topic=topic))
    # Photos are large metadata with no value for the reasoning context.
    for item in result.get("items", []):
        item.pop("photo", None)
    return result


@mcp.tool(annotations=READ)
async def connection_filters() -> dict:
    """List valid company, role and topic filters for the connection directory."""
    result = await request("connections")
    return {"count": result["count"], "filters": result["filters"]}


@mcp.tool(annotations=READ)
async def explain_connection(person_id: str) -> dict:
    """Retrieve the actual goal-to-person graph path and evidence. No path means unknown."""
    try:
        return await request("graph/path", params={"person": person_id})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"person_id": person_id, "path": None, "message": "No recorded goal-to-person path."}
        raise


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

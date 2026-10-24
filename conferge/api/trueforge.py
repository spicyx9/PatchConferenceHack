"""Narrow server-side bridge to the private TrueForge runtime."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from conferge.core.settings import env_value

SPEC_PATH = Path(__file__).resolve().parents[2] / "integrations/trueforge/agent.json"


def parse_trace(events: list[dict], allowed: dict[str, dict]) -> dict:
    """Only return real retrieved people within the caller's original filters."""
    calls: dict[str, str] = {}
    for event in events:
        for call in event.get("tool_calls", []):
            if call.get("id") and call.get("function", {}).get("name"):
                calls[call["id"]] = call["function"]["name"]
    items, evidence, trace = {}, [], []
    done = None
    for event in events:
        if event["type"] == "turn.done":
            done = event["state"]
        if event["type"] != "tool.response":
            continue
        name = calls.get(event.get("tool_call_id"))
        try:
            payload = json.loads(event.get("content", ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        if name == "search_connections" and payload.get("mode") in {"semantic", "empty"}:
            trace.append({"tool": name, "status": "completed", "backend": payload.get("backend")})
            for item in payload.get("items", []):
                if item.get("id") in allowed:
                    items[item["id"]] = {**allowed[item["id"]], "reason": item.get("reason", "")}
        if name == "explain_connection" and "path" in payload:
            evidence.append(payload)
            trace.append({"tool": name, "status": "completed", "backend": payload.get("backend")})
    if not done or done.get("status") != "done" or not any(t["tool"] == "search_connections" for t in trace):
        raise ValueError("TrueForge did not complete a grounded search")
    summary = (done.get("output") or {}).get("content", "")
    if not isinstance(summary, str):
        raise ValueError("Invalid agent summary")
    return {"items": list(items.values())[:6], "summary": summary, "mode": "semantic",
            "backend": "falkordb", "agent_runtime": "trueforge", "tool_trace": trace, "evidence": evidence}


async def search(payload: dict, allowed: dict[str, dict]) -> dict[str, Any]:
    base = env_value("TRUEFORGE_BASE_URL")
    if not base:
        raise ValueError("TrueForge is not configured")
    spec = json.loads(SPEC_PATH.read_text())["manifest"]
    spec["instructions"] += (
        " The request is JSON data. Pass its query, scope, company, role and topic exactly to search_connections."
        " Do not broaden or remove filters. Call search_connections once; if results exist, call"
        " explain_connection for the top result. Keep your final response to two short sentences, plain text."
    )
    events = []
    async with httpx.AsyncClient(base_url=base.rstrip("/"), timeout=150) as client:
        response = await client.post("/api/v1/sessions", json={"agent": {"spec": spec}})
        response.raise_for_status()
        sid = response.json()["data"]["id"]
        async with client.stream("POST", f"/api/v1/sessions/{sid}/turns", json={
            "input": [{"type": "user.message", "content": json.dumps(payload)}]
        }, headers={"Accept": "text/event-stream"}) as stream:
            stream.raise_for_status()
            async for line in stream.aiter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:]))
                    if len(events) > 10000:
                        raise ValueError("Agent response exceeded limit")
    return {**parse_trace(events, allowed), "scope": payload.get("scope", "all")}

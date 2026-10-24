# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.28,<1"]
# ///
"""Run a real TrueForge tool-calling turn and keep its trace outside Git."""
import json
import os
from pathlib import Path

import httpx

BASE = os.environ.get("TRUEFORGE_BASE_URL", "http://127.0.0.1:8790").rstrip("/")


def main() -> None:
    spec = json.loads(Path(__file__).with_name("agent.json").read_text())
    with httpx.Client(base_url=BASE, timeout=180) as client:
        created = client.post("/api/v1/agents", json=spec)
        if created.status_code != 409:
            created.raise_for_status()
        session = client.post("/api/v1/sessions", json={"agent": {"spec": spec["manifest"]}})
        session.raise_for_status()
        sid = session.json()["data"]["id"]
        print("Session:", sid, flush=True)
        events = []
        with client.stream("POST", f"/api/v1/sessions/{sid}/turns", json={"input": [{
            "type": "user.message", "content": "Find two people who can help with developer tools. Use search_connections and explain_connection for your top match. Give evidence and do not assume attendance."
        }]}, headers={"Accept": "text/event-stream"}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data:"):
                    event = json.loads(line[5:])
                    events.append(event)
                    print(json.dumps(event), flush=True)
        Path("/tmp/conferge-trueforge-trace.json").write_text(json.dumps(events, indent=2))
        done = next((e for e in reversed(events) if e["type"] == "turn.done"), None)
        responses = [e for e in events if e["type"] == "tool.response"]
        called = {call.get("function", {}).get("name") for e in events
                  for call in e.get("tool_calls", [])}
        assert done and done["state"]["status"] == "done", "TrueForge turn did not complete"
        assert {"search_connections", "explain_connection"} <= called, "Required tools were not called"
        assert len(responses) >= 2, "Missing tool responses"
        payloads = [json.loads(e["content"]) for e in responses]
        assert any(p.get("mode") == "semantic" and p.get("items") for p in payloads), "No semantic matches"
        assert any("path" in p and p.get("backend") == "falkordb" for p in payloads), "No FalkorDB evidence"
        print("PASS: completed TrueForge turn with search and graph evidence tools", flush=True)


if __name__ == "__main__":
    main()

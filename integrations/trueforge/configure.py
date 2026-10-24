# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.28,<1", "python-dotenv>=1,<2"]
# ///
"""Register OpenAI and Conferge MCP on a local TrueForge instance; never print keys."""
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main() -> None:
    settings = {**dotenv_values(Path(__file__).resolve().parents[2] / ".env"), **os.environ}
    key = settings.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("Set OPENAI_API_KEY in the environment or the project's ignored .env.")
    base = "http://127.0.0.1:8790/api/v1/settings"
    manifests = {
        "model-providers": {"type": "openai", "auth": {"api_key": key}, "models": [{
            "name": "conferge-model", "model_id": settings.get("CONNECTIONS_OPENAI_MODEL", "gpt-5.6-terra"),
            "properties": {}}]},
        "mcp-servers": {"type": "remote", "name": "conferge", "description": "Search people and graph evidence.",
                        "url": "http://127.0.0.1:8792/mcp"},
    }
    with httpx.Client(timeout=60) as client:
        for route, manifest in manifests.items():
            response = client.post(f"{base}/{route}", json={"manifest": manifest})
            if response.status_code == 409:
                print(route, "already configured; existing settings preserved")
            else:
                # Status only: upstream bodies may contain credential fields.
                if response.is_error:
                    raise SystemExit(f"{route}: HTTP {response.status_code}; inspect local TrueForge settings.")
                print(route, "configured")


if __name__ == "__main__":
    main()

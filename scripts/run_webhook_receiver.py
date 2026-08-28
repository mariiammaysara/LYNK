"""Run the Meeting BaaS webhook receiver locally on 127.0.0.1:8090 (IPv4).

Local diagnostic only — not started by Hermes, not deployed. Port 8090
was picked to avoid Hermes (8642) and any existing profile port.

USAGE:
    uv run python scripts/run_webhook_receiver.py

Then point a Meeting BaaS bot's webhook URL at this machine (e.g. via a
tunnel — ngrok, an SSH reverse tunnel — since Meeting BaaS's servers
can't reach localhost directly).

Binds `0.0.0.0` (IPv4) deliberately. On Windows, binding `::` does NOT
give you dual-stack (unlike Linux) — it's IPv6-only, so `127.0.0.1`
stops working. A tunnel tool (e.g. ngrok) that resolves "localhost" to
`::1` first will then fail against this IPv4-only bind. Point the
tunnel at the explicit address instead of "localhost" to sidestep the
ambiguity entirely: `ngrok http 127.0.0.1:8090`, not `ngrok http 8090`.
"""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "rel_mcp.transcripts.webhook_receiver:app",
        host="0.0.0.0",
        port=8090,
        log_level="info",
    )


if __name__ == "__main__":
    main()

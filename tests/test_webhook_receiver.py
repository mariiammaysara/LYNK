"""Webhook receiver — one smoke test. Diagnostic tool, not part of the
permanent architecture; deep coverage isn't the point."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rel_mcp.transcripts.webhook_receiver import app


def test_webhook_returns_200_for_valid_body(valid_env: dict[str, str]) -> None:
    client = TestClient(app)

    response = client.post(
        "/webhooks/meetingbaas",
        json={
            "event": "complete",
            "bot_id": "bot-123",
            "recording_url": "https://cdn.example/rec.mp4",
            "transcript_url": "https://cdn.example/transcript.json",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "received"}

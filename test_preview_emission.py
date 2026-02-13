#!/usr/bin/env python3
"""Test script to trigger preview and check if preview_ready events are emitted."""

import asyncio
import json
import requests

BASE_URL = "http://localhost:8000/api/v1"

async def test_preview_emission():
    """Test the preview emission via agent conversation."""

    # 1. Connect a data source (CSV)
    print("[1] Connecting data source...")
    csv_path = "/Users/matthewhans/Desktop/Programming/ShipAgent/uploads/sample_shipments.csv"
    resp = requests.post(
        f"{BASE_URL}/saved-sources/reconnect",
        json={"source_type": "csv", "file_path": csv_path}
    )
    print(f"    Data source connected: {resp.status_code}")

    # 2. Create conversation session
    print("[2] Creating conversation session...")
    resp = requests.post(f"{BASE_URL}/conversations/")
    session_data = resp.json()
    session_id = session_data["session_id"]
    print(f"    Session ID: {session_id}")

    # 3. Send message to trigger preview
    print("[3] Sending command to agent...")
    command = "Create a preview for shipping the first 5 California orders using UPS Ground"
    resp = requests.post(
        f"{BASE_URL}/conversations/{session_id}/messages",
        json={"content": command}
    )
    print(f"    Message sent: {resp.status_code}")

    # 4. Monitor SSE stream for preview_ready event
    print("[4] Monitoring SSE stream for preview_ready event...")
    print("    (Waiting for agent to process...)\n")

    from sseclient import SSEClient
    sse_url = f"{BASE_URL}/conversations/{session_id}/stream"

    response = requests.get(sse_url, stream=True, headers={'Accept': 'text/event-stream'})
    client = SSEClient(response)

    event_count = 0
    preview_ready_seen = False

    for event in client.events():
        if event.data:
            try:
                data = json.loads(event.data)
                event_type = data.get("event")
                event_count += 1

                print(f"    Event {event_count}: {event_type}")

                if event_type == "preview_ready":
                    preview_ready_seen = True
                    print(f"    ✅ PREVIEW_READY EVENT RECEIVED!")
                    print(f"       Data keys: {list(data.get('data', {}).keys())}")
                    break

                if event_type == "done":
                    print(f"    Agent finished")
                    break

            except json.JSONDecodeError:
                pass

    print(f"\n[5] Results:")
    print(f"    Total events: {event_count}")
    print(f"    preview_ready seen: {preview_ready_seen}")

    if not preview_ready_seen:
        print(f"\n    ❌ ISSUE CONFIRMED: preview_ready event was NOT emitted")
        print(f"    Check backend.log for [DEBUG] messages from _emit_event()")
    else:
        print(f"\n    ✅ Event emission working correctly")

    # Cleanup
    requests.delete(f"{BASE_URL}/conversations/{session_id}")

if __name__ == "__main__":
    asyncio.run(test_preview_emission())

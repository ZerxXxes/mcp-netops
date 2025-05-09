"""Minimal CLI that lets you chat with GPT‑4o‑mini and *automatically* calls the
MCP gateway tools (`run_command`, `show_inventory`).

Usage:
    export OPENAI_API_KEY=...
    poetry run python scripts/chat_llm.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

import httpx
from openai import OpenAI

MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp")

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function‑calling spec)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a read‑only CLI show command on a device.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Hostname in inventory"},
                    "command": {"type": "string", "description": "CLI show command"},
                },
                "required": ["device", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_inventory",
            "description": "Get the list of devices available to this user.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# ---------------------------------------------------------------------------
# MCP gateway helpers
# ---------------------------------------------------------------------------

client = httpx.Client(timeout=30)

def mcp_run_command(device: str, command: str) -> Dict[str, Any]:
    resp = client.post(f"{MCP_URL}/run_command", json={"device": device, "command": command})
    resp.raise_for_status()
    return resp.json()

def mcp_show_inventory():
    resp = client.get(f"{MCP_URL}/show_inventory")
    resp.raise_for_status()
    return resp.json()

FUNCTION_MAP = {
    "run_command": mcp_run_command,
    "show_inventory": mcp_show_inventory,
}

# ---------------------------------------------------------------------------
# Chat loop
# ---------------------------------------------------------------------------

openai = OpenAI()
messages: List[Dict[str, Any]] = [
    {
        "role": "system",
        "content": (
            "You are a network assistant. Use the available tools to gather data from network devices to help answer questions or troubleshoot issues in the network."
        ),
    }
]

print("Network chat (type 'exit' to quit)\n")

while True:
    user_input = input("🧑‍💻 > ").strip()
    if user_input.lower() in {"exit", "quit"}:
        sys.exit(0)

    messages.append({"role": "user", "content": user_input})

    while True:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        # Store assistant message FIRST (required by spec)
        messages.append(msg.model_dump())

        # If the model calls a tool, execute it and feed the result back
        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments or "{}")
                print(f"🤖 → calling {fn_name}({args})")
                try:
                    result = FUNCTION_MAP[fn_name](**args)
                except Exception as exc:  # noqa: BLE001
                    result = {"error": str(exc)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": fn_name,
                        "content": json.dumps(result),
                    }
                )
            # model should now get another turn with the new tool messages
            continue

        # Otherwise, print assistant reply and break to outer loop
        print(f"🤖 {msg.content}\n")
        break

"""Web chat interface for the network assistant example (Gradio).

This is a *drop-in* alternative to ``scripts/chat_llm.py`` that runs the
conversation through a simple browser UI instead of the command line.  It uses
Gradio's ``ChatInterface`` component so Markdown in the LLM responses is
rendered automatically.

Environment variables (same as the CLI version):

    OPENAI_API_KEY  – API key for the OpenAI-compatible service (required).
    BASE_URL        – Optional custom base URL (e.g. https://my-endpoint/v1).
    MCP_URL         – URL of the MCP gateway (default http://localhost:8000/mcp).

Run locally (inside Poetry shell):

    poetry run python scripts/chat_llm_web.py

Point your browser to ``http://127.0.0.1:7860``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

import inspect  # noqa: E402 – intentionally placed early so it is available later

import httpx
import gradio as gr
from openai import OpenAI

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

# MCP Gateway base URL (local FastAPI service)
MCP_URL: str = os.getenv("MCP_URL", "http://localhost:8000/mcp")

# Optional: override the base URL for the OpenAI-compatible endpoint so the
# script can be pointed at alternative providers (e.g. Azure OpenAI).
BASE_URL: str | None = os.getenv("BASE_URL")

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling spec)
# ---------------------------------------------------------------------------

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a read-only CLI show command on a device.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {
                        "type": "string",
                        "description": "Hostname in inventory",
                    },
                    "command": {
                        "type": "string",
                        "description": "CLI show command",
                    },
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
# MCP gateway helpers (same as CLI script)
# ---------------------------------------------------------------------------

_http_client = httpx.Client(timeout=30)


def _mcp_run_command(device: str, command: str) -> Dict[str, Any]:
    resp = _http_client.post(f"{MCP_URL}/run_command", json={"device": device, "command": command})
    resp.raise_for_status()
    return resp.json()


def _mcp_show_inventory() -> Dict[str, Any]:
    resp = _http_client.get(f"{MCP_URL}/show_inventory")
    resp.raise_for_status()
    return resp.json()


_FUNCTION_MAP = {
    "run_command": _mcp_run_command,
    "show_inventory": _mcp_show_inventory,
}

# ---------------------------------------------------------------------------
# OpenAI client & chat helper
# ---------------------------------------------------------------------------

# Instantiate OpenAI client once so it can be reused for *all* requests.
_openai = OpenAI(base_url=BASE_URL)

# ---------------------------------------------------------------------------
# Dynamically fetch the list of available models so the dropdown always shows
# the correct choices – this works irrespective of which OpenAI-compatible
# backend the user points the client at.
# ---------------------------------------------------------------------------

# Attempt to list the models via the API.  If the request fails (e.g. because
# the key does not allow the operation or the endpoint does not implement the
# ``/models`` route) we fall back to the previously hard-coded default so the
# UI still launches.

# ``try``/``except`` requires an indented block – wrap the call in a single
# line statement.
try:
    _AVAILABLE_MODELS = [m.id for m in _openai.models.list().data]
# If anything goes wrong (permission issues, incompatible endpoint, …) fall
# back to a single default model so the application still starts.
except Exception:  # noqa: BLE001 – any error → revert to sane default
    _AVAILABLE_MODELS = ["o4-mini"]

# Make sure the list is never empty so the dropdown always has at least one
# choice (this covers the corner-case where the endpoint returns an empty list
# without raising an error).
if not _AVAILABLE_MODELS:
    _AVAILABLE_MODELS = ["o4-mini"]

# Pick a sensible default for the dropdown – prefer ``o4-mini`` as that is what
# the example previously used.  If it is not present, just use the first model
# returned by the API.
_DEFAULT_MODEL = "o4-mini" if "o4-mini" in _AVAILABLE_MODELS else _AVAILABLE_MODELS[0]

# System prompt that establishes the assistant behaviour (same as CLI script).
_SYSTEM_MSG = {
    "role": "system",
    "content": (
        "You are a network assistant. Use the available tools to gather data "
        "from network devices to help answer questions or troubleshoot issues "
        "in the network."
    ),
}


# NB: ``model`` is passed in from the UI dropdown so each request uses the
# currently selected model.

def _assistant_response(messages: List[Dict[str, Any]], model: str) -> str:
    """Run the model until a *final* assistant message is produced.

    The function handles the iterative tool-calling flow: if the model chooses
    to invoke a function, we call the MCP gateway, append the tool results to
    the message list, and make another request – exactly mirroring the logic in
    the CLI example.
    """

    while True:
        response = _openai.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        msg = response.choices[0].message
        # Store assistant message first as required by the spec
        messages.append(msg.model_dump())

        # If the model decided to call a tool, execute it and continue loop
        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments or "{}")

                # Run the mapped Python function (MCP gateway call)
                try:
                    result = _FUNCTION_MAP[fn_name](**args)
                except Exception as exc:  # noqa: BLE001 – return error to model
                    result = {"error": str(exc)}

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": fn_name,
                        "content": json.dumps(result),
                    }
                )

            # With the new tool messages appended, let the model take another
            # turn to produce the *real* assistant reply.
            continue

        # No tool call → final assistant message ready.
        return msg.content or ""


# ---------------------------------------------------------------------------
# Gradio chat wrapper
# ---------------------------------------------------------------------------


# ``ChatInterface`` passes (user_msg, history, *additional_inputs).  With the
# dropdown added below the extra argument will be the selected *model*.

def chat_fn(user_msg: str, history: List[Tuple[str, str]], model: str) -> str:  # noqa: D401 – simple!
    """Generate assistant reply for the current user message.

    Gradio passes the *entire* history (list of tuples).  We rebuild the list of
    messages expected by the OpenAI client from that history + the incoming
    user message, run the assistant logic, and return the response.  Gradio
    handles updating the UI for us.
    """

    # Rebuild full message list with role metadata
    messages: List[Dict[str, Any]] = [_SYSTEM_MSG]

    for user, assistant in history:
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant})

    # Current user turn
    messages.append({"role": "user", "content": user_msg})

    assistant_reply = _assistant_response(messages, model=model)
    return assistant_reply


# ---------------------------------------------------------------------------
# Launch UI
# ---------------------------------------------------------------------------


DESCRIPTION = (
    "Ask questions about your network.  The assistant can automatically "
    "collect data from devices using the MCP gateway (``run_command`` / "
    "``show_inventory``) when needed.  Markdown in the responses is rendered "
    "inline."
)

# Build the UI with an additional *Model* dropdown so users can select the LLM
# to run their queries against.

# ---------------------------------------------------------------------------
# Build the Gradio UI.
#
# Older Gradio versions (< 4.12) do not support the
# ``additional_inputs_placement`` argument – passing it would raise the exact
# TypeError reported by the user.  To keep the script compatible with *any*
# Gradio release, we add the parameter only if the currently installed version
# supports it.
# ---------------------------------------------------------------------------

# ``inspect`` is already imported at the top of the file.
# Dropdown that lets the user choose the model used for the backend requests.
_MODEL_DROPDOWN = gr.Dropdown(
    choices=_AVAILABLE_MODELS,
    value=_DEFAULT_MODEL,
    label="Model",
)

# Common constructor arguments for ``ChatInterface``
# Collect constructor arguments for ``ChatInterface`` – we only add parameters
# that are supported by the current Gradio version to stay backwards
# compatible.

# Assemble constructor arguments common to all Gradio versions.
#
# The *examples* parameter must match the *number* of input components.  If a
# model dropdown is added via ``additional_inputs`` we need to supply a
# *nested* list where every sub-list contains an entry for **each** input
# component (the *user message* and the *Model* selector).  When the dropdown
# is not present, the interface only has the single text input, therefore each
# inner list only needs the message.

# Base user questions that we want to show as clickable examples in the UI.
_BASE_EXAMPLES = [
    "Which interfaces are down on r1?",
    "Show me the inventory",
]

# Initial constructor arguments (added incrementally below so we can stay
# compatible with older Gradio releases that may not implement newer keyword
# parameters).
_chat_kwargs: Dict[str, Any] = {
    "fn": chat_fn,
    "title": "Network Assistant (MCP PoC)",
    "description": DESCRIPTION,
}

# Check which optional arguments are accepted by the installed Gradio build.
_ci_params = inspect.signature(gr.ChatInterface.__init__).parameters

if "additional_inputs" in _ci_params:
    _chat_kwargs["additional_inputs"] = _MODEL_DROPDOWN

# Build examples list that matches the number of input components.
if "additional_inputs" in _ci_params:
    # ChatInterface will have two inputs: text + dropdown
    _chat_kwargs["examples"] = [[q, _DEFAULT_MODEL] for q in _BASE_EXAMPLES]
else:
    # Only the text input is present.
    _chat_kwargs["examples"] = [[q] for q in _BASE_EXAMPLES]

# Add sidebar placement if supported by the installed Gradio version.
if "additional_inputs_placement" in _ci_params:
    _chat_kwargs["additional_inputs_placement"] = "sidebar"

# Finally, create the UI instance.
demo = gr.ChatInterface(**_chat_kwargs)


if __name__ == "__main__":
    # Expose on all interfaces so it works inside containers/VMs as well.
    demo.launch(server_name="127.0.0.1", server_port=7860)

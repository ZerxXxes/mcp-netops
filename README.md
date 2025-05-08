# MCP‑NetOps PoC

> **Middle layer that exposes a Model‑Context‑Protocol (MCP) interface to network devices** so any compliant LLM can run *read‑only* CLI commands (via Netmiko) and receive structured JSON (via pyATS Genie) for troubleshooting.

---

## Features

* **MCP endpoints** – `/run_command` & `/show_inventory` exposed through FastAPI.
* **Device inventory** – simple `inventory.yaml`; supports RBAC tags.
* **Connection pool** – re‑uses Netmiko SSH sessions for speed.
* **Best‑effort parsing** – returns raw *and* JSON (currently `show ip int brief`).
* **Audit trail** – every LLM/tool call logged to `audit.log`.
* **JWT auth (PoC level)** – HS256 tokens or automatic demo user.

---

## Getting started (Poetry)

### 1. Install Poetry (once)

```bash
pipx install poetry  # or see https://python-poetry.org/docs/#installation
```

### 2. Clone & install

```bash
git clone https://github.com/your-org/mcp-netops-poc.git
cd mcp-netops-poc

poetry install       # creates .venv & installs deps per pyproject.toml
```

> **Tip – VS Code:** set the interpreter to `.venv/bin/python` when prompted.

### 3. Add lab devices

Create `mcp_gateway/inventory/inventory.yaml` (or edit the default) – example:

```yaml
devices:
  - hostname: r1
    host: 192.0.2.10
    platform: ios
    username: lab
    password: lab123
    tags: [lab]
  - hostname: sw1
    host: 192.0.2.11
    platform: nxos
    username: lab
    password: lab123
    tags: [lab]
```

### 4. Run the API

```bash
# activate the venv shell (optional)
poetry shell

uvicorn mcp_gateway.main:app --reload  # http://127.0.0.1:8000/docs
```

### 5. Test with `curl`

```bash
curl -X POST http://localhost:8000/mcp/run_command \
     -H 'Content-Type: application/json' \
     -d '{"device":"r1","command":"show ip int brief"}'
```

You should get JSON like:

```jsonc
{
  "stdout": "Interface              IP-Address      OK? Method Status ...",
  "json": {
    "interfaces": [
      {"interface": "Gig0/0", "ip_address": "192.0.2.1", "status": "up", ...}
    ]
  }
}
```

---

## Next steps

| Task             | File/Doc                   | Notes                                    |
| ---------------- | -------------------------- | ---------------------------------------- |
| Add more parsers | `services/parser.py`       | Hook pyATS Genie for full coverage       |
| Dockerise        | `Dockerfile`               | `FROM python:3.11-slim` + Poetry install |
| Real auth        | `services/auth.py`         | Replace HS256 with OIDC / JWKS           |
| gNMI adapter     | `devices/gnmi_client.py`   | Structured streaming, no scraping        |
| CI tests         | `.github/workflows/ci.yml` | pytest + ruff + mypy                     |

---



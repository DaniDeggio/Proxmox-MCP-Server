# Deggio Infra MCP

> Homelab infrastructure provisioning MCP server for automated service deployment on Proxmox LXC containers.

**deggio-infra-mcp** is a production-ready [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that orchestrates end-to-end service provisioning in a Proxmox-based homelab. It combines:

- **Proxmox LXC management** — clone templates, configure, start containers
- **Pi-hole DNS automation** — automatic local DNS record creation
- **Nginx Proxy Manager** — automated reverse proxy host setup
- **Agy bootstrap** — AI-driven service setup inside containers
- **Full orchestration** — one `create_service` tool that does everything

## Architecture

```
┌─────────────────────────────────────────────┐
│           MCP Transport (stdio)             │
│         FastMCP · server.py                 │
├─────────────────────────────────────────────┤
│             MCP Tools Layer                 │
│       tools/service_tools.py                │
│    (validate → call service → respond)      │
├─────────────────────────────────────────────┤
│            Service Layer                    │
│  services/provisioning.py  (orchestration)  │
│  services/ipam.py          (IP allocation)  │
│  services/prompt_generator.py               │
├─────────────────────────────────────────────┤
│          Provider Layer (adapters)          │
│  providers/proxmox.py  → proxmoxer         │
│  providers/pihole.py   → Pi-hole v6 API    │
│  providers/npm.py      → NPM REST API      │
│  providers/agy.py      → exec via Proxmox  │
├─────────────────────────────────────────────┤
│    Config + Models + State + Logging        │
│  config.py · models/ · utils/ · logging.py  │
└─────────────────────────────────────────────┘
```

**Design principles:**
- Clean separation: tools → services → providers
- Provider interfaces (ABCs) decouple business logic from API details
- Configuration-driven — everything is in YAML, secrets in env vars
- Idempotent operations where possible
- Structured logging with correlation IDs per request

## Repository Structure

```
├── pyproject.toml                    # Project definition + dependencies
├── .env.example                      # Required environment variables
├── config/
│   └── config.example.yaml           # Full configuration template
├── deploy/
│   └── deggio-infra-mcp.service      # Systemd unit for LXC deployment
├── scripts/
│   └── run_dev.sh                    # Dev startup script
├── src/deggio_infra_mcp/
│   ├── __init__.py
│   ├── server.py                     # FastMCP server entry point
│   ├── config.py                     # YAML config + env var interpolation
│   ├── logging.py                    # Structured logging (structlog)
│   ├── models/
│   │   ├── errors.py                 # Domain exceptions
│   │   ├── service.py                # Request/result/step models
│   │   └── templates.py              # Template definitions
│   ├── providers/
│   │   ├── __init__.py               # Abstract base classes
│   │   ├── proxmox.py                # Proxmox via proxmoxer
│   │   ├── pihole.py                 # Pi-hole v6 REST API
│   │   ├── npm.py                    # Nginx Proxy Manager API
│   │   └── agy.py                    # Agy execution via SSH
│   ├── services/
│   │   ├── ipam.py                   # IP address management
│   │   ├── provisioning.py           # Orchestration engine
│   │   └── prompt_generator.py       # Agy prompt generation
│   ├── tools/
│   │   └── service_tools.py          # MCP tool definitions
│   └── utils/
│       └── network.py                # TCP reachability helpers
└── tests/
    ├── conftest.py                   # Mock providers + fixtures
    ├── test_config.py
    ├── test_ipam.py
    ├── test_provisioning.py
    ├── test_prompt_generator.py
    ├── test_npm_provider.py
    └── test_pihole_provider.py
```

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip
- **Proxmox VE** with API token access
- **Pi-hole** (v6) for local DNS
- **Nginx Proxy Manager** for reverse proxying
- **Agy** (optional) installed or available in LXC templates

## Installation

### With uv (recommended)

```bash
# Clone the repo
git clone https://github.com/DaniDeggio/ProxmoxMcp.git
cd ProxmoxMcp

# Create venv and install
uv venv
uv pip install -e ".[dev]"
```

### With pip

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

### 1. Create config file

```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml` with your environment details:
- Proxmox host, port, and node name
- Template VMIDs
- IP range for new containers
- Pi-hole and NPM URLs

### 2. Set environment variables

```bash
cp .env.example .env
```

Fill in the secrets:

| Variable | Description |
|----------|-------------|
| `PROXMOX_TOKEN_ID` | Proxmox API token ID (`user@pam!token-name`) |
| `PROXMOX_TOKEN_SECRET` | Proxmox API token secret |
| `PIHOLE_PASSWORD` | Pi-hole admin password |
| `NPM_USER` | Nginx Proxy Manager email |
| `NPM_PASSWORD` | Nginx Proxy Manager password |

### 3. Proxmox API token

Create a dedicated API token in Proxmox:

```bash
# On your Proxmox host
pveum user add mcp@pam --comment "MCP automation user"
pveum aclmod / -user mcp@pam -role PVEVMAdmin
pveum user token add mcp@pam mcp-token --privsep=0
```

Save the token ID and secret in your `.env` file.

## ProxmoxMCP-Plus Integration

This project does **not** import ProxmoxMCP-Plus as a library. After inspecting its source, its internal modules are tightly coupled to their own config/MCP transport and are not designed for library use.

Instead, we use **[proxmoxer](https://github.com/proxmoxer/proxmoxer)** directly — the same underlying Proxmox API library that ProxmoxMCP-Plus wraps. This gives us:

- Identical Proxmox API capabilities
- Zero version coupling to ProxmoxMCP-Plus internals
- Clean provider abstraction behind `ProxmoxProvider`
- Full compatibility if you also run ProxmoxMCP-Plus as a separate MCP server

If you want both servers available to your agents, configure them as separate MCP servers — they use the same Proxmox API tokens and will not conflict.

## Running

### Development

```bash
# Via the dev script
./scripts/run_dev.sh

# Or directly
source .env
DEGGIO_INFRA_CONFIG=config/config.yaml uv run deggio-infra-mcp
```

### As an MCP Server (stdio)

Configure your MCP client (Claude Desktop, Cursor, etc.):

```json
{
  "mcpServers": {
    "deggio-infra-mcp": {
      "command": "uv",
      "args": ["--directory", "/path/to/ProxmoxMcp", "run", "deggio-infra-mcp"],
      "env": {
        "DEGGIO_INFRA_CONFIG": "/path/to/ProxmoxMcp/config/config.yaml",
        "PROXMOX_TOKEN_ID": "mcp@pam!mcp-token",
        "PROXMOX_TOKEN_SECRET": "your-secret",
        "PIHOLE_PASSWORD": "your-password",
        "NPM_USER": "admin@example.com",
        "NPM_PASSWORD": "your-password"
      }
    }
  }
}
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `list_templates()` | List configured LXC templates |
| `allocate_ip(hostname)` | Get next free IP from range |
| `create_lxc_from_template(template_key, hostname, ip)` | Clone + configure a container |
| `start_container(vmid)` | Start an LXC container |
| `wait_for_container(vmid)` | Wait until SSH is reachable |
| `add_pihole_dns_record(domain, ip)` | Create Pi-hole DNS record |
| `create_npm_proxy_host(domain, host, port)` | Create NPM proxy host |
| `run_agy_bootstrap(vmid, prompt)` | Execute Agy inside container |
| `generate_agy_prompt(name, type, ...)` | Build a bootstrap prompt |
| **`create_service(...)`** | **Full orchestration flow** |

### Example: create_service

```
Use the create_service tool:
- service_name: "my-web-app"
- template_key: "base"
- forward_port: 3000
- repo_urls: ["https://github.com/user/my-app"]
```

This will automatically: allocate an IP → clone the template → configure networking → start the container → wait for SSH → add DNS record (`my-web-app.deggio.local`) → create reverse proxy → run Agy to set up the service.

## Deployment in LXC

### 1. Prepare the LXC

```bash
# Inside your dedicated MCP LXC (Debian/Ubuntu)
apt update && apt install -y python3.11 python3.11-venv git

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create service user
useradd -r -m -d /opt/deggio-infra-mcp -s /bin/bash deggio-mcp
```

### 2. Deploy

```bash
# As deggio-mcp user
sudo -u deggio-mcp bash
cd /opt/deggio-infra-mcp

git clone https://github.com/DaniDeggio/ProxmoxMcp.git .
uv venv
uv pip install -e .

# Configure
cp config/config.example.yaml config/config.yaml
cp .env.example .env
# Edit both files with your values

# Create state directory
mkdir -p state
```

### 3. Install systemd service

```bash
sudo cp deploy/deggio-infra-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable deggio-infra-mcp
sudo systemctl start deggio-infra-mcp

# Check status
sudo systemctl status deggio-infra-mcp
sudo journalctl -u deggio-infra-mcp -f
```

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ -v --cov=deggio_infra_mcp --cov-report=term-missing

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/deggio_infra_mcp/
```

## Security Notes

- **Never commit `.env` or `config/config.yaml`** — they contain secrets
- Use Proxmox API tokens with **minimal permissions** (not root)
- The MCP server runs over **stdio** — it does not listen on any port
- Pi-hole and NPM credentials are per-session and not persisted
- File-based IPAM state uses file locking for safety
- The systemd unit includes hardening (`NoNewPrivileges`, `ProtectSystem`, `ProtectHome`)

## Roadmap

- [ ] HTTP/Streamable transport support
- [ ] SQLite-backed state instead of JSON files
- [ ] Container health-check beyond SSH port
- [ ] Template auto-discovery from Proxmox
- [ ] Rollback capability for partial failures
- [ ] Pi-hole v5 compatibility adapter
- [ ] Let's Encrypt certificate automation via NPM
- [ ] Metrics/observability endpoint

## License

MIT

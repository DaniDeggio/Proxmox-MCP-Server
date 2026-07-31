# Proxmox MCP Server

> Homelab infrastructure provisioning MCP server for automated service deployment on Proxmox LXC containers.

**proxmox-mcp-server** is a production-ready [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that orchestrates end-to-end service provisioning in a Proxmox-based homelab. It combines:

- **Proxmox LXC management** — clone templates, configure networking & tags, start/stop containers
- **Pi-hole DNS automation** — automatic local DNS record creation and management
- **Nginx Proxy Manager** — automated reverse proxy host setup
- **Coding Agent Bootstrap (Agy)** — AI-driven service setup inside containers using Google Antigravity CLI
- **Full orchestration** — one `create_service` tool that handles the entire pipeline

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
│  providers/proxmox.py  → proxmoxer          │
│  providers/pihole.py   → Pi-hole v6 API     │
│  providers/npm.py      → NPM REST API       │
│  providers/agy.py      → exec via Proxmox   │
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
- Session retry logic (401 token refresh) for long-running MCP servers

## Repository Structure

```
├── pyproject.toml                    # Project definition + dependencies
├── .env.example                      # Required environment variables
├── config/
│   └── config.example.yaml           # Full configuration template
├── deploy/
│   └── proxmox-mcp-server.service    # Systemd unit for LXC deployment
├── scripts/
│   └── run_dev.sh                    # Dev startup script
├── src/proxmox_mcp_server/
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
│   │   ├── pihole.py                 # Pi-hole v6 REST API (with 401 retry)
│   │   ├── npm.py                    # Nginx Proxy Manager API (with 401 retry)
│   │   └── agy.py                    # Agy execution via Proxmox
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
    ├── test_npm_http.py
    ├── test_pihole_provider.py
    ├── test_pihole_http.py
    └── test_agy_provider.py
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
- Template VMIDs and network bridge
- IP range for new containers
- Pi-hole and NPM URLs
- Domain suffix (`homelab.local` by default)

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
| `PROXMOX_MCP_CONFIG` | Optional config file path override (default: `config/config.yaml`) |
| `PROXMOX_MCP_LOG_LEVEL` | Optional log level override (default: `INFO`) |

### 3. Proxmox API token

Create a dedicated API token in Proxmox:

```bash
# On your Proxmox host
pveum user add mcp@pam --comment "MCP automation user"
pveum aclmod / -user mcp@pam -role PVEVMAdmin
pveum user token add mcp@pam mcp-token --privsep=0
```

Save the token ID and secret in your `.env` file.

## Coding Agent Integration (Agy)

This server supports automated in-container service setup using **[Agy](https://antigravity.google/docs/cli/getting-started)**, the CLI coding agent from Google Antigravity.

### Installing Agy in Templates
To allow Agy to bootstrap services automatically inside cloned LXC containers, install it in your base LXC template:
```bash
# Inside the LXC template
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

### Headless Execution
When `create_service` runs an Agy bootstrap step, it executes Agy in headless/print mode. By default, `skip_permissions: true` is enabled in `config/config.yaml`, which passes `--dangerously-skip-permissions` to Agy so it can install packages, clone repositories, and configure systemd services without waiting for interactive TTY confirmation.

If your Agy workflows require authentication in headless server environments, make sure `ANTIGRAVITY_API_KEY` is configured in your template's environment.

### Supporting Other Agents
The agent integration is abstracted behind `BaseAgentProvider`. While Agy (`AgyProvider`) is currently the supported default, the architecture makes it straightforward to integrate other CLI agents in the future (such as OpenCode or Claude Code) by implementing the `BaseAgentProvider` interface.

## Running

### Development

```bash
# Via the dev script
./scripts/run_dev.sh

# Or directly
source .env
PROXMOX_MCP_CONFIG=config/config.yaml uv run proxmox-mcp-server
```

### As an MCP Server (stdio)

Configure your MCP client (Claude Desktop, Cursor, etc.):

```json
{
  "mcpServers": {
    "proxmox-mcp-server": {
      "command": "uv",
      "args": ["--directory", "/path/to/ProxmoxMcp", "run", "proxmox-mcp-server"],
      "env": {
        "PROXMOX_MCP_CONFIG": "/path/to/ProxmoxMcp/config/config.yaml",
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
| `stop_container(vmid)` | Stop an LXC container |
| `get_container_status(vmid)` | Query status of a container |
| `wait_for_container(vmid)` | Wait until SSH is reachable |
| `list_ip_reservations()` | List all IPAM reservations |
| `release_ip(ip)` | Release an allocated IP address |
| `add_pihole_dns_record(domain, ip)` | Create Pi-hole DNS record |
| `delete_pihole_dns_record(domain, ip)` | Delete a Pi-hole DNS record |
| `list_pihole_dns_records()` | List custom DNS records in Pi-hole |
| `create_npm_proxy_host(domain, host, port)` | Create NPM proxy host |
| `delete_npm_proxy_host(host_id)` | Delete an NPM proxy host by ID |
| `list_npm_proxy_hosts()` | List all configured proxy hosts |
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

This will automatically: allocate an IP → clone the template → configure networking → start the container → wait for SSH → add DNS record (`my-web-app.homelab.local`) → create reverse proxy → run Agy to set up the service.

## Deployment in LXC

### 1. Prepare the LXC

```bash
# Inside your dedicated MCP LXC (Debian/Ubuntu)
apt update && apt install -y python3.11 python3.11-venv git

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create service user
useradd -r -m -d /opt/proxmox-mcp-server -s /bin/bash proxmox-mcp
```

### 2. Deploy

```bash
# As proxmox-mcp user
sudo -u proxmox-mcp bash
cd /opt/proxmox-mcp-server

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
sudo cp deploy/proxmox-mcp-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable proxmox-mcp-server
sudo systemctl start proxmox-mcp-server

# Check status
sudo systemctl status proxmox-mcp-server
sudo journalctl -u proxmox-mcp-server -f
```

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ -v --cov=proxmox_mcp_server --cov-report=term-missing

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/proxmox_mcp_server/
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

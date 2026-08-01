# Proxmox MCP Server

> Homelab infrastructure provisioning MCP server for automated service deployment on Proxmox LXC containers.

**proxmox-mcp-server** is a production-ready [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that orchestrates end-to-end service provisioning in a Proxmox-based homelab. It combines:

- **Proxmox LXC & Host management** — clone templates, configure networking, start/stop containers, and execute direct host diagnostics
- **Pi-hole DNS automation** — automatic local DNS record creation and management
- **Nginx Proxy Manager** — automated reverse proxy host setup
- **Coding Agent Integration (Agy)** — AI-driven service setup inside LXC containers AND direct Proxmox host administration with built-in safety guardrails
- **Full orchestration** — one `create_service` tool that handles the entire pipeline

## Architecture

```
┌─────────────────────────────────────────────┐
│    MCP Transport (stdio / HTTP Streaming)   │
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

### Host-Level Administration
In addition to inside-LXC bootstrap, Agy can be executed directly on the **Proxmox VE hypervisor host** via SSH (`run_host_agy`) for complex host tasks such as configuring ZFS datasets, managing LXC templates, or setting up bridge networking.

To ensure safety when operating on critical hypervisor infrastructure, use `generate_host_agy_prompt` to generate prompts equipped with explicit guardrails:
- Prevents removal of Proxmox/Ceph/Corosync packages (`proxmox-*`, `pve-*`, `ceph-*`, `corosync`).
- Protects `/etc/pve/` configurations from direct modification.
- Requires automatic timestamped backups before modifying config files.

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

### As an MCP Server (HTTP Streaming / SSE)
You can run the server over HTTP streaming (`streamable-http`, `sse`, `http`) by specifying CLI flags or setting the `transport` option in `config/config.yaml`:

```bash
# Start with Streamable HTTP on 0.0.0.0:8000
uv run proxmox-mcp-server --transport streamable-http --host 0.0.0.0 --port 8000

# Start with Server-Sent Events (SSE)
uv run proxmox-mcp-server --transport sse --port 8000
```

## MCP Tools


| Tool | Description | Category |
|------|-------------|----------|
| **`create_service(...)`** | **Full end-to-end orchestration flow** | Orchestration |
| `list_templates()` | List configured LXC templates | Provisioning |
| `create_lxc_from_template(template_key, ...)` | Clone + configure a new LXC container | Provisioning |
| `import_existing_lxc(vmid, ...)` | Adopt an existing LXC container into MCP management | Provisioning |
| `list_containers()` | List all managed containers | Operations |
| `start_container(vmid)` | Start an LXC container | Operations |
| `stop_container(vmid)` | Stop an LXC container | Operations |
| `get_container_status(vmid)` | Query status and resource usage of a container | Operations |
| `wait_for_container(vmid)` | Wait until SSH is reachable inside container | Operations |
| `exec_lxc_command(vmid, command)` | Execute a shell command inside an LXC container | Diagnostics |
| `get_lxc_service_logs(vmid, service_name)` | Fetch systemd journal logs from a container | Diagnostics |
| `get_storage_status()` | Check Proxmox storage pool usage and availability | Infrastructure |
| `resize_lxc_disk(vmid, disk, size)` | Resize an LXC container disk volume | Infrastructure |
| `update_lxc_resources(vmid, cores, memory_mb)` | Adjust CPU/memory resources for a container | Infrastructure |
| `get_task_status(upid)` | Check status of an asynchronous Proxmox task | Infrastructure |
| `get_task_log(upid)` | Read log output of a Proxmox UPID task | Infrastructure |
| `create_lxc_snapshot(vmid, name)` | Create a snapshot of an LXC container | Snapshots |
| `list_lxc_snapshots(vmid)` | List all snapshots for an LXC container | Snapshots |
| `rollback_lxc_snapshot(vmid, name)` | Roll back an LXC container to a snapshot | Snapshots |
| `allocate_ip(hostname)` | Get next free IP address from range | IPAM |
| `list_ip_reservations()` | List all IPAM reservations | IPAM |
| `release_ip(ip)` | Release an allocated IP address | IPAM |
| `add_pihole_dns_record(domain, ip)` | Create local Pi-hole DNS record | DNS |
| `delete_pihole_dns_record(domain, ip)` | Delete a Pi-hole DNS record | DNS |
| `list_pihole_dns_records()` | List custom DNS records in Pi-hole | DNS |
| `create_npm_proxy_host(domain, host, port)` | Create reverse proxy host in Nginx Proxy Manager | Proxy |
| `list_npm_proxy_hosts()` | List all configured proxy hosts in NPM | Proxy |
| `delete_npm_proxy_host(host_id)` | Delete an NPM proxy host by ID | Proxy |
| `run_agy_bootstrap(vmid, prompt)` | Execute Agy coding agent inside LXC container | Agent (LXC) |
| `generate_agy_prompt_tool(...)` | Build a bootstrap prompt for container setup | Agent (LXC) |
| `exec_host_command(command)` | Execute command directly on Proxmox VE host | Agent (Host) |
| `run_host_agy(prompt)` | Execute Agy directly on Proxmox VE hypervisor host | Agent (Host) |
| `generate_host_agy_prompt(...)` | Build a safety-guarded prompt for host administration | Agent (Host) |


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
- The MCP server defaults to **stdio** (no open ports), but supports optional **HTTP streaming** with configurable host/port bindings
- Pi-hole and NPM credentials are per-session and not persisted
- File-based IPAM state uses file locking for safety
- The systemd unit includes hardening (`NoNewPrivileges`, `ProtectSystem`, `ProtectHome`)
- Host-level Agy prompts include explicit guardrails to protect Proxmox core packages and `/etc/pve/` configurations

## Roadmap

- [x] HTTP/Streamable transport support (`streamable-http`, `sse`, `http`)
- [x] Host-level Agy administration with safety guardrails
- [ ] SQLite-backed state instead of JSON files
- [ ] Container health-check beyond SSH port
- [ ] Template auto-discovery from Proxmox
- [ ] Rollback capability for partial failures
- [ ] Pi-hole v5 compatibility adapter
- [ ] Let's Encrypt certificate automation via NPM
- [ ] Metrics/observability endpoint

## License

MIT


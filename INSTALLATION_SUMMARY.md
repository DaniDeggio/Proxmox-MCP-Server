# Proxmox MCP Server Installation Summary

## Overview

The **Proxmox MCP Server** has been successfully installed and configured from scratch on this LXC container.

---

## What Was Installed

1. **System Dependencies & Prerequisites**:
   - `git`, `curl`, `make`, `build-essential`
   - `python3`, `python3-venv`, `python3-pip`, `python3-dev`
2. **Package Manager**:
   - `uv` (v0.12.1) installed at `/usr/local/bin/uv`
3. **Python Runtime & Virtual Environment**:
   - CPython 3.11 runtime installed at `/opt/python/cpython-3.11-linux-x86_64-gnu`
   - Virtual environment created at `/opt/proxmox-mcp-server/.venv`
4. **Application Package**:
   - `proxmox-mcp-server` editable installation with development dependencies (`uv pip install -e ".[dev]"`)
5. **System User & State Directory**:
   - Service user and group `proxmox-mcp:proxmox-mcp`
   - Persistent state directory at `/opt/proxmox-mcp-server/state`

---

## File Locations & Configuration

- **Repository Root**: `/opt/proxmox-mcp-server`
- **Virtual Environment**: `/opt/proxmox-mcp-server/.venv`
- **Main Config File**: `/opt/proxmox-mcp-server/config/config.yaml` *(created from `config.example.yaml`)*
- **Environment Secrets File**: `/opt/proxmox-mcp-server/.env` *(created from `.env.example`)*
- **Systemd Unit File**: `/etc/systemd/system/proxmox-mcp-server.service` *(copied from `deploy/proxmox-mcp-server.service`)*
- **State Directory**: `/opt/proxmox-mcp-server/state`

---

## Service Management

The systemd service `proxmox-mcp-server` is enabled to start on system boot.

### Service Commands:
```bash
# Check service status
sudo systemctl status proxmox-mcp-server

# Start service
sudo systemctl start proxmox-mcp-server

# Stop service
sudo systemctl stop proxmox-mcp-server

# Restart service
sudo systemctl restart proxmox-mcp-server

# View live logs
sudo journalctl -u proxmox-mcp-server -f --no-tail -n 20
```

---

## Running Tests

To verify package functionality and unit test pass rates:
```bash
cd /opt/proxmox-mcp-server
make test
```
*Current test suite result: 135 passed in ~1.3s.*

---

## Next Steps for User Configuration

The service template configuration files have been initialized, but you must populate your real credentials and homelab details:

1. **Edit the main configuration file**:
   ```bash
   nano /opt/proxmox-mcp-server/config/config.yaml
   ```
   Provide real values for:
   - Proxmox VE connection details (host, port, user, token_name, token_value, node)
   - Pi-hole configuration (host, password / API key)
   - NGINX Proxy Manager configuration (host, user, password)
   - Network IP ranges and subnet definitions

2. **(Optional) Edit environment variables**:
   ```bash
   nano /opt/proxmox-mcp-server/.env
   ```

3. **Restart the systemd service**:
   ```bash
   sudo systemctl restart proxmox-mcp-server
   ```

4. **Verify service status**:
   ```bash
   sudo systemctl status proxmox-mcp-server
   ```

---

## Troubleshooting Commands

If issues occur:

- **Check python virtual environment**:
  ```bash
  /opt/proxmox-mcp-server/.venv/bin/python --version
  ```
- **Check uv installation**:
  ```bash
  uv --version
  ```
- **Inspect systemd service definition**:
  ```bash
  systemctl cat proxmox-mcp-server
  ```
- **Check detailed error logs**:
  ```bash
  journalctl -u proxmox-mcp-server -n 50 --no-pager
  ```

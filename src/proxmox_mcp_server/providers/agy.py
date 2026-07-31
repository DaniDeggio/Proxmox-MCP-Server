"""Agy provider — executes Agy bootstrap sessions inside LXC containers.

Agy is the CLI coding agent from Google Antigravity (https://antigravity.google/docs/cli/getting-started).
It is assumed to be available (or installable) inside the container.
The provider delegates actual command execution to a ``BaseProxmoxProvider``
so it works regardless of how we reach the container (SSH, Proxmox exec, etc.).
Future coding agents (such as OpenCode or Claude Code) can be supported by
implementing additional classes conforming to ``BaseAgentProvider``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from proxmox_mcp_server.logging import get_logger
from proxmox_mcp_server.models.errors import AgentExecutionError
from proxmox_mcp_server.providers import BaseAgentProvider, BaseProxmoxProvider

if TYPE_CHECKING:
    from proxmox_mcp_server.config import AgyConfig
    from proxmox_mcp_server.models.service import CommandResult

log = get_logger("providers.agy")


class AgyProvider(BaseAgentProvider):
    """Runs Agy inside a container via the Proxmox provider's exec capability."""

    def __init__(
        self,
        config: AgyConfig,
        proxmox: BaseProxmoxProvider,
    ) -> None:
        self._config = config
        self._proxmox = proxmox

    async def run_bootstrap(
        self,
        vmid: int,
        prompt: str,
        *,
        working_dir: str | None = None,
    ) -> CommandResult:
        wd = working_dir or self._config.working_dir or "/root"
        agy_cmd = self._config.command

        # Build the command that will be executed inside the container.
        # We write the prompt to a temp file to avoid shell quoting issues,
        # then invoke Agy with it.
        skip_flag = " --dangerously-skip-permissions" if self._config.skip_permissions else ""
        full_command = (
            f"cd {wd} && "
            f"cat <<'AGYPROMPT_EOF' > /tmp/agy_bootstrap_prompt.txt\n"
            f"{prompt}\n"
            f"AGYPROMPT_EOF\n"
            f"{agy_cmd} --prompt-file /tmp/agy_bootstrap_prompt.txt{skip_flag}"
        )

        log.info(
            "agy_bootstrap_starting",
            vmid=vmid,
            working_dir=wd,
            prompt_length=len(prompt),
        )

        try:
            result = await self._proxmox.execute_command(
                vmid,
                full_command,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            raise AgentExecutionError(
                f"Agy bootstrap failed in VMID {vmid}: {exc}",
                vmid=vmid,
            ) from exc

        if result.exit_code != 0:
            log.warning(
                "agy_bootstrap_nonzero_exit",
                vmid=vmid,
                exit_code=result.exit_code,
                stderr=result.stderr[:500],
            )
            raise AgentExecutionError(
                f"Agy exited with code {result.exit_code} in VMID {vmid}",
                vmid=vmid,
                exit_code=result.exit_code,
                details={
                    "stdout": result.stdout[:2000],
                    "stderr": result.stderr[:2000],
                },
            )

        log.info(
            "agy_bootstrap_completed",
            vmid=vmid,
            duration=result.duration_seconds,
        )
        return result

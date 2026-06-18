"""BenchEval Harbor Claude Code agent wrapper."""

from __future__ import annotations

import os
import shlex

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment

_NODE_VERSION = "22.16.0"
_NODE_DIST = f"node-v{_NODE_VERSION}-linux-x64"
_NODE_TARBALL_URL = f"https://nodejs.org/dist/v{_NODE_VERSION}/{_NODE_DIST}.tar.gz"
_NPM_REGISTRY_ENV = "BENCHEVAL_CLAUDE_CODE_NPM_REGISTRY"


class ClaudeCodeNpmInstall(ClaudeCode):
    """Claude Code agent that installs the CLI from npm on every Linux base image."""

    async def install(self, environment: BaseEnvironment) -> None:
        await self.exec_as_root(
            environment,
            command=(
                "if command -v curl &> /dev/null; then"
                "  exit 0;"
                " elif command -v apk &> /dev/null; then"
                "  apk add --no-cache curl bash;"
                " elif command -v apt-get &> /dev/null; then"
                "  apt-get update &&"
                "  apt-get install -y --no-install-recommends curl;"
                " elif command -v yum &> /dev/null; then"
                "  yum install -y curl;"
                " else"
                '  echo "Error: curl is required to install Node" >&2;'
                "  exit 1;"
                " fi"
            ),
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        version_spec = f"@{self._version}" if self._version else ""
        registry = os.environ.get(_NPM_REGISTRY_ENV)
        registry_arg = f" --registry={shlex.quote(registry)}" if registry else ""
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                f'node_root="$HOME/.local/{_NODE_DIST}"; '
                'if [[ ! -x "$node_root/bin/node" ]]; then '
                '  mkdir -p "$HOME/.local" && '
                f"  curl -fsSL {_NODE_TARBALL_URL} | "
                'tar -xzf - -C "$HOME/.local"; '
                "fi; "
                'export PATH="$node_root/bin:$PATH"; '
                f"npm install -g{registry_arg} @anthropic-ai/claude-code{version_spec}; "
                'mkdir -p "$HOME/.local/bin" && '
                'ln -sf "$(command -v node)" "$HOME/.local/bin/node" && '
                'ln -sf "$(command -v claude)" "$HOME/.local/bin/claude" && '
                '"$HOME/.local/bin/claude" --version'
            ),
        )


__all__ = ["ClaudeCodeNpmInstall"]

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
_NPM_FETCH_TIMEOUT_ENV = "BENCHEVAL_CLAUDE_CODE_NPM_FETCH_TIMEOUT_MS"
_NPM_FETCH_RETRIES_ENV = "BENCHEVAL_CLAUDE_CODE_NPM_FETCH_RETRIES"


class ClaudeCodeNpmInstall(ClaudeCode):
    """Claude Code agent that installs the CLI from npm on every Linux base image."""

    async def install(self, environment: BaseEnvironment) -> None:
        await self.exec_as_root(
            environment,
            command=(
                "if command -v curl &> /dev/null &&"
                " command -v bash &> /dev/null &&"
                " [[ -s /etc/ssl/certs/ca-certificates.crt ]]; then"
                "  exit 0;"
                "fi;"
                "if command -v apk &> /dev/null; then"
                "  apk add --no-cache ca-certificates curl bash;"
                "elif command -v apt-get &> /dev/null; then"
                "  apt-get update &&"
                "  apt-get install -y --no-install-recommends ca-certificates curl bash;"
                "elif command -v yum &> /dev/null; then"
                "  yum install -y ca-certificates curl bash;"
                "else"
                '  echo "Error: curl, bash, and ca-certificates are required to install Node" >&2;'
                "  exit 1;"
                "fi;"
                "if ! command -v curl &> /dev/null ||"
                " ! command -v bash &> /dev/null ||"
                " [[ ! -s /etc/ssl/certs/ca-certificates.crt ]]; then"
                '  echo "Error: failed to install curl, bash, or ca-certificates" >&2;'
                "  exit 1;"
                "fi"
            ),
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        version_spec = f"@{self._version}" if self._version else ""
        registry = os.environ.get(_NPM_REGISTRY_ENV)
        registry_arg = f" --registry={shlex.quote(registry)}" if registry else ""
        fetch_timeout = os.environ.get(_NPM_FETCH_TIMEOUT_ENV, "120000")
        fetch_retries = os.environ.get(_NPM_FETCH_RETRIES_ENV, "2")
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
                'npm_proxy="${http_proxy:-${HTTP_PROXY:-}}"; '
                'npm_https_proxy="${https_proxy:-${HTTPS_PROXY:-$npm_proxy}}"; '
                'if [[ -n "$npm_proxy" ]]; then npm config set proxy "$npm_proxy"; fi; '
                'if [[ -n "$npm_https_proxy" ]]; then '
                'npm config set https-proxy "$npm_https_proxy"; '
                "fi; "
                f"npm config set fetch-timeout {shlex.quote(fetch_timeout)}; "
                f"npm config set fetch-retries {shlex.quote(fetch_retries)}; "
                f"npm install -g --no-audit --no-fund{registry_arg} "
                f"@anthropic-ai/claude-code{version_spec}; "
                'mkdir -p "$HOME/.local/bin" && '
                'ln -sf "$(command -v node)" "$HOME/.local/bin/node" && '
                'ln -sf "$(command -v claude)" "$HOME/.local/bin/claude" && '
                '"$HOME/.local/bin/claude" --version'
            ),
        )


__all__ = ["ClaudeCodeNpmInstall"]

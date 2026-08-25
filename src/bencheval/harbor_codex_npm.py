"""BenchEval Harbor Codex CLI agent wrapper."""

from __future__ import annotations

import os
import shlex

from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment

_NODE_VERSION = "22.16.0"
_NODE_DIST = f"node-v{_NODE_VERSION}-linux-x64"
_NODE_TARBALL_URL = f"https://nodejs.org/dist/v{_NODE_VERSION}/{_NODE_DIST}.tar.gz"
# nodejs.org SHASUMS256.txt for node-v22.16.0-linux-x64.tar.gz; same pin as
# harbor_claude_code_npm so both Harbor agents share one verified Node tree.
_NODE_TARBALL_SHA256 = "fb870226119d47378fa9c92c4535389c72dae14fcc7b47e6fdcc82c43de5a547"
_NPM_REGISTRY_ENV = "BENCHEVAL_CODEX_NPM_REGISTRY"
_NPM_FETCH_TIMEOUT_ENV = "BENCHEVAL_CODEX_NPM_FETCH_TIMEOUT_MS"
_NPM_FETCH_RETRIES_ENV = "BENCHEVAL_CODEX_NPM_FETCH_RETRIES"
_VERSION_COMMAND = (
    f'export PATH="$HOME/.local/{_NODE_DIST}/bin:$HOME/.local/bin:$PATH"; codex --version'
)
# Agent-written absolute node/codex paths. Harbor Codex.run() invokes bare
# `codex` with no PATH prefix, so root must link these onto /usr/local/bin.
_BIN_MARKER = "/tmp/bencheval-codex-bins"
_FORWARDED_PROXY_ENVS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")


def _env_without_forwarded_proxy(env: dict[str, str] | None) -> dict[str, str]:
    cleaned = dict(env or {})
    for name in _FORWARDED_PROXY_ENVS:
        cleaned[name] = ""
    return cleaned


class CodexNpmInstall(Codex):
    """Codex agent that installs the CLI from npm on every Linux base image."""

    _INSTALL_CHECK_COMMAND = (
        f'export PATH="$HOME/.local/{_NODE_DIST}/bin:$HOME/.local/bin:$PATH"; '
        "command -v codex >/dev/null 2>&1"
    )
    _INSTALL_VERSION_COMMAND = _VERSION_COMMAND

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not self._version:
            raise ValueError(
                "CodexNpmInstall requires an explicit pinned version "
                "(version=...); an unpinned npm install is not reproducible",
            )

    def get_version_command(self) -> str | None:
        return _VERSION_COMMAND

    async def exec_as_agent(
        self,
        environment: BaseEnvironment,
        command: str,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_sec: int | None = None,
    ) -> object:
        # npm install needs the forwarded host proxy; Codex provider calls must
        # not. Live HTTP /v1/responses to 172.17.0.1:4011 was 403'd by CONNECT
        # through the corporate proxy (HTML body, not the role shim).
        if "codex exec" in command:
            env = _env_without_forwarded_proxy(env)
        return await super().exec_as_agent(
            environment,
            command,
            env=env,
            cwd=cwd,
            timeout_sec=timeout_sec,
        )

    def _build_register_mcp_servers_command(self) -> str | None:
        # Harbor Codex.run() appends only openai_base_url to $CODEX_HOME/config.toml
        # and then execs this hook. The evidence mount at /logs/agent/config.toml is
        # not Codex's config. A custom HTTP provider is required: the built-in
        # OpenAI provider ignores top-level supports_websockets=false and opens
        # ws:// through the forwarded corporate proxy.
        parent = super()._build_register_mcp_servers_command()
        extra = (
            'cat >"$CODEX_HOME/config.toml" <<TOML\n'
            'model_provider = "bytellm"\n'
            'openai_base_url = "${OPENAI_BASE_URL}"\n'
            "\n"
            "[model_providers.bytellm]\n"
            'name = "ByteLLM"\n'
            'base_url = "${OPENAI_BASE_URL}"\n'
            'env_key = "OPENAI_API_KEY"\n'
            "supports_websockets = false\n"
            'wire_api = "responses"\n'
            "TOML"
        )
        if parent:
            return f"{extra}\n{parent}"
        return extra

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
        version_spec = f"@{self._version}"
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
                f'  curl -fsSL {_NODE_TARBALL_URL} -o "$HOME/.local/{_NODE_DIST}.tar.gz" && '
                f'  echo "{_NODE_TARBALL_SHA256}  $HOME/.local/{_NODE_DIST}.tar.gz" | '
                "  sha256sum -c - && "
                f'  tar -xzf "$HOME/.local/{_NODE_DIST}.tar.gz" -C "$HOME/.local" && '
                f'  rm -f "$HOME/.local/{_NODE_DIST}.tar.gz"; '
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
                f"@openai/codex{version_spec}; "
                'mkdir -p "$HOME/.local/bin" && '
                'ln -sf "$(command -v node)" "$HOME/.local/bin/node" && '
                'ln -sf "$(command -v codex)" "$HOME/.local/bin/codex" && '
                '"$HOME/.local/bin/codex" --version && '
                f'printf "%s\\n%s\\n" "$(command -v node)" "$(command -v codex)" '
                f"> {_BIN_MARKER}"
            ),
        )
        # Harbor Codex.run() invokes bare `codex` as the agent user after
        # optional nvm and does not prepend $HOME/.local/bin. Link the pinned
        # binaries onto /usr/local/bin, which is on the default agent PATH.
        await self.exec_as_root(
            environment,
            command=(
                "set -euo pipefail; "
                "mkdir -p /usr/local/bin; "
                "node=''; "
                "codex=''; "
                f"if [[ -s {_BIN_MARKER} ]]; then "
                f'  node="$(sed -n "1p" {_BIN_MARKER})"; '
                f'  codex="$(sed -n "2p" {_BIN_MARKER})"; '
                "fi; "
                'if [[ ! -x "$node" || ! -x "$codex" ]]; then '
                "  for home in /home/* /root; do "
                f'    cand_node="$home/.local/{_NODE_DIST}/bin/node"; '
                f'    cand_codex="$home/.local/{_NODE_DIST}/bin/codex"; '
                '    if [[ -x "$cand_node" && -x "$cand_codex" ]]; then '
                '      node="$cand_node"; '
                '      codex="$cand_codex"; '
                "      break; "
                "    fi; "
                "  done; "
                "fi; "
                'if [[ ! -x "$node" || ! -x "$codex" ]]; then '
                '  echo "Error: pinned node/codex not found for /usr/local/bin" >&2; '
                "  exit 1; "
                "fi; "
                'ln -sfn "$node" /usr/local/bin/node; '
                'ln -sfn "$codex" /usr/local/bin/codex; '
                "/usr/local/bin/codex --version"
            ),
        )


__all__ = ["CodexNpmInstall"]

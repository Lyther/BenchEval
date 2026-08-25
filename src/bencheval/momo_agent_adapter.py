"""Back-compat re-exports for the cataloged, non-executable momo scaffold."""

from bencheval import external_agent_adapter as _ext

MOMO_ADAPTER_ID = "momo-agent"
MomoCliResult = _ext.ExternalAgentCliResult
MomoInstanceOutcome = _ext.ExternalAgentInstanceOutcome
MomoProcessRunner = _ext.ExternalAgentProcessRunner
MomoRunSummary = _ext.ExternalAgentRunSummary
build_momo_run_command = _ext.build_external_agent_command
execute_momo_agent_run = _ext.execute_external_agent_run
run_momo_instance = _ext.run_external_agent_instance

__all__ = [
    "MOMO_ADAPTER_ID",
    "MomoCliResult",
    "MomoInstanceOutcome",
    "MomoProcessRunner",
    "MomoRunSummary",
    "build_momo_run_command",
    "execute_momo_agent_run",
    "run_momo_instance",
]

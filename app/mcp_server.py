"""Read-only MCP server. A bot on the LAN can review the pump. It cannot write to it."""

import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations

from app.agent_data import AgentDataError
from app.agent_data import behavior as load_behavior
from app.agent_data import check_changes as load_check_changes
from app.agent_data import energy as load_energy
from app.agent_data import household_settings as load_household_settings
from app.agent_data import pump_status as load_pump_status

GUIDE = """You review a household heat pump from stored measurements. Do not invent measurements.
Call pump_status, behavior, energy, and household_settings. behavior and energy take hours from 1 to 168, or an ISO since and until. When hours, since, and until are omitted, the window is the advice window from App settings. A short cycle is a completed compressor run shorter than the threshold in the behavior result.
Suggest a change only for heating mode, hot water mode, hot water temperature, or the heating setpoint, and only when the figures give a concrete reason. Prefer no change. Do not suggest Second heatsource. Pass any proposal to check_changes before you show it.
These tools do not write to the controller. The owner confirms one change on the Pump settings page.
Over stdio, connected and polling describe this process, not the logger. Use latest.recorded_at and latest_age_s to see when a sample was last stored."""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)

mcp = MCPServer(
    name="Luxlogger",
    instructions=(
        "Read stored heat-pump measurements and check suggested changes to four household settings. "
        "Do not invent measurements. Nothing you call writes to the controller."
    ),
)


def _readonly(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AgentDataError as exc:
            return {"error": str(exc)}

    return wrapped


@mcp.tool(name="pump_status", annotations=READ_ONLY)
@_readonly
def pump_status() -> dict:
    """Latest connection, temperatures, operating mode, indoor reading, and equipment. Uses the last stored sample."""
    return load_pump_status()


@mcp.tool(name="behavior", annotations=READ_ONLY)
@_readonly
def behavior(hours: int | None = None, since: str | None = None, until: str | None = None) -> dict:
    """Compressor starts, short cycles, runtimes, and temperature spreads for a window. Does not return raw samples."""
    return load_behavior(hours=hours, since=since, until=until)


@mcp.tool(name="energy", annotations=READ_ONLY)
@_readonly
def energy(hours: int | None = None, since: str | None = None, until: str | None = None) -> dict:
    """Heat delivered and cost for a window, plus the lifetime heat-meter totals."""
    return load_energy(hours=hours, since=since, until=until)


@mcp.tool(name="household_settings", annotations=READ_ONLY)
@_readonly
def household_settings() -> dict:
    """The four settings a suggestion may change, with live values when the controller can be read. Does not write."""
    return load_household_settings()


@mcp.tool(name="check_changes", annotations=READ_ONLY)
@_readonly
def check_changes(changes: list[dict]) -> dict:
    """Check proposed setting changes. Returns what would be kept and why the rest were dropped. Does not write."""
    return load_check_changes(changes)


@mcp.resource(
    "luxlogger://guide",
    name="guide",
    description="How to review the heat pump, and which settings a suggestion may change.",
    mime_type="text/plain",
)
def guide() -> str:
    return GUIDE


@mcp.prompt(description="Review recent heat-pump behavior and suggest only the four household settings.")
def review_pump() -> str:
    return GUIDE


def http_app():
    """Streamable HTTP app mounted at /mcp. Trust matches the dashboard: the LAN, and no write."""
    return mcp.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

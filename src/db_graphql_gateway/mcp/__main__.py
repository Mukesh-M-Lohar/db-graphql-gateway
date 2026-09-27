"""
CLI entry-point for the sgql MCP server.

Usage:
    python -m db_graphql_gateway.mcp [OPTIONS]

This module is also exposed as the `sgql-mcp` script entry-point via pyproject.toml.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import click
import yaml

from db_graphql_gateway.mcp.config import MCPConfig
from db_graphql_gateway.mcp.server import build_mcp_server


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


@click.command("sgql-mcp")
@click.option(
    "--config",
    default="sgql-mcp.yaml",
    envvar="SGQL_MCP_CONFIG",
    show_default=True,
    help="Path to sgql-mcp.yaml configuration file.",
)
@click.option(
    "--scope",
    type=click.Choice(["read", "write"]),
    default=None,
    envvar="SGQL_MCP_SCOPE",
    help="Override scope from config (read|write). Default: read.",
)
@click.option(
    "--gateway-url",
    default=None,
    envvar="SGQL_GATEWAY_URL",
    help="Override gateway URL from config.",
)
@click.option(
    "--gateway-token",
    default=None,
    envvar="SGQL_GATEWAY_TOKEN",
    help="JWT Bearer token for the gateway (overrides config).",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    default=None,
    envvar="SGQL_MCP_TRANSPORT",
    help="Transport to use (stdio|sse|streamable-http). Default: stdio.",
)
@click.option(
    "--host",
    default=None,
    envvar="SGQL_MCP_HOST",
    help="Host for SSE/HTTP transport (default 127.0.0.1).",
)
@click.option(
    "--port",
    default=None,
    type=int,
    envvar="SGQL_MCP_PORT",
    help="Port for SSE/HTTP transport (default 8765).",
)
@click.option(
    "--log-level",
    default="INFO",
    envvar="SGQL_MCP_LOG_LEVEL",
    help="Logging level (DEBUG|INFO|WARNING|ERROR).",
)
def main(
    config: str,
    scope: str | None,
    gateway_url: str | None,
    gateway_token: str | None,
    transport: str | None,
    host: str | None,
    port: int | None,
    log_level: str,
) -> None:
    """Run the sgql MCP server.

    Connects to the existing sgql gateway and exposes it to MCP clients
    (Claude Desktop, Claude Code, Cursor, etc.) via stdio or HTTP transport.
    """
    _setup_logging(log_level)
    logger = logging.getLogger("sgql.mcp.cli")

    # ── Load base config ───────────────────────────────────────────────────
    cfg_path = Path(config)
    cfg_data: dict[str, Any] = {}
    if cfg_path.exists():
        with cfg_path.open() as f:
            cfg_data = yaml.safe_load(f) or {}
        logger.info("Loaded MCP config from %s", cfg_path)
    else:
        logger.info("No %s found — using defaults / CLI flags / env vars", cfg_path)

    # ── Apply CLI / env overrides ──────────────────────────────────────────
    if scope is not None:
        cfg_data["scope"] = scope
    if gateway_url is not None:
        cfg_data["gateway_url"] = gateway_url
    if gateway_token is not None:
        cfg_data["gateway_token"] = gateway_token
    if transport is not None:
        cfg_data["transport"] = transport
    if host is not None:
        cfg_data["host"] = host
    if port is not None:
        cfg_data["port"] = port

    # Fall back to environment variable for token if not yet set
    if not cfg_data.get("gateway_token"):
        env_token = os.environ.get("SGQL_GATEWAY_TOKEN")
        if env_token:
            cfg_data["gateway_token"] = env_token

    mcp_config = MCPConfig(**cfg_data)

    logger.info(
        "Starting sgql MCP server | scope=%s transport=%s gateway=%s",
        mcp_config.scope,
        mcp_config.transport,
        mcp_config.gateway_url,
    )

    mcp_server = build_mcp_server(mcp_config)

    # ── Start the server ───────────────────────────────────────────────────
    match mcp_config.transport:
        case "stdio":
            mcp_server.run("stdio")
        case "sse":
            mcp_server.run(
                "sse",
                host=mcp_config.host,
                port=mcp_config.port,
            )
        case "streamable-http":
            mcp_server.run(
                "streamable-http",
                host=mcp_config.host,
                port=mcp_config.port,
            )
        case _:
            click.echo(f"Unknown transport: {mcp_config.transport}", err=True)
            sys.exit(1)


if __name__ == "__main__":
    main()

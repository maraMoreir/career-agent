"""Compatibilidade entre versoes do SDK MCP para Python.

O SDK renomeou a classe de servidor de alto nivel:

    mcp >= 2.0 : `from mcp.server import MCPServer`
    mcp <  2.0 : `from mcp.server.fastmcp import FastMCP`

A API usada por este projeto e identica nas duas (`Servidor(nome)`,
`@servidor.tool()`, `servidor.run()` com stdio por padrao), entao um unico
ponto de importacao resolve. Sem isso, atualizar o SDK quebraria os tres
servidores de uma vez.
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_server", "SDK_FLAVOR"]

try:  # SDK 2.x
    from mcp.server import MCPServer as _ServerClass

    SDK_FLAVOR = "mcp>=2.0 (MCPServer)"
except ImportError:  # pragma: no cover - SDK 1.x
    try:
        from mcp.server.fastmcp import FastMCP as _ServerClass

        SDK_FLAVOR = "mcp<2.0 (FastMCP)"
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "SDK MCP nao encontrado. Rode scripts/install.ps1 ou:\n"
            "  C:\\career-agent\\.venv\\Scripts\\python.exe -m pip install mcp"
        ) from exc


def build_server(name: str, instructions: str | None = None) -> Any:
    """Cria o servidor MCP de alto nivel da versao de SDK instalada."""
    try:
        return _ServerClass(name, instructions=instructions)
    except TypeError:  # versao antiga sem `instructions`
        return _ServerClass(name)

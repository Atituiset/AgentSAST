# src/agentsast/layer2/mcp_lsp_backend.py
"""McpLspBackend：程序化直连 mcp-language-server(clangd)的语义级 caller/callee 后端。

组合 McpLspConnection(共享自 _mcp_client)，仅实现 ProgramUnderstandingBackend
到 mcp callers/callees tool 的映射。行为与重构前等价。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..layer1.models import Location
from ._mcp_client import McpLspConnection, parse_refs
from .backend import FunctionRef

logger = logging.getLogger(__name__)


class McpLspBackend:
    """clangd(MCP)后端。需要 mcp SDK + mcp-language-server 二进制 + clangd + compile_commands。"""

    def __init__(
        self,
        workspace: Path | None = None,
        compile_commands_dir: Path | None = None,
        mcp_binary: str = "mcp-language-server",
        lsp: str = "clangd",
        connection: McpLspConnection | None = None,
    ):
        self._conn = connection or McpLspConnection(
            workspace, compile_commands_dir, mcp_binary, lsp
        )

    def is_available(self) -> bool:
        return self._conn.is_available()

    def _guard(self) -> bool:
        if not self.is_available():
            logger.warning("McpLspBackend unavailable (mcp SDK not installed)")
            return False
        return True

    def find_callers(
        self, func_name, loc: Location, project_root=None
    ) -> list[FunctionRef]:
        if not self._guard():
            return []
        try:
            text = self._conn.call_tool(
                "callers",
                {
                    "symbolName": func_name,
                    "filePath": str(loc.file),
                    "line": loc.line,
                    "column": loc.col or 1,
                },
            )
        except Exception:
            logger.exception("McpLspBackend.find_callers failed")
            return []
        return parse_refs(text, default_name=func_name)

    def find_callees(self, func_name, loc: Location) -> list[FunctionRef]:
        if not self._guard():
            return []
        try:
            text = self._conn.call_tool(
                "callees",
                {
                    "symbolName": func_name,
                    "filePath": str(loc.file),
                    "line": loc.line,
                    "column": loc.col or 1,
                },
            )
        except Exception:
            logger.exception("McpLspBackend.find_callees failed")
            return []
        return parse_refs(text, default_name=func_name)

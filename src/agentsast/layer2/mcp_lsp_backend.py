# src/agentsast/layer2/mcp_lsp_backend.py
"""McpLspBackend：通过 MCP 协议调用 mcp-language-server(clangd)，
提供语义级 caller/callee。mcp 为可选依赖；未安装时 is_available() 返回 False。

AgentSAST 是同步 CLI，MCP 是 async，故 _call_tool_async 为内部 async 方法，
公开方法用 asyncio.run 包装（每次调用建立新 session；MVP 可接受，mcp-lsp 非高频）。"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from ..layer1.models import Location
from .backend import FunctionRef

logger = logging.getLogger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    IS_AVAILABLE = True
except ImportError:
    IS_AVAILABLE = False

# mcp-language-server 输出里的位置行，形如 "  /path/file.c:18:1"（可选列号、可选空白）
_LOC_RE = re.compile(r"^(.*?\.\w+):(\d+)(?::(\d+))?\s*$")


class McpLspBackend:
    """clangd(MCP)后端。需要 mcp SDK + mcp-language-server 二进制 + clangd + compile_commands。"""

    def __init__(
        self,
        workspace: Path | None = None,
        compile_commands_dir: Path | None = None,
        mcp_binary: str = "mcp-language-server",
        lsp: str = "clangd",
    ):
        self.workspace = workspace
        self.compile_commands_dir = compile_commands_dir
        self.mcp_binary = mcp_binary
        self.lsp = lsp

    def is_available(self) -> bool:
        return IS_AVAILABLE

    def _server_params(self):
        args = []
        if self.workspace:
            args += ["--workspace", str(self.workspace)]
        args += ["--lsp", self.lsp, "--"]
        if self.compile_commands_dir:
            args += [f"--compile-commands-dir={self.compile_commands_dir}"]
        return StdioServerParameters(command=self.mcp_binary, args=args)

    async def _call_tool_async(self, tool: str, args: dict) -> str:
        """调用 mcp-language-server 的一个 tool，返回其文本输出。"""
        async with stdio_client(self._server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
        # result.content 是 content blocks 列表，取文本拼接
        texts = []
        for block in getattr(result, "content", []) or []:
            t = getattr(block, "text", None)
            if t:
                texts.append(t)
        return "\n".join(texts)

    def _call_tool(self, tool: str, args: dict) -> str:
        return asyncio.run(self._call_tool_async(tool, args))

    @staticmethod
    def _parse_refs(text: str, default_name: str) -> list[FunctionRef]:
        """解析 mcp-language-server 文本输出为 FunctionRef 列表。

        输出格式（MVP 假设）：可能以 caller/callee 函数名作为“标题行”，
        随后是若干 "  path:line:col" 位置行；位置行被解析为 Location。
        非位置行的纯文本若形如标识符，作为其后位置行的函数名，否则回退 default_name。
        """
        refs: list[FunctionRef] = []
        pending_name: str | None = None
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            m = _LOC_RE.match(line)
            if m:
                file = Path(m.group(1).strip())
                line_no = int(m.group(2))
                refs.append(FunctionRef(
                    name=pending_name or default_name,
                    location=Location(file=file, line=line_no, end_line=line_no),
                ))
                pending_name = None
            else:
                # 非位置行：视为潜在函数名（去掉前后空白与常见符号）
                cand = line.strip("`*\"' \t")
                if cand and not cand.isdigit():
                    pending_name = cand
        return refs

    def find_callers(self, func_name, loc, project_root=None) -> list[FunctionRef]:
        if not self.is_available():
            logger.warning("McpLspBackend unavailable (mcp SDK not installed)")
            return []
        try:
            text = self._call_tool("callers", {
                "symbolName": func_name,
                "filePath": str(loc.file), "line": loc.line, "column": loc.col or 1,
            })
        except Exception:
            logger.exception("McpLspBackend.find_callers failed")
            return []
        return self._parse_refs(text, default_name=func_name)

    def find_callees(self, func_name, loc) -> list[FunctionRef]:
        if not self.is_available():
            return []
        try:
            text = self._call_tool("callees", {
                "symbolName": func_name,
                "filePath": str(loc.file), "line": loc.line, "column": loc.col or 1,
            })
        except Exception:
            logger.exception("McpLspBackend.find_callees failed")
            return []
        return self._parse_refs(text, default_name=func_name)

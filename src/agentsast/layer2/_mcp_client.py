# src/agentsast/layer2/_mcp_client.py
"""共享 mcp-language-server 连接与位置解析。

McpLspBackend(程序化直连)与 AgentBackend(LLM 调度 + fallback)共用此模块，
消除 async→sync 与 parse_refs 的重复。mcp 为可选依赖;未安装时 IS_AVAILABLE=False。
"""
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

# mcp-language-server 输出里的位置行，形如 "  /path/file.c:18:1"
_LOC_RE = re.compile(r"^(.*?\.\w+):(\d+)(?::(\d+))?\s*$")


def parse_refs(text: str, default_name: str) -> list[FunctionRef]:
    """解析 mcp-language-server 文本输出为 FunctionRef 列表。

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
            refs.append(
                FunctionRef(
                    name=pending_name or default_name,
                    location=Location(file=file, line=line_no, end_line=line_no),
                )
            )
            pending_name = None
        else:
            cand = line.strip("`*\"' \t")
            if cand and not cand.isdigit():
                pending_name = cand
    return refs


class McpLspConnection:
    """持有 mcp-language-server 连接参数，封装 async→sync 的 call_tool。"""

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

    def server_params(self) -> StdioServerParameters:
        args: list[str] = []
        if self.workspace:
            args += ["--workspace", str(self.workspace)]
        args += ["--lsp", self.lsp, "--"]
        if self.compile_commands_dir:
            args += [f"--compile-commands-dir={self.compile_commands_dir}"]
        return StdioServerParameters(command=self.mcp_binary, args=args)

    async def _call_tool_async(self, tool: str, args: dict) -> str:
        async with stdio_client(self.server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
        texts: list[str] = []
        for block in getattr(result, "content", []) or []:
            t = getattr(block, "text", None)
            if t:
                texts.append(t)
        return "\n".join(texts)

    def call_tool(self, tool: str, args: dict) -> str:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._call_tool_async(tool, args))
        # 已在 event loop 内：用独立线程跑协程，避免阻塞 loop
        return asyncio.run_coroutine_threadsafe(
            self._call_tool_async(tool, args), loop
        ).result()

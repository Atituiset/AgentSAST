# src/agentsast/layer2/agent_backend.py
"""AgentBackend：LLM agent 驱动的程序理解后端。

把 mcp-language-server 的 callers/callees/definition + read_source 当作 LLM 的工具，
由模型自主调度回答 caller/callee 查询，提升复杂路径召回。

AgentBackend 是 McpLspBackend 的超集：LLM 是增强层，--skip-llm/无 key/LLM 失败时
退化到程序化 McpLsp 查询(D4/D7)。AgentSAST 同步 CLI，openai SDK 同步，无需 async 桥接。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from openai import OpenAI

from ..layer1.models import Location
from ._mcp_client import McpLspConnection
from .backend import FunctionRef
from .mcp_lsp_backend import McpLspBackend

logger = logging.getLogger(__name__)


class AgentBackendError(Exception):
    """AgentBackend loop 内部错误，触发 fallback。"""


class AgentBackend:
    """LLM agent 驱动的 caller/callee 后端。

    需要 mcp SDK + mcp-language-server + clangd + compile_commands（同 McpLspBackend），
    额外需要 LLM 可用；否则自动退化为程序化 McpLsp 行为。
    """

    def __init__(
        self,
        workspace: Path | None = None,
        compile_commands_dir: Path | None = None,
        llm_model: str = "gpt-4o",
        llm_api_key: str | None = None,
        llm_base_url: str | None = None,
        skip_llm: bool = False,
        max_iters: int = 8,
        mcp_binary: str = "mcp-language-server",
        lsp: str = "clangd",
    ):
        self._conn = McpLspConnection(workspace, compile_commands_dir, mcp_binary, lsp)
        # 复用同一连接的程序化后端，专司 fallback + skip_llm 路径
        self._direct = McpLspBackend(connection=self._conn)
        # key 解析对齐 LLMJudge(judge.py:30-31)：显式优先，回退环境变量
        key = llm_api_key or os.environ.get("OPENAI_API_KEY", "")
        url = llm_base_url or os.environ.get("OPENAI_BASE_URL", None)
        self._skip_llm = skip_llm or not key
        self._llm_model = llm_model
        self._max_iters = max_iters
        self._client: OpenAI | None = None
        if not self._skip_llm:
            client_kwargs: dict = {"api_key": key}
            if url:
                client_kwargs["base_url"] = url
            self._client = OpenAI(**client_kwargs)

    def is_available(self) -> bool:
        return self._conn.is_available()

    def find_callers(
        self, func_name, loc: Location, project_root=None
    ) -> list[FunctionRef]:
        if not self.is_available():
            logger.warning("AgentBackend unavailable (mcp SDK not installed)")
            return []
        if self._skip_llm:
            return self._direct.find_callers(func_name, loc, project_root)
        # Task 3 替换为真实 agent loop；此处临时走程序化以保证每步可运行
        return self._direct.find_callers(func_name, loc, project_root)

    def find_callees(self, func_name, loc: Location) -> list[FunctionRef]:
        if not self.is_available():
            logger.warning("AgentBackend unavailable (mcp SDK not installed)")
            return []
        if self._skip_llm:
            return self._direct.find_callees(func_name, loc)
        return self._direct.find_callees(func_name, loc)

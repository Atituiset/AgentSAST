# src/agentsast/layer2/agent_backend.py
"""AgentBackend：LLM agent 驱动的程序理解后端。

把 mcp-language-server 的 callers/callees/definition + read_source 当作 LLM 的工具，
由模型自主调度回答 caller/callee 查询，提升复杂路径召回。

AgentBackend 是 McpLspBackend 的超集：LLM 是增强层，--skip-llm/无 key/LLM 失败时
退化到程序化 McpLsp 查询(D4/D7)。AgentSAST 同步 CLI，openai SDK 同步，无需 async 桥接。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

from ..layer1.models import Location
from ._mcp_client import McpLspConnection
from .backend import FunctionRef
from .mcp_lsp_backend import McpLspBackend

logger = logging.getLogger(__name__)


class AgentBackendError(Exception):
    """AgentBackend loop 内部错误，触发 fallback。"""


class AgentLoopExhausted(AgentBackendError):
    """agent loop 触顶 max_iters 未收敛。"""


_SYSTEM_PROMPT = (
    "你是 C/C++ 调用图分析助手。给定一个目标函数，用提供的工具"
    "(callers/callees/definition/read_source)查清它的调用关系。"
    "可以多次调用工具、读源码判断间接调用。完成后，只输出一个 JSON 数组，"
    "不要任何解释文字："
    " [{\"name\": <函数名>, \"file\": <绝对路径>, \"line\": <行号>}, ...]。"
    "若没有任何结果，输出 []。"
)

# OpenAI function-calling 工具定义
_TOOLS: list[ChatCompletionToolParam] = [
    {"type": "function", "function": {
        "name": "callers", "description": "查找谁调用了指定函数",
        "parameters": {"type": "object", "properties": {
            "symbolName": {"type": "string"}, "filePath": {"type": "string"},
            "line": {"type": "integer"}, "column": {"type": "integer"}},
            "required": ["symbolName", "filePath", "line", "column"]}}},
    {"type": "function", "function": {
        "name": "callees", "description": "查找指定函数调用了哪些函数",
        "parameters": {"type": "object", "properties": {
            "symbolName": {"type": "string"}, "filePath": {"type": "string"},
            "line": {"type": "integer"}, "column": {"type": "integer"}},
            "required": ["symbolName", "filePath", "line", "column"]}}},
    {"type": "function", "function": {
        "name": "definition", "description": "跳转到符号定义",
        "parameters": {"type": "object", "properties": {
            "symbolName": {"type": "string"}, "filePath": {"type": "string"},
            "line": {"type": "integer"}, "column": {"type": "integer"}},
            "required": ["symbolName", "filePath", "line", "column"]}}},
    {"type": "function", "function": {
        "name": "read_source", "description": "读取指定文件的行范围源码",
        "parameters": {"type": "object", "properties": {
            "filePath": {"type": "string"},
            "startLine": {"type": "integer"}, "endLine": {"type": "integer"}},
            "required": ["filePath", "startLine", "endLine"]}}},
]


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
        return self._agent_query("callers", func_name, loc)

    def find_callees(self, func_name, loc: Location) -> list[FunctionRef]:
        if not self.is_available():
            logger.warning("AgentBackend unavailable (mcp SDK not installed)")
            return []
        if self._skip_llm:
            return self._direct.find_callees(func_name, loc)
        return self._agent_query("callees", func_name, loc)

    def _agent_query(
        self, query_kind: str, func_name: str, loc: Location
    ) -> list[FunctionRef]:
        """tool-calling loop：让 LLM 用工具查清 callers/callees，返回 FunctionRef 列表。"""
        # 仅在 not self._skip_llm 时进入，_client 必已构造
        assert self._client is not None
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"找出函数 {func_name}（位置 {loc.file}:{loc.line}:{loc.col or 1}）"
                    f"的所有 {query_kind}。"
                ),
            },
        ]
        for _ in range(self._max_iters):
            resp = self._client.chat.completions.create(
                model=self._llm_model,
                messages=messages,
                tools=_TOOLS,
                temperature=0,
            )
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                return self._parse_final(msg.content or "", func_name)
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or "{}",
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    content = self._dispatch(name, args)
                except Exception as e:  # 单 tool 异常：回填错误让 agent 自纠
                    logger.warning("tool %s failed: %s", name, e)
                    content = f"tool error: {e}"
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": content}
                )
        raise AgentLoopExhausted(f"max_iters={self._max_iters} reached")

    def _dispatch(self, name: str, args: dict) -> str:
        if name in ("callers", "callees", "definition"):
            return self._conn.call_tool(name, args)
        if name == "read_source":
            return self._read_source(
                args.get("filePath", ""),
                int(args.get("startLine", 1)),
                int(args.get("endLine", 1)),
            )
        return f"unknown tool: {name}"

    @staticmethod
    def _read_source(file_path: str, start_line: int, end_line: int) -> str:
        p = Path(file_path)
        if not p.is_file():
            return f"file not found: {file_path}"
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError as e:
            return f"read error: {e}"
        start = max(1, start_line)
        end = min(len(lines), end_line)
        if start > end:
            return "empty range"
        return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))

    @staticmethod
    def _parse_final(content: str, default_name: str) -> list[FunctionRef]:
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AgentBackendError(f"final JSON parse failed: {e}")
        if not isinstance(data, list):
            raise AgentBackendError("final JSON is not a list")
        refs: list[FunctionRef] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            file = item.get("file")
            line = item.get("line")
            if not file or not line:
                continue
            refs.append(
                FunctionRef(
                    name=item.get("name", default_name),
                    location=Location(
                        file=Path(file), line=int(line), end_line=int(line)
                    ),
                )
            )
        return refs

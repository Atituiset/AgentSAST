# Layer2 AgentBackend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Layer2 新增第三档后端 `AgentBackend`(`--l2-backend mcp-lsp-agent`),用 LLM tool-calling loop 驱动 mcp-language-server 查 caller/callee,LLM 不可用/失败时 fallback 到程序化查询。

**Architecture:** `ProgramUnderstandingBackend` 协议与 `Slicer` 零改动。先提取共享 `_mcp_client.py`(D6,行为等价重构),`McpLspBackend` 改组合;再新增 `AgentBackend` = `McpLspBackend` 超集 + LLM 增强层(openai tool-calling,复用 Layer3 client 构造)。CLI/pipeline 加 `mcp-lsp-agent` 档。

**Tech Stack:** Python 3.10+、`openai` SDK(已依赖)、`mcp` SDK(optional,`[layer2-mcp]`)、pytest、click。

**Spec:** `docs/superpowers/specs/2026-06-25-layer2-agent-backend-design.md`

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `src/agentsast/layer2/_mcp_client.py` | 共享:`IS_AVAILABLE`、`McpLspConnection`(server_params/call_tool,async→sync)、`parse_refs` | Create |
| `src/agentsast/layer2/mcp_lsp_backend.py` | 薄壳:组合 `McpLspConnection`,实现 Protocol | Modify(行为等价) |
| `src/agentsast/layer2/agent_backend.py` | `AgentBackend`:LLM loop + 工具分发 + fallback | Create |
| `src/agentsast/cli.py:108` | `--l2-backend` Choice 加 `mcp-lsp-agent` | Modify |
| `src/agentsast/pipeline/engine.py:88-100` | backend 构造加 `mcp-lsp-agent` 分支 | Modify |
| `tests/layer2/test_mcp_lsp_backend.py` | mock 目标改为 `McpLspConnection.call_tool` | Modify(断言不变) |
| `tests/layer2/test_agent_backend.py` | `AgentBackend` 全套测试 | Create |
| `tests/pipeline/test_engine_l2_backend.py` | engine 按 `l2_backend` 构造正确后端 | Create |
| `docs/ARCHITECTURE.md` | §3.2 加 `mcp-lsp-agent` 说明 | Modify |

---

## Task 1: 提取共享 `_mcp_client.py` + `McpLspBackend` 改组合(D6,行为等价)

**Files:**
- Create: `src/agentsast/layer2/_mcp_client.py`
- Modify: `src/agentsast/layer2/mcp_lsp_backend.py`(整文件重写为薄壳)
- Test: `tests/layer2/test_mcp_lsp_backend.py`(改 mock 目标)

- [ ] **Step 1: 跑现有 layer2 测试,确认基线绿**

Run: `pytest tests/layer2/test_mcp_lsp_backend.py -v`
Expected: 3 passed

- [ ] **Step 2: 创建 `src/agentsast/layer2/_mcp_client.py`**

```python
# src/agentsast/layer2/_mcp_client.py
"""共享 mcp-language-server 连接与位置解析。

McpLspBackend(程序化直连)与 AgentBackend(LLM 调度 + fallback)共用此模块,
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
```

- [ ] **Step 3: 重写 `src/agentsast/layer2/mcp_lsp_backend.py` 为薄壳**

```python
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
```

- [ ] **Step 4: 更新 `tests/layer2/test_mcp_lsp_backend.py` 的 mock 目标**

整文件替换为:

```python
# tests/layer2/test_mcp_lsp_backend.py
"""McpLspBackend 测试：mock McpLspConnection.call_tool，不依赖真实 mcp/clangd。"""
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.models import Location


def test_is_available_reflects_mcp_import(monkeypatch):
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.mcp_lsp_backend import McpLspBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", False)
    assert McpLspBackend().is_available() is False


def test_find_callers_parses_mocked_tool_result(monkeypatch):
    from agentsast.layer2.mcp_lsp_backend import McpLspBackend

    b = McpLspBackend()
    # mock 同步 call_tool：返回 callers tool 的文本（标题行 + 每行一个 "file:line"）
    monkeypatch.setattr(
        b._conn,
        "call_tool",
        lambda tool, args: "handle_connection\n  /src/main.c:18:1\n  /src/other.c:5:1",
    )
    refs = b.find_callers("process_buffer", Location(file=Path("/src/main.c"), line=8))
    names = [r.name for r in refs]
    assert "handle_connection" in names
    assert all(r.location.line > 0 for r in refs)


def test_find_callers_empty_when_no_result(monkeypatch):
    from agentsast.layer2.mcp_lsp_backend import McpLspBackend

    b = McpLspBackend()
    monkeypatch.setattr(b._conn, "call_tool", lambda tool, args: "")
    assert b.find_callers("x", Location(file=Path("a.c"), line=1)) == []
```

- [ ] **Step 5: 跑测试确认行为等价**

Run: `pytest tests/layer2/test_mcp_lsp_backend.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/agentsast/layer2/_mcp_client.py src/agentsast/layer2/mcp_lsp_backend.py tests/layer2/test_mcp_lsp_backend.py
git commit -m "refactor(layer2): extract _mcp_client shared helper (McpLspBackend composes, behavior-equivalent)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: `AgentBackend` 骨架 + `is_available` + `skip_llm` 程序化路径(D7)

**Files:**
- Create: `src/agentsast/layer2/agent_backend.py`
- Test: `tests/layer2/test_agent_backend.py`

- [ ] **Step 1: 写失败测试(仅 skip_llm + unavailable 路径)**

创建 `tests/layer2/test_agent_backend.py`:

```python
# tests/layer2/test_agent_backend.py
"""AgentBackend 测试：mock LLM client 与 McpLspConnection，不依赖真实 LLM/clangd。"""
from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock

from agentsast.layer1.models import Location


def _loc():
    return Location(file=Path("/src/main.c"), line=8, col=1)


def test_unavailable_returns_empty(monkeypatch):
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", False)
    b = AgentBackend(llm_api_key="sk-test")
    assert b.is_available() is False
    assert b.find_callers("process_buffer", _loc()) == []


def test_skip_llm_uses_programmatic_direct(monkeypatch):
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)
    b = AgentBackend(skip_llm=True)
    # 无 key/skip_llm 时不应构造 LLM client
    assert b._skip_llm is True
    assert b._client is None
    # 直接走程序化 direct
    monkeypatch.setattr(
        b._direct._conn,
        "call_tool",
        lambda tool, args: "caller_a\n  /src/main.c:18:1",
    )
    refs = b.find_callers("process_buffer", _loc())
    assert [r.name for r in refs] == ["caller_a"]


def test_no_api_key_implies_skip_llm(monkeypatch):
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    b = AgentBackend()  # 无 key、无 env
    assert b._skip_llm is True
    assert b._client is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/layer2/test_agent_backend.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'agentsast.layer2.agent_backend'`

- [ ] **Step 3: 创建 `src/agentsast/layer2/agent_backend.py`(骨架版)**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/layer2/test_agent_backend.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer2/agent_backend.py tests/layer2/test_agent_backend.py
git commit -m "feat(layer2): AgentBackend skeleton (is_available + skip_llm programmatic path)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: tool-calling loop 成功路径 + 工具分发(D2/D5)

**Files:**
- Modify: `src/agentsast/layer2/agent_backend.py`(替换 find_callers/find_callees 的非 skip_llm 分支为真实 loop)
- Test: `tests/layer2/test_agent_backend.py`(追加 loop 测试)

- [ ] **Step 1: 追加失败测试(loop 成功 / read_source / tool 自纠)**

在 `tests/layer2/test_agent_backend.py` 末尾追加:

```python
def _tc(name, args, tcid="t1"):
    """构造一个 openai tool_call 形态的对象（兼容 SimpleNamespace fake）。"""
    return types.SimpleNamespace(
        id=tcid,
        function=types.SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _resp(content=None, tool_calls=None):
    """构造一个 openai chat completion response 形态的对象。"""
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


def _backend_with_fake_llm(monkeypatch, responses, key="sk-test"):
    """构造 AgentBackend，其 LLM create() 依次返回 responses（list）。"""
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)  # 默认 mcp 可用，走到 loop
    b = AgentBackend(llm_api_key=key)
    it = iter(responses)
    b._client.chat.completions.create = MagicMock(side_effect=lambda **kw: next(it))
    return b


def test_loop_success_calls_tool_then_parses_json(monkeypatch):
    # 第 1 轮：LLM 调 callers 工具；第 2 轮：LLM 给最终 JSON
    responses = [
        _resp(tool_calls=[_tc("callers", {"symbolName": "process_buffer",
                                          "filePath": "/src/main.c", "line": 8, "column": 1})]),
        _resp(content='[{"name": "caller_a", "file": "/src/main.c", "line": 18}]'),
    ]
    b = _backend_with_fake_llm(monkeypatch, responses)
    monkeypatch.setattr(
        b._conn, "call_tool", lambda tool, args: "caller_a\n  /src/main.c:18:1"
    )
    refs = b.find_callers("process_buffer", _loc())
    assert [r.name for r in refs] == ["caller_a"]
    assert refs[0].location.line == 18


def test_read_source_tool_reads_file_range(tmp_path, monkeypatch):
    f = tmp_path / "main.c"
    f.write_text("line1\nline2\nline3\nline4\n")
    responses = [
        _resp(tool_calls=[_tc("read_source", {"filePath": str(f), "startLine": 2, "endLine": 3})]),
        _resp(content="[]"),
    ]
    b = _backend_with_fake_llm(monkeypatch, responses)
    captured: list[str] = []
    # 捕获回填给 LLM 的 tool message 内容
    real_dispatch = b._dispatch
    monkeypatch.setattr(b, "_dispatch", lambda name, args, *a, **k: (
        captured.append(real_dispatch(name, args, *a, **k)) or captured[-1]))
    b.find_callers("process_buffer", _loc())
    assert any("2: line2" in c and "3: line3" in c for c in captured)


def test_tool_exception_self_corrects(monkeypatch):
    # 第 1 轮 callers 工具抛异常 → 回填错误；第 2 轮 LLM 给最终 JSON
    responses = [
        _resp(tool_calls=[_tc("callers", {"symbolName": "x", "filePath": "/a.c", "line": 1, "column": 1})]),
        _resp(content="[]"),
    ]
    b = _backend_with_fake_llm(monkeypatch, responses)

    def boom(tool, args):
        raise RuntimeError("mcp timeout")

    monkeypatch.setattr(b._conn, "call_tool", boom)
    # 不应抛出，agent 收到错误后正常返回 []
    assert b.find_callers("x", _loc()) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/layer2/test_agent_backend.py -v`
Expected: 3 个新测试 FAIL（`_dispatch` 不存在 / loop 未实现），前 3 个仍 PASS

- [ ] **Step 3: 实现 loop + 工具分发 + 解析**

在 `src/agentsast/layer2/agent_backend.py` 中:

(a) 文件顶部 import 区追加:
```python
import json
```

(b) 在 `class AgentBackendError` 之后、`class AgentBackend` 之前插入常量与异常:
```python
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
_TOOLS = [
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
```

(c) 替换 `find_callers` / `find_callees` 的非 skip_llm 分支(去掉 Task 2 的临时 direct 调用),并新增 loop 相关方法。将 `find_callers`、`find_callees` 改为:

```python
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
```

并在类内追加(loop + dispatch + read_source + parse_final):

```python
    def _agent_query(
        self, query_kind: str, func_name: str, loc: Location
    ) -> list[FunctionRef]:
        """tool-calling loop：让 LLM 用工具查清 callers/callees，返回 FunctionRef 列表。"""
        messages: list[dict] = [
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/layer2/test_agent_backend.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer2/agent_backend.py tests/layer2/test_agent_backend.py
git commit -m "feat(layer2): AgentBackend tool-calling loop + tool dispatch (callers/callees/definition/read_source)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: fallback 到程序化查询(D4)

**Files:**
- Modify: `src/agentsast/layer2/agent_backend.py`(find_callers/find_callees 包 try/except)
- Test: `tests/layer2/test_agent_backend.py`(追加 fallback 测试)

- [ ] **Step 1: 追加失败测试**

在 `tests/layer2/test_agent_backend.py` 末尾追加:

```python
def test_fallback_on_llm_error(monkeypatch):
    # LLM create 抛异常 → fallback 到程序化 direct
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)
    b = AgentBackend(llm_api_key="sk-test")
    b._client.chat.completions.create = MagicMock(side_effect=RuntimeError("503"))
    monkeypatch.setattr(
        b._direct._conn,
        "call_tool",
        lambda tool, args: "caller_a\n  /src/main.c:18:1",
    )
    refs = b.find_callers("process_buffer", _loc())
    assert [r.name for r in refs] == ["caller_a"]  # 来自 fallback direct


def test_fallback_on_max_iters(monkeypatch):
    # LLM 每轮都只调工具、永不收敛 → 触顶 max_iters → fallback
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)
    b = AgentBackend(llm_api_key="sk-test", max_iters=2)
    loop_resp = _resp(tool_calls=[_tc("callers", {"symbolName": "x", "filePath": "/a.c", "line": 1, "column": 1})])
    b._client.chat.completions.create = MagicMock(return_value=loop_resp)
    monkeypatch.setattr(
        b._direct._conn,
        "call_tool",
        lambda tool, args: "caller_b\n  /a.c:5:1",
    )
    refs = b.find_callers("x", _loc())
    assert [r.name for r in refs] == ["caller_b"]


def test_fallback_on_parse_failure(monkeypatch):
    # LLM 最终返回非 JSON → fallback
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)
    b = AgentBackend(llm_api_key="sk-test")
    b._client.chat.completions.create = MagicMock(return_value=_resp(content="不是 JSON"))
    monkeypatch.setattr(
        b._direct._conn,
        "call_tool",
        lambda tool, args: "caller_c\n  /a.c:9:1",
    )
    refs = b.find_callers("x", _loc())
    assert [r.name for r in refs] == ["caller_c"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/layer2/test_agent_backend.py -v`
Expected: 3 个新测试 FAIL（异常未捕获、向上抛出）

- [ ] **Step 3: 给 `find_callers` / `find_callees` 包 fallback try/except**

将 Task 3 写入的 `find_callers` / `find_callees` 改为:

```python
    def find_callers(
        self, func_name, loc: Location, project_root=None
    ) -> list[FunctionRef]:
        if not self.is_available():
            logger.warning("AgentBackend unavailable (mcp SDK not installed)")
            return []
        if self._skip_llm:
            return self._direct.find_callers(func_name, loc, project_root)
        try:
            return self._agent_query("callers", func_name, loc)
        except Exception:
            logger.exception(
                "AgentBackend.find_callers failed, falling back to programmatic"
            )
            return self._direct.find_callers(func_name, loc, project_root)

    def find_callees(self, func_name, loc: Location) -> list[FunctionRef]:
        if not self.is_available():
            logger.warning("AgentBackend unavailable (mcp SDK not installed)")
            return []
        if self._skip_llm:
            return self._direct.find_callees(func_name, loc)
        try:
            return self._agent_query("callees", func_name, loc)
        except Exception:
            logger.exception(
                "AgentBackend.find_callees failed, falling back to programmatic"
            )
            return self._direct.find_callees(func_name, loc)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/layer2/test_agent_backend.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer2/agent_backend.py tests/layer2/test_agent_backend.py
git commit -m "feat(layer2): AgentBackend fallback to programmatic McpLsp on LLM failure/exhaustion/parse-error" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: CLI + pipeline 接入 `mcp-lsp-agent`(§8)

**Files:**
- Modify: `src/agentsast/cli.py:108`(`--l2-backend` Choice)
- Modify: `src/agentsast/pipeline/engine.py:88-100`(backend 构造分支)
- Test: `tests/pipeline/test_engine_l2_backend.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/pipeline/test_engine_l2_backend.py`:

```python
# tests/pipeline/test_engine_l2_backend.py
"""Pipeline 按 l2_backend 构造正确后端。仅验证构造分支，不跑真实扫描。"""
from __future__ import annotations

from agentsast.pipeline.engine import Pipeline


def _build(l2_backend):
    """构造 Pipeline 并触发 Layer2 backend 选择逻辑（mock 掉扫描）。"""
    p = Pipeline(l2_backend=l2_backend, skip_llm=True)
    return p


def test_pipeline_accepts_mcp_lsp_agent_choice():
    # 构造不应抛错（Choice 校验在 CLI 层，Pipeline 接受字符串）
    p = _build("mcp-lsp-agent")
    assert p.l2_backend == "mcp-lsp-agent"


def test_engine_builds_agent_backend_for_mcp_lsp_agent(monkeypatch, tmp_path):
    import agentsast.pipeline.engine as eng

    constructed: list[str] = []

    # mock Layer1 扫描返回 1 个 anchor，驱动 Layer2 backend 构造分支
    fake_anchor = type(
        "A",
        (),
        {
            "file": tmp_path / "a.c",
            "line": 1,
            "to_dict": lambda self: {},
        },
    )()
    monkeypatch.setattr(eng, "layer1_scan", lambda *a, **k: [fake_anchor])

    # 捕获 SlicingEngine 收到的 backend 类型
    real_engine = eng.SlicingEngine

    def spy_engine(max_call_depth, backend):
        constructed.append(type(backend).__name__)
        return real_engine(max_call_depth=max_call_depth, backend=backend)

    monkeypatch.setattr(eng, "SlicingEngine", spy_engine)
    # 让 slice_anchor 不真正切片（避免依赖 tree-sitter 解析 a.c）
    monkeypatch.setattr(
        eng.SlicingEngine, "slice_anchor", lambda self, anchor, project_root=None: _empty()
    )

    p = _build("mcp-lsp-agent")
    p.run(tmp_path, project_root=tmp_path)
    assert constructed == ["AgentBackend"]


def _empty():
    from agentsast.layer2.models import SlicingResult

    return SlicingResult(struct_defs=[], dataflow_slices=[], caller_slices=[])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/pipeline/test_engine_l2_backend.py -v`
Expected: FAIL —— engine 仍把 `mcp-lsp-agent` 当未知 backend，构造的是默认 `TreeSitterBackend`

- [ ] **Step 3: 改 `src/agentsast/cli.py:108-109` 的 Choice**

将:
```python
@click.option("--l2-backend", type=click.Choice(["treesitter", "mcp-lsp"]),
              default="treesitter", help="Layer2 program-understanding backend")
```
改为:
```python
@click.option(
    "--l2-backend",
    type=click.Choice(["treesitter", "mcp-lsp", "mcp-lsp-agent"]),
    default="treesitter",
    help="Layer2 program-understanding backend",
)
```

- [ ] **Step 4: 改 `src/agentsast/pipeline/engine.py:88-100` 的 backend 构造分支**

将现有的:
```python
        from ..layer2.backend import ProgramUnderstandingBackend
        from ..layer2.treesitter_backend import TreeSitterBackend
        backend: ProgramUnderstandingBackend = TreeSitterBackend(
            max_call_depth=self.max_call_depth
        )
        if self.l2_backend == "mcp-lsp":
            from ..layer2.mcp_lsp_backend import McpLspBackend
            backend = McpLspBackend(
                workspace=target,
                compile_commands_dir=(
                    self.compile_db.parent if self.compile_db else None
                ),
            )
```
改为(在 `if self.l2_backend == "mcp-lsp":` 块之后追加 `elif`):
```python
        from ..layer2.backend import ProgramUnderstandingBackend
        from ..layer2.treesitter_backend import TreeSitterBackend
        backend: ProgramUnderstandingBackend = TreeSitterBackend(
            max_call_depth=self.max_call_depth
        )
        if self.l2_backend == "mcp-lsp":
            from ..layer2.mcp_lsp_backend import McpLspBackend
            backend = McpLspBackend(
                workspace=target,
                compile_commands_dir=(
                    self.compile_db.parent if self.compile_db else None
                ),
            )
        elif self.l2_backend == "mcp-lsp-agent":
            from ..layer2.agent_backend import AgentBackend
            backend = AgentBackend(
                workspace=target,
                compile_commands_dir=(
                    self.compile_db.parent if self.compile_db else None
                ),
                llm_model=self.llm_model,
                llm_api_key=self.llm_api_key,
                llm_base_url=self.llm_base_url,
                skip_llm=self.skip_llm,
            )
```

- [ ] **Step 5: 跑测试确认通过 + 跑全量回归**

Run: `pytest tests/pipeline/test_engine_l2_backend.py tests/layer2/ -v`
Expected: 全部 passed（含原 3 个 mcp_lsp + 9 个 agent + 新 engine 测试）

- [ ] **Step 6: Commit**

```bash
git add src/agentsast/cli.py src/agentsast/pipeline/engine.py tests/pipeline/test_engine_l2_backend.py
git commit -m "feat(pipeline): --l2-backend mcp-lsp-agent wiring (CLI + engine construction)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: 文档收尾 + 全量验证

**Files:**
- Modify: `docs/ARCHITECTURE.md`(§3.2)

- [ ] **Step 1: 更新 `docs/ARCHITECTURE.md` 的 Layer2 backend 说明**

找到现有的 Layer2 可插拔后端那段(约 §3.2 / 第 146 行附近):
```
> **可插拔程序理解后端**：Layer2 的 caller/callee 查找通过 `ProgramUnderstandingBackend` 协议抽象。默认为 **tree-sitter**（语法级，零依赖）；可选 **clangd via MCP** 语义级后端，经 `--l2-backend mcp-lsp` 启用（需 `pip install -e ".[layer2-mcp]"` + `mcp-language-server` 二进制 + `clangd` + `compile_commands`）。
```
在末尾追加一句:
```
 另有 **`mcp-lsp-agent`** 档：在 mcp-lsp 基础上叠加 LLM tool-calling loop（复用 `--llm-*` 配置），由模型自主调度 callers/callees/definition/read_source 工具，提升复杂路径召回；LLM 不可用或失败时自动退化到程序化 mcp-lsp 行为。
```

- [ ] **Step 2: 全量测试 + lint + typecheck**

Run: `pytest -q && ruff check src/ tests/ && mypy src/agentsast/layer2/`
Expected: 全部测试通过、ruff 无报错、mypy 无报错

- [ ] **Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs: Layer2 mcp-lsp-agent backend (LLM-driven slicing, graceful fallback)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 验收(对应 spec §11)

- [ ] `--l2-backend mcp-lsp-agent` 可选,默认 `treesitter` 不变
- [ ] `tests/layer2/test_mcp_lsp_backend.py` 经 Task 1 调整后 3 passed(行为等价)
- [ ] `tests/layer2/test_agent_backend.py` 9 passed(loop 成功 / read_source / tool 自纠 / 3 类 fallback / skip_llm / unavailable / 无 key)
- [ ] `tests/pipeline/test_engine_l2_backend.py` 验证 engine 构造 AgentBackend
- [ ] `ProgramUnderstandingBackend` 协议、`Slicer`、`Pipeline` 签名零改动
- [ ] 全量 `pytest` + `ruff` + `mypy` 绿
```

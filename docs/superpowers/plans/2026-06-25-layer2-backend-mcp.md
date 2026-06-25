# Layer2 可插拔后端 + MCP 接入 实现计划 (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Layer2 切片引擎引入可插拔的"程序理解后端"抽象(`ProgramUnderstandingBackend`),默认 `TreeSitterBackend` 封装现有 tree-sitter 逻辑(行为等价),新增 `McpLspBackend` 通过 MCP 协议调用 mcp-language-server(clangd)提供语义级 callers/callees,经 `--l2-backend` 选择。

**Architecture:** 新增 `backend.py`(Protocol + FunctionRef)、`treesitter_backend.py`(封装现有 `_find_callers`/`_find_callees` + 跨文件搜索,返回 FunctionRef);`slicer.py` 的 `_extract_callers`/`_extract_callees` 改为调 backend(默认 TreeSitterBackend 保证 12 个现有测试行为等价);新增 `mcp_lsp_backend.py`(MCP client,内部 asyncio.run 包装 async 调用,mcp 可选依赖 try-import);`pipeline`/`cli` 串通 `--l2-backend`。

**Tech Stack:** Python 3.10+、pytest、tree-sitter(现有)、`mcp` SDK(modelcontextprotocol/python-sdk,optional extra)、asyncio。

**关联:** spec `docs/superpowers/specs/2026-06-25-gen-auto-sarif-bridge-design.md` §5.6–5.7;Plan 1(已合并 main)提供 `Anchor`/`Location`(layer1.models)与 compile_commands 供应。

**前置:** 现有 `SlicingEngine.slice_anchor` 产出 `SlicingResult`(struct_defs/dataflow_slices/caller_slices/callee_slices/raw_function)。本计划只重构 caller/callee 的"查找"环节(抽象为 backend),其余切片逻辑不动。

---

## File Structure

```
src/agentsast/layer2/
├── models.py            # 不变(CodeSlice/SlicingResult)
├── parser.py            # 不变(ASTParser)
├── slicer.py            # 改:SlicingEngine 接收 backend, _extract_callers/_extract_callees 调 backend
├── backend.py           # 新:ProgramUnderstandingBackend Protocol + FunctionRef
├── treesitter_backend.py# 新:TreeSitterBackend(封装现有 _find_callers/_find_callees + 跨文件)
└── mcp_lsp_backend.py   # 新:McpLspBackend(MCP client, async→sync, mcp 可选依赖)

src/agentsast/
├── pipeline/engine.py   # 改:Pipeline 接收 l2_backend, 传给 SlicingEngine
└── cli.py               # 改:--l2-backend {treesitter,mcp-lsp}

pyproject.toml           # 改:加 mcp 到 optional-dependencies (layer2-mcp extra)

tests/layer2/            # 新
├── __init__.py
├── test_backend.py
├── test_treesitter_backend.py
├── test_slicer_backend.py
└── test_mcp_lsp_backend.py
```

---

## Task 1: ProgramUnderstandingBackend Protocol + FunctionRef

**Files:**
- Create: `src/agentsast/layer2/backend.py`
- Test: `tests/layer2/test_backend.py`

- [ ] **Step 1: Write the failing test** → create `tests/layer2/test_backend.py`:

```python
# tests/layer2/test_backend.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer2.backend import FunctionRef, ProgramUnderstandingBackend
from agentsast.layer1.models import Location


def test_function_ref_holds_name_and_location():
    ref = FunctionRef(name="handle_connection", location=Location(file=Path("a.c"), line=18, end_line=25))
    assert ref.name == "handle_connection"
    assert ref.location.line == 18
    assert ref.location.end_line == 25


def test_protocol_methods_exist_as_attrs():
    # Protocol 的方法签名存在(结构化子类型检查)
    for meth in ("find_callers", "find_callees"):
        assert hasattr(ProgramUnderstandingBackend, meth)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest tests/layer2/test_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentsast.layer2.backend'`.

- [ ] **Step 3: Write minimal implementation** → create `src/agentsast/layer2/backend.py`:

```python
# src/agentsast/layer2/backend.py
"""Layer2 程序理解后端抽象。切片引擎通过此接口获取 caller/callee，
默认实现是 tree-sitter，可替换为 clangd(MCP)等语义级后端。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..layer1.models import Location


@dataclass
class FunctionRef:
    """一个函数引用(用于 caller/callee 切片)。location 含起止行。"""
    name: str
    location: Location


class ProgramUnderstandingBackend(Protocol):
    """程序理解后端：提供 caller/callee 查找。

    实现需保证 find_callers/find_callees 返回的 FunctionRef.location 含
    起止行(start_line/end_line)，供切片引擎读取函数源码片段。
    """

    def find_callers(self, func_name: str, loc: Location, project_root=None) -> list[FunctionRef]: ...

    def find_callees(self, func_name: str, loc: Location) -> list[FunctionRef]: ...
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest tests/layer2/test_backend.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
cd /home/atituiset/Projects/AgentSAST
git add src/agentsast/layer2/backend.py tests/layer2/test_backend.py
git commit -m "feat(layer2): add ProgramUnderstandingBackend protocol + FunctionRef"
```

---

## Task 2: TreeSitterBackend 封装现有 caller/callee 查找

**Files:**
- Create: `src/agentsast/layer2/treesitter_backend.py`
- Test: `tests/layer2/test_treesitter_backend.py`

> 复用 samples/vulnerable_server.c(Plan 1 已有)。该文件 `handle_connection` 调用 `process_buffer`,故 `find_callers("process_buffer")` 应含 `handle_connection`,`find_callees("handle_connection")` 应含 `process_buffer`。

- [ ] **Step 1: Write the failing test** → create `tests/layer2/test_treesitter_backend.py`:

```python
# tests/layer2/test_treesitter_backend.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer2.treesitter_backend import TreeSitterBackend
from agentsast.layer1.models import Location

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
VULN = SAMPLES / "vulnerable_server.c"


def test_find_callers_of_process_buffer():
    backend = TreeSitterBackend()
    callers = backend.find_callers("process_buffer", Location(file=VULN, line=8))
    names = [c.name for c in callers]
    assert "handle_connection" in names


def test_find_callees_of_handle_connection():
    backend = TreeSitterBackend()
    callees = backend.find_callees("handle_connection", Location(file=VULN, line=18))
    names = [c.name for c in callees]
    assert "process_buffer" in names


def test_function_ref_has_end_line():
    backend = TreeSitterBackend()
    callers = backend.find_callers("process_buffer", Location(file=VULN, line=8))
    hc = [c for c in callers if c.name == "handle_connection"][0]
    assert hc.location.line > 0
    assert hc.location.end_line >= hc.location.line
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest tests/layer2/test_treesitter_backend.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation** → create `src/agentsast/layer2/treesitter_backend.py`:

```python
# src/agentsast/layer2/treesitter_backend.py
"""TreeSitterBackend：封装现有 tree-sitter caller/callee 查找逻辑，
使其满足 ProgramUnderstandingBackend 接口。行为与原 slicer 的
_find_callers/_find_callees 等价（含跨文件搜索）。"""
from __future__ import annotations

from pathlib import Path

from tree_sitter import Node

from ..layer1.models import Location
from .backend import FunctionRef
from .parser import ASTParser

_SRC_EXTS = (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp")


def _walk(node: Node):
    stack = list(node.children)
    while stack:
        c = stack.pop()
        yield c
        stack.extend(c.children)


def _get_function_name(func_node: Node) -> str:
    decl = func_node.child_by_field_name("declarator")
    if not decl:
        return ""
    for child in decl.children:
        if child.type == "identifier":
            return child.text.decode()
        if child.type in ("pointer_declarator", "function_declarator"):
            for sub in child.children:
                if sub.type == "identifier":
                    return sub.text.decode()
    return ""


def _find_caller_funcs(root: Node, func_name: str) -> list[Node]:
    callers: list[Node] = []
    for node in _walk(root):
        if node.type == "function_definition":
            body = node.child_by_field_name("body")
            if body is None:
                continue
            for child in _walk(body):
                if child.type == "call_expression":
                    fn = child.child_by_field_name("function")
                    if fn and fn.text.decode().strip() == func_name:
                        callers.append(node)
                        break
    return callers


def _find_callee_funcs(func_node: Node) -> list[tuple[str, Node]]:
    callees: list[tuple[str, Node]] = []
    body = func_node.child_by_field_name("body")
    if not body:
        return callees
    for child in _walk(body):
        if child.type == "call_expression":
            fn = child.child_by_field_name("function")
            if fn:
                callees.append((fn.text.decode().strip(), child))
    return callees


def _find_enclosing_function(root: Node, line: int) -> Node | None:
    best: Node | None = None
    for node in _walk(root):
        if node.type == "function_definition":
            sp, ep = node.start_point[0] + 1, node.end_point[0] + 1
            if sp <= line <= ep:
                if best is None or (ep - sp < best.end_point[0] - best.start_point[0]):
                    best = node
    return best


class TreeSitterBackend:
    """默认后端：tree-sitter 语法级 caller/callee。"""

    def __init__(self, max_call_depth: int = 2):
        self.parser = ASTParser()
        self.max_call_depth = max_call_depth
        self._cache: dict[Path, Node | None] = {}

    def _ast(self, path: Path) -> Node | None:
        rp = path.resolve()
        if rp not in self._cache:
            self._cache[rp] = self.parser.parse_file(rp)
        return self._cache[rp]

    def find_callers(self, func_name, loc, project_root=None) -> list[FunctionRef]:
        if not func_name:
            return []
        refs: list[FunctionRef] = []
        root = self._ast(Path(loc.file))
        if root:
            for node in _find_caller_funcs(root, func_name):
                refs.append(FunctionRef(
                    name=_get_function_name(node) or func_name,
                    location=Location(
                        file=Path(loc.file),
                        line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                    ),
                ))
        # 跨文件搜索
        if project_root:
            pr = Path(project_root)
            search_dir = pr if pr.is_dir() else Path(loc.file).parent
            for src in search_dir.rglob("*"):
                if src.suffix.lower() not in _SRC_EXTS:
                    continue
                if src.resolve() == Path(loc.file).resolve():
                    continue
                other = self._ast(src)
                if not other:
                    continue
                for node in _find_caller_funcs(other, func_name):
                    refs.append(FunctionRef(
                        name=_get_function_name(node) or func_name,
                        location=Location(
                            file=src, line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                        ),
                    ))
                if len(refs) >= self.max_call_depth:
                    break
        return refs[: self.max_call_depth]

    def find_callees(self, func_name, loc) -> list[FunctionRef]:
        root = self._ast(Path(loc.file))
        if not root:
            return []
        func_node = _find_enclosing_function(root, loc.line)
        if not func_node:
            return []
        refs: list[FunctionRef] = []
        for name, call_node in _find_callee_funcs(func_node)[:5]:
            refs.append(FunctionRef(
                name=name,
                location=Location(
                    file=Path(loc.file),
                    line=call_node.start_point[0] + 1,
                    end_line=call_node.end_point[0] + 1,
                ),
            ))
        return refs
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest tests/layer2/test_treesitter_backend.py -q`
Expected: PASS (all 3).

- [ ] **Step 5: Commit**
```bash
cd /home/atituiset/Projects/AgentSAST
git add src/agentsast/layer2/treesitter_backend.py tests/layer2/test_treesitter_backend.py
git commit -m "feat(layer2): TreeSitterBackend wrapping existing caller/callee logic"
```

---

## Task 3: SlicingEngine 改用 backend(行为等价)

**Files:**
- Modify: `src/agentsast/layer2/slicer.py` (READ it first — keep `slice_anchor`/`_extract_struct_defs`/`_extract_dataflow` and the module-level `_walk_tree`/`_find_enclosing_function`/`_find_struct_defs`/`_extract_type_names_from_node`/`_backward_slice_var`/`_get_typedef_name` UNCHANGED; only `_extract_callers`/`_extract_callees` and `__init__` change)
- Test: `tests/layer2/test_slicer_backend.py` + existing `tests/test_pipeline.py` must stay green

- [ ] **Step 1: Write the failing test** → create `tests/layer2/test_slicer_backend.py`:

```python
# tests/layer2/test_slicer_backend.py
"""验证 SlicingEngine 接受 backend 参数,且默认行为与原来一致。"""
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.models import Anchor, Location, Severity
from agentsast.layer2.slicer import SlicingEngine
from agentsast.layer2.treesitter_backend import TreeSitterBackend

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
VULN = SAMPLES / "vulnerable_server.c"


def _memcpy_anchor(line=17):
    return Anchor(
        rule_id="t", tool="t", severity=Severity.WARNING, message="m",
        location=Location(file=VULN, line=line), cwe="CWE-120", sink_function="memcpy",
    )


def test_slicing_engine_accepts_backend():
    backend = TreeSitterBackend()
    engine = SlicingEngine(backend=backend)
    assert engine.backend is backend


def test_slicing_engine_defaults_to_treesitter():
    engine = SlicingEngine()
    assert isinstance(engine.backend, TreeSitterBackend)


def test_caller_slice_via_backend():
    engine = SlicingEngine()
    result = engine.slice_anchor(_memcpy_anchor())
    # process_buffer 被 handle_connection 调用 → caller slice 应含 handle_connection
    labels = " ".join(s.label for s in result.caller_slices)
    assert "handle_connection" in labels or "caller_of:process_buffer" in labels
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest tests/layer2/test_slicer_backend.py -v`
Expected: FAIL — `SlicingEngine` has no `backend` param.

- [ ] **Step 3: Modify `src/agentsast/layer2/slicer.py`** (read it first):

3a. Add imports near top:
```python
from .backend import FunctionRef
from .treesitter_backend import TreeSitterBackend
```

3b. Change `SlicingEngine.__init__` to accept an optional backend (default → TreeSitterBackend preserving the old max_call_depth):
```python
class SlicingEngine:
    def __init__(self, max_call_depth: int = 2, backend=None):
        self.parser = ASTParser()
        self.max_call_depth = max_call_depth
        self._file_cache: dict[Path, Node] = {}
        self.backend = backend if backend is not None else TreeSitterBackend(max_call_depth=max_call_depth)
```

3c. Replace `_extract_callers` body to delegate to `self.backend.find_callers` then build `CodeSlice` from each `FunctionRef` (read source lines via `ASTParser.get_line_content`):
```python
    def _extract_callers(self, file_path, root, func_node, project_root):
        from .models import CodeSlice  # local import avoids cycle if needed
        slices: list[CodeSlice] = []
        func_name = _get_function_name(func_node)
        if not func_name:
            return slices
        refs = self.backend.find_callers(
            func_name,
            Location(file=file_path, line=func_node.start_point[0] + 1),
            project_root=project_root,
        )
        for ref in refs:
            content = ASTParser.get_line_content(ref.location.file, ref.location.line, ref.location.end_line)
            slices.append(CodeSlice(
                file=ref.location.file, start_line=ref.location.line,
                end_line=ref.location.end_line, content=content,
                slice_type="caller", label=f"caller_of:{func_name}",
            ))
        return slices[: self.max_call_depth]
```
(Add `from ..layer1.models import Location` import at top of slicer.py if not present — it's already imported as `Anchor`; add `Location` to that import line.)

3d. Replace `_extract_callees` body to delegate to `self.backend.find_callees`:
```python
    def _extract_callees(self, file_path, func_node):
        slices: list[CodeSlice] = []
        func_name = _get_function_name(func_node)
        refs = self.backend.find_callees(
            func_name,
            Location(file=file_path, line=func_node.start_point[0] + 1),
        )
        for ref in refs:
            content = ASTParser.get_line_content(ref.location.file, ref.location.line, ref.location.end_line)
            slices.append(CodeSlice(
                file=ref.location.file, start_line=ref.location.line,
                end_line=ref.location.end_line, content=content,
                slice_type="callee", label=f"callee:{ref.name}",
            ))
        return slices
```

3e. Keep the old module-level `_find_callers`/`_find_callees`/`_get_function_name` functions in slicer.py ONLY IF something else still references them; otherwise they are now dead code (moved into treesitter_backend.py). Check: if `_find_callers`/`_find_callees`/`_get_function_name` are no longer referenced in slicer.py after the above edits, DELETE them from slicer.py (DRY — they live in treesitter_backend.py now). Keep `_get_function_name` in slicer.py ONLY if `_extract_callers`/`_extract_callees` still call it (they do, for `func_name` — so KEEP `_get_function_name` in slicer.py; delete only `_find_callers`/`_find_callees` if unreferenced).

- [ ] **Step 4: Run tests — CRITICAL behavior-equivalence check**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest -q`
Expected: ALL pass — the 3 new backend-slicer tests AND the original 12 `tests/test_pipeline.py` tests (TestSlicingEngine) must stay green. If any of the 12 fails, the refactor broke behavior — re-examine `_extract_callers`/`_extract_callees` (most likely the caller/callee slice labels or line ranges drifted).

- [ ] **Step 5: Commit**
```bash
cd /home/atituiset/Projects/AgentSAST
git add src/agentsast/layer2/slicer.py tests/layer2/test_slicer_backend.py
git commit -m "refactor(layer2): SlicingEngine delegates caller/callee to pluggable backend"
```

---

## Task 4: pyproject 加 mcp 可选依赖并安装

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the optional extra**
Edit `pyproject.toml` `[project.optional-dependencies]` — add a `layer2-mcp` extra alongside the existing `dev` extra:
```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.5",
    "mypy>=1.10",
]
layer2-mcp = [
    "mcp>=1.2",
]
```

- [ ] **Step 2: Install it into the venv**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/pip install -e ".[layer2-mcp]" 2>&1 | tail -5`
Expected: installs `mcp` (+ any transitive deps). Verify: `.venv/bin/python -c "import mcp; print(mcp.__name__)"` prints `mcp`.

- [ ] **Step 3: Commit**
```bash
cd /home/atituiset/Projects/AgentSAST
git add pyproject.toml
git commit -m "build: add layer2-mcp optional extra (mcp SDK)"
```

---

## Task 5: McpLspBackend(MCP client,async→sync,可选依赖)

**Files:**
- Create: `src/agentsast/layer2/mcp_lsp_backend.py`
- Test: `tests/layer2/test_mcp_lsp_backend.py`

> 设计要点:① mcp 是 optional 依赖,顶部 `try: import mcp` + `IS_AVAILABLE` 标志;② MCP 是 async,但 AgentSAST 同步,故 `_call_tool_async` 是 async 内部方法,公开方法用 `asyncio.run` 包装;③ 测试 mock `_call_tool_async`(绕过真实 mcp/clangd 连接,不依赖二进制)。

- [ ] **Step 1: Write the failing test** → create `tests/layer2/test_mcp_lsp_backend.py`:

```python
# tests/layer2/test_mcp_lsp_backend.py
"""McpLspBackend 测试：mock _call_tool_async，不依赖真实 mcp/clangd。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentsast.layer1.models import Location
from agentsast.layer2.backend import FunctionRef


def test_is_available_reflects_mcp_import(monkeypatch):
    from agentsast.layer2 import mcp_lsp_backend as mod
    from agentsast.layer2.mcp_lsp_backend import McpLspBackend
    monkeypatch.setattr(mod, "IS_AVAILABLE", False)
    b = McpLspBackend()
    assert b.is_available() is False


def test_find_callers_parses_mocked_tool_result(monkeypatch):
    from agentsast.layer2.mcp_lsp_backend import McpLspBackend
    b = McpLspBackend()
    # mock async 调用：返回 callers tool 的文本（每行一个引用 "file:line"）
    async def fake_call(tool, args):
        return "handle_connection\n  /src/main.c:18:1\n  /src/other.c:5:1"
    monkeypatch.setattr(b, "_call_tool_async", fake_call)
    refs = b.find_callers("process_buffer", Location(file=Path("/src/main.c"), line=8))
    names = [r.name for r in refs]
    assert "handle_connection" in names
    assert all(r.location.line > 0 for r in refs)


def test_find_callers_empty_when_no_result(monkeypatch):
    from agentsast.layer2.mcp_lsp_backend import McpLspBackend
    b = McpLspBackend()
    async def fake_call(tool, args):
        return ""
    monkeypatch.setattr(b, "_call_tool_async", fake_call)
    assert b.find_callers("x", Location(file=Path("a.c"), line=1)) == []
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest tests/layer2/test_mcp_lsp_backend.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation** → create `src/agentsast/layer2/mcp_lsp_backend.py`:

```python
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

# mcp-language-server 输出里的位置行，形如 "  /path/file.c:18:1"
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
        refs: list[FunctionRef] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = _LOC_RE.match(line)
            if m:
                file, line_no = Path(m.group(1)), int(m.group(2))
                refs.append(FunctionRef(
                    name=default_name,
                    location=Location(file=file, line=line_no, end_line=line_no),
                ))
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
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest tests/layer2/test_mcp_lsp_backend.py -q`
Expected: PASS (all 3, after fixing the test typo noted in Step 1).

- [ ] **Step 5: Commit**
```bash
cd /home/atituiset/Projects/AgentSAST
git add src/agentsast/layer2/mcp_lsp_backend.py tests/layer2/test_mcp_lsp_backend.py
git commit -m "feat(layer2): McpLspBackend (clangd via MCP, async->sync, optional dep)"
```

---

## Task 6: Pipeline + CLI 串通 --l2-backend

**Files:**
- Modify: `src/agentsast/pipeline/engine.py`
- Modify: `src/agentsast/cli.py`
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Write the failing test** → append to `tests/test_cli.py`:

```python
def test_cli_accepts_l2_backend(tmp_path):
    runner = CliRunner()
    target = tmp_path / "a.c"
    target.write_text("int main(){return 0;}")
    result = runner.invoke(main, [
        str(target), "--skip-llm", "--tools", "flawfinder",
        "--l2-backend", "treesitter",
    ])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest tests/test_cli.py::test_cli_accepts_l2_backend -v`
Expected: FAIL — `--l2-backend` unknown option.

- [ ] **Step 3a: Modify `src/agentsast/pipeline/engine.py`**:
- `Pipeline.__init__` add param `l2_backend: str = "treesitter"`; store `self.l2_backend = l2_backend`.
- In `run()`, build the backend before slicing:
```python
from ..layer2.treesitter_backend import TreeSitterBackend
# (only construct mcp-lsp lazily to avoid hard mcp dependency at import time)
backend = TreeSitterBackend(max_call_depth=self.max_call_depth)
if self.l2_backend == "mcp-lsp":
    from ..layer2.mcp_lsp_backend import McpLspBackend
    backend = McpLspBackend(
        workspace=target, compile_commands_dir=(self.compile_db.parent if self.compile_db else None),
    )
engine = SlicingEngine(max_call_depth=self.max_call_depth, backend=backend)
```

- [ ] **Step 3b: Modify `src/agentsast/cli.py`**:
- Add option:
```python
@click.option("--l2-backend", type=click.Choice(["treesitter", "mcp-lsp"]),
              default="treesitter", help="Layer2 program-understanding backend")
```
- Add `l2_backend` param to `main(...)` and pass `l2_backend=l2_backend` into `Pipeline(...)`.

- [ ] **Step 4: Run tests**
Run: `cd /home/atituiset/Projects/AgentSAST && .venv/bin/python -m pytest -q`
Expected: ALL pass.

- [ ] **Step 5: Commit**
```bash
cd /home/atituiset/Projects/AgentSAST
git add src/agentsast/pipeline/engine.py src/agentsast/cli.py tests/test_cli.py
git commit -m "feat(pipeline): --l2-backend {treesitter,mcp-lsp} wiring"
```

---

## Task 7: 全量回归 + ruff/mypy + docs

**Files:**
- Modify: `docs/ARCHITECTURE.md` (light)

- [ ] **Step 1: Run full suite + linters, fix issues in OUR files**
```bash
cd /home/atituiset/Projects/AgentSAST
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
```
Fix any ruff/mypy issues in layer2/* or pipeline/cli touched by this plan. Pre-existing mypy errors in layer2/parser.py, layer2/slicer.py (the parts we didn't touch), layer3/* are out of scope — but if our refactor of slicer.py introduced NEW mypy errors, fix them.

- [ ] **Step 2: Behavior-equivalence final check**
The original 12 `tests/test_pipeline.py` tests (incl. TestSlicingEngine) MUST still pass — proving the backend refactor didn't change slicing output. If any fail, that's a regression to fix before finishing.

- [ ] **Step 3: Docs**
In `docs/ARCHITECTURE.md`, add a one-line note in §3.2 that Layer2 now has a pluggable program-understanding backend (tree-sitter default, clangd via MCP optional via `--l2-backend mcp-lsp`, requires `pip install -e ".[layer2-mcp]"` + mcp-language-server binary + clangd + compile_commands).

- [ ] **Step 4: Commit**
```bash
cd /home/atituiset/Projects/AgentSAST
git add -A
git commit -m "docs: Layer2 pluggable backend (tree-sitter / clangd-via-MCP)"
```

---

## Self-Review

**Spec coverage (§5.6–5.7):**
- §5.6 ProgramUnderstandingBackend Protocol → **Task 1** ✓
- §5.6 TreeSitterBackend(封装现有) → **Task 2** ✓
- §5.6/§5.7 SlicingEngine 面向 backend → **Task 3** ✓
- §5.7 mcp 可选依赖 → **Task 4** ✓
- §5.7 McpLspBackend(MCP client, async→sync) → **Task 5** ✓
- §5.8 `--l2-backend` CLI + Pipeline → **Task 6** ✓
- §6 降级(mcp 不可用→treesitter;mcp 未装→IS_AVAILABLE False) → Task 5 `is_available` + Task 6 默认 treesitter ✓
- §7 测试(mock MCP,不依赖真 clangd) → Task 5 mock `_call_tool_async` ✓

**类型一致性:** `FunctionRef(name, location)`,`Location` 用 layer1.models(含 line/end_line);`find_callers(func_name, loc, project_root=None)`/`find_callees(func_name, loc)` 在 backend.py、treesitter_backend.py、mcp_lsp_backend.py 三处签名一致;`SlicingEngine(backend=)`/`Pipeline(l2_backend=)`/`--l2-backend` 串通。

**已知边界/风险(实现时注意):**
- Task 3 重构:`_extract_callers`/`_extract_callees` 从"用 Node 切片"改为"用 FunctionRef 的 line/end_line 读源码"。对函数级切片行为等价,但若 12 个旧测试有断言失败,先查 label/行范围。
- Task 5 mock:`_call_tool_async` 被 monkeypatch,绕过真实 mcp;真实 mcp-language-server/clangd 集成需手动验证(装 mcp + 二进制 + compile_commands)。
- mcp async→sync:`asyncio.run` per-call,MVP 可接受;mcp-lsp 非高频。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-25-layer2-backend-mcp.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task + two-stage review
2. **Inline Execution** — batch with checkpoints

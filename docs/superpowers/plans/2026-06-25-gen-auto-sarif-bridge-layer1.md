# Layer1 SARIF 桥接 + 编译供应 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 gen-auto 的 Infer/CSA/Cppcheck 三件套以原生编译、两线并存的形态接入 AgentSAST Layer1,以 SARIF v2.1.0 为工具→AgentSAST 的传递格式,扩展 Anchor 保留 source→sink 路径,并提供统一的 compile_commands.json 供应机制。

**Architecture:** 定义可插拔 `Scanner` Protocol(自研工具实现+注册即可接入);新增通用 SARIF 解析层(`sarif_parser.py`,解析 `codeFlows` 还原路径)+ 工具特化 handler(参考 gen-auto 逻辑全新实现);新增 `compile.py` 三入口编译供应(`--compile-db`/`--compile-dir`/`--build-cmd`)。全部代码在 AgentSAST 内全新实现,gen-auto 仅作逻辑参考。

**Tech Stack:** Python 3.10+、pytest、tree-sitter(现有)、subprocess(调用分析器)、stdlib `json`/`xml.etree`。

**关联:** spec `docs/superpowers/specs/2026-06-25-gen-auto-sarif-bridge-design.md`。本计划覆盖 spec §5.1–5.5 + §5.8(Layer1 部分);spec §5.6–5.7(Layer2 MCP 后端)留待后续 Plan 2。

---

## File Structure

```
src/agentsast/layer1/
├── models.py          # 改:Anchor +source_location +dataflow_path;Location +message
├── base.py            # 新:Scanner Protocol + ScanContext + SCANNER_REGISTRY + @register_scanner
├── scanner.py         # 改:scan() 基于 registry 分发,接收 compile_db
├── semgrep.py         # 改:实现 Protocol + 注册 + scan(ScanContext)
├── flawfinder.py      # 改:实现 Protocol + 注册 + scan(ScanContext)
├── sarif_parser.py    # 新:parse_sarif_to_anchors(通用 codeFlows→dataflow_path)
├── compile.py         # 新:resolve_compile_commands(三入口优先级)
├── infer.py           # 新:InferScanner
├── csa.py             # 新:CsaScanner
├── cppcheck.py        # 新:CppcheckScanner(含 xml_to_sarif 适配)
└── handlers/          # 新:工具特化提取逻辑
    ├── __init__.py
    ├── infer.py
    ├── csa.py
    └── cppcheck.py

src/agentsast/
├── pipeline/engine.py # 改:Pipeline 接收/传递 compile_db
└── cli.py             # 改:新增 --compile-db/--compile-dir/--build-cmd

tests/
├── layer1/            # 新:测试目录
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_scanner_registry.py
│   ├── test_sarif_parser.py
│   ├── test_handlers_infer.py
│   ├── test_handlers_csa.py
│   ├── test_handlers_cppcheck.py
│   ├── test_compile.py
│   ├── test_infer_scanner.py
│   ├── test_csa_scanner.py
│   └── test_cppcheck_scanner.py
└── fixtures/          # 新:真实 SARIF/XML 样本
    ├── infer_null_deref.sarif
    ├── csa_null_deref.sarif
    └── cppcheck_buffer.xml
```

---

## Phase 0:数据模型与可插拔扫描器层

### Task 1: 扩展 Anchor 保留 source→sink 路径

**Files:**
- Modify: `src/agentsast/layer1/models.py`
- Test: `tests/layer1/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_models.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.models import Anchor, Location, Severity


def test_anchor_defaults_no_path():
    a = Anchor(
        rule_id="r", tool="t", severity=Severity.WARNING,
        message="m", location=Location(file=Path("a.c"), line=1),
    )
    assert a.source_location is None
    assert a.dataflow_path == []


def test_anchor_with_path_serializes():
    a = Anchor(
        rule_id="r", tool="t", severity=Severity.WARNING,
        message="m", location=Location(file=Path("a.c"), line=10),
        source_location=Location(file=Path("a.c"), line=3),
        dataflow_path=[
            Location(file=Path("a.c"), line=3),
            Location(file=Path("a.c"), line=7),
            Location(file=Path("a.c"), line=10),
        ],
    )
    d = a.to_dict()
    assert d["source_location"]["line"] == 3
    assert [loc["line"] for loc in d["dataflow_path"]] == [3, 7, 10]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/atituiset/Projects/AgentSAST && python -m pytest tests/layer1/test_models.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'source_location'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/models.py  (修改 Location 与 Anchor)
@dataclass
class Location:
    file: Path
    line: int
    col: int = 0
    end_line: int = 0
    end_col: int = 0
    message: str = ""                       # 新增

    def __post_init__(self):
        self.file = Path(self.file)

    def to_dict(self) -> dict:              # 新增
        return {
            "file": str(self.file),
            "line": self.line,
            "col": self.col,
            "end_line": self.end_line,
            "end_col": self.end_col,
            "message": self.message,
        }


@dataclass
class Anchor:
    rule_id: str
    tool: str
    severity: Severity
    message: str
    location: Location
    cwe: str = ""
    sink_function: str = ""
    sink_params: list[str] = field(default_factory=list)
    raw_sarif: dict = field(default_factory=dict)
    source_location: Location | None = None                      # 新增
    dataflow_path: list[Location] = field(default_factory=list)  # 新增

    @property
    def file(self) -> Path:
        return self.location.file

    @property
    def line(self) -> int:
        return self.location.line

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "tool": self.tool,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location.to_dict(),
            "cwe": self.cwe,
            "sink_function": self.sink_function,
            "sink_params": self.sink_params,
            "source_location": self.source_location.to_dict() if self.source_location else None,
            "dataflow_path": [loc.to_dict() for loc in self.dataflow_path],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_models.py tests/test_pipeline.py -v`
Expected: PASS（含原有 12 个测试，确认向后兼容）

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/models.py tests/layer1/test_models.py
git commit -m "feat(layer1): extend Anchor with source_location and dataflow_path"
```

---

### Task 2: 定义 Scanner Protocol、ScanContext 与注册机制

**Files:**
- Create: `src/agentsast/layer1/base.py`
- Test: `tests/layer1/test_scanner_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_scanner_registry.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext, Scanner, register_scanner, SCANNER_REGISTRY


def test_scan_context_carries_compile_db():
    ctx = ScanContext(target=Path("a.c"), compile_db=Path("cc.json"))
    assert ctx.compile_db == Path("cc.json")


def test_register_scanner_adds_to_registry():
    @register_scanner("dummy-tool")
    class DummyScanner:
        name = "Dummy"
        requires_compilation = False
        def is_available(self) -> bool:
            return True
        def scan(self, ctx: ScanContext):
            return []

    assert "dummy-tool" in SCANNER_REGISTRY
    assert SCANNER_REGISTRY["dummy-tool"] is DummyScanner
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/layer1/test_scanner_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentsast.layer1.base'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from .models import Anchor


@dataclass
class ScanContext:
    target: Path
    compile_db: Path | None = None
    timeout: int = 600
    config: dict = field(default_factory=dict)


class Scanner(Protocol):
    name: str
    requires_compilation: bool

    def is_available(self) -> bool: ...

    def scan(self, ctx: ScanContext) -> list[Anchor]: ...


SCANNER_REGISTRY: dict[str, type] = {}
_T = TypeVar("_T")


def register_scanner(key: str):
    """注册扫描器，使其可被 --tools <key> 选中。"""
    def deco(cls: _T) -> _T:
        SCANNER_REGISTRY[key] = cls  # type: ignore[assignment]
        return cls
    return deco
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_scanner_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/base.py tests/layer1/test_scanner_registry.py
git commit -m "feat(layer1): add Scanner protocol, ScanContext and registry"
```

---

### Task 3: 改造 SemgrepScanner 实现 Protocol 并注册

**Files:**
- Modify: `src/agentsast/layer1/semgrep.py`
- Test: `tests/layer1/test_scanner_registry.py`（追加用例）

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/layer1/test_scanner_registry.py 末尾
def test_semgrep_is_registered_and_protocol_compatible():
    from agentsast.layer1.base import SCANNER_REGISTRY, ScanContext
    from agentsast.layer1.semgrep import SemgrepScanner
    assert "semgrep" in SCANNER_REGISTRY
    scanner = SCANNER_REGISTRY["semgrep"](config="p/c")
    assert scanner.name == "Semgrep"
    assert scanner.requires_compilation is False
    # Protocol 方法存在性
    assert callable(scanner.is_available)
    assert callable(scanner.scan)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/layer1/test_scanner_registry.py::test_semgrep_is_registered_and_protocol_compatible -v`
Expected: FAIL — `semgrep` 不在 registry

- [ ] **Step 3: Write minimal implementation**

修改 `src/agentsast/layer1/semgrep.py`：顶部导入注册器并装饰类；新增类属性 `requires_compilation`；保留旧 `scan(target)` 逻辑，新增 `scan(ctx: ScanContext)` 适配。

```python
# 文件顶部 import 区新增：
from .base import ScanContext, register_scanner

# 类装饰 + 属性 + ctx 适配：
@register_scanner("semgrep")
class SemgrepScanner:
    NAME = "Semgrep"
    requires_compilation = False

    def __init__(self, config: str = "p/c", timeout: int = 300):
        self.config = config
        self.timeout = timeout

    def is_available(self) -> bool:
        # ... 现有实现不变 ...

    def scan(self, ctx) -> list[Anchor]:
        # 同时兼容 ScanContext 和旧的 target: Path 调用
        target = ctx.target if isinstance(ctx, ScanContext) else ctx
        # ... 现有 scan(target) 主体原样移入（self._parse_sarif 等不变） ...
```

> 说明：把原 `scan(self, target: Path)` 主体移入新 `scan(self, ctx)`，首行用上面的三元式取 target，其余逻辑（is_available 检查、subprocess 调用、`_parse_sarif`）保持不变。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_scanner_registry.py tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/semgrep.py tests/layer1/test_scanner_registry.py
git commit -m "refactor(layer1): SemgrepScanner implements Scanner protocol + registered"
```

---

### Task 4: 改造 FlawfinderScanner 实现 Protocol 并注册

**Files:**
- Modify: `src/agentsast/layer1/flawfinder.py`
- Test: `tests/layer1/test_scanner_registry.py`（追加用例）

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/layer1/test_scanner_registry.py
def test_flawfinder_is_registered_and_protocol_compatible():
    from agentsast.layer1.base import SCANNER_REGISTRY, ScanContext
    from agentsast.layer1.flawfinder import FlawfinderScanner
    assert "flawfinder" in SCANNER_REGISTRY
    scanner = SCANNER_REGISTRY["flawfinder"]()
    assert scanner.name == "Flawfinder"
    assert scanner.requires_compilation is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/layer1/test_scanner_registry.py::test_flawfinder_is_registered_and_protocol_compatible -v`
Expected: FAIL — `flawfinder` 不在 registry

- [ ] **Step 3: Write minimal implementation**

修改 `src/agentsast/layer1/flawfinder.py`，与 Task 3 同构：

```python
from .base import ScanContext, register_scanner

@register_scanner("flawfinder")
class FlawfinderScanner:
    NAME = "Flawfinder"
    requires_compilation = False

    def __init__(self, min_level: int = 3, timeout: int = 300):
        self.min_level = min_level
        self.timeout = timeout

    # is_available / _parse_sarif_output / _pattern_scan 等不变

    def scan(self, ctx) -> list[Anchor]:
        target = ctx.target if isinstance(ctx, ScanContext) else ctx
        # ... 原 scan(self, target: Path) 主体原样移入 ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_scanner_registry.py tests/test_pipeline.py -v`
Expected: PASS（含现有 `TestFlawfinderPatternScan`，它直接调用 `_pattern_scan`，不受影响）

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/flawfinder.py tests/layer1/test_scanner_registry.py
git commit -m "refactor(layer1): FlawfinderScanner implements Scanner protocol + registered"
```

---

### Task 5: 重构 scan() 基于 registry 分发并接收 compile_db

**Files:**
- Modify: `src/agentsast/layer1/scanner.py`
- Test: `tests/layer1/test_scanner_registry.py`（追加用例）

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/layer1/test_scanner_registry.py
def test_scan_skips_compilation_scanner_without_compile_db(monkeypatch, tmp_path):
    # 注册一个假的编译期扫描器，断言它在无 compile_db 时被跳过
    from agentsast.layer1 import scanner as scanner_mod
    from agentsast.layer1.base import register_scanner, ScanContext, SCANNER_REGISTRY

    called = {"n": 0}

    @register_scanner("fake-compiler")
    class _FakeCompiler:
        name = "Fake"
        requires_compilation = True
        def is_available(self):
            return True
        def scan(self, ctx):
            called["n"] += 1
            return []

    anchors = scanner_mod.scan(tmp_path, tools=["fake-compiler"])
    assert anchors == []
    assert called["n"] == 0  # 无 compile_db，编译期扫描器被跳过
    # 清理 registry 避免污染其它测试
    SCANNER_REGISTRY.pop("fake-compiler", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/layer1/test_scanner_registry.py::test_scan_skips_compilation_scanner_without_compile_db -v`
Expected: FAIL — `requires_compilation` 当前未参与分发

- [ ] **Step 3: Write minimal implementation**

重写 `src/agentsast/layer1/scanner.py` 的 `scan()`（保留 `parse_sarif_file` 供向后兼容）：

```python
from __future__ import annotations

import logging
from pathlib import Path

from .base import ScanContext, SCANNER_REGISTRY
from .flawfinder import FlawfinderScanner   # 触发注册（import 副作用）
from .models import Anchor
from .semgrep import SemgrepScanner          # 触发注册（import 副作用）

logger = logging.getLogger(__name__)


def parse_sarif_file(sarif_path: Path) -> list[Anchor]:
    # ... 现有实现保留不变 ...


def scan(
    target: Path,
    tools: list[str] | None = None,
    config: str = "p/c",
    compile_db: Path | None = None,
) -> list[Anchor]:
    if tools is None:
        tools = ["semgrep", "flawfinder"]

    target = Path(target).resolve()
    if not target.exists():
        raise FileNotFoundError(f"Target path does not exist: {target}")

    ctx = ScanContext(target=target, compile_db=compile_db)
    all_anchors: list[Anchor] = []
    seen: set[tuple[str, str, int]] = set()

    for key in tools:
        if key not in SCANNER_REGISTRY:
            logger.warning("Unknown scanner: %s, skipping", key)
            continue
        kwargs: dict = {"config": config} if key == "semgrep" else {}
        scanner = SCANNER_REGISTRY[key](**kwargs)
        if scanner.requires_compilation and ctx.compile_db is None:
            logger.warning(
                "Scanner %s requires compilation but no compile_db provided, skipping",
                scanner.name,
            )
            continue
        try:
            if not scanner.is_available():
                logger.warning("Scanner %s not available, skipping", scanner.name)
                continue
            anchors = scanner.scan(ctx)
        except Exception:
            logger.exception("Scanner %s failed", getattr(scanner, "name", key))
            continue

        for anchor in anchors:
            akey = (anchor.tool, str(anchor.file), anchor.line)
            if akey not in seen:
                seen.add(akey)
                all_anchors.append(anchor)

    logger.info("Layer1 total unique anchors: %d", len(all_anchors))
    return all_anchors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_scanner_registry.py tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/scanner.py tests/layer1/test_scanner_registry.py
git commit -m "refactor(layer1): scan() dispatches via registry, skips compilers w/o compile_db"
```

---

## Phase 1:通用 SARIF 解析层 + 工具 handler

### Task 6: 通用 SARIF 解析（codeFlows → dataflow_path）

**Files:**
- Create: `src/agentsast/layer1/sarif_parser.py`
- Create: `tests/fixtures/csa_null_deref.sarif`
- Test: `tests/layer1/test_sarif_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_sarif_parser.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.sarif_parser import parse_sarif_to_anchors

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parses_result_to_anchor():
    anchors = parse_sarif_to_anchors(FIXTURES / "csa_null_deref.sarif")
    assert len(anchors) == 1
    a = anchors[0]
    assert a.location.line == 12            # sink 行
    assert a.location.file.name == "main.c"
    # codeFlows 被还原成 dataflow_path
    assert len(a.dataflow_path) >= 2
    assert a.source_location is not None
    assert a.source_location.line == 5      # source 行
```

- [ ] **Step 2: Create the fixture, then run test to verify it fails**

```json
// tests/fixtures/csa_null_deref.sarif
{
  "version": "2.1.0",
  "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
  "runs": [{
    "tool": {"driver": {"name": "clang", "rules": [{"id": "core.NullDereference"}]}},
    "results": [{
      "ruleId": "core.NullDereference",
      "level": "warning",
      "message": {"text": "Dereference of null pointer"},
      "locations": [{
        "physicalLocation": {
          "artifactLocation": {"uri": "main.c"},
          "region": {"startLine": 12, "startColumn": 5}
        }
      }],
      "codeFlows": [{
        "threadFlows": [{
          "locations": [
            {"location": {"physicalLocation": {"artifactLocation": {"uri": "main.c"}, "region": {"startLine": 5}}, "message": {"text": "p assigned NULL"}}},
            {"location": {"physicalLocation": {"artifactLocation": {"uri": "main.c"}, "region": {"startLine": 9}}, "message": {"text": "p passed"}}},
            {"location": {"physicalLocation": {"artifactLocation": {"uri": "main.c"}, "region": {"startLine": 12}}, "message": {"text": "dereferenced"}}}
          ]
        }]
      }]
    }]
  }]
}
```

Run: `python -m pytest tests/layer1/test_sarif_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentsast.layer1.sarif_parser'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/sarif_parser.py
from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import Anchor, Location, Severity

logger = logging.getLogger(__name__)


def _region_to_location(phys: dict, default_msg: str = "") -> Location:
    art = phys.get("artifactLocation", {})
    region = phys.get("region", {})
    uri = art.get("uri", "")
    fp = Path(str(uri).lstrip("/")) if Path(str(uri)).is_absolute() else Path(uri)
    return Location(
        file=fp,
        line=region.get("startLine", 0),
        col=region.get("startColumn", 0),
        end_line=region.get("endLine", 0),
        end_col=region.get("endColumn", 0),
        message=phys.get("message", {}).get("text", default_msg),
    )


def _extract_cwe(rule: dict) -> str:
    for tag in rule.get("properties", {}).get("tags", []):
        if isinstance(tag, str) and tag.startswith("CWE-"):
            return tag
    return ""


def _flow_to_path(result: dict) -> list[Location]:
    """把 result.codeFlows 展平成有序 Location 列表（source 在前）。"""
    path: list[Location] = []
    for flow in result.get("codeFlows", []):
        for tf in flow.get("threadFlows", []):
            for step in tf.get("locations", []):
                phys = step.get("location", {}).get("physicalLocation", {})
                msg = step.get("location", {}).get("message", {}).get("text", "")
                if phys:
                    path.append(_region_to_location(phys, msg))
    return path


def parse_sarif_to_anchors(sarif_path: Path) -> list[Anchor]:
    with open(sarif_path) as f:
        sarif = json.load(f)

    anchors: list[Anchor] = []
    for run in sarif.get("runs", []):
        driver = run.get("tool", {}).get("driver", {})
        tool_name = driver.get("name", "unknown")
        rules_map = {r["id"]: r for r in driver.get("rules", [])}

        for result in run.get("results", []):
            try:
                rule_id = result.get("ruleId", "unknown")
                locs = result.get("locations", [])
                if not locs:
                    continue
                sink = _region_to_location(
                    locs[0].get("physicalLocation", {}),
                    result.get("message", {}).get("text", ""),
                )
                dataflow = _flow_to_path(result)
                source = dataflow[0] if dataflow else None

                anchors.append(Anchor(
                    rule_id=rule_id,
                    tool=tool_name,
                    severity=Severity(result.get("level", "warning")),
                    message=result.get("message", {}).get("text", ""),
                    location=sink,
                    cwe=_extract_cwe(rules_map.get(rule_id, {})),
                    raw_sarif=result,
                    source_location=source,
                    dataflow_path=dataflow,
                ))
            except Exception:
                logger.exception("Failed to parse a SARIF result (ruleId=%s)", result.get("ruleId"))
                continue

    logger.info("SARIF parsed: %d anchors from %s", len(anchors), sarif_path)
    return anchors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_sarif_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/sarif_parser.py tests/fixtures/csa_null_deref.sarif tests/layer1/test_sarif_parser.py
git commit -m "feat(layer1): generic SARIF parser with codeFlows->dataflow_path"
```

---

### Task 7: Infer handler（从 message 提取 source/sink）

**Files:**
- Create: `src/agentsast/layer1/handlers/__init__.py`
- Create: `src/agentsast/layer1/handlers/infer.py`
- Create: `tests/fixtures/infer_null_deref.sarif`
- Test: `tests/layer1/test_handlers_infer.py`

> 背景：Infer 的 SARIF 不规范，source/sink 行号嵌在 `result.message.text` 中（如 `... assigned ... line 5 ... dereferenced ... line 12`）。通用层无法还原路径，需要本 handler 解析 message 并补全 `source_location`/`dataflow_path`。

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_handlers_infer.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.sarif_parser import parse_sarif_to_anchors
from agentsast.layer1.handlers import infer as infer_handlers  # noqa: F401  触发注册

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_infer_handler_extracts_path_from_message():
    anchors = parse_sarif_to_anchors(FIXTURES / "infer_null_deref.sarif")
    # parse_sarif_to_anchors 需在解析后调用 handler 覆写；本 task 先验证 handler 单体
```

> 注：完整的"parse 后自动应用 handler"接线放在 Task 11（InferScanner）做。本 Task 的测试聚焦 handler 单体函数：

```python
def test_infer_extract_locations_from_message():
    from agentsast.layer1.handlers.infer import extract_path_from_message
    msg = "pointer `p` assigned at line 5; dereferenced at line 12"
    sink_line, src_line = extract_path_from_message(msg)
    assert src_line == 5
    assert sink_line == 12
```

- [ ] **Step 2: Create fixture + run test to verify it fails**

```json
// tests/fixtures/infer_null_deref.sarif
{
  "version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
  "runs": [{
    "tool": {"driver": {"name": "Infer", "rules": [{"id": "NULL_DEREFERENCE"}]}},
    "results": [{
      "ruleId": "NULL_DEREFERENCE",
      "level": "error",
      "message": {"text": "pointer `p` assigned at line 5; dereferenced at line 12"},
      "locations": [{
        "physicalLocation": {
          "artifactLocation": {"uri": "main.c"},
          "region": {"startLine": 12, "startColumn": 5}
        }
      }]
    }]
  }]
}
```

Run: `python -m pytest tests/layer1/test_handlers_infer.py -v`
Expected: FAIL — `extract_path_from_message` 未定义

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/handlers/__init__.py
# (空文件，标记为包)
```

```python
# src/agentsast/layer1/handlers/infer.py
"""Infer SARIF 特化提取逻辑。参考 gen-auto/sarif/infer.py（逻辑参考，全新实现）。

Infer 的 source/sink 行号嵌在 result.message.text 中，SARIF 不提供 codeFlows，
故需要从 message 正则还原 source→sink。
"""
from __future__ import annotations

import re

# 匹配 "assigned at line N" / "line N" 形式
_ASSIGN_RE = re.compile(r"assigned(?:[^.]*?)line\s+(\d+)", re.IGNORECASE)
_DEREF_RE = re.compile(r"deref\w*(?:[^.]*?)line\s+(\d+)", re.IGNORECASE)


def extract_path_from_message(message: str) -> tuple[int | None, int | None]:
    """返回 (source_line, sink_line)；无法提取则为 None。"""
    src = _ASSIGN_RE.search(message)
    sink = _DEREF_RE.search(message)
    return (int(src.group(1)) if src else None,
            int(sink.group(1)) if sink else None)


def enhance_anchor(anchor) -> None:
    """对通用层产出的 Anchor 补全 source_location / dataflow_path（原地修改）。"""
    if anchor.source_location is not None and anchor.dataflow_path:
        return  # 通用层已还原，无需处理
    src_line, sink_line = extract_path_from_message(anchor.message)
    if src_line and sink_line:
        anchor.source_location = type(anchor.location)(
            file=anchor.location.file, line=src_line
        )
        anchor.dataflow_path = [
            type(anchor.location)(file=anchor.location.file, line=src_line),
            type(anchor.location)(file=anchor.location.file, line=sink_line),
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_handlers_infer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/handlers/ tests/fixtures/infer_null_deref.sarif tests/layer1/test_handlers_infer.py
git commit -m "feat(layer1): Infer handler extracting source/sink from message"
```

---

### Task 8: CSA handler（从 sink 反推 source）

**Files:**
- Create: `src/agentsast/layer1/handlers/csa.py`
- Test: `tests/layer1/test_handlers_csa.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_handlers_csa.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.models import Anchor, Location, Severity
from agentsast.layer1.handlers.csa import enhance_anchor, is_csa_result


def test_is_csa_result_detects_clang():
    a = Anchor(rule_id="core.NullDereference", tool="clang",
               severity=Severity.WARNING, message="m",
               location=Location(file=Path("a.c"), line=10))
    assert is_csa_result(a) is True


def test_enhance_uses_codeflows_when_present():
    a = Anchor(rule_id="core.NullDereference", tool="clang",
               severity=Severity.WARNING, message="m",
               location=Location(file=Path("a.c"), line=12),
               dataflow_path=[Location(file=Path("a.c"), line=5)])
    enhance_anchor(a)
    assert a.source_location is not None
    assert a.source_location.line == 5


def test_enhance_noop_without_info():
    a = Anchor(rule_id="core.NullDereference", tool="clang",
               severity=Severity.WARNING, message="no lines here",
               location=Location(file=Path("a.c"), line=12))
    enhance_anchor(a)
    assert a.source_location is None  # 无 codeFlows 且 message 无行号 → 保持空
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/layer1/test_handlers_csa.py -v`
Expected: FAIL — module 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/handlers/csa.py
"""CSA (Clang Static Analyzer) 特化。CSA 的 SARIF 通常带 codeFlows，
通用层即可还原路径；本 handler 处理无 codeFlows 时从 message 反推（参考 gen-auto/sarif/csa.py）。"""
from __future__ import annotations

import re

_LINE_RE = re.compile(r"line\s+(\d+)", re.IGNORECASE)


def is_csa_result(anchor) -> bool:
    return anchor.tool.lower() in ("clang", "csa") or anchor.rule_id.startswith("core.")


def enhance_anchor(anchor) -> None:
    if anchor.source_location is not None:
        return
    if anchor.dataflow_path:
        anchor.source_location = anchor.dataflow_path[0]
        return
    # 无 codeFlows：CSA message 一般不含行号，无法反推 → 保持空（保守，不编造）
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_handlers_csa.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/handlers/csa.py tests/layer1/test_handlers_csa.py
git commit -m "feat(layer1): CSA handler using codeFlows + conservative message fallback"
```

---

### Task 9: Cppcheck handler（XML → SARIF 适配）

**Files:**
- Create: `src/agentsast/layer1/handlers/cppcheck.py`
- Create: `tests/fixtures/cppcheck_buffer.xml`
- Test: `tests/layer1/test_handlers_cppcheck.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_handlers_cppcheck.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.handlers.cppcheck import cppcheck_xml_to_anchors

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_xml_to_anchors_basic():
    anchors = cppcheck_xml_to_anchors(FIXTURES / "cppcheck_buffer.xml")
    assert len(anchors) == 1
    a = anchors[0]
    assert a.tool == "Cppcheck"
    assert a.location.line == 8
    assert a.location.file.name == "main.c"
    assert a.rule_id == "bufferAccessOutOfBounds"
```

- [ ] **Step 2: Create fixture + run test to verify it fails**

```xml
<!-- tests/fixtures/cppcheck_buffer.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<results version="2">
  <cppcheck version="2.12.1"/>
  <errors>
    <error id="bufferAccessOutOfBounds" severity="error" msg="Buffer is accessed out of bounds." verbose="Buffer out of bounds at buf[64].">
      <location file="main.c" line="8" column="9"/>
    </error>
  </errors>
</results>
```

Run: `python -m pytest tests/layer1/test_handlers_cppcheck.py -v`
Expected: FAIL — module 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/handlers/cppcheck.py
"""Cppcheck XML → Anchor。参考 gen-auto/parse_cppcheck.py（全新实现，去除全局变量竞态）。

CWE 映射表（参考 gen-auto INTERESTED_ERRORS）。
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import Anchor, Location, Severity

logger = logging.getLogger(__name__)

CWE_MAP = {
    "bufferAccessOutOfBounds": "CWE-120",
    "nullPointer": "CWE-476",
    "memleak": "CWE-401",
    "deallocDealloc": "CWE-415",
    "integerOverflow": "CWE-190",
}
SEVERITY_MAP = {"error": Severity.ERROR, "warning": Severity.WARNING, "style": Severity.NOTE}


def cppcheck_xml_to_anchors(xml_path: Path) -> list[Anchor]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    anchors: list[Anchor] = []
    for err in root.iter("error"):
        error_id = err.get("id", "unknown")
        msg = err.get("msg", "")
        loc = err.find("location")
        if loc is None:
            continue
        anchors.append(Anchor(
            rule_id=error_id,
            tool="Cppcheck",
            severity=SEVERITY_MAP.get(err.get("severity", "warning"), Severity.WARNING),
            message=msg,
            location=Location(
                file=Path(loc.get("file", "")),
                line=int(loc.get("line", "0")),
                col=int(loc.get("column", "0")),
            ),
            cwe=CWE_MAP.get(error_id, ""),
        ))
    logger.info("Cppcheck XML parsed: %d anchors", len(anchors))
    return anchors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_handlers_cppcheck.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/handlers/cppcheck.py tests/fixtures/cppcheck_buffer.xml tests/layer1/test_handlers_cppcheck.py
git commit -m "feat(layer1): Cppcheck XML->Anchor adapter with CWE mapping"
```

---

## Phase 2:编译命令供应

### Task 10: compile.py 三入口优先级解析

**Files:**
- Create: `src/agentsast/layer1/compile.py`
- Test: `tests/layer1/test_compile.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_compile.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.compile import resolve_compile_commands


def test_explicit_compile_db_wins(tmp_path):
    db = tmp_path / "cc.json"
    db.write_text("[]")
    assert resolve_compile_commands(compile_db=db) == db


def test_compile_dir_resolves_json(tmp_path):
    (tmp_path / "compile_commands.json").write_text("[]")
    assert resolve_compile_commands(compile_dir=tmp_path) == tmp_path / "compile_commands.json"


def test_build_cmd_runs_bear(tmp_path, monkeypatch):
    # 伪造 bear 生成 cc.json
    out = tmp_path / "cc.json"
    monkeypatch.setattr(
        "agentsast.layer1.compile._run_subprocess",
        lambda cmd, cwd: (0, ""),
    )
    # 让 _write_fake 模拟 bear 产出文件
    def fake_gen(cmd, cwd, dest):
        dest.write_text("[]")
        return dest
    monkeypatch.setattr("agentsast.layer1.compile._generate_with_bear", fake_gen)
    result = resolve_compile_commands(build_cmd="make", build_dir=tmp_path)
    assert result == out or result.name == "compile_commands.json"


def test_none_when_nothing_provided():
    assert resolve_compile_commands() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/layer1/test_compile.py -v`
Expected: FAIL — module 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/compile.py
"""compile_commands.json 供应：用户直供(--compile-db/--compile-dir) > 本地生成(--build-cmd via Bear/intercept-build) > None。"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

COMPILE_DB_NAME = "compile_commands.json"


def _run_subprocess(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))
    return proc.returncode, proc.stdout + proc.stderr


def _generate_with_bear(build_cmd: str, build_dir: Path, dest: Path) -> Path:
    """用 Bear（make/autotools）拦截生成 compile_commands.json。"""
    bear = shutil.which("bear") or "bear"
    cmd = [bear, "--", *build_cmd.split()]
    rc, out = _run_subprocess(cmd, build_dir)
    if rc != 0:
        logger.warning("Bear build reported rc=%d: %s", rc, out[:200])
    # Bear 默认在 build_dir 产出 compile_commands.json
    produced = build_dir / COMPILE_DB_NAME
    if produced.exists():
        return produced
    return dest


def resolve_compile_commands(
    compile_db: Path | None = None,
    compile_dir: Path | None = None,
    build_cmd: str | None = None,
    build_dir: Path | None = None,
) -> Path | None:
    """按优先级解析 compile_commands.json 路径，无解则返回 None。"""
    # 1. 用户直供文件
    if compile_db is not None:
        if compile_db.exists():
            return compile_db
        logger.warning("--compile-db not found: %s", compile_db)
    # 2. 目录（远端同步产物）
    if compile_dir is not None:
        candidate = Path(compile_dir) / COMPILE_DB_NAME
        if candidate.exists():
            return candidate
        logger.warning("No %s under --compile-dir %s", COMPILE_DB_NAME, compile_dir)
    # 3. 本地生成
    if build_cmd is not None:
        bd = Path(build_dir) if build_dir else Path.cwd()
        dest = bd / COMPILE_DB_NAME
        try:
            return _generate_with_bear(build_cmd, bd, dest)
        except Exception:
            logger.exception("Failed to generate compile_commands via build-cmd")
    # 4. 都没有 → None（编译线扫描器将降级跳过）
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_compile.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/compile.py tests/layer1/test_compile.py
git commit -m "feat(layer1): compile_commands supply with db/dir/build-cmd priority"
```

---

## Phase 3:三件套扫描器

> 通用模式：每个 Scanner `requires_compilation=True`，`scan(ctx)` 在 `ctx.compile_db` 缺失时返回 `[]`，`is_available()` 探测二进制。`scan` 内：调用工具 → 产出文件 → 调 handler 增强后返回 Anchor 列表。

### Task 11: InferScanner

**Files:**
- Create: `src/agentsast/layer1/infer.py`
- Test: `tests/layer1/test_infer_scanner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_infer_scanner.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext
from agentsast.layer1.infer import InferScanner


def test_requires_compilation():
    assert InferScanner.requires_compilation is True


def test_scan_no_compile_db_returns_empty(tmp_path):
    scanner = InferScanner()
    ctx = ScanContext(target=tmp_path, compile_db=None)
    assert scanner.scan(ctx) == []


def test_scan_parses_report(monkeypatch, tmp_path):
    FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
    scanner = InferScanner()

    # 桩：跳过真实 infer 调用，直接用 fixture SARIF
    monkeypatch.setattr(scanner, "_run_infer", lambda ctx: FIXTURES / "infer_null_deref.sarif")

    ctx = ScanContext(target=tmp_path, compile_db=tmp_path / "cc.json")
    anchors = scanner.scan(ctx)
    assert len(anchors) == 1
    assert anchors[0].source_location is not None
    assert anchors[0].source_location.line == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/layer1/test_infer_scanner.py -v`
Expected: FAIL — module 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/infer.py
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .base import ScanContext, register_scanner
from .sarif_parser import parse_sarif_to_anchors
from .handlers import infer as infer_handler

logger = logging.getLogger(__name__)


@register_scanner("infer")
class InferScanner:
    name = "Infer"
    requires_compilation = True

    def __init__(self, timeout: int = 1800):
        self.timeout = timeout

    def is_available(self) -> bool:
        return shutil.which("infer") is not None

    def _run_infer(self, ctx: ScanContext) -> Path:
        """执行 infer，返回 report.sarif 路径。"""
        cmd = [
            "infer", "--sarif", "--biabduction", "--pulse",
            "--compilation-database", str(ctx.compile_db),
        ]
        out_dir = ctx.target / "infer-out"
        subprocess.run(cmd, capture_output=True, text=True,
                       cwd=str(ctx.target), timeout=self.timeout)
        return out_dir / "report.sarif"

    def scan(self, ctx: ScanContext) -> list:
        from .models import Anchor  # noqa: F401
        if ctx.compile_db is None or not self.is_available():
            logger.warning("Infer skipped (compile_db=%s, available=%s)",
                           ctx.compile_db, self.is_available())
            return []
        try:
            report = self._run_infer(ctx)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.exception("Infer execution failed")
            return []
        if not report.exists():
            logger.warning("Infer produced no report at %s", report)
            return []
        anchors = parse_sarif_to_anchors(report)
        for a in anchors:
            if a.tool.lower() == "infer":
                infer_handler.enhance_anchor(a)
        return anchors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_infer_scanner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/infer.py tests/layer1/test_infer_scanner.py
git commit -m "feat(layer1): InferScanner with SARIF parse + handler enhancement"
```

---

### Task 12: CsaScanner

**Files:**
- Create: `src/agentsast/layer1/csa.py`
- Test: `tests/layer1/test_csa_scanner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_csa_scanner.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext
from agentsast.layer1.csa import CsaScanner


def test_requires_compilation():
    assert CsaScanner.requires_compilation is True


def test_scan_parses_report(monkeypatch, tmp_path):
    FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
    scanner = CsaScanner()
    monkeypatch.setattr(scanner, "_run_csa", lambda ctx: FIXTURES / "csa_null_deref.sarif")
    ctx = ScanContext(target=tmp_path, compile_db=tmp_path / "cc.json")
    anchors = scanner.scan(ctx)
    assert len(anchors) == 1
    assert anchors[0].source_location is not None  # codeFlows 还原
    assert anchors[0].source_location.line == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/layer1/test_csa_scanner.py -v`
Expected: FAIL — module 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/csa.py
from __future__ import annotations

import glob
import logging
import shutil
import subprocess
from pathlib import Path

from .base import ScanContext, register_scanner
from .sarif_parser import parse_sarif_to_anchors
from .handlers import csa as csa_handler

logger = logging.getLogger(__name__)


@register_scanner("csa")
class CsaScanner:
    name = "CSA"
    requires_compilation = True

    def __init__(self, timeout: int = 1800):
        self.timeout = timeout

    def is_available(self) -> bool:
        return shutil.which("analyze-build") is not None

    def _run_csa(self, ctx: ScanContext) -> Path:
        out_dir = ctx.target / "result-csa"
        cmd = [
            "analyze-build", "--status-bugs", "--sarif",
            "-o", str(out_dir),
        ]
        subprocess.run(cmd, capture_output=True, text=True,
                       cwd=str(ctx.target), timeout=self.timeout)
        sarifs = glob.glob(str(out_dir / "*.sarif"))
        return Path(sarifs[0]) if sarifs else out_dir / "results-merged.sarif"

    def scan(self, ctx: ScanContext) -> list:
        if ctx.compile_db is None or not self.is_available():
            logger.warning("CSA skipped (compile_db=%s, available=%s)",
                           ctx.compile_db, self.is_available())
            return []
        try:
            report = self._run_csa(ctx)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.exception("CSA execution failed")
            return []
        if not report.exists():
            logger.warning("CSA produced no report at %s", report)
            return []
        anchors = parse_sarif_to_anchors(report)
        for a in anchors:
            if csa_handler.is_csa_result(a):
                csa_handler.enhance_anchor(a)
        return anchors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_csa_scanner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/csa.py tests/layer1/test_csa_scanner.py
git commit -m "feat(layer1): CsaScanner with SARIF parse + handler enhancement"
```

---

### Task 13: CppcheckScanner

**Files:**
- Create: `src/agentsast/layer1/cppcheck.py`
- Test: `tests/layer1/test_cppcheck_scanner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/layer1/test_cppcheck_scanner.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext
from agentsast.layer1.cppcheck import CppcheckScanner


def test_requires_compilation():
    assert CppcheckScanner.requires_compilation is True


def test_scan_parses_xml(monkeypatch, tmp_path):
    FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
    scanner = CppcheckScanner()
    monkeypatch.setattr(scanner, "_run_cppcheck", lambda ctx: FIXTURES / "cppcheck_buffer.xml")
    ctx = ScanContext(target=tmp_path, compile_db=tmp_path / "cc.json")
    anchors = scanner.scan(ctx)
    assert len(anchors) == 1
    assert anchors[0].tool == "Cppcheck"
    assert anchors[0].cwe == "CWE-120"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/layer1/test_cppcheck_scanner.py -v`
Expected: FAIL — module 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# src/agentsast/layer1/cppcheck.py
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .base import ScanContext, register_scanner
from .handlers.cppcheck import cppcheck_xml_to_anchors

logger = logging.getLogger(__name__)


@register_scanner("cppcheck")
class CppcheckScanner:
    name = "Cppcheck"
    requires_compilation = True

    def __init__(self, timeout: int = 1800):
        self.timeout = timeout

    def is_available(self) -> bool:
        return shutil.which("cppcheck") is not None

    def _run_cppcheck(self, ctx: ScanContext) -> Path:
        out = ctx.target / "cppcheck.xml"
        cmd = [
            "cppcheck", "--project=" + str(ctx.compile_db),
            "--xml", "--enable=all", "-j", "4",
        ]
        with open(out, "w") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE,
                           cwd=str(ctx.target), timeout=self.timeout)
        return out

    def scan(self, ctx: ScanContext) -> list:
        if ctx.compile_db is None or not self.is_available():
            logger.warning("Cppcheck skipped (compile_db=%s, available=%s)",
                           ctx.compile_db, self.is_available())
            return []
        try:
            xml = self._run_cppcheck(ctx)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.exception("Cppcheck execution failed")
            return []
        if not xml.exists():
            return []
        return cppcheck_xml_to_anchors(xml)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/layer1/test_cppcheck_scanner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/layer1/cppcheck.py tests/layer1/test_cppcheck_scanner.py
git commit -m "feat(layer1): CppcheckScanner with XML adapter"
```

---

## Phase 4:Pipeline 与 CLI 集成

### Task 14: Pipeline 传递 compile_db

**Files:**
- Modify: `src/agentsast/pipeline/engine.py`
- Test: `tests/test_pipeline.py`（追加用例，无需真跑工具）

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_pipeline.py
class TestPipelineCompileDb:
    def test_pipeline_accepts_compile_db(self, tmp_path):
        from agentsast.pipeline.engine import Pipeline
        p = Pipeline(tools=["semgrep"], compile_db=tmp_path / "cc.json")
        assert p.compile_db == tmp_path / "cc.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py::TestPipelineCompileDb -v`
Expected: FAIL — `Pipeline` 无 `compile_db` 参数

- [ ] **Step 3: Write minimal implementation**

修改 `src/agentsast/pipeline/engine.py`：`Pipeline.__init__` 增加 `compile_db: Path | None = None`；`run()` 中将 `compile_db` 传入 `layer1_scan`。

```python
class Pipeline:
    def __init__(
        self,
        tools: list[str] | None = None,
        semgrep_config: str = "p/c",
        max_call_depth: int = 2,
        llm_model: str = "gpt-4o",
        llm_api_key: str | None = None,
        llm_base_url: str | None = None,
        skip_llm: bool = False,
        compile_db: Path | None = None,          # 新增
    ):
        self.tools = tools or ["semgrep", "flawfinder"]
        self.semgrep_config = semgrep_config
        self.max_call_depth = max_call_depth
        self.skip_llm = skip_llm
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url
        self.compile_db = compile_db             # 新增

    def run(self, target, project_root=None):
        # ... 不变 ...
        anchors = layer1_scan(
            target, tools=self.tools, config=self.semgrep_config,
            compile_db=self.compile_db,           # 新增
        )
        # ... 其余不变 ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS（全部用例，含新增）

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/pipeline/engine.py tests/test_pipeline.py
git commit -m "feat(pipeline): thread compile_db through Pipeline.run to Layer1 scan"
```

---

### Task 15: CLI 扩展（--compile-db / --compile-dir / --build-cmd）

**Files:**
- Modify: `src/agentsast/cli.py`
- Test: `tests/test_cli.py`（新建）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from agentsast.cli import main


def test_cli_accepts_compile_options(tmp_path):
    runner = CliRunner()
    target = tmp_path / "a.c"
    target.write_text("int main(){return 0;}")
    result = runner.invoke(main, [
        str(target), "--skip-llm", "--tools", "flawfinder",
        "--compile-dir", str(tmp_path),
    ])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `--compile-dir` 未知选项

- [ ] **Step 3: Write minimal implementation**

修改 `src/agentsast/cli.py`：新增三个 click option，调用 `resolve_compile_commands`，传入 Pipeline。

```python
# 顶部 import 新增：
from .layer1.compile import resolve_compile_commands

# 在 main() 上新增 options（紧跟现有 --max-call-depth 之后）：
@click.option("--compile-db", type=click.Path(), default=None,
              help="Path to compile_commands.json (user-supplied)")
@click.option("--compile-dir", type=click.Path(), default=None,
              help="Directory containing compile_commands.json (remote-synced)")
@click.option("--build-cmd", default=None,
              help="Build command to generate compile_commands.json via Bear")

# main() 签名新增参数 + body：
def main(
    target, project_root, tools, semgrep_config, max_call_depth,
    llm_model, llm_api_key, llm_base_url, skip_llm, output, verbose,
    compile_db, compile_dir, build_cmd,            # 新增
):
    _setup_logging(verbose)

    compile_db_path = resolve_compile_commands(
        compile_db=Path(compile_db) if compile_db else None,
        compile_dir=Path(compile_dir) if compile_dir else None,
        build_cmd=build_cmd,
    )

    pipeline = Pipeline(
        tools=list(tools),
        semgrep_config=semgrep_config,
        max_call_depth=max_call_depth,
        llm_model=llm_model, llm_api_key=llm_api_key,
        llm_base_url=llm_base_url, skip_llm=skip_llm,
        compile_db=compile_db_path,                # 新增
    )
    # ... 其余 run / _print_results / output 不变 ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentsast/cli.py tests/test_cli.py
git commit -m "feat(cli): add --compile-db/--compile-dir/--build-cmd options"
```

---

## Phase 5:全量回归与端到端验证

### Task 16: 全量测试 + ruff/mypy + 端到端 SARIF 解析验证

**Files:**
- Test: `tests/layer1/test_e2e_sarif.py`（新建，无需真跑工具）

- [ ] **Step 1: Write the end-to-end test**

```python
# tests/layer1/test_e2e_sarif.py
"""端到端：用三件套 fixture 验证 Scanner 解析接线（桩掉真实工具调用）。"""
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext
from agentsast.layer1.infer import InferScanner
from agentsast.layer1.csa import CsaScanner
from agentsast.layer1.cppcheck import CppcheckScanner

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_e2e_all_three_parse_fixtures(monkeypatch, tmp_path):
    cc = tmp_path / "cc.json"
    ctx = ScanContext(target=tmp_path, compile_db=cc)

    infer = InferScanner()
    monkeypatch.setattr(infer, "_run_infer", lambda c: FIXTURES / "infer_null_deref.sarif")
    a_infer = infer.scan(ctx)
    assert a_infer and a_infer[0].source_location is not None

    csa = CsaScanner()
    monkeypatch.setattr(csa, "_run_csa", lambda c: FIXTURES / "csa_null_deref.sarif")
    a_csa = csa.scan(ctx)
    assert a_csa and a_csa[0].source_location is not None

    cpp = CppcheckScanner()
    monkeypatch.setattr(cpp, "_run_cppcheck", lambda c: FIXTURES / "cppcheck_buffer.xml")
    a_cpp = cpp.scan(ctx)
    assert a_cpp and a_cpp[0].cwe == "CWE-120"
```

- [ ] **Step 2: Run full suite + linters**

Run:
```bash
cd /home/atituiset/Projects/AgentSAST
python -m pytest -v
ruff check src tests
mypy src
```
Expected: 全部测试 PASS（原有 12 + 新增），ruff 无报错，mypy 无新增类型错误。

- [ ] **Step 3: 手动冒烟（可选，需装 flawfinder）**

Run: `python -m agentsast.cli samples/vulnerable_server.c --skip-llm --tools flawfinder`
Expected: 正常输出 Rich 表格（确认免编译线未破坏）。

- [ ] **Step 4: Commit**

```bash
git add tests/layer1/test_e2e_sarif.py
git commit -m "test(layer1): e2e SARIF/XML parsing for all three scanners"
```

- [ ] **Step 5: 收尾**

更新 `docs/ARCHITECTURE.md` §3.1 与 §7.2 路线图，把"Infer/CSA/Cppcheck 编译线接入"标记为已完成；在 §3.1 扫描器表追加三行。

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs: mark Layer1 compilation-line (Infer/CSA/Cppcheck) as done"
```

---

## Self-Review（spec 覆盖核对）

- spec §5.1 Anchor 扩展 → **Task 1** ✓
- spec §5.2 Scanner Protocol + 注册 → **Task 2-5** ✓
- spec §5.3 SARIF 解析分层(通用+handler) → **Task 6-9** ✓
- spec §5.4 编译命令供应(三入口+统一纽带) → **Task 10** ✓（统一纽带跨 Layer2 部分留 Plan 2）
- spec §5.5 三件套扫描器 → **Task 11-13** ✓
- spec §5.8 CLI → **Task 14-15** ✓
- spec §6 降级策略(工具缺失/编译缺失) → **Task 5**(scan 跳过)+ **Task 11-13**(is_available/compile_db 检查)✓
- spec §7 测试策略(fixture/契约/降级/优先级) → 各 Task 测试 ✓
- spec §5.6-5.7 Layer2 MCP 后端 → **明确留 Plan 2**（本计划不实现，避免范围蔓延）

**类型一致性**：`ScanContext.compile_db: Path | None`、`Scanner.requires_compilation: bool`、`Anchor.source_location: Location | None`、`Anchor.dataflow_path: list[Location]` 在所有 Task 中一致；`scan()` 签名 `scan(target, tools, config, compile_db)` 与 Pipeline/CLI 调用一致。

**无占位符**：所有 step 含可执行代码与命令；Task 3/4 的"现有 scan 主体原样移入"已给出明确的移入方式（三元式取 target），非占位符。

---

## 后续：Plan 2（Layer2 可插拔后端 + MCP 接入）

本计划交付后，再开一个独立 spec/plan 实现 spec §5.6–5.7：
- `layer2/backend.py`：`ProgramUnderstandingBackend` Protocol
- `layer2/treesitter_backend.py`：封装现有 slicer 逻辑（行为零变化）
- `layer2/mcp_lsp_backend.py`：MCP client → mcp-language-server(clangd)
- `cli.py`：`--l2-backend {treesitter,mcp-lsp}`
- 依赖 Plan 1 的 `Anchor` 扩展与 `compile.py`（统一纽带）

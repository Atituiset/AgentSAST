# 设计规格:静态分析能力桥接 —— gen-auto 三件套 + SARIF 标准化 + MCP 语义后端

- **日期**:2026-06-25
- **状态**:Draft(待评审)
- **所属项目**:AgentSAST(`/home/atituiset/Projects/AgentSAST`)
- **参考实现**:`vul-auto-private/gen-auto`(仅作逻辑参考,代码全新实现)
- **外部依赖**:`isaacphi/mcp-language-server`(Go,通过 MCP 协议接入)

---

## 1. 背景与动机

AgentSAST 是一个面向 C/C++ 的三层静态分析工具:Layer1 高召回锚点识别 → Layer2 程序切片 → Layer3 LLM 裁判。其产品定位为**"静态初筛 + LLM 二次校准,以提高 True Case(真阳/召回)比率"**。

当前 Layer1 仅有 **Semgrep(语法级 AST)** 与 **Flawfinder(函数词典)** 两个免编译扫描器,对**深层语义缺陷**(空指针解引用 NPE、Double Free、Resource Leak、Buffer/Integer Overflow)召回不足。`vul-auto-private/gen-auto` 已成熟集成 **Infer / CSA / Cppcheck** 三大编译期深度分析器,并具备高质量的 SARIF/XML 解析与缺陷路径还原逻辑。

本设计将 gen-auto 的三件套扫描与解析能力**以原生编译、两线并存的形态接入 AgentSAST Layer1**,以 SARIF v2.1.0 作为工具→AgentSAST 的统一传递载体,扩展数据模型保留 source→sink 路径,并额外引入 `mcp-language-server`(clangd)作为 Layer2 的高精度程序理解后端,目标是显著提升内存安全缺陷的召回与判定质量。

## 2. 设计目标与非目标

### 目标
1. **Layer1 三件套齐上**:Infer / CSA / Cppcheck 作为新扫描器接入,与现有免编译线并存。
2. **弹性可插拔扫描器层**:定义 `Scanner` 统一抽象,自研工具实现接口 + 注册即可被 `--tools` 调用,零侵入。
3. **SARIF 标准化传递**:工具(Infer/CSA 原生 SARIF、Cppcheck XML→SARIF 适配)→ 统一解析 → `Anchor`;解析其 `codeFlows` 还原 source→sink 路径。
4. **保留缺陷路径**:扩展 `Anchor` 增加 `source_location` / `dataflow_path`,供 Layer2/Layer3 使用。
5. **编译命令统一供应**:`--compile-db` / `--compile-dir` / `--build-cmd` 三入口,一份 `compile_commands.json` 同时供给 Layer1 编译线与 Layer2 clangd。
6. **MCP 语义后端**:AgentSAST 作为 MCP client 消费 `mcp-language-server`,作为 Layer2 可选高精度后端。

### 非目标(本期不做)
- 不在 AgentSAST 环境内捆绑安装 Infer/CSA/Cppcheck/clangd,通过 `is_available()` 探测,缺失则降级。
- 不实现 gen-auto 的 arch-auto 大规模 Celery 流水线与投票聚合(那是数据集构建场景)。
- 不做 SARIF 回写输出为 v0.3+ 范围(预留接口,本期实现到 Anchor 层)。
- 不引入 `sarif-om` / `prettytable` 等 gen-auto 依赖,全部用纯 JSON 遍历重写。

## 3. 核心设计决策(含理由)

| # | 决策 | 理由 |
|---|---|---|
| D1 | 三件套**一并实现**,不分阶段 MVP | 用户明确要求三套齐上;共享 `Scanner` Protocol + `sarif_parser` 使增量可控 |
| D2 | **全新实现**,gen-auto 仅作逻辑参考 | 保持 AgentSAST 依赖轻量、风格统一,不带 gen-auto 的硬编码路径/耦合/已知 bug |
| D3 | 扩展 `Anchor` 保留路径,**非**新建 SARIF-native 模型 | 复用现有三层架构,避免数据类型分裂;路径直接服务召回目标 |
| D4 | **原生编译、两线并存**(不走 Docker) | 用户选择;与 ARCHITECTURE.md §7.3"高精度 CI/CD 路线"对齐 |
| D5 | SARIF codeFlows 是路径主载体;工具 handler 处理不规范 SARIF | Infer 的 source/sink 嵌在 message 文本里,需特化提取 |
| D6 | mcp-language-server 放 **Layer2**,作可插拔后端 | 其 callers/callees/definition/references 是 clangd 语义级,正好补 tree-sitter 的短板 |
| D7 | AgentSAST 作 **MCP client**(非直接 LSP) | 用户明确"接入该 mcp 工具";保留 mcp-language-server 的工具封装层 |
| D8 | compile_commands.json **统一供应**两层 | clangd 与 Infer/CSA/Cppcheck 同样需要它;"远端同步"机制一次配置多处受益 |

## 4. 总体架构

```
                           ┌── compile_commands.json ──┐  统一纽带
                           │ (用户直供/远端同步/本地生成) │
   源码 ───────────────────┼───────────────────────────┼──────────────────┐
                           ▼                           ▼                  ▼
   Layer1 锚点识别   免编译线(保留)              编译线(新增)         弹性层
   (Scanner Protocol)  Semgrep/Flawfinder ──┬──► Infer   → SARIF ─┐   ┌──────────┐
                                          │   CSA     → SARIF ──┼─► │ 自研工具  │
                                          │   Cppcheck→ XML→SARIF┘   │ (Protocol │
                                          └───────────────────────► │  +注册)   │
                                              统一: SARIF codeFlows → Anchor.dataflow_path
                                                                  │
   Layer2 切片引擎   ProgramUnderstandingBackend(可插拔)         │
                     ├─ TreeSitterBackend (免编译,默认) ◄────────┤
                     └─ McpLspBackend (clangd,编译期高精度)       │
                        └► MCP client → mcp-language-server       │
                           callers/callees/definition/references   │
                    source_location 起步逆向切片 ◄─────────────────┘
                                                                  │
   Layer3 LLM 裁判   Anchor(sink + dataflow_path) + 切片上下文 ──► 判真伪
```

## 5. 详细设计

### 5.1 数据模型扩展(`layer1/models.py`)

给 `Anchor` 增加两个**可选**字段(免编译扫描器留空,完全向后兼容):

```python
@dataclass
class Location:
    file: Path
    line: int
    col: int = 0
    end_line: int = 0
    end_col: int = 0
    message: str = ""                 # 新增:位置说明(SARIF location.message)

@dataclass
class Anchor:
    rule_id: str
    tool: str
    severity: Severity
    message: str
    location: Location                # sink 位置(语义不变,与现有一致)
    cwe: str = ""
    sink_function: str = ""
    sink_params: list[str] = field(default_factory=list)
    raw_sarif: dict = field(default_factory=dict)
    # —— 新增 ——
    source_location: Location | None = None                # 缺陷源头(赋值/分配点)
    dataflow_path: list[Location] = field(default_factory=list)  # source→…→sink 有序路径
```

- `location` 语义不变(仍为 sink/触发点),保证 Layer2/Layer3 现有逻辑不受影响。
- Layer2 切片优先用 `source_location` 作为逆向切片起点(若有),提升精度。
- Layer3 Prompt 增量注入 `dataflow_path`(若有),让 LLM 看到完整触发链。
- `to_dict()` 同步序列化新字段。

### 5.2 Layer1 可插拔扫描器层(`layer1/base.py` 新增)

```python
@dataclass
class ScanContext:
    target: Path
    compile_db: Path | None           # compile_commands.json 路径(编译线扫描器用)
    timeout: int = 600
    config: dict = field(default_factory=dict)

class Scanner(Protocol):
    name: str                         # 工具展示名,如 "Infer"
    requires_compilation: bool        # 是否需要 compile_db
    def is_available(self) -> bool: ...
    def scan(self, ctx: ScanContext) -> list[Anchor]: ...

SCANNER_REGISTRY: dict[str, type[Scanner]] = {}

def register_scanner(key: str):
    """装饰器:注册扫描器,使其可被 --tools <key> 选中"""
    def deco(cls): SCANNER_REGISTRY[key] = cls; return cls
    return deco
```

- 现有 `SemgrepScanner` / `FlawfinderScanner` 改为实现该 Protocol 并 `@register_scanner`。
- 新增 `InferScanner` / `CsaScanner` / `CppcheckScanner` 同样实现并注册。
- **自研工具接入**:实现 `Scanner` + `@register_scanner("my-tool")` 即可,`--tools my-tool` 立即可用。MVP 用显式装饰器注册;后续可升级到 `importlib.metadata` entry_points 自动发现。
- `scan()` 统一入口改写为基于 `SCANNER_REGISTRY` 分发;编译线扫描器在 `ctx.compile_db is None` 时自动跳过并 warning。

### 5.3 SARIF 解析分层(`layer1/sarif_parser.py` 新增)

```
通用层  parse_sarif_to_anchors(sarif: dict) -> list[Anchor]
        - 遍历 runs[].results[]
        - locations[0].physicalLocation → Anchor.location (sink)
        - ★ 解析 result.codeFlows[].threadFlows[].locations[] → dataflow_path
          + 取首个非 sink 节点作 source_location
        - rule.tags 中提取 CWE

工具层  handlers/<tool>.py  handle_<rule_id>(result: dict) -> Anchor | None
        - 处理不规范 SARIF:Infer 的 source/sink 在 message.text(正则提取 + 跨函数路径修复)
        - CSA 的 source 从 sink 反推
        - 逻辑参考 gen-auto/sarif/{infer,csa}.py,纯 dict 操作重写
```

- 对规范 SARIF(CSA 多数 rule),通用层直接产出带 `dataflow_path` 的 Anchor。
- 对 Infer 这类不规范 SARIF,通用层先产出骨架,工具层 handler 覆写 `source_location`/`dataflow_path`。
- 解析失败/格式不符的单条结果**跳过并计数**(参考 gen-auto `SKIP_ON_PARSING_ERROR`),不中断整体。
- Cppcheck 输出 XML,先经 `cppcheck_xml_to_sarif()` 转成最小 SARIF 结构再走通用层(**统一 SARIF 传递**,与 D5 一致;XML handler 逻辑参考 gen-auto `parse_cppcheck.py` 重写)。

### 5.4 编译命令供应机制(`layer1/compile.py` 新增)

**三入口,优先级递减**:

| CLI 参数 | 来源 | 说明 |
|---|---|---|
| `--compile-db <file>` | 用户直供 | 直接指向单个 `compile_commands.json` |
| `--compile-dir <dir>` | 远端同步 | 指向含 `compile_commands.json` 的目录(如 build/,远端编译产物同步过来) |
| `--build-cmd "..."` | 本地生成 | AgentSAST 用 **Bear**(make/autotools)或 **intercept-build**(CMake)拦截生成 |

解析流程:
1. `--compile-db` / `--compile-dir` 命中 → 直接使用(**优先**,远端已编译场景)
2. 否则 `--build-cmd` → `resolve_compile_commands()` 用 Bear/intercept-build 生成
3. 都没有 → `compile_db = None`,所有 `requires_compilation=True` 的扫描器跳过,仅跑免编译线

**统一纽带**:解析出的 `compile_db`(指向 `compile_commands.json` **文件**)注入 `ScanContext`,供 Layer1 编译线扫描器使用;其所在**目录** `compile_db.parent` 作为 clangd 的 `--compile-commands-dir` 传给 Layer2 `McpLspBackend`。即一份编译数据库同时驱动两层编译期后端。

### 5.5 三件套扫描器(`layer1/infer.py` / `csa.py` / `cppcheck.py` 新增)

| 扫描器 | 调用(参考 gen-auto `analyzer.py`) | 输出 | 解析 |
|---|---|---|---|
| `InferScanner` | `infer --sarif --biabduction --pulse --compilation-database <db>` | `infer-out/report.sarif` | sarif_parser + handlers/infer |
| `CsaScanner` | `intercept-build <build-cmd>` → `analyze-build --status-bugs --sarif -o result-csa` | `result-csa/*.sarif` | sarif_parser + handlers/csa |
| `CppcheckScanner` | `cppcheck --project=<db> --xml --enable=all` | `dump.xml` | cppcheck_xml_to_sarif → sarif_parser |

- 每个扫描器实现 `is_available()`(探测二进制)与 `scan()`(subprocess 调用 + 解析)。
- 超时/缺失/解析失败均返回 `[]` 并 log,不抛异常(容错隔离)。
- 缺陷类型映射:CWE 表参考 gen-auto(见附录)。

### 5.6 Layer2 可插拔程序理解后端(`layer2/backend.py` 新增)

```python
class ProgramUnderstandingBackend(Protocol):
    def find_callers(self, func_name: str, loc: Location) -> list[FunctionRef]: ...
    def find_callees(self, func_name: str, loc: Location) -> list[FunctionRef]: ...
    def definition_of(self, symbol: str, loc: Location) -> Location | None: ...
    def references_of(self, symbol: str, loc: Location) -> list[Location]: ...
    def find_struct_usage(self, type_name: str) -> list[Location]: ...
```

- 现有 `SlicingEngine` 中直接调用 tree-sitter 的逻辑,重构为依赖该接口。
- **两个实现**:
  - `TreeSitterBackend`:封装现有 `parser.py`/`slicer.py` 逻辑(免编译,默认)。
  - `McpLspBackend`:见 5.7。
- 通过 `--l2-backend {treesitter,mcp-lsp}` 选择,默认 `treesitter`。

### 5.7 mcp-language-server 接入(`layer2/mcp_lsp_backend.py` 新增)

- AgentSAST 引入 Python `mcp` SDK,作为 **MCP client**。
- 启动方式:stdio 子进程 `mcp-language-server --workspace <root> --lsp clangd -- --compile-commands-dir=<db_dir>`。
- 映射 MCP tools → 后端接口:
  - `callers` → `find_callers`
  - `callees` → `find_callees`
  - `definition` → `definition_of`
  - `references` → `references_of`
  - `find_struct_usage` → `find_struct_usage`
- 连接管理:lazy 初始化、进程健康检查、超时与重连;不可用时降级到 `TreeSitterBackend`。
- clangd 同样需要 `compile_commands.json`(由 5.4 统一供应),`--compile-commands-dir` 指向其所在目录。

### 5.8 CLI 接口(`cli.py` 扩展)

新增参数:
| 参数 | 默认 | 说明 |
|---|---|---|
| `--tools` | `semgrep flawfinder` | 扩展可选值:`infer csa cppcheck` 及任意已注册自研工具 |
| `--compile-db` | None | compile_commands.json 文件路径 |
| `--compile-dir` | None | 含 compile_commands.json 的目录(远端同步) |
| `--build-cmd` | None | 本地生成 compile_commands 的 build 命令 |
| `--l2-backend` | `treesitter` | Layer2 后端:`treesitter` / `mcp-lsp` |

## 6. 错误处理与降级策略

| 场景 | 行为 |
|---|---|
| 编译线工具未安装 | `is_available()=False`,该扫描器跳过,warning,继续免编译线 |
| compile_commands 缺失 | 所有 `requires_compilation` 扫描器跳过;Layer2 mcp-lsp 后端不可用,降级 treesitter |
| 工具执行超时/失败 | 返回 `[]`,log,不中断 |
| 单条 SARIF 解析失败 | 跳过并计数(SKIP_ON_PARSING),不中断 |
| mcp-language-server 不可用 | Layer2 降级到 treesitter |
| 任何一层异常 | 单 Anchor 标记 uncertain(沿用现有容错) |

## 7. 测试策略

- **数据驱动验证(无需真跑工具)**:用 gen-auto 仓库中真实的 Infer/CSA SARIF、Cppcheck XML 样本作为 fixtures,验证 `sarif_parser` 正确还原 `dataflow_path`/`source_location`,并与 gen-auto 的解析结果对照(逻辑等价性)。
- **Protocol 契约测试**:为 `Scanner` / `ProgramUnderstandingBackend` 写契约测试,确保现有与新增实现都满足接口。
- **注册机制测试**:自定义一个 fake scanner,验证 `@register_scanner` 后能被 `--tools` 选中并执行。
- **降级测试**:compile_commands 缺失/工具缺失时,验证流程仍跑通(仅免编译线)。
- **编译供应优先级测试**:`--compile-db`/`--compile-dir`/`--build-cmd` 的解析与优先级。
- **MCP 后端**:用 mock MCP server 测试 `McpLspBackend` 接口映射与降级(不依赖真实 clangd)。
- 现有 `tests/test_pipeline.py` 的 12 个用例须保持通过(向后兼容)。

## 8. 风险与边界

| 风险 | 等级 | 缓解 |
|---|---|---|
| 编译环境依赖重(LLVM/Infer/CSA/clangd) | 🔴 | 文档明确前置;探测+降级;不捆绑安装 |
| 通用项目 build 探测难(非 makepkg) | 🟠 | MVP 要求 `--build-cmd`/`--compile-db`,不自动猜 build 系统 |
| Infer SARIF 不规范(source/sink 在 message) | 🟠 | 参考 gen-auto handler 正则+跨函数修复逻辑重写 |
| 引入 MCP SDK 增加依赖与复杂度 | 🟡 | mcp-lsp 为可选后端,默认 treesitter;依赖放 optional |
| Layer2 重构为后端接口的回归风险 | 🟡 | 先抽接口、TreeSitterBackend 行为零变化,再做 McpLspBackend |
| gen-auto 技术债带入 | 🟡 | 重写不搬运,明确剥离硬编码/`config` 耦合/已知 bug |

## 9. 实现范围

本期一次性交付:
1. `Anchor` 扩展(`source_location` / `dataflow_path`)+ 序列化。
2. `Scanner` Protocol + 注册机制;现有两扫描器改造。
3. `sarif_parser`(通用 codeFlows)+ `handlers/{infer,csa,cppcheck}`(全新实现)。
4. `compile.py` 三入口编译供应 + 统一纽带。
5. 三扫描器 `InferScanner`/`CsaScanner`/`CppcheckScanner`。
6. `ProgramUnderstandingBackend` 接口 + `TreeSitterBackend`(重构)+ `McpLspBackend`(MCP client)。
7. CLI 参数扩展。
8. 测试:数据驱动 fixtures + 契约 + 降级 + 优先级。

## 10. 未来扩展

- SARIF 回写输出(`*.sarif`,接 IDE/GitHub)。
- 自研扫描器 entry_points 自动发现(免手动注册)。
- clangd `diagnostics` 作为 Layer1 附加信号源。
- 多工具锚点投票/聚合(参考 gen-auto Vote,但修正其"Infer-anchored 标注"语义)。

## 附录:与 gen-auto 的对照(移植逻辑,不搬代码)

| gen-auto 元素 | AgentSAST 对应 | 处理 |
|---|---|---|
| `parse_sarif.py` + `sarif-om` | `sarif_parser.py` 纯 JSON | 重写,去依赖 |
| `sarif/infer.py` / `csa.py` handler | `handlers/infer.py` / `csa.py` | 移植提取逻辑 |
| `parse_cppcheck.py` | `cppcheck.py` + XML→SARIF | 移植,去全局变量竞态 |
| `analyzer.py` 命令模板 | 各 Scanner.scan() | 移植命令,去硬编码路径 |
| `config.SARIF_SCHEMA`/`SKIP_ON_PARSING_ERROR` | AgentSAST 本地配置/常量 | 重写 |
| `Vote`(投票) | **不移植**(本期非目标) | 留待未来 |
| 自定义 IR `{type,locations}` | 扩展 `Anchor` | 语义映射 |

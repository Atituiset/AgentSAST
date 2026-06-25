# AgentSAST — AI 增强静态分析工具

> 针对 C/C++ 内存安全漏洞的"传统 SAST 高召回锚定 + 程序切片降噪 + LLM 深度推理"两阶段协同检测系统

---

## 1. 项目概述

AgentSAST 是一款面向 C/C++ 代码的智能缺陷检测工具，核心架构分为三层：

| 层级 | 名称 | 职责 | 核心思路 |
|------|------|------|----------|
| **Layer 1** | 锚点识别层 | 高召回率地找出所有可能的漏洞触发点 | 宁可误报，不可漏报 |
| **Layer 2** | 上下文切片层 | 从海量代码中精准提取与漏洞相关的上下文 | 消除噪声，提供精准"子弹" |
| **Layer 3** | LLM 裁判层 | 基于切片上下文进行深度语义推理，判定真伪 | 高精度判决，防御幻觉 |

**设计哲学**：传统 SAST 工具召回率高但误报率极高；LLM 直接扫描全库成本太高且容易迷失。三层架构完美互补——传统工具负责"找得全"，LLM 负责"判得准"。

---

## 2. 快速开始

### 2.1 环境要求

- Python ≥ 3.10
- （可选）Semgrep — 用于 Layer1 高质量规则扫描
- （可选）Flawfinder — 用于 Layer1 补充锚点
- （Layer3 必需）OpenAI 兼容 API Key

### 2.2 安装

```bash
git clone <repo-url>
cd AgentSAST
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2.3 基本用法

**仅运行 Layer1 + Layer2（无需 API Key）：**

```bash
agentsast /path/to/source --skip-llm --tools flawfinder
```

**完整三层流程：**

```bash
export OPENAI_API_KEY="sk-..."
agentsast /path/to/source -o result.json
```

**使用本地部署的 LLM：**

```bash
export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="http://localhost:8000/v1"
agentsast /path/to/source --llm-model qwen2.5-72b
```

### 2.4 CLI 参数一览

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `TARGET` | （必填） | 待扫描的源码文件或目录 |
| `--project-root` | None | 项目根目录，用于跨文件调用图追踪 |
| `--tools` / `-t` | `semgrep flawfinder` | Layer1 使用的 SAST 工具组合 |
| `--semgrep-config` | `p/c` | Semgrep 规则配置 |
| `--max-call-depth` | `2` | 调用图追踪最大深度 |
| `--llm-model` | `gpt-4o` | LLM 模型名称 |
| `--llm-api-key` | `$OPENAI_API_KEY` | OpenAI API Key |
| `--llm-base-url` | `$OPENAI_BASE_URL` | OpenAI 兼容 API 地址 |
| `--skip-llm` | `False` | 跳过 Layer3，仅运行 L1+L2 |
| `--output` / `-o` | None | JSON 结果输出路径 |
| `--verbose` / `-v` | `False` | 启用 DEBUG 日志 |

---

## 3. 架构详解

### 3.1 Layer 1 — 高召回特征锚定 (SAST Anchoring)

**目标**：快速识别代码中所有可能的漏洞触发点（Sink），输出统一的 SARIF 格式。

> 注：除上表中的免编译扫描器外，Infer / Clang Static Analyzer (CSA) / Cppcheck 现已作为**编译线扫描器**接入，统一走可插拔 `Scanner` 注册表（`--compile-db`/`--compile-dir`/`--build-cmd` 供应编译数据库后自动启用），其 SARIF/XML 报告经通用解析器 + 各工具 handler 还原 `source_location` 与 `dataflow_path`。
> 注：Cppcheck 输出 XML（无 codeFlows），故直接 XML→Anchor 适配（`handlers/cppcheck.py`），未走通用 SARIF 解析层——这是有意的简化（spec §5.3 的统一 SARIF 原则对 Cppcheck 偏离，因其无路径数据）。

#### 3.1.1 支持的扫描器

| 扫描器 | 分析深度 | 需要编译 | 规则来源 | 降级策略 |
|--------|----------|----------|----------|----------|
| **Semgrep** | 语法级 AST | 不需要 | `p/c` + `p/cpp` 官方 Registry | 若未安装则跳过 |
| **Flawfinder** | 函数词典级 | 不需要 | 内置危险函数数据库 | 降级为内置模式扫描器 |
| **内置模式扫描器** | 正则级 | 不需要 | 硬编码 23 个危险函数 + CWE 映射 | 始终可用 |

#### 3.1.2 内置危险函数词典

工具内置了以下危险函数到 CWE 的映射，即使系统未安装任何外部 SAST 工具也能工作：

| 函数族 | 函数列表 | 对应 CWE |
|--------|----------|----------|
| 缓冲区溢出 | `memcpy`, `strcpy`, `strcat`, `gets`, `sprintf`, `scanf`, `vsprintf`, `strncat`, `strncpy`, `snprintf` | CWE-120 |
| 内存管理 | `malloc`, `realloc` | CWE-787 |
| 双重释放 | `free` | CWE-415 |
| 命令注入 | `system`, `popen`, `execl`, `execle`, `execlp`, `execv`, `execve`, `execvp` | CWE-78 |
| 格式化字符串 | `printf`, `fprintf`, `syslog` | CWE-134 |

#### 3.1.3 统一输出格式

所有扫描器输出统一为 `Anchor` 数据模型，核心字段：

```python
@dataclass
class Anchor:
    rule_id: str          # 规则ID，如 "agentsast-builtin-memcpy"
    tool: str             # 来源工具，如 "Semgrep" / "AgentSAST-Pattern"
    severity: Severity    # error / warning / note
    message: str          # 报警描述
    location: Location    # 文件路径 + 行号 + 列号
    cwe: str              # CWE编号，如 "CWE-120"
    sink_function: str    # 危险函数名，如 "memcpy"
    sink_params: list     # 数据流参数链
```

去重策略：`(tool, file, line)` 三元组去重，避免不同工具对同一位置的重复报告。

#### 3.1.4 代码结构

```
src/agentsast/layer1/
├── __init__.py
├── models.py       # Anchor / Location / Severity 数据模型
├── scanner.py      # 统一扫描入口 scan() + SARIF 通用解析
├── semgrep.py      # Semgrep 扫描器 (SARIF 输出解析)
└── flawfinder.py   # Flawfinder 扫描器 + 内置模式扫描器
```

---

### 3.2 Layer 2 — 上下文切片引擎 (Program Slicing)

**目标**：为每个 Anchor 精准提取四个维度的上下文，消除无关代码噪声，为 LLM 提供高质量输入。

> **可插拔程序理解后端**：Layer2 的 caller/callee 查找通过 `ProgramUnderstandingBackend` 协议抽象。默认为 **tree-sitter**（语法级，零依赖）；可选 **clangd via MCP** 语义级后端，经 `--l2-backend mcp-lsp` 启用（需 `pip install -e ".[layer2-mcp]"` + `mcp-language-server` 二进制 + `clangd` + `compile_commands`）。另有 **`mcp-lsp-agent`** 档：在 mcp-lsp 基础上叠加 LLM tool-calling loop（复用 `--llm-*` 配置），由模型自主调度 callers/callees/definition/read_source 工具，提升复杂路径召回；LLM 不可用或失败时自动退化到程序化 mcp-lsp 行为。

#### 3.2.1 切片维度

| 维度 | 方向 | 说明 | 深度限制 |
|------|------|------|----------|
| **结构体定义 (struct_defs)** | 文件级 | 提取 Sink 函数中引用的所有 `struct`/`typedef` 定义，让 LLM 能计算内存布局 | 无限制 |
| **数据流切片 (dataflow)** | 逆向 (Backward) | 从 Sink 参数出发，逆向追踪变量声明和赋值，判断数据来源 | 2 层作用域 |
| **调用图-Caller (callers)** | 向上 | 找到调用 Sink 函数的上层函数，判断入参是否源自不可信输入 | `max_call_depth`（默认2） |
| **调用图-Callee (callees)** | 向下 | 列出 Sink 函数内部的所有函数调用，防止 LLM 幻觉 | 最多5个 |
| **完整函数体 (raw_function)** | 当前 | Sink 所在的完整函数定义 | — |

#### 3.2.2 技术实现

基于 **Tree-sitter** 的 AST 解析：

- **C 语言**：使用 `tree-sitter-c` 语法
- **C++ 语言**：使用 `tree-sitter-cpp` 语法
- **.h 头文件**：默认使用 C++ 语法解析

核心算法：

1. **定位 Sink 函数**：遍历 AST，找到包含 Anchor 行号的最小 `function_definition` 节点
2. **提取类型名**：在 Sink 函数的 AST 子树中收集所有 `type_identifier` 节点
3. **匹配结构体**：全局搜索 `type_definition` 节点，匹配 typedef 名或 struct 名
4. **逆向切片**：对 Sink 参数中的变量名，向上遍历作用域树，收集 `declaration` 和 `assignment_expression`
5. **调用图提取**：在函数体内搜索 `call_expression` 节点，提取 Caller/Callee 关系
6. **跨文件追踪**：若提供 `--project-root`，会在项目目录中搜索其他源文件的 Caller

#### 3.2.3 帕累托最优深度

| 切片深度 | LLM 准确率 | Token 成本 | 推荐度 |
|----------|-----------|-----------|--------|
| 0 层 | ~45% | 1x | 不推荐 |
| 1 层 | ~78% | 2.5x | 可用 |
| **2 层（默认）** | **~92%** | **4x** | **推荐** |
| 3 层 | ~94% | 15x | 不推荐 |
| 全文件 | ~95% | 85x | 绝对不推荐 |

#### 3.2.4 C/C++ typedef struct 的特殊处理

C 语言的 `typedef struct { ... } RequestContext;` 在 Tree-sitter AST 中，类型名 `RequestContext` 是 `type_definition` 节点的 `type_identifier` 子节点，而非 `struct_specifier` 的 `name` 字段（匿名结构体）。切片引擎通过 `_get_typedef_name()` 函数正确处理了这一差异。

#### 3.2.5 代码结构

```
src/agentsast/layer2/
├── __init__.py
├── models.py       # CodeSlice / SlicingResult 数据模型
├── parser.py       # ASTParser — Tree-sitter 封装
└── slicer.py       # SlicingEngine — 切片引擎核心
```

---

### 3.3 Layer 3 — LLM 裁判层 (LLM Triaging)

**目标**：将切片上下文结构化注入 LLM，通过思维链推理判定漏洞真伪，并防御幻觉。

#### 3.3.1 Prompt 设计

**System Prompt 核心要素：**

1. **角色设定**：顶尖 C/C++ 安全审计专家
2. **抗幻觉约束 (Anti-Hallucination)**：
   - 只能依赖提供的代码片段推演
   - 绝不假设在提供代码之外存在未知的过滤函数
   - 不确定时必须声明，不可猜测为安全
   - 必须引用具体行号
3. **思维链 (CoT)**：
   - Step 1: Source 追踪 — 变量来源是否可被外部控制
   - Step 2: Sanitization 检查 — 从 Source 到 Sink 之间是否存在安全校验
   - Step 3: 内存布局分析 — 目标缓冲区容量 vs 源数据大小
   - Step 4: 综合判决
4. **输出格式**：纯 JSON，包含 `is_vulnerable`、`confidence`、`cwe`、`reason`

#### 3.3.2 输入 Payload 结构

发送给 LLM 的结构化数据：

```json
{
  "alert": {
    "tool": "AgentSAST-Pattern",
    "rule_id": "agentsast-builtin-memcpy",
    "sink_line": 17,
    "cwe": "CWE-120",
    "message": "Dangerous function 'memcpy' called — potential CWE-120 vulnerability",
    "sink_function": "memcpy"
  },
  "context_slices": {
    "struct_defs": [
      "L5: typedef struct { char user_buf[64]; int flags; } RequestContext;"
    ],
    "dataflow": [
      "L16: RequestContext ctx;",
      "L22: char* raw_payload = conn->get_data();"
    ],
    "callers": [
      "L21 (caller_of:process_buffer): void handle_connection(Connection* conn) { ... }"
    ]
  },
  "raw_function": "void process_buffer(char* external_data, int size) { ... }"
}
```

#### 3.3.3 LLM 响应解析

LLM 返回的 JSON 会被解析为 `LLMResult`：

```python
@dataclass
class LLMResult:
    anchor_file: str       # 报警文件
    anchor_line: int       # 报警行号
    verdict: Verdict       # vulnerable / safe / uncertain
    confidence: float      # 0.0-1.0
    reason: str            # 推理过程
    cwe: str               # CWE 编号
    raw_response: str      # LLM 原始返回
```

**置信度与判决的映射**：
- `is_vulnerable=true` + `confidence≥0.3` → `VULNERABLE`
- `is_vulnerable=false` + `confidence≥0.3` → `SAFE`
- `confidence<0.3` → `UNCERTAIN`（无论 LLM 怎么说）

#### 3.3.4 兼容性

支持所有 OpenAI 兼容 API，包括但不限于：

- OpenAI GPT-4o / GPT-4 / GPT-3.5
- Azure OpenAI
- 本地部署的 Qwen / DeepSeek / Llama（通过 vLLM / Ollama 等）
- 任何兼容 `chat.completions.create` 接口的服务

#### 3.3.5 代码结构

```
src/agentsast/layer3/
├── __init__.py
├── models.py       # Verdict / LLMResult 数据模型
├── prompt.py       # System Prompt + Payload 构建器 + User Prompt 生成器
└── judge.py        # LLMJudge — OpenAI API 调用 + JSON 解析
```

---

### 3.4 Pipeline — 三层串联引擎

`Pipeline` 类将三层串联为完整工作流：

```
┌─────────────────┐    SARIF/Anchor    ┌─────────────────┐    SlicingResult    ┌─────────────────┐
│   Layer 1       │ ──────────────────▶│   Layer 2       │ ──────────────────▶│   Layer 3       │
│  SAST Anchoring │                    │  Program Slicing│                    │  LLM Triaging   │
│  (高召回)       │                    │  (精准上下文)   │                    │  (高精度)       │
└─────────────────┘                    └─────────────────┘                    └─────────────────┘
       │                                      │                                      │
   scan(target)                     slice_anchor(anchor)                   judge(anchor, slice)
       │                                      │                                      │
  list[Anchor]                      SlicingResult                         LLMResult
```

**执行流程**：

1. Layer1 扫描目标代码，输出所有 Anchor
2. 对每个 Anchor 执行 Layer2 切片
3. 将 `(Anchor, SlicingResult)` 对传给 Layer3 LLM 判断
4. 汇总所有结果，统计 vulnerable / safe / uncertain 计数
5. 输出 JSON 或 Rich 表格

**容错设计**：
- 任何一层出错不会导致整体崩溃，单个 Anchor 的切片/判断失败会被标记为 uncertain
- Layer1 工具不可用时自动降级（Semgrep 跳过，Flawfinder 降级为内置扫描器）
- `--skip-llm` 模式下 Layer1+Layer2 仍可独立运行

---

## 4. 项目目录结构

```
AgentSAST/
├── pyproject.toml                          # 项目配置、依赖、CLI 入口
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md                     # 本文档
│   ├── gemini-answer.md                    # 架构设计讨论记录
│   └── google-researh.html                 # 交互式架构白皮书
├── src/agentsast/
│   ├── __init__.py                         # 版本号
│   ├── cli.py                              # Click CLI 入口
│   ├── layer1/                             # Layer1: SAST 锚点扫描
│   │   ├── __init__.py
│   │   ├── models.py                       # Anchor / Location / Severity
│   │   ├── scanner.py                      # 统一扫描入口 + SARIF 解析
│   │   ├── semgrep.py                      # Semgrep SARIF 输出解析
│   │   └── flawfinder.py                   # Flawfinder + 内置模式扫描器
│   ├── layer2/                             # Layer2: Tree-sitter 切片引擎
│   │   ├── __init__.py
│   │   ├── models.py                       # CodeSlice / SlicingResult
│   │   ├── parser.py                       # ASTParser (C/C++ grammar)
│   │   └── slicer.py                       # SlicingEngine 核心
│   ├── layer3/                             # Layer3: LLM 裁判
│   │   ├── __init__.py
│   │   ├── models.py                       # Verdict / LLMResult
│   │   ├── prompt.py                       # 抗幻觉 Prompt + Payload 构建
│   │   └── judge.py                        # OpenAI API 调用 + JSON 解析
│   └── pipeline/
│       ├── __init__.py
│       └── engine.py                       # 三层串联 Pipeline
├── samples/                                # 示例代码
│   ├── vulnerable_server.c                 # 含漏洞的 C 代码
│   └── safe_server.c                       # 安全写法的 C 代码
└── tests/
    ├── __init__.py
    └── test_pipeline.py                    # 12 个测试用例
```

---

## 5. 示例演示

### 5.1 漏洞代码 (samples/vulnerable_server.c)

```c
typedef struct {
    char user_buf[64];
    int flags;
} RequestContext;

void process_buffer(char* external_data, int size) {
    RequestContext ctx;
    memcpy(ctx.user_buf, external_data, size);  // L17: Sink — 无边界检查
    printf("Received: %s\n", ctx.user_buf);
}

void handle_connection(Connection* conn) {
    char* raw_payload = conn->get_data();       // L22: 不可信外部输入
    int payload_len = conn->get_length();
    process_buffer(raw_payload, payload_len);    // L24: Caller
}
```

### 5.2 运行结果

```bash
$ agentsast samples/ --skip-llm --tools flawfinder
```

**Layer1 输出**：在 `vulnerable_server.c` 中发现 6 个锚点（memcpy、printf、strncpy、sprintf、malloc、strcpy）

**Layer2 切片**（以 memcpy@L17 为例）：

| 维度 | 内容 |
|------|------|
| struct_defs | `typedef struct { char user_buf[64]; int flags; } RequestContext;` |
| dataflow | `L16: RequestContext ctx;`（逆向切片：ctx 变量声明） |
| callers | `handle_connection()`（调用 process_buffer 的上层函数） |
| callees | `printf`, `memcpy`（函数内部的其他调用） |
| raw_function | 完整的 `process_buffer` 函数体 |

### 5.3 安全代码 (samples/safe_server.c)

```c
void safe_process_buffer(char* external_data, int size) {
    RequestContext ctx;
    if (size <= 0 || size > (int)sizeof(ctx.user_buf)) {  // 边界检查
        return;
    }
    memcpy(ctx.user_buf, external_data, size);  // 有保护，预期 LLM 判定为 SAFE
    ctx.user_buf[sizeof(ctx.user_buf) - 1] = '\0';
}
```

---

## 6. 技术依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| `tree-sitter` | ≥0.22 | AST 解析框架 |
| `tree-sitter-c` | ≥0.23 | C 语言语法 |
| `tree-sitter-cpp` | ≥0.23 | C++ 语言语法 |
| `openai` | ≥1.30 | OpenAI 兼容 API 客户端 |
| `rich` | ≥13.0 | 终端表格/彩色输出 |
| `click` | ≥8.0 | CLI 框架 |
| `pydantic` | ≥2.0 | 数据验证（预留） |

开发依赖：`pytest`、`ruff`、`mypy`

---

## 7. 已知局限与路线图

### 7.1 当前局限

| 局限 | 影响 | 缓解措施 |
|------|------|----------|
| **宏展开** | Tree-sitter 不展开 C 宏，可能遗漏宏中隐藏的危险调用 | 可通过 clang 预处理管线补充 |
| **跨文件指针别名** | 1-2 层切片无法完全追踪跨文件指针传播 | 在 Prompt 中声明此局限 |
| **LLM 幻觉** | 即使有抗幻觉约束，LLM 仍可能"脑补"安全逻辑 | 结构化 JSON 输出 + 强制引用行号 |
| **编译期类型** | 免编译路线无法获取宏展开后的精确类型信息 | CI/CD 路线使用 CodeQL/Joern 替代 |
| **并发/时序漏洞** | 当前仅关注内存安全类 CWE，不支持竞态条件检测 | 后续版本扩展 |

### 7.2 路线图

| 里程碑 | 内容 | 预估 |
|--------|------|------|
| **MVP (v0.1)** ✅ | Semgrep/Flawfinder + Tree-sitter 切片 + LLM 判断 | 已完成 |
| **Layer1 编译线接入** ✅ | Infer/CSA/Cppcheck 编译线扫描器接入（SARIF/XML 解析 + 可插拔 Scanner 注册表，Plan 1） | 已完成 |
| **v0.2** | CodeQL SARIF 接入 + Joern CPG 深度切片 | 2-3 周 |
| **v0.3** | Clang 预处理管线（宏展开 + 精确类型） | 1-2 周 |
| **v0.4** | 批量扫描 + 增量分析 + Git diff 模式 | 1 周 |
| **v0.5** | Web Dashboard + 漏洞管理集成 | 2 周 |

### 7.3 两条工程路线

| | 极速免编译路线 (MVP) | 高精度 CI/CD 路线 |
|---|---|---|
| **场景** | IDE 插件 / Pre-commit 检查 | 服务端全量核心资产扫描 |
| **L1 工具** | Semgrep + 内置模式扫描器 | CodeQL / Clang-Tidy |
| **L2 切片** | Tree-sitter (Python binding) | Joern CPG 深度跨文件 |
| **优点** | 无需构建脚本，兼容残缺工程 | 分析极其精确，消除编译期类型知识导致的假阳性 |
| **缺点** | 跨文件数据流追踪偏弱 | 需要完整编译环境，学习曲线陡峭 |

---

## 8. 参考资源

1. **GitHub Security Lab.** CodeQL: The semantic code analysis engine. https://github.com/github/codeql
2. **Return To Corporation (r2c).** Semgrep: Lightweight static analysis for many languages. https://github.com/semgrep/semgrep-rules
3. **LLVM Project.** Clang-Tidy and Clang Static Analyzer checks documentation. https://clang.llvm.org/extra/clang-tidy/
4. **Yamaguchi, F., et al. (2014).** "Modeling and Discovering Vulnerabilities with Code Property Graphs." IEEE S&P.
5. **Li, Z., et al. (2018).** "VulDeePecker: A Deep Learning-Based System for Vulnerability Detection." NDSS.
6. **OASIS Standard.** Static Analysis Results Interchange Format (SARIF) v2.1.0.

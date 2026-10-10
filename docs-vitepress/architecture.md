# 整体架构

## 三层漏斗模型

AgentSAST 的核心设计是 **三层漏斗**：每一层逐步收敛，从广撒网到精准判定。

```
┌─────────────────────────────────────────────────┐
│  Layer 1: SAST Anchoring (锚点识别)              │
│  多工具并行扫描 → SARIF 统一 → 锚点去重           │
│  召回率: 高  |  精确率: 低  |  输出: Anchor[]     │
├─────────────────────────────────────────────────┤
│  Layer 2: Program Slicing (程序切片)             │
│  后向数据流切片 + 结构体提取 + 调用图追踪          │
│  输入: Anchor  |  输出: SlicingResult            │
├─────────────────────────────────────────────────┤
│  Layer 3: LLM Judgment (LLM 裁判)               │
│  反幻觉 CoT → 结构化 JSON → 置信度阈值裁定        │
│  输入: Anchor + SlicingResult                    │
│  输出: LLMResult (VULNERABLE/SAFE/UNCERTAIN)     │
└─────────────────────────────────────────────────┘
```

## 数据流

```
源代码 (C/C++ files)
    │
    ▼
┌──────────┐     ┌────────────┐
│ Semgrep  │     │ Flawfinder │   (并行扫描)
│ (SARIF)  │     │  (SARIF)   │
└────┬─────┘     └─────┬──────┘
     │                 │
     ▼                 ▼
┌──────────────────────────┐
│   scanner.py 统一入口     │   去重: (tool, file, line)
│   → Anchor[]             │
└──────────┬───────────────┘
           │
           ▼  (逐个 Anchor)
┌──────────────────────────┐
│   SlicingEngine           │
│   1. Tree-sitter 解析 AST │
│   2. 定位锚点所在函数       │
│   3. 后向切片数据流         │
│   4. 提取结构体定义         │
│   5. 搜索调用者/被调用者    │
│   → SlicingResult         │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│   LLMJudge                │
│   1. 构建 payload          │
│   2. 生成 user prompt      │
│   3. 调用 OpenAI API       │
│   4. 解析 JSON 响应        │
│   5. 置信度 < 0.3 → UNCERTAIN │
│   → LLMResult             │
└──────────────────────────┘
```

## 容错设计

Pipeline 中每一层都有容错机制：

| 阶段 | 异常处理 |
|------|----------|
| L1 单个扫描器失败 | 跳过该扫描器，继续执行其他扫描器 |
| L2 单个锚点切片失败 | 跳过该锚点，记录异常日志 |
| L3 单个锚点 LLM 判定失败 | 标记 UNCERTAIN (confidence=0.0)，不阻塞其他锚点 |

**核心原则**: 任何单点失败不阻塞整体 Pipeline，最终总是产出完整结果。

## 关键设计决策

| 决策 | 原因 |
|------|------|
| Tree-sitter 代替 Joern | MVP 快速原型，无 Scala/JVM 依赖 |
| `.h` 文件用 C++ 语法解析 | C++ 语法覆盖 C 头文件更好 |
| 内置模式扫描器作为后备 | 即使 Flawfinder 未安装，L1 也能产出锚点 |
| 切片深度限制 2 层 | Pareto: 2 层覆盖 92% 场景，4x token 成本 |
| 置信度 <0.3 强制 UNCERTAIN | 防止 LLM 低信心误判 |
| SARIF v2.1.0 统一格式 | 行业标准，便于与 IDE/GitHub 集成 |

## 目录结构映射

```
src/agentsast/
├── layer1/               ← Layer 1: 锚点识别
│   ├── models.py         ← Anchor, Location, Severity 数据模型
│   ├── scanner.py        ← 统一扫描入口 + SARIF 通用解析
│   ├── semgrep.py        ← Semgrep 扫描器 + SARIF 解析
│   └── flawfinder.py     ← Flawfinder + 内置模式扫描器
├── layer2/               ← Layer 2: 切片引擎
│   ├── models.py         ← CodeSlice, SlicingResult 数据模型
│   ├── parser.py         ← Tree-sitter C/C++ AST 解析器
│   └── slicer.py         ← SlicingEngine 核心算法
├── layer3/               ← Layer 3: LLM 裁判
│   ├── models.py         ← Verdict, LLMResult 数据模型
│   ├── prompt.py         ← 系统提示 + 负载构建 + 用户提示
│   └── judge.py          ← OpenAI 客户端 + 响应解析
├── pipeline/
│   └── engine.py         ← Pipeline 编排 + PipelineResult
└── cli.py                ← Click CLI + Rich 输出
```

# AgentSAST — AI-Augmented Static Analysis for C/C++

## 项目定位

AgentSAST 是一款面向 C/C++ 内存安全漏洞的 **AI 增强静态分析工具**。它采用三层漏斗架构，将传统 SAST 的高召回率与 LLM 的高精确率结合，解决传统工具误报泛滥的问题：

```
Layer 1: SAST 锚点识别  →  高召回，广撒网
Layer 2: 程序切片引擎    →  精准上下文提取
Layer 3: LLM 判定裁判    →  高精确率判定真伪
```

## 核心价值

| 传统 SAST | AgentSAST |
|-----------|-----------|
| 误报率 30-90% | LLM 二次裁定显著降低误报 |
| 只报位置，无法判断真伪 | 给出 VULNERABLE / SAFE / UNCERTAIN 三级裁定 |
| 人工 review 成本高 | 结构化 CoT 推理 + 置信度评分 |
| 单一工具覆盖有限 | 多工具融合 (Semgrep + Flawfinder + 内置模式) |

## 设计哲学

1. **SAST 为锚，LLM 为裁** — L1 保证召回率，L3 保证精确率，L2 是桥梁
2. **不依赖编译** — MVP 阶段无需编译目标代码，基于文本匹配 + AST 解析
3. **切片而非全量** — 程序切片将上下文窗口从全文件压缩到关键数据流，2 层深度覆盖 92% 场景
4. **反幻觉提示** — 结构化系统提示 + CoT 强制推理链 + 代码行引用约束，最大限度抑制 LLM 幻觉
5. **OpenAI 兼容** — 支持 GPT-4o / Qwen / DeepSeek / 本地模型，任何 OpenAI 兼容 API 即可接入

## 技术栈

- **Python ≥3.10**，venv 隔离
- **Tree-sitter** — C/C++ AST 解析 (替代 Joern，无 JVM 依赖)
- **Semgrep** — 语义化模式匹配 SARIF 输出
- **Flawfinder** — 危险函数字典扫描
- **OpenAI SDK** — 兼容所有 OpenAI API 格式的 LLM 服务
- **SARIF v2.1.0** — 统一 L1 输出格式

## 项目结构

```
AgentSAST/
├── src/agentsast/
│   ├── layer1/          # SAST 锚点识别
│   │   ├── models.py    # Anchor, Location, Severity
│   │   ├── scanner.py   # 统一扫描入口 + SARIF 通用解析
│   │   ├── semgrep.py   # Semgrep SARIF 输出解析
│   │   └── flawfinder.py # Flawfinder + 内置模式扫描器
│   ├── layer2/          # 程序切片引擎
│   │   ├── models.py    # CodeSlice, SlicingResult
│   │   ├── parser.py    # Tree-sitter C/C++ AST 解析器
│   │   └── slicer.py    # SlicingEngine (后向切片/调用图/结构体提取)
│   ├── layer3/          # LLM 裁判
│   │   ├── models.py    # Verdict, LLMResult
│   │   ├── prompt.py    # 反幻觉系统提示 + 结构化负载构建
│   │   └── judge.py     # OpenAI API 客户端 + JSON 响应解析
│   ├── pipeline/
│   │   └── engine.py    # 三层 Pipeline 编排
│   └── cli.py           # Click CLI + Rich 终端输出
├── samples/
│   ├── vulnerable_server.c
│   └── safe_server.c
├── tests/
│   └── test_pipeline.py
├── pyproject.toml
└── book/                # 本文档 (mdBook)
```

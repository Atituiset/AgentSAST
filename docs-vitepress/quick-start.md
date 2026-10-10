# 快速开始

## 安装

```bash
# 克隆仓库
git clone https://github.com/atituiset/AgentSAST.git
cd AgentSAST

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装项目
pip install -e .

# 安装开发依赖 (可选)
pip install -e ".[dev]"
```

## 外部工具 (可选)

AgentSAST 内置模式扫描器作为后备，即使不安装外部工具也能工作：

```bash
# 安装 Semgrep (推荐)
pip install semgrep

# 安装 Flawfinder (推荐，Ubuntu/Debian)
sudo apt install flawfinder
```

## 基础用法

### 仅 L1+L2 (跳过 LLM)

无需 API Key，快速扫描：

```bash
agentsast samples/ --skip-llm --tools flawfinder
```

输出示例：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AgentSAST — AI-Augmented Static Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Target: /path/to/samples
Tools: flawfinder
LLM: skipped

┌──────────────────────────────────────────────────────────┐
│  AgentSAST Results — /path/to/samples                    │
├──────────────────┬──────┬─────────────┬────────┬─────────┤
│ File             │ Line │ Tool        │ CWE    │ Verdict │
├──────────────────┼──────┼─────────────┼────────┼─────────┤
│ vulnerable_se…   │   17 │ AgentSAST…  │ CWE-…  │ SKIPPED │
│ vulnerable_se…   │   18 │ AgentSAST…  │ CWE-…  │ SKIPPED │
└──────────────────┴──────┴─────────────┴────────┴─────────┘

Summary: 6 anchors → 0 vulnerable, 0 safe, 0 uncertain
```

### 完整三层 Pipeline

需要 OpenAI 兼容 API Key：

```bash
# 使用 OpenAI GPT-4o
export OPENAI_API_KEY="sk-..."
agentsast samples/ --tools flawfinder

# 使用本地/第三方模型 (Qwen, DeepSeek, Ollama 等)
export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://api.deepseek.com/v1"
agentsast samples/ --llm-model deepseek-chat --tools flawfinder
```

### 输出 JSON

```bash
agentsast samples/ --skip-llm --tools flawfinder -o results.json
```

## CLI 参数一览

| 参数 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `TARGET` | — | (必填) | 扫描目标路径 |
| `--project-root` | — | None | 跨文件切片的项目根目录 |
| `--tools` / `-t` | — | semgrep, flawfinder | 启用的 SAST 工具 |
| `--semgrep-config` | — | p/c | Semgrep 规则集 |
| `--max-call-depth` | — | 2 | 调用链切片最大深度 |
| `--llm-model` | — | gpt-4o | LLM 模型名称 |
| `--llm-api-key` | `OPENAI_API_KEY` | None | API Key |
| `--llm-base-url` | `OPENAI_BASE_URL` | None | API Base URL |
| `--skip-llm` | — | false | 跳过 L3，仅运行 L1+L2 |
| `--output` / `-o` | — | None | JSON 输出文件路径 |
| `--verbose` / `-v` | — | false | 开启 DEBUG 日志 |

## 测试

```bash
pytest tests/ -v
```

12 个测试用例覆盖 L1 模式扫描、L2 切片引擎、L3 提示构建和结果模型。

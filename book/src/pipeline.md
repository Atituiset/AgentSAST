# Pipeline 与 CLI

## Pipeline 编排

> 源码: `src/agentsast/pipeline/engine.py`

### Pipeline 类

`Pipeline` 是三层架构的编排器，串联 L1 → L2 → L3：

```python
class Pipeline:
    def __init__(
        self,
        tools: list[str] | None = None,       # L1 工具列表
        semgrep_config: str = "p/c",           # Semgrep 配置
        max_call_depth: int = 2,               # L2 切片深度
        llm_model: str = "gpt-4o",             # L3 模型
        llm_api_key: str | None = None,        # L3 API Key
        llm_base_url: str | None = None,       # L3 Base URL
        skip_llm: bool = False,                # 跳过 L3
    )
```

### run() 执行流程

```
run(target, project_root)
  │
  ├── === Layer 1: SAST Anchor Scanning ===
  │   ├── layer1_scan(target, tools, config)
  │   ├── anchors = [Anchor, ...]
  │   └── 无锚点 → 直接返回空结果
  │
  ├── === Layer 2: Context Slicing ===
  │   ├── SlicingEngine(max_call_depth)
  │   └── 对每个 anchor:
  │       ├── engine.slice_anchor(anchor, project_root)
  │       ├── 成功 → (anchor, slicing) 加入 sliced_anchors
  │       └── 失败 → 跳过, 记录日志
  │
  ├── skip_llm? ── Yes ──→ 组装结果 (llm=None), 直接返回
  │
  └── === Layer 3: LLM Judgment ===
      ├── LLMJudge(model, api_key, base_url)
      └── 对每个 (anchor, slicing):
          ├── judge.judge(anchor, slicing)
          ├── 成功 → 按 verdict 计数
          └── 失败 → uncertain += 1, llm 字段标记失败
```

### 容错设计

Pipeline 中每一层都有独立的容错：

```python
# L1: 单个扫描器失败不影响其他
for scanner in scanners:
    try:
        anchors = scanner.scan(target)
    except Exception:
        continue

# L2: 单个锚点切片失败不影响其他
for anchor in anchors:
    try:
        slicing = engine.slice_anchor(anchor)
    except Exception:
        continue

# L3: 单个锚点 LLM 判定失败不影响其他
for anchor, slicing in sliced_anchors:
    try:
        llm_result = judge.judge(anchor, slicing)
    except Exception:
        result.uncertain += 1
```

**核心原则**: 任何单点失败不阻塞 Pipeline，最终总是产出完整结果。

### PipelineResult

```python
@dataclass
class PipelineResult:
    target: str              # 扫描目标路径
    total_anchors: int = 0   # L1 锚点总数
    results: list[dict]      # 每个锚点的完整结果
    vulnerable: int = 0      # L3 裁定: 漏洞数
    safe: int = 0            # L3 裁定: 安全数
    uncertain: int = 0       # L3 裁定: 不确定数
```

每个 `results` 条目结构：

```python
{
    "anchor": anchor.to_dict(),
    "slicing": slicing.to_dict(),
    "llm": llm_result.to_dict() | None | {"verdict": "uncertain", ...},
}
```

序列化方法：
- `to_dict()` → Python 字典
- `to_json(indent=2)` → JSON 字符串

## CLI

> 源码: `src/agentsast/cli.py`

### 入口点

通过 `pyproject.toml` 注册：

```toml
[project.scripts]
agentsast = "agentsast.cli:main"
```

安装后可直接执行 `agentsast` 命令。

### Click 命令

```python
@click.command()
@click.argument("target", type=click.Path(exists=True))
@click.option("--project-root", ...)
@click.option("--tools", "-t", multiple=True, default=["semgrep", "flawfinder"])
@click.option("--semgrep-config", default="p/c")
@click.option("--max-call-depth", default=2, type=int)
@click.option("--llm-model", default="gpt-4o")
@click.option("--llm-api-key", envvar="OPENAI_API_KEY")
@click.option("--llm-base-url", envvar="OPENAI_BASE_URL")
@click.option("--skip-llm", is_flag=True)
@click.option("--output", "-o", type=click.Path())
@click.option("--verbose", "-v", is_flag=True)
def main(...)
```

### Rich 输出

CLI 使用 Rich 库生成终端输出：

- **表格**: `Table` 展示每个锚点的文件、行号、工具、CWE、裁定、置信度、理由
- **颜色编码**: VULNERABLE=红色, SAFE=绿色, UNCERTAIN=黄色, SKIPPED=灰色
- **摘要**: 底部显示统计摘要

```
┌──────────────┬──────┬─────────────┬─────────┬────────────┬────────────┬──────────────────┐
│ File         │ Line │ Tool        │ CWE     │ Verdict    │ Confidence │ Reason           │
├──────────────┼──────┼─────────────┼─────────┼────────────┼────────────┼──────────────────┤
│ vuln.c       │   17 │ Flawfinder  │ CWE-120 │ VULNERABLE │        95% │ No bounds check… │
│ safe.c       │   14 │ Flawfinder  │ CWE-120 │ SAFE       │        88% │ Has size check…  │
└──────────────┴──────┴─────────────┴─────────┴────────────┴────────────┴──────────────────┘

Summary: 2 anchors → 1 vulnerable, 1 safe, 0 uncertain
```

### 日志系统

`--verbose` 开启 DEBUG 级别日志，使用 Rich 的 `RichHandler` 格式化输出（含 traceback）。

### JSON 输出

`--output results.json` 将完整结果写入文件，使用 `PipelineResult.to_json()` 序列化。

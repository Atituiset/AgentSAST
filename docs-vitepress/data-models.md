# 数据模型参考

本文档汇总 AgentSAST 全部数据模型，作为快速查阅手册。

## Layer 1 模型

### Severity (`layer1/models.py`)

| 值 | SARIF 映射 | 说明 |
|----|-----------|------|
| `ERROR` | `error` | 确认漏洞 |
| `WARNING` | `warning` | 可疑 |
| `NOTE` | `note` | 信息性 |
| `NONE` | `none` | 无等级 |

### Location (`layer1/models.py`)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `file` | `Path` | (必填) | 文件路径 |
| `line` | `int` | (必填) | 起始行号 (1-indexed) |
| `col` | `int` | `0` | 起始列号 |
| `end_line` | `int` | `0` | 结束行号 |
| `end_col` | `int` | `0` | 结束列号 |

### Anchor (`layer1/models.py`)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `rule_id` | `str` | (必填) | 规则 ID |
| `tool` | `str` | (必填) | 工具名 |
| `severity` | `Severity` | (必填) | 严重等级 |
| `message` | `str` | (必填) | 告警描述 |
| `location` | `Location` | (必填) | 代码位置 |
| `cwe` | `str` | `""` | CWE 编号 |
| `sink_function` | `str` | `""` | 危险函数名 |
| `sink_params` | `list[str]` | `[]` | 数据流参数 |
| `raw_sarif` | `dict` | `{}` | 原始 SARIF 结果 |

## Layer 2 模型

### CodeSlice (`layer2/models.py`)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `file` | `Path` | (必填) | 源文件路径 |
| `start_line` | `int` | (必填) | 起始行号 |
| `end_line` | `int` | (必填) | 结束行号 |
| `content` | `str` | (必填) | 代码内容 |
| `slice_type` | `str` | `"unknown"` | 切片类型 |
| `label` | `str` | `""` | 可读标签 |

### SlicingResult (`layer2/models.py`)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `anchor_file` | `Path` | (必填) | 锚点文件 |
| `anchor_line` | `int` | (必填) | 锚点行号 |
| `struct_defs` | `list[CodeSlice]` | `[]` | 结构体定义切片 |
| `dataflow_slices` | `list[CodeSlice]` | `[]` | 数据流切片 |
| `caller_slices` | `list[CodeSlice]` | `[]` | 调用者切片 |
| `callee_slices` | `list[CodeSlice]` | `[]` | 被调用者切片 |
| `raw_function` | `CodeSlice \| None` | `None` | 完整函数体 |

## Layer 3 模型

### Verdict (`layer3/models.py`)

| 值 | 说明 |
|----|------|
| `VULNERABLE` | 确认真漏洞 |
| `SAFE` | 确认误报 |
| `UNCERTAIN` | 无法判定 |

### LLMResult (`layer3/models.py`)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `anchor_file` | `str` | (必填) | 锚点文件 |
| `anchor_line` | `int` | (必填) | 锚点行号 |
| `verdict` | `Verdict` | (必填) | 裁定结果 |
| `confidence` | `float` | (必填) | 置信度 [0.0, 1.0] |
| `reason` | `str` | (必填) | 推理过程 |
| `cwe` | `str` | `""` | CWE 编号 |
| `raw_response` | `str` | `""` | LLM 原始响应 |

## Pipeline 模型

### PipelineResult (`pipeline/engine.py`)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `target` | `str` | (必填) | 扫描目标路径 |
| `total_anchors` | `int` | `0` | L1 锚点总数 |
| `results` | `list[dict]` | `[]` | 每锚点完整结果 |
| `vulnerable` | `int` | `0` | VULNERABLE 计数 |
| `safe` | `int` | `0` | SAFE 计数 |
| `uncertain` | `int` | `0` | UNCERTAIN 计数 |

## 跨层数据流

```
Anchor (L1)
  │
  ├──→ SlicingEngine.slice_anchor()
  │      │
  │      ▼
  │    SlicingResult (L2)
  │
  ├──→ LLMJudge.judge()
  │      │
  │      ▼
  │    LLMResult (L3)
  │
  └──→ Pipeline results 条目:
       {
         "anchor": Anchor.to_dict(),
         "slicing": SlicingResult.to_dict(),
         "llm": LLMResult.to_dict() | None
       }
```

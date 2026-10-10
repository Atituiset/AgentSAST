# Layer 1 数据模型

> 源码: `src/agentsast/layer1/models.py`

## Severity

告警严重等级枚举，直接映射 SARIF `level` 字段：

```python
class Severity(str, Enum):
    ERROR = "error"      # 确认漏洞
    WARNING = "warning"  # 可疑
    NOTE = "note"        # 信息性
    NONE = "none"        # 无等级
```

继承 `str, Enum` 使其可直接与 SARIF JSON 字符串比较。

## Location

代码位置，对应 SARIF `physicalLocation`：

```python
@dataclass
class Location:
    file: Path           # 文件路径
    line: int            # 起始行号 (1-indexed)
    col: int = 0         # 起始列号
    end_line: int = 0    # 结束行号
    end_col: int = 0     # 结束列号
```

`__post_init__` 确保传入的 `file` 始终转为 `Path` 对象。

## Anchor

L1 的核心输出——一个"锚点"代表一个 SAST 工具报告的潜在漏洞位置：

```python
@dataclass
class Anchor:
    rule_id: str                # 规则 ID (如 "CWE-120", "agentsast-builtin-memcpy")
    tool: str                   # 工具名 (如 "Semgrep", "Flawfinder", "AgentSAST-Pattern")
    severity: Severity          # 严重等级
    message: str                # 告警描述
    location: Location          # 代码位置
    cwe: str = ""               # CWE 编号 (如 "CWE-120")
    sink_function: str = ""     # 危险函数名 (如 "memcpy")
    sink_params: list[str] = field(default_factory=list)  # 数据流参数
    raw_sarif: dict = field(default_factory=dict)          # 原始 SARIF 结果
```

### 便利属性

- `anchor.file` → `anchor.location.file` (快捷访问)
- `anchor.line` → `anchor.location.line` (快捷访问)

### 序列化

`to_dict()` 方法将 Anchor 转为可 JSON 序列化的字典，用于 Pipeline 输出和 CLI 展示。

## 锚点去重

在 `scanner.py` 中，基于 `(tool, file, line)` 三元组去重：

```python
key = (anchor.tool, str(anchor.file), anchor.line)
if key not in seen:
    seen.add(key)
    all_anchors.append(anchor)
```

这保证了同一工具在同一行不会重复报告，但不同工具报告同一行会各自保留。

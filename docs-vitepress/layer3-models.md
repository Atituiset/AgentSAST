# Layer 3 数据模型

> 源码: `src/agentsast/layer3/models.py`

## Verdict

三级裁定枚举：

```python
class Verdict(str, Enum):
    VULNERABLE = "vulnerable"   # 确认真漏洞
    SAFE = "safe"               # 确认误报
    UNCERTAIN = "uncertain"     # 无法判定
```

继承 `str, Enum` 使其可直接序列化为字符串，与 JSON 输出兼容。

## LLMResult

LLM 裁判的完整结果：

```python
@dataclass
class LLMResult:
    anchor_file: str       # 锚点文件
    anchor_line: int       # 锚点行号
    verdict: Verdict       # 裁定结果
    confidence: float      # 置信度 [0.0, 1.0]
    reason: str            # 推理过程
    cwe: str = ""          # CWE 编号 (可能被 LLM 修正)
    raw_response: str = "" # LLM 原始响应文本
```

### 字段说明

| 字段 | 来源 | 说明 |
|------|------|------|
| `anchor_file` | 从 Anchor 传入 | 用于关联 L1 锚点 |
| `anchor_line` | 从 Anchor 传入 | 用于关联 L1 锚点 |
| `verdict` | 从 LLM JSON 响应解析 | 经置信度阈值修正 |
| `confidence` | LLM JSON `confidence` 字段 | <0.3 时 verdict 被覆盖为 UNCERTAIN |
| `reason` | LLM JSON `reason` 字段 | Chain-of-Thought 推理文本 |
| `cwe` | LLM JSON `cwe` 字段，回退到 Anchor.cwe | LLM 可能给出更精确的 CWE |
| `raw_response` | LLM 原始文本 | 用于调试和审计 |

### 便利属性

```python
@property
def is_vulnerable(self) -> bool:
    return self.verdict == Verdict.VULNERABLE
```

### 序列化

`to_dict()` 不包含 `raw_response`（避免输出过大）：

```python
def to_dict(self) -> dict:
    return {
        "anchor_file": self.anchor_file,
        "anchor_line": self.anchor_line,
        "verdict": self.verdict.value,
        "confidence": self.confidence,
        "reason": self.reason,
        "cwe": self.cwe,
    }
```

## 置信度阈值机制

在 `judge.py` 的 `_parse_response()` 中：

```python
verdict = Verdict.VULNERABLE if is_vuln else Verdict.SAFE
if confidence < 0.3:
    verdict = Verdict.UNCERTAIN
```

**设计理由**:
- LLM 在不确定时仍可能输出 `is_vulnerable: false`（保守偏向 safe）
- `confidence < 0.3` 意味着 LLM 自信不足，此时无论 `is_vulnerable` 值是什么，都不应信任
- UNCERTAIN 裁定提示安全工程师需要人工 review

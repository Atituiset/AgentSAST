# Semgrep 扫描器

> 源码: `src/agentsast/layer1/semgrep.py`

## 概述

`SemgrepScanner` 封装了 Semgrep CLI 的调用与 SARIF 输出解析。Semgrep 是一个语义化模式匹配引擎，支持多语言，比正则精确但不需要完整编译。

## 类接口

```python
class SemgrepScanner:
    NAME = "Semgrep"

    def __init__(self, config: str = "p/c", timeout: int = 300)
    def is_available(self) -> bool
    def scan(self, target: Path) -> list[Anchor]
    def _parse_sarif(self, sarif_path: Path) -> list[Anchor]
```

## 执行流程

```
scan(target)
  │
  ├── is_available()?  ── No ──→ 返回 [] (跳过)
  │
  ├── 执行: semgrep scan --config p/c --sarif -o /tmp/agentsast_semgrep.sarif --no-git <target>
  │
  ├── 超时/找不到命令 → 返回 []
  │
  └── _parse_sarif(sarif_path)
       ├── 解析 SARIF JSON
       ├── 遍历 runs[].results[]
       ├── 提取 ruleId, level, message, location
       ├── 从 rules[].properties.tags 提取 CWE 编号
       ├── _extract_sink(): 从消息文本提取危险函数名
       ├── _extract_sink_params(): 从 codeFlows 提取数据流参数
       └── 返回 Anchor[]
```

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `config` | `p/c` | Semgrep 规则集 (p/c = C 语言社区规则) |
| `timeout` | 300 | CLI 执行超时 (秒) |

## SARIF 解析细节

Semgrep 的 SARIF 输出结构：

```json
{
  "runs": [{
    "tool": { "driver": { "name": "Semgrep", "rules": [...] } },
    "results": [{
      "ruleId": "c.lang.buffer.memcpy-no-size-check",
      "level": "warning",
      "message": { "text": "..." },
      "locations": [{
        "physicalLocation": {
          "artifactLocation": { "uri": "src/main.c" },
          "region": { "startLine": 17, "startColumn": 5 }
        }
      }],
      "codeFlows": [{ "threadFlows": [...] }]
    }]
  }]
}
```

关键解析逻辑：

1. **规则映射**: 先将 `rules[]` 建成 `rules_map[id→rule]`，用于后续 CWE 提取
2. **CWE 提取**: 从 `rule.properties.tags` 中查找 `CWE-*` 前缀的标签
3. **路径处理**: 如果 SARIF 中的 `uri` 是绝对路径，去除前导 `/` 使其相对化
4. **Sink 提取**: 从消息文本中匹配已知的危险函数名列表

## 可用性检测

`is_available()` 通过执行 `semgrep --version` 判断 Semgrep 是否在 PATH 中，10 秒超时。不可用时优雅跳过，不影响其他扫描器。

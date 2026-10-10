# Layer 3: LLM 裁判

Layer 3 是 AgentSAST 漏斗的最后一层，职责是 **用 LLM 对 L2 切片上下文进行精确判定**，输出 VULNERABLE / SAFE / UNCERTAIN 三级裁定。

## 核心挑战

LLM 裁判面临两个核心挑战：

1. **幻觉问题** — LLM 可能"脑补"代码中不存在的安全检查
2. **一致性** — 同一漏洞，不同提示可能导致不同判定

AgentSAST 的解决方案：
- 反幻觉系统提示 (4 条硬约束)
- 强制 Chain-of-Thought 推理链 (4 步分析流程)
- 结构化 JSON 输出 + 置信度阈值

## 三级裁定

| 裁定 | 含义 | 条件 |
|------|------|------|
| `VULNERABLE` | 确认真漏洞 | `is_vulnerable=true` 且 `confidence≥0.3` |
| `SAFE` | 确认误报 | `is_vulnerable=false` 且 `confidence≥0.3` |
| `UNCERTAIN` | 无法判定 | `confidence<0.3` 或 API 失败 |

**置信度阈值**: `confidence < 0.3` 时强制为 UNCERTAIN，防止低信心误判。

## 数据流

```
Anchor + SlicingResult
    │
    ▼
build_payload()          ← 构建结构化负载
    │
    ▼
build_user_prompt()      ← 生成用户提示
    │
    ▼
OpenAI API 调用          ← system_prompt + user_prompt
    │
    ▼
_parse_response()        ← 解析 JSON + 置信度阈值
    │
    ▼
LLMResult
```

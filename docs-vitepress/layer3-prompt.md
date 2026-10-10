# 反幻觉提示工程

> 源码: `src/agentsast/layer3/prompt.py`

## 系统提示

`SYSTEM_PROMPT` 是 AgentSAST 反幻觉策略的核心，包含 4 条硬约束 + 4 步分析流程：

### 四条反幻觉硬约束

```
## CRITICAL CONSTRAINTS (Anti-Hallucination)
1. You MUST base your reasoning ONLY on the code fragments
   provided in `context_slices`.
2. You MUST NOT assume the existence of any sanitization,
   bounds-checking, or validation logic that is NOT present
   in the provided code.
3. If you are unsure whether a check exists, state it
   explicitly — do NOT guess that it is safe.
4. You MUST reference specific line numbers from the
   provided context when making your argument.
```

| 约束 | 对抗的幻觉模式 |
|------|---------------|
| 仅基于提供代码 | LLM 倾向"脑补"项目其他文件中的检查 |
| 不得假设检查存在 | LLM 可能认为"开发者肯定做了校验" |
| 不确定时明确声明 | 防止低信心判定被输出为 SAFE |
| 引用具体行号 | 强制 LLM 定位到代码，而非泛泛而谈 |

### Chain-of-Thought 四步分析

```
Step 1: Source Tracing     → 追踪变量来源，判断是否外部可控
Step 2: Sanitization Check → 沿数据流路径搜索校验逻辑
Step 3: Memory Layout      → 分析缓冲区大小 vs 数据大小
Step 4: Verdict            → 综合以上步骤做出裁定
```

### 结构化 JSON 输出

```json
{
    "is_vulnerable": true/false,
    "confidence": 0.0-1.0,
    "cwe": "CWE-XXX or empty",
    "reason": "Detailed reasoning with line references"
}
```

严格要求"仅输出 JSON，无 markdown、无额外解释"，便于程序化解析。

## build_payload()

将 Anchor + SlicingResult 转换为结构化负载字典：

```python
def build_payload(anchor: Anchor, slicing: SlicingResult) -> dict:
```

输出结构：

```python
{
    "alert": {
        "tool": "Flawfinder",
        "rule_id": "agentsast-builtin-memcpy",
        "sink_line": 17,
        "cwe": "CWE-120",
        "message": "Dangerous function 'memcpy' called — ...",
        "sink_function": "memcpy",
    },
    "context_slices": {
        "struct_defs": ["L5: typedef struct { char user_buf[64]; ... }"],
        "dataflow": ["L15: void process_buffer(char* external_data, int size)"],
        "callers": ["L21 (caller_of:process_buffer): void handle_connection(...)"],
    },
    "raw_function": "void process_buffer(char* external_data, int size) { ... }"
}
```

**格式化规则**:
- 每个 slice 前缀行号: `L{start_line}: {content}`
- caller 额外标注 label: `L{start_line} ({label}): {content}`
- 内容 `.strip()` 去除首尾空白

## build_user_prompt()

将结构化负载转为 LLM 友好的用户提示文本：

```python
def build_user_prompt(payload: dict) -> str:
```

输出格式：

```markdown
## Alert from Flawfinder
- Rule: agentsast-builtin-memcpy
- CWE: CWE-120
- Sink at line 17: function `memcpy`
- Message: Dangerous function 'memcpy' called — ...

## Struct/Type Definitions
L5: typedef struct { char user_buf[64]; int flags; } RequestContext;

## Data Flow (Backward Slicing)
L15: void process_buffer(char* external_data, int size)

## Caller Context
L21 (caller_of:process_buffer): void handle_connection(Connection* conn) { ... }

## Sink Function (Full)
void process_buffer(char* external_data, int size) { ... }
```

**条件渲染**: 只有存在对应切片时才渲染该 section，避免空 section 干扰 LLM。

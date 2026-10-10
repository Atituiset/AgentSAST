# OpenAI 兼容客户端

> 源码: `src/agentsast/layer3/judge.py`

## 概述

`LLMJudge` 封装 OpenAI API 调用，支持任何 OpenAI 兼容的 LLM 服务。

## 类接口

```python
class LLMJudge:
    def __init__(
        self,
        model: str = "gpt-4o",           # 模型名称
        api_key: str | None = None,       # API Key (默认从环境变量)
        base_url: str | None = None,      # API Base URL (默认从环境变量)
        temperature: float = 0.1,         # 低温 → 更确定性的输出
        max_tokens: int = 2048,           # 最大输出 token 数
    )
    def judge(self, anchor: Anchor, slicing: SlicingResult) -> LLMResult
```

## 初始化

API Key 和 Base URL 的优先级：

```python
key = api_key or os.environ.get("OPENAI_API_KEY", "")
url = base_url or os.environ.get("OPENAI_BASE_URL", None)

client_kwargs = {"api_key": key}
if url:
    client_kwargs["base_url"] = url

self.client = OpenAI(**client_kwargs)
```

| 来源 | 优先级 |
|------|--------|
| 构造函数参数 | 最高 |
| 环境变量 `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 次高 |

这使得以下用法都有效：

```python
# GPT-4o
LLMJudge(model="gpt-4o", api_key="sk-...")

# DeepSeek
LLMJudge(model="deepseek-chat", api_key="...", base_url="https://api.deepseek.com/v1")

# 本地 Ollama
LLMJudge(model="llama3", api_key="ollama", base_url="http://localhost:11434/v1")

# 环境变量
os.environ["OPENAI_API_KEY"] = "sk-..."
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"
LLMJudge(model="deepseek-chat")
```

## judge() 流程

```
judge(anchor, slicing)
  │
  ├── build_payload(anchor, slicing)    ← 结构化负载
  ├── build_user_prompt(payload)        ← 用户提示文本
  │
  ├── client.chat.completions.create(
  │       model=self.model,
  │       messages=[
  │           {"role": "system", "content": SYSTEM_PROMPT},
  │           {"role": "user",   "content": user_prompt},
  │       ],
  │       temperature=0.1,    ← 低温: 更确定性
  │       max_tokens=2048,
  │   )
  │
  ├── API 调用失败 → 返回 UNCERTAIN (confidence=0.0)
  │
  └── _parse_response(raw_text, anchor)
       ├── 清理 markdown 代码块包裹
       ├── json.loads() 解析
       ├── 提取 is_vulnerable, confidence, reason, cwe
       ├── confidence < 0.3 → UNCERTAIN
       └── 返回 LLMResult
```

## 响应解析

### Markdown 清理

LLM 有时返回 markdown 包裹的 JSON：

````
```json
{"is_vulnerable": true, ...}
```
````

`_parse_response()` 处理这种情况：

```python
if text.startswith("```"):
    lines = text.split("\n")
    text = "\n".join(lines[1:])  # 去除首行 ```json
if text.endswith("```"):
    text = text[:-3]            # 去除末行 ```
```

### JSON 解析失败

如果 LLM 输出不是有效 JSON，返回：

```python
LLMResult(
    verdict=Verdict.UNCERTAIN,
    confidence=0.0,
    reason="Failed to parse LLM response",
    raw_response=raw_text,  # 保留原始文本用于调试
)
```

### 置信度阈值

```python
verdict = Verdict.VULNERABLE if is_vuln else Verdict.SAFE
if confidence < 0.3:
    verdict = Verdict.UNCERTAIN
```

**阈值选择理由**:
- `0.3` 以下意味着 LLM 对自己的判断几乎没有信心
- 实践中发现 LLM 在不确定时倾向于输出 `false` (偏向 safe)，此时 `confidence` 通常很低
- 0.3 是经验值，未来可能需要根据模型调整

## 温度参数

`temperature=0.1` 是刻意选择的低值：
- 安全审计需要确定性判断，不需要创造性
- 低温度减少同一漏洞在不同次调用中得出不同裁定的概率
- 完全 `0.0` 可能导致某些 API 的边界行为，`0.1` 更安全

# Flawfinder 扫描器

> 源码: `src/agentsast/layer1/flawfinder.py`

## 概述

`FlawfinderScanner` 提供两种模式：
1. **原生 Flawfinder** — 调用系统安装的 Flawfinder CLI，获取 SARIF 输出
2. **内置模式扫描器** — Flawfinder 未安装时的后备方案，基于正则匹配危险函数

## 危险函数映射表

内置 23 个危险函数到 CWE 的映射：

```python
DANGER_FUNCTIONS = {
    # CWE-120: 缓冲区溢出 (11 个)
    "memcpy": "CWE-120", "strcpy": "CWE-120", "strcat": "CWE-120",
    "gets": "CWE-120", "sprintf": "CWE-120", "scanf": "CWE-120",
    "vsprintf": "CWE-120", "strncat": "CWE-120", "strncpy": "CWE-120",
    "snprintf": "CWE-120",
    # CWE-787: 堆溢出 (2 个)
    "malloc": "CWE-787", "realloc": "CWE-787",
    # CWE-415: 双重释放 (1 个)
    "free": "CWE-415",
    # CWE-78: 命令注入 (7 个)
    "system": "CWE-78", "popen": "CWE-78",
    "execl": "CWE-78", "execle": "CWE-78", "execlp": "CWE-78",
    "execv": "CWE-78", "execve": "CWE-78", "execvp": "CWE-78",
    # CWE-134: 格式化字符串 (3 个)
    "printf": "CWE-134", "fprintf": "CWE-134", "syslog": "CWE-134",
}
```

## 执行流程

```
scan(target)
  │
  ├── is_available()? ── Yes ──→ 执行 Flawfinder CLI
  │   │                           │
  │   │                           ├── flawfinder --minlevel 3 --sarif <target>
  │   │                           │
  │   │                           └── _parse_sarif_output(stdout)
  │   │                                ├── 解析 SARIF JSON
  │   │                                ├── 提取 location, message, CWE
  │   │                                └── _extract_sink_from_message()
  │   │
  │   └── No ──→ _pattern_scan(target)
  │                │
  │                ├── _collect_source_files(target)  ← 递归收集 C/C++ 文件
  │                │
  │                ├── 正则匹配: \b(func1|func2|...)\s*\(
  │                │
  │                └── 为每个匹配生成 Anchor
  │                     ├── rule_id = "agentsast-builtin-{func_name}"
  │                     ├── tool = "AgentSAST-Pattern"
  │                     └── severity = WARNING (固定)
```

## 内置模式扫描器详解

### 文件收集

`_collect_source_files()` 支持扫描目录或单文件，匹配扩展名：

```python
extensions = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx"}
```

### 正则匹配

```python
func_pattern = re.compile(
    r"\b(" + "|".join(re.escape(f) for f in DANGER_FUNCTIONS) + r")\s*\("
)
```

这个模式：
- 使用 `\b` 词边界防止子串匹配 (如 `my_memcpy` 不会误匹配 `memcpy`)
- 匹配函数名后紧跟 `(` 的调用形式
- `re.escape` 处理函数名中的特殊字符

### 行号计算

```python
line_no = content[: match.start()].count("\n") + 1
```

通过统计匹配位置之前的换行符数量来确定行号 (1-indexed)。

## Flawfinder CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_level` | 3 | 最低风险等级 (1-5, 5 最严重) |
| `timeout` | 300 | 执行超时 (秒) |

## CWE 提取策略

`_extract_cwe()` 有两层回退：

1. 优先从 `properties.tags` 中提取 `CWE-*` 标签
2. 回退到从 `message.text` 中正则匹配 `CWE-\d+`

## 局限性

Flawfinder 本质是危险函数字典扫描器，与内置模式扫描器同一级别：
- **无数据流分析** — 不知道参数来源和大小
- **无路径敏感** — 不考虑分支条件
- **高误报率** — 这是设计上的权衡，精确率留给 L3

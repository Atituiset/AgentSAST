# Layer 1: 锚点识别

Layer 1 是 AgentSAST 漏斗的第一层，职责是 **高召回率地识别潜在漏洞锚点**。它的设计哲学是"宁报勿漏"——宁可多报误报，也不能漏掉真正的漏洞。误报的过滤交给 L2 和 L3 完成。

## 工作原理

```
源代码
  │
  ├──→ Semgrep 扫描器 ──→ SARIF ──→ Anchor[]
  │
  ├──→ Flawfinder 扫描器 ──→ SARIF ──→ Anchor[]
  │
  └──→ (Flawfinder 不可用时)
       内置模式扫描器 ──→ Anchor[]
                │
                ▼
         scanner.py 统一入口
         去重: (tool, file, line) 三元组
                │
                ▼
            Anchor[]
```

## 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| 数据模型 | `layer1/models.py` | `Anchor`, `Location`, `Severity` 定义 |
| 统一入口 | `layer1/scanner.py` | 并行调度扫描器 + SARIF 通用解析 + 去重 |
| Semgrep | `layer1/semgrep.py` | 调用 Semgrep CLI + 解析 SARIF 输出 |
| Flawfinder | `layer1/flawfinder.py` | 调用 Flawfinder CLI + 内置模式扫描器后备 |

## 去重策略

多个扫描器可能报告同一位置的同一问题。去重基于 `(tool, file, line)` 三元组：

- 同一工具、同一文件、同一行 → 只保留第一个
- 不同工具报告同一行 → 都保留（不同工具视角互补）

## SARIF v2.1.0 统一格式

所有 L1 扫描器最终产出 SARIF v2.1.0 格式的结果，这是 OASIS 标准，便于与 GitHub Code Scanning、VS Code 等生态集成。SARIF 核心字段映射：

| SARIF 字段 | Anchor 字段 | 说明 |
|------------|-------------|------|
| `ruleId` | `rule_id` | 规则 ID |
| `level` | `severity` | 严重等级 |
| `message.text` | `message` | 告警描述 |
| `locations[0].physicalLocation` | `location` | 文件+行列号 |
| `properties.tags` (CWE-*) | `cwe` | CWE 编号 |
| — | `sink_function` | 危险函数名 (从消息提取) |
| — | `sink_params` | 数据流参数 (从 codeFlows 提取) |

## 内置模式扫描器

当 Flawfinder 未安装时，自动启用内置模式扫描器。它维护了一个 23 项的危险函数→CWE 映射表：

| 函数族 | CWE | 典型函数 |
|--------|-----|----------|
| 缓冲区溢出 | CWE-120 | memcpy, strcpy, strcat, gets, sprintf, scanf, vsprintf |
| 堆溢出 | CWE-787 | malloc, realloc |
| 双重释放 | CWE-415 | free |
| 命令注入 | CWE-78 | system, popen, execl/execle/execlp/execv/execve/execvp |
| 格式化字符串 | CWE-134 | printf, fprintf, syslog |

这个扫描器本质上是正则级别（`\b(func_name)\s*\(`），没有数据流分析，因此误报率很高——但这正是 L2+L3 存在的意义。

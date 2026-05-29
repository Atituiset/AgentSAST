# 统一扫描入口

> 源码: `src/agentsast/layer1/scanner.py`

## 概述

`scanner.py` 是 Layer 1 的统一入口，负责：
1. 调度多个扫描器并行执行
2. 通用 SARIF 文件解析 (独立于任何扫描器)
3. 锚点去重

## scan() 函数

```python
def scan(
    target: Path,
    tools: list[str] | None = None,   # 默认 ["semgrep", "flawfinder"]
    config: str = "p/c",              # Semgrep 规则集
) -> list[Anchor]
```

### 执行流程

```
scan(target, tools)
  │
  ├── 路径验证: target 必须存在
  │
  ├── 根据 tools 列表实例化扫描器:
  │   ├── "semgrep"    → SemgrepScanner(config=config)
  │   └── "flawfinder" → FlawfinderScanner()
  │
  ├── 逐个执行扫描器 (容错):
  │   ├── scanner.scan(target) ── 成功 → anchors
  │   └── scanner.scan(target) ── 异常 → 跳过, 记录日志
  │
  ├── 去重: 基于 (tool, file, line) 三元组
  │
  └── 返回 all_anchors: list[Anchor]
```

### 容错机制

```python
for scanner in scanners:
    try:
        anchors = scanner.scan(target)
    except Exception:
        logger.exception("Scanner %s failed", scanner.NAME)
        continue  # 不阻塞其他扫描器
```

单个扫描器的任何异常都不会影响其他扫描器的执行。

## parse_sarif_file() 函数

独立的 SARIF 文件解析器，不依赖任何扫描器类。用于解析已有的 SARIF 文件（例如从 CI 管线中获取的）：

```python
def parse_sarif_file(sarif_path: Path) -> list[Anchor]
```

解析逻辑与 `SemgrepScanner._parse_sarif()` 类似，但更通用：
- 从 `runs[].tool.driver.name` 提取工具名
- 从 `runs[].tool.driver.rules[]` 构建规则映射
- 从 `properties.tags` 提取 CWE

## 去重策略

```python
seen: set[tuple[str, str, int]] = set()

for anchor in anchors:
    key = (anchor.tool, str(anchor.file), anchor.line)
    if key not in seen:
        seen.add(key)
        all_anchors.append(anchor)
```

**去重粒度**: 同一工具 + 同一文件 + 同一行 → 只保留第一个命中。

**为什么不去重不同工具的重复报告**: 不同工具的视角互补。Semgrep 可能基于数据流报告，Flawfinder 基于函数调用报告——即使同位置，信息维度不同，各自保留供 L2/L3 参考。

## 工具选择

CLI 通过 `--tools` 参数控制启用哪些工具：

```bash
# 仅使用 Flawfinder + 内置模式
agentsast samples/ --tools flawfinder

# 使用全部工具
agentsast samples/ --tools semgrep --tools flawfinder

# 多次 -t 也可
agentsast samples/ -t semgrep -t flawfinder
```

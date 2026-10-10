# AST 解析器

> 源码: `src/agentsast/layer2/parser.py`

## 概述

`ASTParser` 封装 Tree-sitter C/C++ 语法解析，为切片引擎提供 AST 节点访问和代码片段提取能力。

## 语法选择策略

```python
C_EXTENSIONS = {".c", ".h"}
CPP_EXTENSIONS = {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"}
```

`_get_language()` 根据文件扩展名选择 Tree-sitter 语法：

| 扩展名 | 语法 | 说明 |
|--------|------|------|
| `.c` | tree-sitter-c | 标准 C |
| `.h` | tree-sitter-cpp | C++ 语法覆盖 C 头文件更好 (匿名结构体等) |
| `.cpp/.cc/.cxx` | tree-sitter-cpp | C++ |
| `.hpp/.hh/.hxx` | tree-sitter-cpp | C++ 头文件 |

**设计决策**: `.h` 文件使用 C++ 语法解析，因为 C 语法对匿名结构体和 typedef 的处理不如 C++ 语法完善。

## ASTParser 类

### 解析文件

```python
class ASTParser:
    def __init__(self):
        self._parsers: dict[Language, Parser] = {}  # 缓存 Parser 实例

    def parse_file(self, file_path: Path) -> Node | None:
```

- 每个 `Language` 只创建一次 `Parser` 实例（缓存优化）
- 读取文件为字节流 (`read_bytes`)，Tree-sitter 原生处理 bytes
- 解析失败返回 `None`，不抛异常

### 获取行内容

```python
@staticmethod
def get_line_content(file_path: Path, start_line: int, end_line: int) -> str:
```

从文件中提取指定行范围的文本内容。注意：
- `start_line` 是 1-indexed，内部转换为 0-indexed
- `end_line` 是 1-indexed 且包含该行
- 使用 `errors="replace"` 读取，容忍编码问题

### AST 节点转 CodeSlice

```python
@staticmethod
def node_to_slice(file_path: Path, node: Node, slice_type: str, label: str = "") -> CodeSlice:
```

将 Tree-sitter `Node` 转换为 `CodeSlice`：
- `start_point[0] + 1` → 1-indexed 起始行
- `end_point[0] + 1` → 1-indexed 结束行
- 从源文件读取实际代码内容（而非 `node.text`，确保有换行等格式）

## Tree-sitter 依赖

```
tree-sitter >= 0.22        # 核心库
tree-sitter-c >= 0.23      # C 语法
tree-sitter-cpp >= 0.23    # C++ 语法
```

这些是 Python 绑定包，不需要单独编译 grammar。`pip install` 即可。

## 错误处理

- 语法不可用 (扩展名不匹配) → 日志警告，返回 `None`
- 文件读取失败 → 日志错误，返回 `None`
- 不抛出异常，所有错误在调用方处理

# 切片算法

> 源码: `src/agentsast/layer2/slicer.py`

## 概述

`SlicingEngine` 是 Layer 2 的核心，实现基于 Tree-sitter AST 的程序切片。本文档详解每个算法步骤。

## 辅助函数

### _walk_tree(node)

广度优先遍历 AST 所有后代节点：

```python
def _walk_tree(node: Node):
    stack = list(node.children)
    while stack:
        child = stack.pop()
        yield child
        stack.extend(child.children)
```

> 注意：使用 `stack.pop()` 实现的是 DFS（后进先出），而非 BFS。这对切片结果不影响——我们只关心"找到"节点，不关心遍历顺序。

### _contains_line(node, line)

判断 AST 节点是否包含指定行号：

```python
def _contains_line(node: Node, line: int) -> bool:
    return node.start_point[0] + 1 <= line <= node.end_point[0] + 1
```

### _find_enclosing_function(root, line)

查找包含指定行的最小 `function_definition` 节点：

```python
def _find_enclosing_function(root: Node, line: int) -> Node | None:
    best: Node | None = None
    for node in _walk_tree(root):
        if node.type == "function_definition" and _contains_line(node, line):
            if best is None or (node 跨度 < best 跨度):
                best = node
    return best
```

**选最小函数**: 如果有嵌套函数定义（C 语法不支持，但 C++ lambda 可能有类似情况），选择跨度最小的——即最内层函数。

## 结构体提取

### _extract_type_names_from_node(node)

从函数体中提取所有类型标识符：

- 遍历所有 `type_identifier` 节点
- 遍历所有 `struct_specifier` 的 `name` 字段

返回类型名集合，如 `{"RequestContext", "NetworkPacket"}`。

### _find_struct_defs(root, type_names)

在全文件 AST 中搜索匹配的结构体定义，支持三种形式：

1. **typedef struct** — `type_definition` 包含 `type_identifier` 子节点
2. **struct specifier** — `struct_specifier` 有 `name` 字段
3. **匿名 typedef struct** — `struct_specifier` 在 `type_definition` 内

```python
def _find_struct_defs(root: Node, type_names: set[str]) -> list[Node]:
    # 优先匹配 typedef_name (type_identifier)
    # 其次匹配 struct_specifier.name
    # 去重：同一 type_definition 不重复添加
```

**C typedef 特殊处理**: C 语言中 `typedef struct { ... } RequestContext;` 的类型名在 `type_identifier` 子节点上，而非 `struct_specifier.name`。这是因为匿名结构体的 `struct_specifier` 没有 `name` 字段。

## 后向数据流切片

### _backward_slice_var(node, var_name, max_depth=2)

从目标节点向上搜索变量的定义和赋值：

```python
def _backward_slice_var(node: Node, var_name: str, max_depth: int = 2) -> list[Node]:
    related: list[Node] = []
    scope = node.parent
    depth = 0
    while scope and depth < max_depth:
        for child in _walk_tree(scope):
            if child.type == "declaration" and 包含 var_name:
                related.append(child)
            elif child.type == "assignment_expression" and left == var_name:
                related.append(child)
        scope = scope.parent
        depth += 1
    return related
```

**作用域爬升**: 从当前节点开始，逐层向上搜索父作用域，最多爬升 `max_depth` 层。

### _extract_dataflow() 完整流程

```
_extract_dataflow(file_path, root, func_node, anchor)
  │
  ├── 提取函数参数名
  │   ├── parameter_declaration → declarator → identifier
  │   └── pointer_declarator → identifier
  │
  ├── 提取 sink 函数参数变量
  │   ├── call_expression.function == anchor.sink_function
  │   ├── arguments → identifier (直接变量)
  │   └── arguments → pointer_expression/field_expression → identifier
  │
  ├── 对每个变量执行 _backward_slice_var
  │   └── 排除与 sink 同行的声明 (避免冗余)
  │
  └── 降级: 如果无切片结果
       └── 生成 "full_function_backdrop" (函数开头到 sink)
```

## 调用图追踪

### _find_callers(root, func_name)

搜索调用指定函数的所有函数定义：

```python
def _find_callers(root: Node, func_name: str) -> list[Node]:
    for node in _walk_tree(root):
        if node.type == "function_definition":
            body = node.child_by_field_name("body")
            for child in _walk_tree(body):
                if child.type == "call_expression":
                    func = child.child_by_field_name("function")
                    if func.text.decode().strip() == func_name:
                        callers.append(node)
                        break  # 一个函数只记录一次
```

### _find_callees(func_node)

提取函数体内调用的所有函数：

```python
def _find_callees(func_node: Node) -> list[tuple[str, Node]]:
    body = func_node.child_by_field_name("body")
    for child in _walk_tree(body):
        if child.type == "call_expression":
            func = child.child_by_field_name("function")
            callees.append((func.text.decode().strip(), child))
    return callees
```

## 跨文件调用者搜索

`_extract_callers()` 在提供 `project_root` 时，会搜索项目中其他源文件：

```python
if project_root and file_path != project_root:
    for src_file in search_dir.rglob("*"):
        if src_file.suffix in (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"):
            if src_file.resolve() != file_path.resolve():
                other_root = self._get_ast(src_file)
                other_callers = _find_callers(other_root, func_name)
                # 添加到 slices
                if len(slices) >= max_call_depth:
                    break
```

结果受 `max_call_depth` 限制（默认 2），防止单个锚点的调用者切片爆炸。

## 函数名提取

`_get_function_name()` 从 `function_definition` 节点提取函数名，处理多种声明形式：

```
int foo()           → declarator → identifier "foo"
int *foo()          → declarator → pointer_declarator → identifier "foo"
int (*foo)(int)     → declarator → function_declarator → identifier "foo"
```

## 已知局限

1. **宏不展开** — Tree-sitter 不预处理 C 宏，`DANGEROUS_CALL(x)` 不会被识别
2. **指针别名追踪有限** — 1-2 层深度无法完整追踪多级指针间接
3. **跨文件搜索全量扫描** — `rglob("*")` 对大项目性能不佳
4. **C++ 虚函数/函数指针** — 只能匹配静态调用，无法追踪动态分发

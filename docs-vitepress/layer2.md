# Layer 2: 切片引擎

Layer 2 是 AgentSAST 的核心桥梁，职责是将 L1 产出的稀疏锚点 **膨胀为丰富的代码上下文**，供 L3 的 LLM 进行精确判定。

## 为什么需要切片？

LLM 的判定质量高度依赖上下文完整度。如果把整个文件喂给 LLM：
- Token 浪费：一个 500 行文件中，与漏洞相关的可能只有 20 行
- 信息噪音：无关代码干扰 LLM 判断
- 窗口限制：大文件可能超出上下文窗口

程序切片技术从锚点出发，**只提取与漏洞相关的代码片段**。

## 四类切片

`SlicingEngine` 对每个 Anchor 提取四类上下文：

| 切片类型 | 目的 | 源字段 |
|----------|------|--------|
| **raw_function** | 锚点所在的完整函数体 | `SlicingResult.raw_function` |
| **struct_defs** | 函数中使用的结构体/类型定义 | `SlicingResult.struct_defs` |
| **dataflow_slices** | 从数据源到 sink 的后向切片 | `SlicingResult.dataflow_slices` |
| **caller_slices** | 调用当前函数的上游函数 | `SlicingResult.caller_slices` |
| **callee_slices** | 当前函数调用的下游函数 | `SlicingResult.callee_slices` |

## 执行流程

```
slice_anchor(anchor, project_root)
  │
  ├── 1. 解析锚点文件 → AST
  │
  ├── 2. 定位锚点所在函数 (_find_enclosing_function)
  │
  ├── 3. 提取原始函数体 → raw_function
  │
  ├── 4. 提取结构体定义 (_extract_struct_defs)
  │     └── 从函数体提取类型名 → 全文件搜索定义
  │
  ├── 5. 后向数据流切片 (_extract_dataflow)
  │     ├── 提取函数参数名
  │     ├── 提取 sink 函数参数变量
  │     └── 对每个变量执行 _backward_slice_var
  │
  ├── 6. 调用者搜索 (_extract_callers)
  │     ├── 当前文件内搜索
  │     └── 跨文件搜索 (project_root)
  │
  └── 7. 被调用者搜索 (_extract_callees)
        └── 函数体内所有 call_expression
```

## 切片深度控制

`max_call_depth` 参数控制调用链追踪深度：
- 默认值 2：覆盖 92% 的实用场景
- 深度越深 → 上下文越完整，但 token 成本指数增长
- Pareto 最优点：2 层是精度/成本的最佳平衡

## 跨文件搜索

当提供 `project_root` 时，`_extract_callers` 会在整个项目中搜索调用当前函数的其他文件：

```python
for src_file in search_dir.rglob("*"):
    if src_file.suffix in (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"):
        other_root = self._get_ast(src_file)
        other_callers = _find_callers(other_root, func_name)
```

搜索结果受 `max_call_depth` 限制，防止爆炸。

## AST 缓存

`SlicingEngine._file_cache` 缓存已解析的 AST，避免同一文件重复解析：

```python
def _get_ast(self, file_path: Path) -> Node | None:
    file_path = file_path.resolve()
    if file_path not in self._file_cache:
        self._file_cache[file_path] = self.parser.parse_file(file_path)
    return self._file_cache[file_path]
```

**注意**: 长时间运行的会话中，缓存不会失效。如果文件在运行期间被修改，需要重建 `SlicingEngine` 实例。

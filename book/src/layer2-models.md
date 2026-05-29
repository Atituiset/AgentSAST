# Layer 2 数据模型

> 源码: `src/agentsast/layer2/models.py`

## CodeSlice

单个代码切片，代表一段从源文件中提取的代码片段：

```python
@dataclass
class CodeSlice:
    file: Path            # 源文件路径
    start_line: int       # 起始行号 (1-indexed)
    end_line: int         # 结束行号 (1-indexed)
    content: str          # 代码内容
    slice_type: str = "unknown"  # 切片类型
    label: str = ""              # 可读标签
```

### slice_type 取值

| 值 | 说明 |
|----|------|
| `"raw_function"` | 锚点所在的完整函数体 |
| `"struct_def"` | 结构体/类型定义 |
| `"dataflow"` | 后向数据流切片 |
| `"caller"` | 调用者函数 |
| `"callee"` | 被调用函数 |
| `"full_function_backdrop"` | 降级模式：函数从头到 sink 的全量代码 |

### label 示例

| slice_type | label 格式 | 示例 |
|------------|-----------|------|
| `raw_function` | `"sink_function"` | — |
| `struct_def` | 类型名 | `"RequestContext"` |
| `dataflow` | `"backward_slice:{var}"` | `"backward_slice:external_data"` |
| `caller` | `"caller_of:{func}"` | `"caller_of:process_buffer"` |
| `callee` | `"callee:{func}"` | `"callee:printf"` |

### 序列化

```python
def to_dict(self) -> dict:
    return {
        "file": str(self.file),
        "start_line": self.start_line,
        "end_line": self.end_line,
        "content": self.content,
        "slice_type": self.slice_type,
        "label": self.label,
    }
```

## SlicingResult

一个锚点的完整切片结果，包含所有四类切片：

```python
@dataclass
class SlicingResult:
    anchor_file: Path                               # 锚点文件
    anchor_line: int                                # 锚点行号
    struct_defs: list[CodeSlice] = field(default_factory=list)
    dataflow_slices: list[CodeSlice] = field(default_factory=list)
    caller_slices: list[CodeSlice] = field(default_factory=list)
    callee_slices: list[CodeSlice] = field(default_factory=list)
    raw_function: CodeSlice | None = None
```

### all_slices()

便利方法，返回所有切片的合并列表：

```python
def all_slices(self) -> list[CodeSlice]:
    slices = []
    slices.extend(self.struct_defs)
    slices.extend(self.dataflow_slices)
    slices.extend(self.caller_slices)
    slices.extend(self.callee_slices)
    if self.raw_function:
        slices.append(self.raw_function)
    return slices
```

### to_dict()

序列化时 `callee_slices` 不包含在输出中（当前版本简化），但 `raw_function` 会单独处理：

```python
def to_dict(self) -> dict:
    result = {
        "anchor_file": str(self.anchor_file),
        "anchor_line": self.anchor_line,
        "struct_defs": [s.to_dict() for s in self.struct_defs],
        "dataflow_slices": [s.to_dict() for s in self.dataflow_slices],
        "caller_slices": [s.to_dict() for s in self.caller_slices],
    }
    if self.raw_function:
        result["raw_function"] = self.raw_function.to_dict()
    return result
```

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CodeSlice:
    file: Path
    start_line: int
    end_line: int
    content: str
    slice_type: str = "unknown"
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "file": str(self.file),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "slice_type": self.slice_type,
            "label": self.label,
        }


@dataclass
class SlicingResult:
    anchor_file: Path
    anchor_line: int
    struct_defs: list[CodeSlice] = field(default_factory=list)
    dataflow_slices: list[CodeSlice] = field(default_factory=list)
    caller_slices: list[CodeSlice] = field(default_factory=list)
    callee_slices: list[CodeSlice] = field(default_factory=list)
    raw_function: CodeSlice | None = None

    def all_slices(self) -> list[CodeSlice]:
        slices = []
        slices.extend(self.struct_defs)
        slices.extend(self.dataflow_slices)
        slices.extend(self.caller_slices)
        slices.extend(self.callee_slices)
        if self.raw_function:
            slices.append(self.raw_function)
        return slices

    def to_dict(self) -> dict:
        result: dict = {
            "anchor_file": str(self.anchor_file),
            "anchor_line": self.anchor_line,
            "struct_defs": [s.to_dict() for s in self.struct_defs],
            "dataflow_slices": [s.to_dict() for s in self.dataflow_slices],
            "caller_slices": [s.to_dict() for s in self.caller_slices],
        }
        if self.raw_function:
            result["raw_function"] = self.raw_function.to_dict()
        return result

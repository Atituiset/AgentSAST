from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"
    NONE = "none"


@dataclass
class Location:
    file: Path
    line: int
    col: int = 0
    end_line: int = 0
    end_col: int = 0
    message: str = ""

    def __post_init__(self):
        self.file = Path(self.file)

    def to_dict(self) -> dict:
        return {
            "file": str(self.file),
            "line": self.line,
            "col": self.col,
            "end_line": self.end_line,
            "end_col": self.end_col,
            "message": self.message,
        }


@dataclass
class Anchor:
    rule_id: str
    tool: str
    severity: Severity
    message: str
    location: Location
    cwe: str = ""
    sink_function: str = ""
    sink_params: list[str] = field(default_factory=list)
    raw_sarif: dict = field(default_factory=dict)
    source_location: Location | None = None
    dataflow_path: list[Location] = field(default_factory=list)

    @property
    def file(self) -> Path:
        return self.location.file

    @property
    def line(self) -> int:
        return self.location.line

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "tool": self.tool,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location.to_dict(),
            "cwe": self.cwe,
            "sink_function": self.sink_function,
            "sink_params": self.sink_params,
            "source_location": self.source_location.to_dict() if self.source_location else None,
            "dataflow_path": [loc.to_dict() for loc in self.dataflow_path],
        }

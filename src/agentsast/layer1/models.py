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

    def __post_init__(self):
        self.file = Path(self.file)


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
            "location": {
                "file": str(self.location.file),
                "line": self.location.line,
                "col": self.location.col,
            },
            "cwe": self.cwe,
            "sink_function": self.sink_function,
            "sink_params": self.sink_params,
        }

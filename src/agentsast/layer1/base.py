# src/agentsast/layer1/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from .models import Anchor


@dataclass
class ScanContext:
    target: Path
    compile_db: Path | None = None
    timeout: int = 600
    config: dict = field(default_factory=dict)


class Scanner(Protocol):
    name: str
    requires_compilation: bool

    def is_available(self) -> bool: ...

    def scan(self, ctx: ScanContext) -> list[Anchor]: ...


SCANNER_REGISTRY: dict[str, type] = {}
_T = TypeVar("_T")


def register_scanner(key: str):
    """注册扫描器，使其可被 --tools <key> 选中。"""
    def deco(cls: _T) -> _T:
        SCANNER_REGISTRY[key] = cls  # type: ignore[assignment]
        return cls
    return deco

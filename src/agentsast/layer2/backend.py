# src/agentsast/layer2/backend.py
"""Layer2 程序理解后端抽象。切片引擎通过此接口获取 caller/callee，
默认实现是 tree-sitter，可替换为 clangd(MCP)等语义级后端。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..layer1.models import Location


@dataclass
class FunctionRef:
    """一个函数引用(用于 caller/callee 切片)。location 含起止行。"""
    name: str
    location: Location


class ProgramUnderstandingBackend(Protocol):
    """程序理解后端：提供 caller/callee 查找。

    实现需保证 find_callers/find_callees 返回的 FunctionRef.location 含
    起止行(start_line/end_line)，供切片引擎读取函数源码片段。
    """

    def find_callers(
        self,
        func_name: str,
        loc: Location,
        project_root: Path | None = None,
    ) -> list[FunctionRef]: ...

    def find_callees(self, func_name: str, loc: Location) -> list[FunctionRef]: ...

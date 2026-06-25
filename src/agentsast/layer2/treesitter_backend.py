# src/agentsast/layer2/treesitter_backend.py
"""TreeSitterBackend：封装现有 tree-sitter caller/callee 查找逻辑，
使其满足 ProgramUnderstandingBackend 接口。行为与原 slicer 的
_find_callers/_find_callees 等价（含跨文件搜索）。"""
from __future__ import annotations

from pathlib import Path

from tree_sitter import Node

from ..layer1.models import Location
from .backend import FunctionRef
from .parser import ASTParser

_SRC_EXTS = (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp")


def _walk(node: Node):
    stack = list(node.children)
    while stack:
        c = stack.pop()
        yield c
        stack.extend(c.children)


def _get_function_name(func_node: Node) -> str:
    decl = func_node.child_by_field_name("declarator")
    if not decl:
        return ""
    for child in decl.children:
        if child.type == "identifier":
            return child.text.decode()
        if child.type in ("pointer_declarator", "function_declarator"):
            for sub in child.children:
                if sub.type == "identifier":
                    return sub.text.decode()
    return ""


def _find_caller_funcs(root: Node, func_name: str) -> list[Node]:
    callers: list[Node] = []
    for node in _walk(root):
        if node.type == "function_definition":
            body = node.child_by_field_name("body")
            if body is None:
                continue
            for child in _walk(body):
                if child.type == "call_expression":
                    fn = child.child_by_field_name("function")
                    if fn and fn.text.decode().strip() == func_name:
                        callers.append(node)
                        break
    return callers


def _find_callee_funcs(func_node: Node) -> list[tuple[str, Node]]:
    callees: list[tuple[str, Node]] = []
    body = func_node.child_by_field_name("body")
    if not body:
        return callees
    for child in _walk(body):
        if child.type == "call_expression":
            fn = child.child_by_field_name("function")
            if fn:
                callees.append((fn.text.decode().strip(), child))
    return callees


def _find_enclosing_function(root: Node, line: int) -> Node | None:
    best: Node | None = None
    for node in _walk(root):
        if node.type == "function_definition":
            sp, ep = node.start_point[0] + 1, node.end_point[0] + 1
            if sp <= line <= ep:
                if best is None or (ep - sp < best.end_point[0] - best.start_point[0]):
                    best = node
    return best


class TreeSitterBackend:
    """默认后端：tree-sitter 语法级 caller/callee。"""

    def __init__(self, max_call_depth: int = 2):
        self.parser = ASTParser()
        self.max_call_depth = max_call_depth
        self._cache: dict[Path, Node | None] = {}

    def _ast(self, path: Path) -> Node | None:
        rp = path.resolve()
        if rp not in self._cache:
            self._cache[rp] = self.parser.parse_file(rp)
        return self._cache[rp]

    def find_callers(self, func_name, loc, project_root=None) -> list[FunctionRef]:
        if not func_name:
            return []
        refs: list[FunctionRef] = []
        root = self._ast(Path(loc.file))
        if root:
            for node in _find_caller_funcs(root, func_name):
                refs.append(FunctionRef(
                    name=_get_function_name(node) or func_name,
                    location=Location(
                        file=Path(loc.file),
                        line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                    ),
                ))
        # 跨文件搜索
        if project_root:
            pr = Path(project_root)
            search_dir = pr if pr.is_dir() else Path(loc.file).parent
            for src in search_dir.rglob("*"):
                if src.suffix.lower() not in _SRC_EXTS:
                    continue
                if src.resolve() == Path(loc.file).resolve():
                    continue
                other = self._ast(src)
                if not other:
                    continue
                for node in _find_caller_funcs(other, func_name):
                    refs.append(FunctionRef(
                        name=_get_function_name(node) or func_name,
                        location=Location(
                            file=src, line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                        ),
                    ))
                if len(refs) >= self.max_call_depth:
                    break
        return refs[: self.max_call_depth]

    def find_callees(self, func_name, loc) -> list[FunctionRef]:
        root = self._ast(Path(loc.file))
        if not root:
            return []
        func_node = _find_enclosing_function(root, loc.line)
        if not func_node:
            return []
        refs: list[FunctionRef] = []
        for name, call_node in _find_callee_funcs(func_node)[:5]:
            refs.append(FunctionRef(
                name=name,
                location=Location(
                    file=Path(loc.file),
                    line=call_node.start_point[0] + 1,
                    end_line=call_node.end_point[0] + 1,
                ),
            ))
        return refs

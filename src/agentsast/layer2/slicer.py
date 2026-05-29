from __future__ import annotations

import logging
from pathlib import Path

from tree_sitter import Node

from ..layer1.models import Anchor
from .models import CodeSlice, SlicingResult
from .parser import ASTParser

logger = logging.getLogger(__name__)


def _walk_tree(node: Node):
    stack = list(node.children)
    while stack:
        child = stack.pop()
        yield child
        stack.extend(child.children)


def _contains_line(node: Node, line: int) -> bool:
    return node.start_point[0] + 1 <= line <= node.end_point[0] + 1


def _find_enclosing_function(root: Node, line: int) -> Node | None:
    best: Node | None = None
    for node in _walk_tree(root):
        if node.type == "function_definition" and _contains_line(node, line):
            if best is None or (
                node.end_point[0] - node.start_point[0]
                < best.end_point[0] - best.start_point[0]
            ):
                best = node
    return best


def _find_struct_defs(root: Node, type_names: set[str]) -> list[Node]:
    results: list[Node] = []
    for node in _walk_tree(root):
        if node.type == "type_definition":
            struct_spec = None
            typedef_name = None
            for child in node.children:
                if child.type in ("struct_specifier", "class_specifier"):
                    struct_spec = child
                elif child.type == "type_identifier":
                    typedef_name = child.text.decode()
            if typedef_name and typedef_name in type_names:
                results.append(node)
                continue
            if struct_spec:
                name_node = struct_spec.child_by_field_name("name")
                if name_node and name_node.text.decode() in type_names:
                    results.append(node)
        elif node.type in ("struct_specifier", "class_specifier"):
            name_node = node.child_by_field_name("name")
            if name_node and name_node.text.decode() in type_names:
                parent = node.parent
                if parent and parent.type == "type_definition":
                    if parent not in results:
                        results.append(parent)
                else:
                    if node not in results:
                        results.append(node)
    return results


def _extract_type_names_from_node(node: Node) -> set[str]:
    types: set[str] = set()
    for child in _walk_tree(node):
        if child.type == "type_identifier":
            types.add(child.text.decode())
        elif child.type == "struct_specifier":
            name = child.child_by_field_name("name")
            if name:
                types.add(name.text.decode())
    return types


def _find_callers(root: Node, func_name: str) -> list[Node]:
    callers: list[Node] = []
    for node in _walk_tree(root):
        if node.type == "function_definition":
            body = node.child_by_field_name("body")
            if body is None:
                continue
            for child in _walk_tree(body):
                if child.type == "call_expression":
                    func = child.child_by_field_name("function")
                    if func and func.text.decode().strip() == func_name:
                        callers.append(node)
                        break
    return callers


def _find_callees(func_node: Node) -> list[tuple[str, Node]]:
    callees: list[tuple[str, Node]] = []
    body = func_node.child_by_field_name("body")
    if not body:
        return callees
    for child in _walk_tree(body):
        if child.type == "call_expression":
            func = child.child_by_field_name("function")
            if func:
                callees.append((func.text.decode().strip(), child))
    return callees


def _backward_slice_var(
    node: Node, var_name: str, max_depth: int = 2
) -> list[Node]:
    related: list[Node] = []
    scope = node.parent
    depth = 0
    while scope and depth < max_depth:
        for child in _walk_tree(scope):
            if child.type == "declaration":
                for sub in _walk_tree(child):
                    if (
                        sub.type == "identifier"
                        and sub.text.decode() == var_name
                    ):
                        related.append(child)
                        break
            elif child.type == "assignment_expression":
                left = child.child_by_field_name("left")
                if left and left.text.decode() == var_name:
                    related.append(child)
        scope = scope.parent
        depth += 1
    return related


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


def _get_typedef_name(node: Node) -> str:
    if node.type != "type_definition":
        name = node.child_by_field_name("name")
        return name.text.decode() if name else ""
    for child in node.children:
        if child.type == "type_identifier":
            return child.text.decode()
    return ""


class SlicingEngine:
    def __init__(self, max_call_depth: int = 2):
        self.parser = ASTParser()
        self.max_call_depth = max_call_depth
        self._file_cache: dict[Path, Node] = {}

    def _get_ast(self, file_path: Path) -> Node | None:
        file_path = file_path.resolve()
        if file_path not in self._file_cache:
            self._file_cache[file_path] = self.parser.parse_file(file_path)
        return self._file_cache[file_path]

    def _resolve_file_from_root(self, root: Node) -> Path:
        for path, cached_root in self._file_cache.items():
            if cached_root is root:
                return path
        return Path("unknown")

    def slice_anchor(
        self, anchor: Anchor, project_root: Path | None = None
    ) -> SlicingResult:
        file_path = anchor.file.resolve()
        if not file_path.exists():
            if project_root:
                candidate = project_root / anchor.file
                if candidate.exists():
                    file_path = candidate.resolve()

        root = self._get_ast(file_path)
        if root is None:
            logger.warning("Cannot parse %s, returning empty slice", file_path)
            return SlicingResult(
                anchor_file=anchor.file, anchor_line=anchor.line
            )

        result = SlicingResult(
            anchor_file=anchor.file, anchor_line=anchor.line
        )

        func_node = _find_enclosing_function(root, anchor.line)
        if func_node is None:
            logger.warning(
                "Could not find enclosing function for line %d in %s",
                anchor.line,
                file_path,
            )
            return result

        result.raw_function = ASTParser.node_to_slice(
            file_path, func_node, "raw_function", "sink_function"
        )
        result.struct_defs = self._extract_struct_defs(
            file_path, root, func_node
        )
        result.dataflow_slices = self._extract_dataflow(
            file_path, root, func_node, anchor
        )
        result.caller_slices = self._extract_callers(
            file_path, root, func_node, project_root
        )
        result.callee_slices = self._extract_callees(file_path, func_node)

        return result

    def _extract_struct_defs(
        self, file_path: Path, root: Node, func_node: Node
    ) -> list[CodeSlice]:
        type_names = _extract_type_names_from_node(func_node)
        if not type_names:
            return []

        struct_nodes = _find_struct_defs(root, type_names)
        slices: list[CodeSlice] = []
        for node in struct_nodes:
            label = _get_typedef_name(node) or "unknown"
            slices.append(
                ASTParser.node_to_slice(file_path, node, "struct_def", label)
            )
        return slices

    def _extract_dataflow(
        self,
        file_path: Path,
        root: Node,
        func_node: Node,
        anchor: Anchor,
    ) -> list[CodeSlice]:
        slices: list[CodeSlice] = []

        body = func_node.child_by_field_name("body")
        if not body:
            return slices

        sink_line = anchor.line
        params_node = func_node.child_by_field_name("declarator")
        param_names: set[str] = set()
        if params_node:
            for child in _walk_tree(params_node):
                if child.type == "parameter_declaration":
                    decl = child.child_by_field_name("declarator")
                    if decl and decl.type == "identifier":
                        param_names.add(decl.text.decode())
                    elif decl and decl.type == "pointer_declarator":
                        for sub in decl.children:
                            if sub.type == "identifier":
                                param_names.add(sub.text.decode())

        var_names = set(param_names)
        if anchor.sink_function:
            for child in _walk_tree(body):
                if child.type == "call_expression":
                    func = child.child_by_field_name("function")
                    if (
                        func
                        and func.text.decode().strip() == anchor.sink_function
                    ):
                        args = child.child_by_field_name("arguments")
                        if args:
                            for arg in args.children:
                                if arg.type == "identifier":
                                    var_names.add(arg.text.decode())
                                elif arg.type in (
                                    "pointer_expression",
                                    "field_expression",
                                ):
                                    for sub in _walk_tree(arg):
                                        if (
                                            sub.type == "identifier"
                                            and sub.text.decode()
                                            not in var_names
                                        ):
                                            var_names.add(
                                                sub.text.decode()
                                            )

        for var_name in var_names:
            related_nodes = _backward_slice_var(
                func_node, var_name, max_depth=self.max_call_depth
            )
            for node in related_nodes:
                if node.start_point[0] + 1 != sink_line:
                    label = f"backward_slice:{var_name}"
                    slices.append(
                        ASTParser.node_to_slice(
                            file_path, node, "dataflow", label
                        )
                    )

        if not slices:
            start = max(1, func_node.start_point[0] + 1)
            end = min(func_node.end_point[0] + 1, sink_line)
            content = ASTParser.get_line_content(file_path, start, end)
            slices.append(
                CodeSlice(
                    file=file_path,
                    start_line=start,
                    end_line=end,
                    content=content,
                    slice_type="dataflow",
                    label="full_function_backdrop",
                )
            )

        return slices

    def _extract_callers(
        self,
        file_path: Path,
        root: Node,
        func_node: Node,
        project_root: Path | None,
    ) -> list[CodeSlice]:
        slices: list[CodeSlice] = []
        func_name = _get_function_name(func_node)
        if not func_name:
            return slices

        caller_nodes = _find_callers(root, func_name)
        for caller in caller_nodes:
            if caller is not func_node:
                label = f"caller_of:{func_name}"
                slices.append(
                    ASTParser.node_to_slice(
                        file_path, caller, "caller", label
                    )
                )

        if project_root and file_path != project_root:
            search_dirs = (
                [project_root]
                if project_root.is_dir()
                else [file_path.parent]
            )
            for search_dir in search_dirs:
                src_exts = (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp")
                for src_file in search_dir.rglob("*"):
                    if (
                        src_file.suffix.lower() in src_exts
                        and src_file.resolve() != file_path.resolve()
                    ):
                        other_root = self._get_ast(src_file)
                        if other_root:
                            other_callers = _find_callers(
                                other_root, func_name
                            )
                            for caller in other_callers:
                                label = f"caller_of:{func_name}"
                                slices.append(
                                    ASTParser.node_to_slice(
                                        src_file, caller, "caller", label
                                    )
                                )
                            if len(slices) >= self.max_call_depth:
                                break
                if len(slices) >= self.max_call_depth:
                    break

        return slices[: self.max_call_depth]

    def _extract_callees(
        self, file_path: Path, func_node: Node
    ) -> list[CodeSlice]:
        slices: list[CodeSlice] = []
        callees = _find_callees(func_node)
        for name, call_node in callees[:5]:
            start = call_node.start_point[0] + 1
            end = call_node.end_point[0] + 1
            content = ASTParser.get_line_content(file_path, start, end)
            slices.append(
                CodeSlice(
                    file=file_path,
                    start_line=start,
                    end_line=end,
                    content=content,
                    slice_type="callee",
                    label=f"callee:{name}",
                )
            )
        return slices

from __future__ import annotations

import logging
from pathlib import Path

from tree_sitter import Language, Node, Parser

try:
    import tree_sitter_c as tsc
except ImportError:
    tsc = None

try:
    import tree_sitter_cpp as tscpp
except ImportError:
    tscpp = None

from .models import CodeSlice

logger = logging.getLogger(__name__)

C_EXTENSIONS = {".c", ".h"}
CPP_EXTENSIONS = {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"}
ALL_EXTENSIONS = C_EXTENSIONS | CPP_EXTENSIONS


def _get_language(ext: str) -> Language | None:
    if tsc is not None and ext in C_EXTENSIONS:
        return Language(tsc.language())
    if tscpp is not None and ext in CPP_EXTENSIONS:
        return Language(tscpp.language())
    if tscpp is not None and ext == ".h":
        return Language(tscpp.language())
    return None


class ASTParser:
    def __init__(self):
        self._parsers: dict[Language, Parser] = {}

    def parse_file(self, file_path: Path) -> Node | None:
        ext = file_path.suffix.lower()
        lang = _get_language(ext)
        if lang is None:
            logger.warning("No tree-sitter grammar for extension %s", ext)
            return None

        if lang not in self._parsers:
            parser = Parser(lang)
            self._parsers[lang] = parser

        try:
            content = file_path.read_bytes()
        except OSError:
            logger.error("Cannot read file: %s", file_path)
            return None

        tree = self._parsers[lang].parse(content)
        return tree.root_node

    @staticmethod
    def get_line_content(
        file_path: Path, start_line: int, end_line: int
    ) -> str:
        try:
            lines = file_path.read_text(errors="replace").splitlines(
                keepends=True
            )
            start = max(0, start_line - 1)
            end = min(len(lines), end_line)
            return "".join(lines[start:end])
        except OSError:
            return ""

    @staticmethod
    def node_to_slice(
        file_path: Path, node: Node, slice_type: str, label: str = ""
    ) -> CodeSlice:
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        content = ASTParser.get_line_content(file_path, start_line, end_line)
        return CodeSlice(
            file=file_path,
            start_line=start_line,
            end_line=end_line,
            content=content,
            slice_type=slice_type,
            label=label,
        )

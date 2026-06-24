# tests/layer1/test_handlers_infer.py
from __future__ import annotations

from agentsast.layer1.handlers.infer import extract_path_from_message


def test_extract_path_finds_both_lines():
    msg = "pointer `p` assigned at line 5; dereferenced at line 12"
    src_line, sink_line = extract_path_from_message(msg)
    assert src_line == 5
    assert sink_line == 12


def test_extract_path_returns_none_when_missing():
    msg = "some message with no line info"
    src_line, sink_line = extract_path_from_message(msg)
    assert src_line is None
    assert sink_line is None


def test_extract_path_with_path_bearing_message():
    msg = (
        "pointer `p` assigned at line 5 (see /src/main.c); "
        "dereferenced at line 12 (see /src/main.c)"
    )
    src_line, sink_line = extract_path_from_message(msg)
    assert src_line == 5
    assert sink_line == 12

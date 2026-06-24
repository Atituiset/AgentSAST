# src/agentsast/layer1/handlers/infer.py
"""Infer SARIF 特化提取逻辑。参考 gen-auto/sarif/infer.py（逻辑参考，全新实现）。

Infer 的 source/sink 行号嵌在 result.message.text 中，SARIF 不提供 codeFlows，
故需要从 message 正则还原 source→sink。
"""
from __future__ import annotations

import re

# 匹配 "assigned at line N" / "line N" 形式（DOTALL + 非捕获宽松间隔：消息可能含换行/路径的点）
_ASSIGN_RE = re.compile(r"assigned(?:.*?)line\s+(\d+)", re.IGNORECASE | re.DOTALL)
_DEREF_RE = re.compile(r"deref\w*(?:.*?)line\s+(\d+)", re.IGNORECASE | re.DOTALL)


def extract_path_from_message(message: str) -> tuple[int | None, int | None]:
    """返回 (source_line, sink_line)；无法提取则为 None。"""
    src = _ASSIGN_RE.search(message)
    sink = _DEREF_RE.search(message)
    return (int(src.group(1)) if src else None,
            int(sink.group(1)) if sink else None)


def enhance_anchor(anchor) -> None:
    """对通用层产出的 Anchor 补全 source_location / dataflow_path（原地修改）。

    仅当通用层未还原路径（source_location/dataflow_path 为空）时，从 message 提取。
    """
    if anchor.source_location is not None and anchor.dataflow_path:
        return  # 通用层已还原，无需处理
    src_line, sink_line = extract_path_from_message(anchor.message)
    if src_line and sink_line:
        Loc = type(anchor.location)
        anchor.source_location = Loc(file=anchor.location.file, line=src_line)
        anchor.dataflow_path = [
            Loc(file=anchor.location.file, line=src_line),
            Loc(file=anchor.location.file, line=sink_line),
        ]

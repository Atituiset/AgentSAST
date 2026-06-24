# src/agentsast/layer1/handlers/csa.py
"""CSA (Clang Static Analyzer) 特化。CSA 的 SARIF 通常带 codeFlows，
通用层即可还原路径；本 handler 处理 source_location 缺失但有 dataflow_path 的情况，
并在无 codeFlows 时保守地不编造 source。"""
from __future__ import annotations


def is_csa_result(anchor) -> bool:
    return anchor.tool.lower() in ("clang", "csa") or anchor.rule_id.startswith("core.")


def enhance_anchor(anchor) -> None:
    if anchor.source_location is not None:
        return
    if anchor.dataflow_path:
        anchor.source_location = anchor.dataflow_path[0]
        return
    # 无 codeFlows：CSA message 一般不含行号，无法反推 → 保持空（保守，不编造）

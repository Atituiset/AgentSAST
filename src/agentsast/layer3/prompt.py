from __future__ import annotations

import logging

from ..layer1.models import Anchor
from ..layer2.models import SlicingResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a top-tier C/C++ security auditor. Your task is to "
    "evaluate whether a static analysis alert represents a TRUE "
    "vulnerability or a FALSE POSITIVE, based ONLY on the code "
    "context slices provided.\n"
    "\n"
    "## CRITICAL CONSTRAINTS (Anti-Hallucination)\n"
    "1. You MUST base your reasoning ONLY on the code fragments "
    "provided in `context_slices`.\n"
    "2. You MUST NOT assume the existence of any sanitization, "
    "bounds-checking, or validation logic that is NOT present "
    "in the provided code.\n"
    "3. If you are unsure whether a check exists, state it "
    "explicitly — do NOT guess that it is safe.\n"
    "4. You MUST reference specific line numbers from the "
    "provided context when making your argument.\n"
    "\n"
    "## ANALYSIS PROCEDURE (Chain-of-Thought)\n"
    "Follow these steps strictly:\n"
    "\n"
    "### Step 1: Source Tracing\n"
    "- Identify the origin of each variable/parameter that "
    "flows into the dangerous sink.\n"
    "- Determine: Is the source controllable by an external/"
    "untrusted input? (e.g., network data, user input, "
    "file I/O, environment variables)\n"
    "\n"
    "### Step 2: Sanitization Check\n"
    "- Trace the data path from source to sink.\n"
    "- Check: Does any code in the provided slices perform "
    "bounds checking, input validation, or sanitization "
    "on the variable?\n"
    "- If a sanitization check is present AND correct, "
    "the alert may be a false positive.\n"
    "\n"
    "### Step 3: Memory Layout Analysis (for buffer-related CWEs)\n"
    "- If the alert involves a buffer overflow or out-of-bounds "
    "access:\n"
    "  - Determine the declared size of the destination buffer "
    "from the struct definitions.\n"
    "  - Determine whether the source data size can exceed the "
    "buffer capacity.\n"
    "  - Check for off-by-one errors or integer overflow in "
    "size calculations.\n"
    "\n"
    "### Step 4: Verdict\n"
    "- Based on Steps 1-3, decide: Is this a TRUE POSITIVE "
    "(vulnerable) or FALSE POSITIVE (safe)?\n"
    "\n"
    "## OUTPUT FORMAT\n"
    'Respond with ONLY a JSON object (no markdown, no '
    "explanation outside the JSON):\n"
    "{\n"
    '  "is_vulnerable": true/false,\n'
    '  "confidence": 0.0-1.0,\n'
    '  "cwe": "CWE-XXX or empty",\n'
    '  "reason": "Your detailed reasoning referencing '
    'specific code lines"\n'
    "}\n"
)


def build_payload(anchor: Anchor, slicing: SlicingResult) -> dict:
    struct_defs = [
        f"L{s.start_line}: {s.content.strip()}"
        for s in slicing.struct_defs
    ]
    dataflow = [
        f"L{s.start_line}: {s.content.strip()}"
        for s in slicing.dataflow_slices
    ]
    callers = [
        f"L{s.start_line} ({s.label}): {s.content.strip()}"
        for s in slicing.caller_slices
    ]

    raw_fn = ""
    if slicing.raw_function:
        raw_fn = slicing.raw_function.content.strip()

    return {
        "alert": {
            "tool": anchor.tool,
            "rule_id": anchor.rule_id,
            "sink_line": anchor.line,
            "cwe": anchor.cwe,
            "message": anchor.message,
            "sink_function": anchor.sink_function,
        },
        "context_slices": {
            "struct_defs": struct_defs,
            "dataflow": dataflow,
            "callers": callers,
        },
        "raw_function": raw_fn,
    }


def build_user_prompt(payload: dict) -> str:
    alert = payload["alert"]
    ctx = payload["context_slices"]
    raw_fn = payload["raw_function"]

    parts: list[str] = [
        f"## Alert from {alert['tool']}",
        f"- Rule: {alert['rule_id']}",
        f"- CWE: {alert['cwe'] or 'N/A'}",
    ]

    if alert.get("sink_function"):
        parts.append(
            f"- Sink at line {alert['sink_line']}: "
            f"function `{alert['sink_function']}`"
        )
    else:
        parts.append(f"- Sink at line {alert['sink_line']}")

    parts.append(f"- Message: {alert['message']}")
    parts.append("")

    if ctx["struct_defs"]:
        parts.append("## Struct/Type Definitions")
        parts.extend(ctx["struct_defs"])
        parts.append("")

    if ctx["dataflow"]:
        parts.append("## Data Flow (Backward Slicing)")
        parts.extend(ctx["dataflow"])
        parts.append("")

    if ctx["callers"]:
        parts.append("## Caller Context")
        parts.extend(ctx["callers"])
        parts.append("")

    if raw_fn:
        parts.append("## Sink Function (Full)")
        parts.append(raw_fn)

    return "\n".join(parts)

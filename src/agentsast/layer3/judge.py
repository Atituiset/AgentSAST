from __future__ import annotations

import json
import logging
import os

from openai import OpenAI

from ..layer1.models import Anchor
from ..layer2.models import SlicingResult
from .models import LLMResult, Verdict
from .prompt import SYSTEM_PROMPT, build_payload, build_user_prompt

logger = logging.getLogger(__name__)


class LLMJudge:
    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        url = base_url or os.environ.get("OPENAI_BASE_URL", None)

        client_kwargs: dict = {"api_key": key}
        if url:
            client_kwargs["base_url"] = url

        self.client = OpenAI(**client_kwargs)

    def judge(self, anchor: Anchor, slicing: SlicingResult) -> LLMResult:
        payload = build_payload(anchor, slicing)
        user_prompt = build_user_prompt(payload)

        logger.info(
            "Sending to LLM: anchor at %s:%d (CWE: %s)",
            anchor.file,
            anchor.line,
            anchor.cwe,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception:
            logger.exception("LLM API call failed")
            return LLMResult(
                anchor_file=str(anchor.file),
                anchor_line=anchor.line,
                verdict=Verdict.UNCERTAIN,
                confidence=0.0,
                reason="LLM API call failed",
                cwe=anchor.cwe,
                raw_response="",
            )

        raw_text = response.choices[0].message.content.strip()
        return self._parse_response(raw_text, anchor)

    def _parse_response(
        self, raw_text: str, anchor: Anchor
    ) -> LLMResult:
        text = raw_text
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse LLM response as JSON:\n%s", raw_text
            )
            return LLMResult(
                anchor_file=str(anchor.file),
                anchor_line=anchor.line,
                verdict=Verdict.UNCERTAIN,
                confidence=0.0,
                reason="Failed to parse LLM response",
                cwe=anchor.cwe,
                raw_response=raw_text,
            )

        is_vuln = data.get("is_vulnerable", False)
        confidence = float(data.get("confidence", 0.5))
        reason = data.get("reason", "")
        cwe = data.get("cwe", anchor.cwe)

        verdict = Verdict.VULNERABLE if is_vuln else Verdict.SAFE
        if confidence < 0.3:
            verdict = Verdict.UNCERTAIN

        return LLMResult(
            anchor_file=str(anchor.file),
            anchor_line=anchor.line,
            verdict=verdict,
            confidence=confidence,
            reason=reason,
            cwe=cwe,
            raw_response=raw_text,
        )

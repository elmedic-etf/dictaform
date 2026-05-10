"""OpenRouter client that turns a free-form transcript into structured fields.

We try a list of free OpenRouter models in priority order. If a model is rate-
limited, returns malformed JSON, or otherwise fails, we fall through to the
next one. This is critical because free-tier models have aggressive limits
(typically ~20 requests/minute and a daily cap).
"""
import json
import logging
import os
import re

import httpx

from .config_loader import FormConfig

logger = logging.getLogger(__name__)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Free-tier models tried in order. The original plan listed gemini-2.0-flash-exp,
# llama-3.3, and deepseek-chat-v3 — OpenRouter has since retired the gemini and
# deepseek entries and the llama tier is heavily rate-limited. These three were
# the working set in our smoke test, intentionally chosen across three providers
# (OpenAI / Google / Z AI) so a single upstream's quota doesn't take us out.
MODELS: tuple[str, ...] = (
    "openai/gpt-oss-120b:free",
    "google/gemma-4-31b-it:free",
    "z-ai/glm-4.5-air:free",
)

# 30 s is generous: free-tier models are often slow under load. Keeping the UI
# responsive while we wait is the worker's job, not ours.
HTTP_TIMEOUT_S = 30.0


SYSTEM_PROMPT = (
    "You are a medical dictation structuring assistant. The doctor's speech may be "
    "in English or Serbian. Extract the requested fields from the transcript and "
    "return ONLY a single JSON object — no markdown, no commentary, no surrounding "
    "text. If a field is not clearly stated in the transcript, OMIT it from the "
    "JSON entirely (do not guess, do not return null, do not invent values). "
    "Preserve the language of the transcript in the field values; do not translate."
)


class Structurer:
    """Single-call extraction: transcript in, structured ``dict`` out."""

    def __init__(self, config: FormConfig) -> None:
        self.config = config
        # Trim whitespace because users routinely paste keys with newlines.
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not self.api_key:
            logger.warning(
                "OPENROUTER_API_KEY is not set — structuring will be skipped. "
                "Set it in .env to enable AI form filling."
            )
        self._client = httpx.Client(timeout=HTTP_TIMEOUT_S)
        self._schema_text = self._render_schema()

    def close(self) -> None:
        self._client.close()

    # ---------- Public API ---------------------------------------------------

    def extract(self, transcript: str) -> dict:
        """Run the model fallback chain. Returns {field_key: value} (possibly empty)."""
        if not self.api_key or not transcript.strip():
            return {}

        user_prompt = (
            f"{self._schema_text}\n\n"
            f'Transcript:\n"""\n{transcript.strip()}\n"""\n\n'
            "Return a single JSON object with only the fields you can extract."
        )

        for model in MODELS:
            try:
                logger.info("Calling OpenRouter model %s", model)
                raw = self._call(model, user_prompt)
                parsed = self._parse_json(raw)
                cleaned = self._coerce(parsed)
                logger.info("Structured fields from %s: %s", model, cleaned)
                return cleaned
            except Exception as exc:  # noqa: BLE001 — we genuinely want to retry on anything.
                logger.warning("Model %s failed (%s) — falling back", model, exc)

        logger.error("All OpenRouter models failed — returning empty structuring")
        return {}

    # ---------- Internals ----------------------------------------------------

    def _render_schema(self) -> str:
        """Plain-text description of the form fields, embedded in every prompt."""
        lines = ["Fields to extract (use these exact keys):"]
        for field in self.config.all_fields():
            lines.append(f'  - "{field.key}" ({field.type}): {field.label}')
        return "\n".join(lines)

    def _call(self, model: str, user_prompt: str) -> str:
        """One HTTP call to OpenRouter. Returns the raw assistant message text."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter requests a Referer + Title for free-tier attribution.
            "HTTP-Referer": "https://localhost/medical-dictation",
            "X-Title": "Medical Dictation Transcriber",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            # Many free models honor json_object mode; for those that don't,
            # _parse_json strips fences and locates the first {...} block.
            "response_format": {"type": "json_object"},
            # Low temperature — we want consistent extraction, not creative writing.
            "temperature": 0.1,
            # Generous ceiling: reasoning-capable models (gpt-oss et al.) can
            # otherwise burn the whole budget on hidden thinking and return
            # empty content.
            "max_tokens": 2000,
            # Tell models that support it to skip the reasoning channel — we
            # only want the final JSON, and reasoning tokens count toward
            # max_tokens. Models that don't recognise this key ignore it.
            "reasoning": {"exclude": True},
        }
        response = self._client.post(OPENROUTER_URL, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        # OpenRouter sometimes returns 200 with an error body (e.g., upstream
        # provider hiccup). Surface that as an exception so the fallback chain
        # advances to the next model instead of throwing a confusing KeyError.
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"OpenRouter error body: {data['error']}")
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            raise RuntimeError(f"No 'choices' in response: {str(data)[:200]}")
        message = choices[0].get("message", {}) or {}
        # Some models put their answer in `reasoning` instead of `content` if
        # the request didn't fully suppress reasoning. Fall back to it.
        content = (message.get("content") or message.get("reasoning") or "").strip()
        if not content:
            raise RuntimeError("Empty content in response")
        return content

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Best-effort JSON extraction even when the model adds extra text."""
        text = text.strip()

        # Strip ```json ... ``` fences if the model wrapped the response.
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        # If the model included commentary before/after the JSON, locate the
        # outermost {...} block. Greedy match catches nested braces.
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            text = match.group(0)

        result = json.loads(text)
        if not isinstance(result, dict):
            raise ValueError(f"Expected JSON object, got {type(result).__name__}")
        return result

    def _coerce(self, parsed: dict) -> dict:
        """Coerce raw values to declared field types and drop unknown/empty keys."""
        types = {field.key: field.type for field in self.config.all_fields()}
        out: dict = {}
        for key, value in parsed.items():
            if key not in types:
                continue
            if value is None or value == "":
                continue
            try:
                if types[key] == "integer":
                    out[key] = int(value)
                else:
                    # "string" and "text" both serialize as plain strings —
                    # the difference is purely about how the UI renders them.
                    out[key] = str(value).strip()
            except (ValueError, TypeError):
                logger.warning("Could not coerce %r=%r to %s", key, value, types[key])
        return out

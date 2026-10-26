"""Gemini-backed suggestions for malformed standard codes.

Suggestions are formatting/identification hypotheses based on the model's
knowledge of real standards designations. This module does not verify a
code against an authoritative standards catalogue and does not do a live
web/catalogue lookup, so callers must keep ``verified=False`` for any
AI-corrected code. ``explanation`` is the pipeline-facing field name;
it mirrors ``reason`` so the JSON output schema in docs/PIPELINE.md
stays stable even if the Gemini schema changes.
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


load_dotenv()

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OUTPUT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "suggested_code": {"type": "STRING"},
        "alternatives": {"type": "ARRAY", "items": {"type": "STRING"}},
        "status": {"type": "STRING", "enum": ["normalized", "ambiguous", "unrecognized"]},
        "confidence": {"type": "NUMBER", "minimum": 0, "maximum": 1},
        "reason": {"type": "STRING"},
        # Optional alias: some prompts/models fill this instead of reason.
        "explanation": {"type": "STRING"},
    },
    "required": ["suggested_code", "alternatives", "status", "confidence", "reason"],
}


class GeminiConfigurationError(RuntimeError):
    """Raised when Gemini credentials are not configured."""


class GeminiRequestError(RuntimeError):
    """Raised when Gemini rejects the request or returns invalid data."""


def suggest_standard_code(raw_code: str, timeout: float = 30.0) -> dict:
    """Ask Gemini to interpret a malformed code and return a structured suggestion.

    Set GEMINI_API_KEY in the environment or project .env file. The call sends
    only ``raw_code`` to Google's Gemini API.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiConfigurationError("GEMINI_API_KEY is not configured")

    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    prompt = (
        "You are correcting a possibly malformed, incomplete, or wrongly "
        "formatted technical standard designation. Use your knowledge of "
        "real standards designations (TCVN, QCVN, ISO, EN, BS, IEC, ASTM, "
        "and similar bodies) to research the most plausible correct code. "
        "Preserve meaningful parts, year, and amendment when they are "
        "present in the input. In 'reason'/'explanation', explain in one "
        "or two sentences what was wrong or missing and what you changed "
        "and why. Do not claim that a code exists or is officially valid; "
        "the caller will keep it unverified. If multiple readings are "
        "plausible, use status=ambiguous and list them in 'alternatives'. "
        "If there is not enough information, use status=unrecognized and an "
        "empty suggested_code. "
        "IMPORTANT - parenthetical notes in Vietnamese: do NOT drop a "
        "parenthetical note, and do NOT mistake it for a version. "
        "A note such as '(các phần 1-6)', '(phần 1 đến 3)', "
        "'(phần 1-3)', '(các phần 1, 3, 5)' or '(parts 1-6)' is a "
        "PART RANGE / PART LIST, not a version or amendment: 'các phần' "
        "means 'parts', 'phần' means 'part', and 'đến' means 'to'. "
        "For such an input, normalise the parts field to the range, "
        "e.g. input 'TCVN 13566:2022 (các phần 1-6)' -> parts '1-6' "
        "and suggested_code 'TCVN 13566-1-6:2022'; input "
        "'TCVN 1234:2020 (phần 1 đến 3)' -> parts '1-3' and "
        "suggested_code 'TCVN 1234-1-3:2020'. If a range cannot be "
        "encoded cleanly as hyphenated parts, keep the note verbatim "
        "in suggested_code, e.g. 'TCVN 13566:2022 (các phần 1-6)', "
        "and in every case state the range explicitly in "
        "'reason'/'explanation', e.g. 'parenthetical note is a part "
        "range 1-6, not a version'. Never return the bare code "
        "'TCVN 13566:2022' for such an input, because that loses the "
        "parts. By contrast, a note such as '(rev 1)', '(version 2)' "
        "or '(bản sửa đổi 1)' IS a version/amendment: do not turn it "
        "into parts, and mention it in 'reason'/'explanation' if you "
        "keep it. "
        "Return ONLY JSON matching the provided schema, with exactly "
        "these fields and no extra fields: suggested_code, alternatives, "
        "status, confidence, reason, and optionally explanation "
        "(explanation must mirror reason). Input: "
        + json.dumps(raw_code, ensure_ascii=False)
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": OUTPUT_SCHEMA,
            "temperature": 0,
        },
    }
    request = Request(
        API_URL.format(model=model),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        suggestion = json.loads(text)
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise GeminiRequestError(f"Gemini standard-code request failed: {exc}") from exc

    if suggestion.get("status") not in {"normalized", "ambiguous", "unrecognized"}:
        raise GeminiRequestError("Gemini returned an unsupported status")
    if suggestion.get("suggested_code") and not isinstance(suggestion["suggested_code"], str):
        raise GeminiRequestError("Gemini returned an invalid suggested_code")
    suggestion["verified"] = False
    # Pipeline output uses 'explanation'; keep it in sync with 'reason'.
    suggestion["explanation"] = suggestion.get("explanation") or suggestion.get("reason", "")
    suggestion["reason"] = suggestion.get("reason") or suggestion["explanation"]
    return suggestion

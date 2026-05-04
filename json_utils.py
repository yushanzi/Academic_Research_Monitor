from __future__ import annotations

import json


def extract_json_object_text(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and start < end:
        raw = raw[start : end + 1]

    return raw


def parse_json_object(raw: str) -> dict:
    return json.loads(extract_json_object_text(raw))

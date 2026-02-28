"""Core markdown/front matter transformation logic.

This module intentionally uses text operations instead of YAML round-tripping so payload
ordering and formatting remain as close to user input as possible.
"""

from __future__ import annotations

import re
import secrets
import time
from typing import Dict, Optional, Tuple

_UUID_LINE_RE = re.compile(
    r"^uuid(?P<key_ws>\s*):(?P<post_colon_ws>\s*)(?P<value>[^\r\n]*)(?P<line_end>\r?\n|$)",
    re.MULTILINE,
)
_CLOSE_MARKERS = {"---", "..."}


def detect_newline(text: str) -> str:
    """Return CRLF when present, otherwise LF."""
    return "\r\n" if "\r\n" in text else "\n"


def generate_uuidv7() -> str:
    """Generate UUIDv7 using local bit composition (no external dependency)."""
    unix_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)

    value = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    hex32 = f"{value:032x}"
    return f"{hex32[0:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"


def normalize_payload_text(payload_text: str) -> str:
    """Accept raw YAML pairs or a wrapped front matter block and return payload body text."""
    payload = _strip_bom(payload_text)
    lines = payload.splitlines(keepends=True)
    if not lines:
        return payload

    if lines[0].rstrip("\r\n") != "---":
        return payload

    for index in range(1, len(lines)):
        marker = lines[index].rstrip("\r\n")
        if marker in _CLOSE_MARKERS:
            return "".join(lines[1:index])

    raise ValueError("Payload starts with '---' but has no closing marker ('---' or '...').")


def transform_markdown(
    text: str,
    payload_text: str,
    *,
    preserve_uuid: bool = True,
) -> Tuple[str, Dict[str, object]]:
    """Replace markdown front matter with payload content.

    Rules:
    - Front matter is only recognized at file start.
    - Existing top-level ``uuid`` is preserved when requested.
    - ``uuid: {uuidv7}`` token in payload generates a UUIDv7 when no existing uuid is preserved.
    """
    clean_text = _strip_bom(text)
    newline = detect_newline(clean_text)

    had_frontmatter, existing_frontmatter, body, parse_error = _parse_frontmatter(clean_text)
    info: Dict[str, object] = {
        "had_frontmatter": had_frontmatter,
        "preserved_uuid": False,
        "generated_uuid": False,
        "error": False,
        "reason": "",
    }

    if parse_error:
        info["error"] = True
        info["reason"] = parse_error
        return clean_text, info

    payload = normalize_payload_text(payload_text)
    payload = _coerce_newlines(payload, newline)

    existing_uuid = _extract_uuid_value(existing_frontmatter) if had_frontmatter else None

    if preserve_uuid and existing_uuid is not None:
        payload, replaced = _replace_first_uuid_value(payload, existing_uuid)
        if not replaced:
            payload = _prepend_uuid_line(payload, existing_uuid, newline)
        info["preserved_uuid"] = True
    else:
        match = _UUID_LINE_RE.search(payload)
        if match and _is_uuidv7_token(match.group("value")):
            payload, _ = _replace_first_uuid_value(payload, generate_uuidv7())
            info["generated_uuid"] = True

    payload_block = payload
    if payload_block and not payload_block.endswith(("\n", "\r")):
        payload_block = f"{payload_block}{newline}"

    new_text = f"---{newline}{payload_block}---{newline}{body}"
    return new_text, info


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith("\ufeff") else text


def _coerce_newlines(text: str, newline: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)


def _parse_frontmatter(text: str) -> Tuple[bool, str, str, str]:
    lines = text.splitlines(keepends=True)
    if not lines:
        return False, "", text, ""

    if lines[0].rstrip("\r\n") != "---":
        return False, "", text, ""

    for index in range(1, len(lines)):
        marker = lines[index].rstrip("\r\n")
        if marker in _CLOSE_MARKERS:
            frontmatter = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            return True, frontmatter, body, ""

    return True, "", text, "Front matter starts with '---' but has no closing marker."


def _extract_uuid_value(frontmatter_text: str) -> Optional[str]:
    match = _UUID_LINE_RE.search(frontmatter_text)
    if not match:
        return None
    return match.group("value").strip()


def _replace_first_uuid_value(text: str, value: str) -> Tuple[str, bool]:
    match = _UUID_LINE_RE.search(text)
    if not match:
        return text, False

    replacement = (
        f"uuid{match.group('key_ws')}:{match.group('post_colon_ws')}"
        f"{value}{match.group('line_end')}"
    )
    replaced = f"{text[:match.start()]}{replacement}{text[match.end():]}"
    return replaced, True


def _prepend_uuid_line(payload: str, uuid_value: str, newline: str) -> str:
    prefix = f"uuid: {uuid_value}{newline}"
    return f"{prefix}{payload}" if payload else prefix


def _is_uuidv7_token(value_text: str) -> bool:
    candidate = value_text.strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {'"', "'"}:
        candidate = candidate[1:-1].strip()
    return candidate == "{uuidv7}"

from __future__ import annotations

import json
import logging
from io import BytesIO
from typing import Any

import qrcode



_VOUCHER_STATE_KEY_PREFIX = "voucher_dm_"


def _state_key(user_id: int) -> str:
    return f"{_VOUCHER_STATE_KEY_PREFIX}{int(user_id)}"


def _encode_state(*, code: str, message_id: int, use_count: int) -> str:
    return json.dumps(
        {
            "code": str(code),
            "message_id": int(message_id),
            "use_count": int(use_count),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _decode_state(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
        if not isinstance(v, dict):
            return None
        return v
    except Exception:
        return None


def _make_qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

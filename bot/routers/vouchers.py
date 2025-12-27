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
    # Store state as a list of codes to support multiple vouchers per user.
    return json.dumps(
        {
            "codes": [
                {
                    "code": str(code),
                    "message_id": int(message_id),
                    "use_count": int(use_count),
                }
            ]
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

        # Backwards compatibility: previously state was a flat object with
        # keys `code`, `message_id`, `use_count`. Convert that into the
        # new shape with a `codes` list.
        if "codes" in v and isinstance(v["codes"], list):
            return v
        if "code" in v:
            return {
                "codes": [
                    {
                        "code": str(v.get("code") or ""),
                        "message_id": int(v.get("message_id") or 0),
                        "use_count": int(v.get("use_count") or 0),
                    }
                ]
            }

        # Unknown shape
        return None
    except Exception:
        return None


def _make_qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

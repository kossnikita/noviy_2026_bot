from __future__ import annotations

import json
from io import BytesIO
from typing import Any

import qrcode


_VOUCHER_STATE_KEY_PREFIX = "voucher_dm_"


def _state_key(user_id: int) -> str:
    return f"{_VOUCHER_STATE_KEY_PREFIX}{int(user_id)}"


def _encode_state(*, code: str, message_id: int) -> str:
    return json.dumps(
        {
            "codes": [
                {
                    "code": str(code),
                    "message_id": int(message_id),
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

        # Current format: "codes" list
        if "codes" in v and isinstance(v["codes"], list):
            # Normalize: ensure each code entry has at least code and message_id
            normalized_codes = []
            for entry in v["codes"]:
                try:
                    code_str = str((entry or {}).get("code") or "").strip()
                    msg_id = int((entry or {}).get("message_id") or 0)
                    if code_str and msg_id > 0:
                        normalized_codes.append(
                            {
                                "code": code_str,
                                "message_id": msg_id,
                            }
                        )
                except (ValueError, TypeError):
                    # Skip malformed entries
                    continue
            if normalized_codes:
                return {"codes": normalized_codes}
            return None

        # Old flat format: code, message_id, use_count
        if "code" in v:
            try:
                code_str = str(v.get("code") or "").strip()
                msg_id = int(v.get("message_id") or 0)
                if code_str and msg_id > 0:
                    return {
                        "codes": [
                            {
                                "code": code_str,
                                "message_id": msg_id,
                            }
                        ]
                    }
            except (ValueError, TypeError):
                pass

        # Unknown shape
        return None
    except Exception:
        return None


def _make_qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()

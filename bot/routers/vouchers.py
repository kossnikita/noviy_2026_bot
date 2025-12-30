from __future__ import annotations

from io import BytesIO

import qrcode


def _make_qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()

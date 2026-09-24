"""
QR code generation for enrollment cards (no heavy numpy dependency on import).
"""

from __future__ import annotations

import base64
from io import BytesIO


def _qr_via_segno(text: str) -> bytes:
    import segno

    q = segno.make(text, error="m")
    buf = BytesIO()
    q.save(buf, kind="png", scale=5, border=1, dark="#0A1628", light="#FFFFFF")
    return buf.getvalue()


def _qr_via_qrcode(text: str) -> bytes:
    import qrcode

    qr = qrcode.QRCode(version=None, box_size=6, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0A1628", back_color="#FFFFFF")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_qr_png_base64(text: str) -> str:
    """Return a data URI (image/png) for embedding in HTML/PDF templates."""
    png_bytes: bytes | None = None
    for generator in (_qr_via_segno, _qr_via_qrcode):
        try:
            png_bytes = generator(text)
            break
        except Exception:
            continue

    if not png_bytes:
        raise RuntimeError("QR generation failed: install segno or qrcode[pil]")

    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_verify_url(origin: str, card_number: str) -> str:
    origin = origin.rstrip("/")
    return f"{origin}/verify/{card_number}"

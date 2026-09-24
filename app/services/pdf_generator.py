"""
HTML-to-PDF enrollment card generation via Playwright at exact CR80 portrait dimensions.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.card_icons import (
    ICON_BATCH,
    ICON_BOOK,
    ICON_CAL,
    ICON_GENDER,
    ICON_HOME,
    ICON_ID,
    ICON_MAIL,
    ICON_PHONE,
    ICON_PIN,
    ICON_SHIELD,
    ICON_USER,
    ICON_USERS,
    brand_word_html,
)
from app.services.enrollment_card_service import EnrollmentCardData
from app.services.qr_service import generate_qr_png_base64

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
THEME_FILE = Path(__file__).resolve().parent.parent / "data" / "card_theme.json"
LOGO_ASSET = Path(__file__).resolve().parent.parent / "assets" / "bvonix-academy-logo.png"


def _load_theme() -> dict[str, Any]:
    if THEME_FILE.is_file():
        return json.loads(THEME_FILE.read_text(encoding="utf-8"))
    return {
        "dimensions": {"width_mm": 53.98, "height_mm": 85.6, "dpi": 300},
        "rules": [],
    }


def _image_to_data_uri(path: Path | None) -> str | None:
    if not path or not path.is_file():
        return None
    import base64
    import mimetypes

    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _split_academy_name(name: str) -> tuple[str, str]:
    parts = name.strip().split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return name, "Academy"


def build_template_context(data: EnrollmentCardData) -> dict[str, Any]:
    theme = _load_theme()
    dims = theme.get("dimensions", {})
    width_mm = float(dims.get("width_mm", 53.98))
    height_mm = float(dims.get("height_mm", 85.6))
    brand_word, brand_suffix = _split_academy_name(data.academy_name)

    front_fields = [
        {"label": "Student Name", "value": data.student_name, "class": "", "icon_svg": ICON_USER},
        {"label": "Student ID", "value": data.student_id, "class": "purple", "icon_svg": ICON_ID},
        {"label": "Course", "value": data.course_name, "class": "", "icon_svg": ICON_BOOK},
        {"label": "Batch", "value": data.batch, "class": "", "icon_svg": ICON_BATCH},
        {"label": "Enrollment Date", "value": data.enrollment_date, "class": "", "icon_svg": ICON_CAL},
        {"label": "Valid Until", "value": data.validity, "class": "", "icon_svg": ICON_SHIELD},
    ]
    back_fields = [
        {"label": "Father / Guardian Name", "value": data.father_guardian_name, "icon_svg": ICON_USERS},
        {"label": "Date of Birth", "value": data.date_of_birth, "icon_svg": ICON_CAL},
        {"label": "Gender", "value": data.gender, "icon_svg": ICON_GENDER},
        {"label": "Phone", "value": data.phone, "icon_svg": ICON_PHONE},
        {"label": "Email", "value": data.email, "icon_svg": ICON_MAIL},
        {"label": "Campus", "value": data.campus, "icon_svg": ICON_PIN},
        {"label": "Address", "value": data.address, "icon_svg": ICON_HOME},
    ]

    academy = theme.get("academy") or {}
    signature_name = academy.get("authorized_signature_name") or "Gul Hassan"
    logo_data_uri = _image_to_data_uri(LOGO_ASSET)

    return {
        "academy_name": data.academy_name,
        "brand_word": brand_word,
        "brand_word_html": brand_word_html(brand_word),
        "brand_suffix": brand_suffix,
        "signature_name": signature_name,
        "logo_data_uri": logo_data_uri,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "front_fields": front_fields,
        "back_fields": back_fields,
        "rules": theme.get("rules") or [],
        "website": data.website,
        "support_email": data.support_email,
        "support_phone": data.support_phone,
        "qr_data_uri": generate_qr_png_base64(data.qr_text),
        "profile_image_data_uri": _image_to_data_uri(data.profile_image_path),
    }


def render_card_html(data: EnrollmentCardData) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("cards/card_print.html")
    return template.render(**build_template_context(data))


def _pdf_via_playwright_sync(html: str, width_mm: float, height_mm: float) -> bytes:
    from playwright.sync_api import sync_playwright

    # High-DPI viewport for crisp print (300 DPI approx.)
    dpi = 300
    width_px = int(width_mm / 25.4 * dpi)
    height_px = int(height_mm / 25.4 * dpi)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": width_px, "height": height_px * 2 + 100},
                device_scale_factor=1,
            )
            page.set_content(html, wait_until="networkidle")
            # Wait for Google Fonts
            page.wait_for_timeout(800)
            page.evaluate("document.fonts.ready")

            pdf_bytes = page.pdf(
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            return pdf_bytes
        finally:
            browser.close()


async def _pdf_via_playwright_async(html: str, width_mm: float, height_mm: float) -> bytes:
    from playwright.async_api import async_playwright

    dpi = 300
    width_px = int(width_mm / 25.4 * dpi)
    height_px = int(height_mm / 25.4 * dpi)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(
                viewport={"width": width_px, "height": height_px * 2 + 100},
            )
            await page.set_content(html, wait_until="networkidle")
            await page.wait_for_timeout(800)
            await page.evaluate("document.fonts.ready")
            return await page.pdf(
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            await browser.close()


def _pdf_via_xhtml2pdf(html: str) -> bytes:
    from io import BytesIO

    from xhtml2pdf import pisa

    buf = BytesIO()
    result = pisa.CreatePDF(html.encode("utf-8"), dest=buf, encoding="utf-8")
    if result.err:
        raise RuntimeError("xhtml2pdf reported errors")
    return buf.getvalue()


def generate_card_pdf_bytes(data: EnrollmentCardData) -> bytes:
    """
    Generate print-ready PDF: 2 pages at exact portrait card size (front + back).
    """
    theme = _load_theme()
    dims = theme.get("dimensions", {})
    width_mm = float(dims.get("width_mm", 53.98))
    height_mm = float(dims.get("height_mm", 85.6))
    html = render_card_html(data)

    try:
        return _pdf_via_playwright_sync(html, width_mm, height_mm)
    except Exception as exc:
        logger.warning("Playwright PDF failed (%s), trying xhtml2pdf", exc)

    try:
        return _pdf_via_xhtml2pdf(html)
    except Exception as exc:
        logger.warning("xhtml2pdf failed (%s), trying ReportLab", exc)

    from app.services import enrollment_card_service as ecs

    try:
        return ecs._pdf_via_reportlab(data)
    except Exception as exc:
        logger.warning("ReportLab failed (%s), using fpdf2", exc)
        fallback = ecs._pdf_via_fpdf2(data)
        if fallback:
            return fallback
        raise RuntimeError("All PDF generation methods failed") from exc


async def generate_card_pdf_bytes_async(data: EnrollmentCardData) -> bytes:
    theme = _load_theme()
    dims = theme.get("dimensions", {})
    width_mm = float(dims.get("width_mm", 53.98))
    height_mm = float(dims.get("height_mm", 85.6))
    html = render_card_html(data)
    try:
        return await _pdf_via_playwright_async(html, width_mm, height_mm)
    except Exception as exc:
        logger.warning("Playwright async PDF failed (%s), using sync/fallback", exc)
        return await asyncio.to_thread(generate_card_pdf_bytes, data)

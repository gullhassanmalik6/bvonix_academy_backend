"""
Enrollment card generation: professional CR80-style front & back PDF.

Uses ReportLab + Pillow (profile photo, QR). Falls back to fpdf2 if ReportLab fails.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

from app.core.config import get_settings
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.user import User

logger = logging.getLogger(__name__)

SITE_SETTINGS_FILE = Path("data") / "site_settings.json"
CARD_SCALE = 2.15  # Scale CR80 for readable on-screen PDF
NAVY = (0.04, 0.09, 0.16)  # #0A1628
PURPLE = (0.49, 0.23, 0.93)  # #7C3AED
PURPLE_DARK = (0.35, 0.15, 0.75)
WHITE = (1, 1, 1)
TEXT_DARK = (0.12, 0.12, 0.15)
TEXT_MUTED = (0.45, 0.45, 0.5)


@dataclass
class EnrollmentCardData:
    academy_name: str
    student_name: str
    student_id: str
    father_guardian_name: str
    date_of_birth: str
    gender: str
    cnic: str
    course_name: str
    batch: str
    enrollment_date: str
    course_duration: str
    mode: str
    campus: str
    phone: str
    email: str
    address: str
    issue_date: str
    validity: str
    profile_image_path: Path | None
    logo_path: Path | None
    qr_text: str
    website: str
    support_email: str
    support_phone: str


def _sanitize(s: str | None, max_len: int = 200) -> str:
    if not s:
        return "—"
    text = str(s).strip().replace("\x00", "").replace("\r", " ")
    if not text:
        return "—"
    return text[:max_len]


def _format_dob(value: str | None) -> str:
    if not value or value.strip() in {"", "—"}:
        return "—"
    raw = value.strip()
    try:
        if len(raw) == 10 and raw[4] == "-":
            dt = datetime.strptime(raw, "%Y-%m-%d")
            return dt.strftime("%d %B %Y")
    except Exception:
        pass
    return _sanitize(raw, 40)


def _format_date(dt: datetime | None) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%d %B %Y")
    except Exception:
        return "—"


def _duration_label(hours: int | None) -> str:
    if not hours or hours <= 0:
        return "—"
    months = max(1, round(hours / 40))
    return f"{months} Months ({hours} hrs)"


def _local_path_from_url(url: str | None) -> Path | None:
    if not url:
        return None
    rel = url.lstrip("/")
    path = Path(rel)
    if path.is_file():
        return path
    alt = Path(".") / rel
    if alt.is_file():
        return alt
    return None


def _load_site_branding() -> dict:
    defaults = {
        "footer_address": "Sonara Bazar, Near Gurdwara Sahib, Daharki",
        "footer_brand_name": "Bvonix Academy",
        "site_logo_url": "/logo.png",
        "footer_contacts": [],
    }
    if not SITE_SETTINGS_FILE.is_file():
        return defaults
    try:
        data = json.loads(SITE_SETTINGS_FILE.read_text(encoding="utf-8"))
        return {**defaults, **{k: data.get(k, v) for k, v in defaults.items()}}
    except Exception:
        return defaults


def _phone_from_site(site: dict) -> str:
    contacts = site.get("footer_contacts") or []
    for c in contacts:
        if c.get("type") in ("phone", "whatsapp") and c.get("value"):
            return str(c["value"])
    return site.get("footer_contact_value") or "—"


def _resolve_logo_path(site: dict, settings) -> Path | None:
    for candidate in (
        site.get("site_logo_url"),
        getattr(settings, "academy_logo_url", None),
        "/logo.png",
        "frontend/public/logo.png",
    ):
        if not candidate:
            continue
        if str(candidate).startswith("http"):
            continue
        path = _local_path_from_url(str(candidate))
        if path:
            return path
    return None


def _make_qr_reader(text: str):
    try:
        import qrcode
        from reportlab.lib.utils import ImageReader

        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#1a2b4e", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return ImageReader(buf)
    except Exception as exc:
        logger.warning("QR generation failed: %s", exc)
        return None


def card_data_from_input(payload) -> EnrollmentCardData:
    """Build EnrollmentCardData from API StudentCardDataInput."""
    settings = get_settings()
    site = _load_site_branding()
    origin = settings.allowed_origins_list()[0] if settings.allowed_origins_list() else "http://localhost:5173"
    card_id = payload.student_id
    qr_text = payload.verify_url or f"{origin}/verify/{card_id}"
    profile_path = _local_path_from_url(payload.profile_image_url)

    return EnrollmentCardData(
        academy_name=_sanitize(payload.academy_name or getattr(settings, "academy_name", None) or site.get("footer_brand_name") or "Bvonix Academy", 80),
        student_name=_sanitize(payload.student_name, 80),
        student_id=_sanitize(card_id, 40),
        father_guardian_name=_sanitize(payload.father_name, 80),
        date_of_birth=_sanitize(payload.date_of_birth, 40),
        gender=_sanitize(payload.gender, 20),
        cnic="—",
        course_name=_sanitize(payload.course, 100),
        batch=_sanitize(payload.batch or "—", 60),
        enrollment_date=_sanitize(payload.enrollment_date, 40),
        course_duration="—",
        mode="—",
        campus=_sanitize(payload.campus or "Main Campus", 80),
        phone=_sanitize(payload.phone, 30),
        email=_sanitize(payload.email, 60),
        address=_sanitize(payload.address, 120),
        issue_date="—",
        validity=_sanitize(payload.valid_until or "Until Course Completion", 60),
        profile_image_path=profile_path,
        logo_path=_resolve_logo_path(site, settings),
        qr_text=qr_text,
        website=_sanitize(payload.website or "www.bvonixacademy.com", 60),
        support_email=_sanitize(payload.support_email or "info@bvonixacademy.com", 60),
        support_phone=_sanitize(payload.support_phone or _phone_from_site(site), 30),
    )


def build_card_data(enrollment: Enrollment, student: User, course: Course) -> EnrollmentCardData:
    settings = get_settings()
    site = _load_site_branding()

    ref_date = enrollment.enrollment_date or datetime.now()
    issue_dt = enrollment.verified_at or enrollment.enrollment_date or datetime.now()
    class_type = (enrollment.class_type or "online").replace("_", " ").title()
    batch = f"Batch – {ref_date.strftime('%B %Y')}"

    origin = settings.allowed_origins_list()[0] if settings.allowed_origins_list() else "http://localhost:5173"
    card_number = enrollment.enrollment_card_number or enrollment.id
    qr_text = f"{origin}/verify/{card_number}"

    campus = _sanitize(site.get("footer_address"), 80)
    if campus == "—":
        campus = "Main Campus"

    return EnrollmentCardData(
        academy_name=_sanitize(getattr(settings, "academy_name", None) or site.get("footer_brand_name") or "Bvonix Academy", 80),
        student_name=_sanitize(student.full_name or student.email, 80),
        student_id=_sanitize(card_number, 40),
        father_guardian_name=_sanitize(enrollment.father_guardian_name or "—", 80),
        date_of_birth=_format_dob(enrollment.date_of_birth),
        gender=_sanitize(enrollment.gender or "—", 20),
        cnic="—",
        course_name=_sanitize(course.title, 100),
        batch=_sanitize(batch, 60),
        enrollment_date=_format_date(enrollment.enrollment_date),
        course_duration=_duration_label(getattr(course, "duration_hours", None)),
        mode=class_type,
        campus=campus,
        phone=_sanitize(enrollment.phone_number or "—", 30),
        email=_sanitize(student.email, 60),
        address=_sanitize(enrollment.address or campus, 120),
        issue_date=_format_date(issue_dt),
        validity="Until Course Completion",
        profile_image_path=_local_path_from_url(enrollment.profile_image_url),
        logo_path=_resolve_logo_path(site, settings),
        qr_text=qr_text,
        website="www.bvonixacademy.com",
        support_email="info@bvonixacademy.com",
        support_phone=_phone_from_site(site),
    )


def _card_dimensions():
    from reportlab.lib.units import mm

    w = 85.6 * mm * CARD_SCALE
    h = 53.98 * mm * CARD_SCALE
    return w, h


def _draw_rounded_rect(c, x, y, w, h, r, fill=None, stroke=None, stroke_width=1):
    if fill:
        c.setFillColorRGB(*fill)
    if stroke:
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(stroke_width)
    else:
        c.setLineWidth(0)
    c.roundRect(x, y, w, h, r, stroke=bool(stroke), fill=bool(fill))


def _draw_photo(c, x, y, w, h, image_path: Path | None):
    _draw_rounded_rect(c, x, y, w, h, 6, fill=(0.95, 0.95, 0.97), stroke=(0.85, 0.85, 0.88), stroke_width=0.8)
    if image_path and image_path.is_file():
        try:
            from reportlab.lib.utils import ImageReader

            c.drawImage(
                ImageReader(str(image_path)),
                x + 2,
                y + 2,
                width=w - 4,
                height=h - 4,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
            return
        except Exception as exc:
            logger.warning("Profile image draw failed: %s", exc)
    c.setFillColorRGB(*TEXT_MUTED)
    c.setFont("Helvetica", 8)
    c.drawCentredString(x + w / 2, y + h / 2 - 4, "Photo")


def _draw_label_value(c, x, y, label: str, value: str, label_size=7, value_size=8.5, max_width=200):
    from reportlab.lib.units import mm

    c.setFillColorRGB(*TEXT_MUTED)
    c.setFont("Helvetica", label_size)
    c.drawString(x, y, label.upper())
    c.setFillColorRGB(*TEXT_DARK)
    c.setFont("Helvetica-Bold", value_size)
    val = value if len(value) <= 48 else value[:45] + "..."
    c.drawString(x, y - (4.2 * mm * CARD_SCALE / 2.15), val)


def _draw_front_card(c, data: EnrollmentCardData, ox: float, oy: float):
    from reportlab.lib.units import mm

    w, h = _card_dimensions()
    r = 8

    _draw_rounded_rect(c, ox, oy, w, h, r, fill=WHITE, stroke=(0.88, 0.88, 0.9), stroke_width=1.2)

    header_h = 14 * mm * CARD_SCALE / 2.15
    c.setFillColorRGB(*NAVY)
    c.roundRect(ox, oy + h - header_h, w, header_h, r, stroke=0, fill=1)
    c.rect(ox, oy + h - header_h, w, header_h - r, stroke=0, fill=1)

    logo_x = ox + 8
    logo_y = oy + h - header_h + 3
    if data.logo_path and data.logo_path.is_file():
        try:
            from reportlab.lib.utils import ImageReader

            c.drawImage(ImageReader(str(data.logo_path)), logo_x, logo_y, width=28, height=12, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    c.setFillColorRGB(*WHITE)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(ox + 40, oy + h - header_h + 8, data.academy_name.upper())

    bar_y = oy + h - header_h - 9
    c.setFillColorRGB(*PURPLE)
    c.rect(ox + 10, bar_y, w - 20, 7, stroke=0, fill=1)
    c.setFillColorRGB(*WHITE)
    c.setFont("Helvetica-Bold", 6.5)
    c.drawCentredString(ox + w / 2, bar_y + 2, "STUDENT ENROLLMENT CARD")

    photo_w = 26 * mm * CARD_SCALE / 2.15
    photo_h = 32 * mm * CARD_SCALE / 2.15
    photo_x = ox + 10
    photo_y = oy + h - header_h - 18 - photo_h
    _draw_photo(c, photo_x, photo_y, photo_w, photo_h, data.profile_image_path)

    sig_y = oy + 12
    c.setFillColorRGB(*PURPLE_DARK)
    c.roundRect(photo_x, sig_y, photo_w, 16, 4, stroke=0, fill=1)
    c.setFillColorRGB(*WHITE)
    c.setFont("Helvetica-Oblique", 6)
    c.drawCentredString(photo_x + photo_w / 2, sig_y + 9, "Authorized Signature")
    c.setLineWidth(0.5)
    c.line(photo_x + 4, sig_y + 6, photo_x + photo_w - 4, sig_y + 6)
    c.setFont("Helvetica", 5)
    c.drawCentredString(photo_x + photo_w / 2, sig_y + 2, "Director / Admin")

    rx = ox + photo_w + 18
    ry = oy + h - header_h - 20
    line_gap = 11.5 * mm * CARD_SCALE / 2.15

    fields = [
        ("Student Name", data.student_name),
        ("Student ID", data.student_id),
        ("Course", data.course_name),
        ("Batch", data.batch),
        ("Enrollment Date", data.enrollment_date),
        ("Valid Until", data.validity),
    ]
    for i, (label, value) in enumerate(fields):
        y = ry - i * line_gap
        c.setFillColorRGB(*PURPLE)
        c.circle(rx - 6, y + 1, 2.2, stroke=0, fill=1)
        c.setFillColorRGB(*TEXT_MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(rx, y, label.upper())
        c.setFillColorRGB(*(PURPLE if label == "Student ID" else TEXT_DARK))
        c.setFont("Helvetica-Bold", 8.5)
        val = value if len(value) <= 48 else value[:45] + "..."
        c.drawString(rx, y - (4.2 * mm * CARD_SCALE / 2.15), val)

    qr_size = 22 * mm * CARD_SCALE / 2.15
    qr_reader = _make_qr_reader(data.qr_text)
    if qr_reader:
        c.drawImage(qr_reader, ox + w - qr_size - 8, oy + 22, width=qr_size, height=qr_size, mask="auto")
        c.setFillColorRGB(*PURPLE)
        c.setFont("Helvetica-Bold", 5)
        c.drawCentredString(ox + w - qr_size / 2 - 8, oy + 18, "SCAN TO VERIFY")

    footer_h = 10
    c.setFillColorRGB(*NAVY)
    c.roundRect(ox, oy, w, footer_h, r, stroke=0, fill=1)
    c.rect(ox, oy + footer_h - r, w, r, stroke=0, fill=1)
    c.setFillColorRGB(*WHITE)
    c.setFont("Helvetica", 5.5)
    c.drawString(ox + 10, oy + 3.5, data.website)
    c.drawRightString(ox + w - 10, oy + 3.5, data.support_email)


def _draw_back_card(c, data: EnrollmentCardData, ox: float, oy: float):
    from reportlab.lib.units import mm

    w, h = _card_dimensions()
    r = 8

    _draw_rounded_rect(c, ox, oy, w, h, r, fill=WHITE, stroke=(0.88, 0.88, 0.9), stroke_width=1.2)

    header_h = 16 * mm * CARD_SCALE / 2.15
    c.setFillColorRGB(*NAVY)
    c.roundRect(ox, oy + h - header_h, w, header_h, r, stroke=0, fill=1)
    c.rect(ox, oy + h - header_h, w, header_h - r, stroke=0, fill=1)

    if data.logo_path and data.logo_path.is_file():
        try:
            from reportlab.lib.utils import ImageReader

            c.drawImage(ImageReader(str(data.logo_path)), ox + 10, oy + h - header_h + 4, width=30, height=13, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    c.setFillColorRGB(*WHITE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(ox + 45, oy + h - header_h + 7, data.academy_name.upper())

    mid_y = oy + h - header_h - 12
    col_w = (w - 24) / 2
    lx = ox + 10
    rx = ox + 12 + col_w

    left_fields = [
        ("Father / Guardian", data.father_guardian_name),
        ("Date of Birth", data.date_of_birth),
        ("Gender", data.gender),
        ("Phone", data.phone),
        ("Email", data.email),
        ("Campus", data.campus),
        ("Address", data.address),
        ("Course Duration", data.course_duration),
        ("Mode", data.mode),
        ("Issue Date", data.issue_date),
    ]
    line_gap = 9.8 * mm * CARD_SCALE / 2.15
    for i, (label, value) in enumerate(left_fields):
        y = mid_y - i * line_gap
        if y < oy + 22:
            break
        c.setFillColorRGB(*PURPLE)
        c.circle(lx - 4, y + 1, 1.8, stroke=0, fill=1)
        _draw_label_value(c, lx, y, label, value, label_size=5.5, value_size=7)

    c.setFillColorRGB(*PURPLE)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(rx, mid_y, "ACADEMY RULES")
    c.setLineWidth(0.8)
    c.setStrokeColorRGB(*PURPLE)
    c.line(rx, mid_y - 2, rx + 50, mid_y - 2)

    rules = [
        "This card must be carried during classes.",
        "Card is non-transferable.",
        "Lost cards must be reported immediately.",
        "Fees must be paid on time.",
        "Misconduct may result in suspension.",
    ]
    c.setFillColorRGB(*TEXT_DARK)
    c.setFont("Helvetica", 6.2)
    rule_y = mid_y - 10
    for rule in rules:
        c.drawString(rx + 2, rule_y, f"• {rule}")
        rule_y -= 8

    footer_h = 12
    c.setFillColorRGB(*NAVY)
    c.roundRect(ox, oy, w, footer_h, r, stroke=0, fill=1)
    c.rect(ox, oy + footer_h - r, w, r, stroke=0, fill=1)
    c.setFillColorRGB(*WHITE)
    c.setFont("Helvetica", 5.5)
    c.drawString(ox + 10, oy + 4, f"Need Help? {data.support_phone}")
    c.drawRightString(ox + w - 10, oy + 4, f"{data.website}  •  {data.support_email}")


def _pdf_via_reportlab(data: EnrollmentCardData) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4
    card_w, card_h = _card_dimensions()

    # Page 1 – Front
    c.setFillColorRGB(*TEXT_MUTED)
    c.setFont("Helvetica", 9)
    c.drawCentredString(page_w / 2, page_h - 36, f"{data.academy_name} — Enrollment Card (Front)")
    fx = (page_w - card_w) / 2
    fy = (page_h - card_h) / 2 - 10
    _draw_front_card(c, data, fx, fy)
    c.showPage()

    # Page 2 – Back
    c.setFont("Helvetica", 9)
    c.drawCentredString(page_w / 2, page_h - 36, f"{data.academy_name} — Enrollment Card (Back)")
    _draw_back_card(c, data, fx, fy)
    c.showPage()

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def _pdf_via_fpdf2(data: EnrollmentCardData) -> bytes | None:
    """Text-only fallback if ReportLab unavailable."""
    try:
        from fpdf import FPDF
    except ImportError:
        return None

    pdf = FPDF()
    pdf.set_auto_page_break(False)

    def page_fields(title: str, rows: list[tuple[str, str]]):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(30, 64, 175)
        pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(4)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 10)
        for label, value in rows:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(45, 7, f"{label}:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 7, _sanitize(value))
            pdf.ln(1)

    front_rows = [
        ("Academy", data.academy_name),
        ("Student Name", data.student_name),
        ("Student ID", data.student_id),
        ("Course", data.course_name),
        ("Batch", data.batch),
        ("Enrollment Date", data.enrollment_date),
        ("Class Mode", data.mode),
        ("Duration", data.course_duration),
        ("Phone", data.phone),
        ("Email", data.email),
        ("Issue Date", data.issue_date),
        ("Validity", data.validity),
    ]
    back_rows = [
        ("Father / Guardian", data.father_guardian_name),
        ("Address", data.address),
        ("Campus", data.campus),
        ("Support Phone", data.support_phone),
        ("Website", data.website),
        ("Email", data.support_email),
    ]
    page_fields("STUDENT ENROLLMENT CARD — FRONT", front_rows)
    page_fields("STUDENT ENROLLMENT CARD — BACK", back_rows)

    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else out


class EnrollmentCardService:
    """Generate enrollment cards: student data → professional front/back PDF."""

    def __init__(self, upload_dir: str = "uploads/enrollment_cards") -> None:
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def generate_enrollment_card(
        self,
        enrollment: Enrollment,
        student: User,
        course: Course,
    ) -> tuple[str, bytes]:
        """
        Generate enrollment card PDF with all enrollment + student + course details.
        Returns (relative_url_path, pdf_bytes).
        """
        data = build_card_data(enrollment, student, course)

        pdf_bytes: bytes | None = None
        try:
            from app.services.pdf_generator import generate_card_pdf_bytes

            pdf_bytes = generate_card_pdf_bytes(data)
        except Exception as exc:
            logger.error("Card PDF generation failed: %s", exc, exc_info=True)

        if not pdf_bytes:
            try:
                pdf_bytes = _pdf_via_reportlab(data)
            except Exception as exc:
                logger.error("ReportLab fallback failed: %s", exc, exc_info=True)

        if not pdf_bytes:
            pdf_bytes = _pdf_via_fpdf2(data)

        if not pdf_bytes:
            raise RuntimeError("Failed to generate enrollment card PDF")

        filename = f"enrollment_card_{enrollment.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        file_path = self.upload_dir / filename
        file_path.write_bytes(pdf_bytes)
        relative_path = f"/uploads/enrollment_cards/{filename}"
        return relative_path, pdf_bytes

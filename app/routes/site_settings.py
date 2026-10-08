"""
Site settings routes - public read, admin write.
Used for hero section and other site-wide config (no auth required for GET).
"""

from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.admin import get_admin_user
from app.models.user import User
from app.utils.exceptions import AppError

router = APIRouter()

SITE_SETTINGS_FILE = Path("data") / "site_settings.json"
HERO_ICONS_DIR = Path("uploads") / "hero_icons"
COMMUNITY_IMAGES_DIR = Path("uploads") / "community_images"
BENEFIT_ICONS_DIR = Path("uploads") / "benefit_icons"
SUBJECT_ICONS_DIR = Path("uploads") / "subject_icons"
TESTIMONIAL_AVATARS_DIR = Path("uploads") / "testimonial_avatars"
LOGOS_DIR = Path("uploads") / "logos"

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB

# Default hero section values
HERO_DEFAULTS = {
    "hero_headline": "Find Your\nPerfect Tutor\nToday",
    "hero_description": "We help you find the perfect tutor for 1-on-1 lessons. It is completely free and private.",
    "hero_cta_text": "Get The App",
    "hero_cta_link": "/courses",
    "hero_cta_subtext": "It is completely free and private",
    "hero_social_text": "More than 23,000+ mentors",
    "hero_icon_url": None,
    "hero_image_alt": "Students learning at Bvonix Academy",
}

# Default community section values
COMMUNITY_DEFAULTS = {
    "community_header": "COMMUNITY HUB DISCUSSION FORUM",
    "community_title": "Discussion Forum for Sharing, Learning, and Helping",
    "community_description": "Dive into our dynamic Community Hub – a central space for rich discussions, shared experiences, and mutual support. Connect with a diverse community of learners, where knowledge knows no bounds. Join us in the journey of collaborative learning and growth! 🌐🚀",
    "community_stat1_value": "12 k",
    "community_stat1_label": "Success Journey",
    "community_stat2_value": "98 +",
    "community_stat2_label": "Best Mentor",
    "community_stat3_value": "21 +",
    "community_stat3_label": "Years Experience",
    "community_image_url": None,
    "community_image_alt": "Community member with laptop",
}

# Default milestones section (wavy line stats)
MILESTONES_DEFAULTS = {
    "milestones_items": [
        {"value": "1k+", "label": "Students"},
        {"value": "50+", "label": "Courses"},
        {"value": "70+", "label": "Mentors"},
        {"value": "100+", "label": "Graduates"},
        {"value": "5k+", "label": "Reviews"},
    ]
}

# Default benefits section (Why Choose Us)
BENEFITS_DEFAULTS = {
    "benefits_header": "WHY CHOOSE US",
    "benefits_title": "Benefits of online tutoring services with us",
    "benefits_items": [
        {
            "title": "One-on-one Teaching",
            "description": "All of our special education experts have a degree in special education",
            "icon_url": None,
            "background_color": "#3B82F6",
        },
        {
            "title": "Expert Mentors",
            "description": "Learn from experienced professionals with years of real-world expertise",
            "icon_url": None,
            "background_color": "#E53935",
        },
        {
            "title": "Flexible Learning",
            "description": "Study at your own pace with flexible schedules and on-demand courses",
            "icon_url": None,
            "background_color": "#EC4899",
        },
        {
            "title": "Certified Programs",
            "description": "Earn certificates upon course completion to showcase your skills",
            "icon_url": None,
            "background_color": "#F97316",
        },
    ],
}

# Default subjects section (9-card grid: Computer Science, Bio Science, etc.)
SUBJECTS_DEFAULTS = {
    "subjects_header": "WHY CHOOSE US",
    "subjects_title": "Benefits of online tutoring services with us",
    "subjects_items": [
        {"title": "Computer Science", "subtitle": "Dive into our dynamic Community Hub", "icon_url": None, "background_color": "#FF3B30"},
        {"title": "Bio Science", "subtitle": "Dive into our dynamic Community Hub", "icon_url": None, "background_color": "#007AFF"},
        {"title": "Physics and Math", "subtitle": "Dive into our dynamic Community Hub", "icon_url": None, "background_color": "#AF52DE"},
        {"title": "Language", "subtitle": "Dive into our dynamic Community Hub", "icon_url": None, "background_color": "#FF9500"},
        {"title": "Human Social", "subtitle": "Dive into our dynamic Community Hub", "icon_url": None, "background_color": "#FF4500"},
        {"title": "Psychological", "subtitle": "Dive into our dynamic Community Hub", "icon_url": None, "background_color": "#5AC8FA"},
        {"title": "Mathematic", "subtitle": "Dive into our dynamic Community Hub", "icon_url": None, "background_color": "#0A66C2"},
        {"title": "Economics", "subtitle": "Dive into our dynamic Community Hub", "icon_url": None, "background_color": "#34C759"},
        {"title": "Engineering Science", "subtitle": "Dive into our dynamic Community Hub", "icon_url": None, "background_color": "#FF2D55"},
    ],
}

# Default testimonials section
TESTIMONIALS_DEFAULTS = {
    "testimonials_header": "OUR TESTIMONIALS",
    "testimonials_title": "What Our Student Say About US",
    "testimonials_items": [
        {
            "testimonial_text": "Lost in the mesmerizing allure of Bali's rice terraces! I am rave about the enchanting beauty and the surreal feeling as the sun sets over these lush landscapes. An unforgettable experience that beckons you to return.",
            "author_name": "Haliza Asyifa",
            "author_title": "Designer - Bali",
            "author_avatar_url": None,
        },
        {"testimonial_text": "Bvonix Academy transformed my learning journey. The quality of courses and expert mentors helped me achieve my goals.", "author_name": "Alex Johnson", "author_title": "Student", "author_avatar_url": None},
        {"testimonial_text": "Best decision I ever made. Flexible schedule and hands-on projects made learning practical and fun.", "author_name": "Sarah Chen", "author_title": "Developer", "author_avatar_url": None},
        {"testimonial_text": "Outstanding curriculum and supportive community. I recommend Bvonix Academy to everyone.", "author_name": "Michael Brown", "author_title": "Graduate", "author_avatar_url": None},
        {"testimonial_text": "The mentors here are incredible. They helped me understand complex concepts with ease.", "author_name": "Emily Davis", "author_title": "Student", "author_avatar_url": None},
        {"testimonial_text": "Professional courses with real-world applications. Worth every penny.", "author_name": "James Wilson", "author_title": "Professional", "author_avatar_url": None},
    ],
}

# Default student dashboard settings (admin customizable)
DASHBOARD_DEFAULTS = {
    "dashboard_banner_title": "Sharpen Your Skills With Professional Online Courses",
    "dashboard_banner_cta_text": "Join Now",
    "dashboard_banner_cta_link": "/courses",
    "dashboard_youtube_url": "",  # YouTube video or playlist URL - admin adds embed
    "dashboard_greeting_prefix": "Good Morning",
    "dashboard_motivational_text": "Continue Your Journey And Achieve Your Target",
    "dashboard_search_placeholder": "Search your course here...",
    "dashboard_friends_items": [],
}

# Default footer
FOOTER_DEFAULTS = {
    "footer_brand_name": "Bvonix Academy",
    "footer_contact_label": "Contact Bvonix Academy",
    "footer_contact_type": "whatsapp",
    "footer_contact_value": "",
    "footer_contacts": [
        {"type": "whatsapp", "value": ""},
        {"type": "email", "value": ""},
        {"type": "phone", "value": ""},
    ],
    "footer_social_links": [
        {"platform": "whatsapp", "url": ""},
        {"platform": "facebook", "url": ""},
        {"platform": "twitter", "url": ""},
        {"platform": "email", "url": ""},
        {"platform": "youtube", "url": ""},
        {"platform": "instagram", "url": ""},
    ],
    "footer_legal_links": [
        {"label": "Cookie Policy", "url": "/cookie-policy"},
        {"label": "Privacy Policy", "url": "/privacy-policy"},
        {"label": "Terms and Conditions", "url": "/terms"},
        {"label": "Contact Us", "url": "/contact"},
        {"label": "About", "url": "/about"},
    ],
    "footer_copyright_text": "© 2025 Bvonix Academy. All rights reserved.",
}

# Default brand / logo settings
BRAND_DEFAULTS = {
    "site_logo_url": "/logo.png",
    "site_logo_display_height": 40,
    "site_logo_type": "image",
    "site_logo_text": "Bvonix\nAcademy",
}


class HeroSettingsUpdate(BaseModel):
    """Schema for hero section text/link updates."""
    hero_headline: str | None = Field(default=None, max_length=500)
    hero_description: str | None = Field(default=None, max_length=1000)
    hero_cta_text: str | None = Field(default=None, max_length=100)
    hero_cta_link: str | None = Field(default=None, max_length=200)
    hero_cta_subtext: str | None = Field(default=None, max_length=200)
    hero_social_text: str | None = Field(default=None, max_length=200)
    hero_image_alt: str | None = Field(default=None, max_length=200)


class CommunitySettingsUpdate(BaseModel):
    """Schema for community section updates."""
    community_header: str | None = Field(default=None, max_length=200)
    community_title: str | None = Field(default=None, max_length=300)
    community_description: str | None = Field(default=None, max_length=1500)
    community_stat1_value: str | None = Field(default=None, max_length=50)
    community_stat1_label: str | None = Field(default=None, max_length=100)
    community_stat2_value: str | None = Field(default=None, max_length=50)
    community_stat2_label: str | None = Field(default=None, max_length=100)
    community_stat3_value: str | None = Field(default=None, max_length=50)
    community_stat3_label: str | None = Field(default=None, max_length=100)
    community_image_alt: str | None = Field(default=None, max_length=200)


class MilestoneItem(BaseModel):
    value: str = Field(max_length=50)
    label: str = Field(max_length=100)


class MilestonesSettingsUpdate(BaseModel):
    """Schema for milestones section updates."""
    milestones_items: list[MilestoneItem] | None = None


class BenefitItem(BaseModel):
    title: str = Field(max_length=150)
    description: str = Field(max_length=500)
    icon_url: str | None = None
    background_color: str = Field(default="#E53935", max_length=20)


class BenefitsSettingsUpdate(BaseModel):
    """Schema for benefits section updates."""
    benefits_header: str | None = Field(default=None, max_length=150)
    benefits_title: str | None = Field(default=None, max_length=300)
    benefits_items: list[BenefitItem] | None = None


class SubjectItem(BaseModel):
    title: str = Field(max_length=150)
    subtitle: str = Field(max_length=300)
    icon_url: str | None = None
    background_color: str = Field(default="#E53935", max_length=20)


class SubjectsSettingsUpdate(BaseModel):
    """Schema for subjects section updates."""
    subjects_header: str | None = Field(default=None, max_length=150)
    subjects_title: str | None = Field(default=None, max_length=300)
    subjects_items: list[SubjectItem] | None = None


class TestimonialItem(BaseModel):
    testimonial_text: str = Field(max_length=1000)
    author_name: str = Field(max_length=100)
    author_title: str = Field(max_length=150)
    author_avatar_url: str | None = None


class TestimonialsSettingsUpdate(BaseModel):
    """Schema for testimonials section updates."""
    testimonials_header: str | None = Field(default=None, max_length=150)
    testimonials_title: str | None = Field(default=None, max_length=300)
    testimonials_items: list[TestimonialItem] | None = None


class SocialLinkItem(BaseModel):
    platform: str = Field(max_length=50)
    url: str = Field(max_length=500)


class LegalLinkItem(BaseModel):
    label: str = Field(max_length=100)
    url: str = Field(max_length=500)


class FooterContactItem(BaseModel):
    type: str = Field(max_length=50)
    value: str = Field(max_length=200)


class DashboardFriendItem(BaseModel):
    name: str = Field(max_length=100)
    role: str = Field(max_length=150)
    avatar_url: str | None = None


class DashboardSettingsUpdate(BaseModel):
    """Schema for student dashboard section updates."""
    dashboard_banner_title: str | None = Field(default=None, max_length=300)
    dashboard_banner_cta_text: str | None = Field(default=None, max_length=100)
    dashboard_banner_cta_link: str | None = Field(default=None, max_length=200)
    dashboard_youtube_url: str | None = Field(default=None, max_length=500)
    dashboard_greeting_prefix: str | None = Field(default=None, max_length=100)
    dashboard_motivational_text: str | None = Field(default=None, max_length=300)
    dashboard_search_placeholder: str | None = Field(default=None, max_length=150)
    dashboard_friends_items: list[DashboardFriendItem] | None = None


class FooterSettingsUpdate(BaseModel):
    """Schema for footer updates."""
    footer_brand_name: str | None = Field(default=None, max_length=100)
    footer_contact_label: str | None = Field(default=None, max_length=150)
    footer_contact_type: str | None = Field(default=None, max_length=50)
    footer_contact_value: str | None = Field(default=None, max_length=200)
    footer_address: str | None = Field(default=None, max_length=500)
    footer_contacts: list[FooterContactItem] | None = None
    footer_social_links: list[SocialLinkItem] | None = None
    footer_legal_links: list[LegalLinkItem] | None = None
    footer_copyright_text: str | None = Field(default=None, max_length=1000)


class BrandSettingsUpdate(BaseModel):
    """Schema for site logo and brand display settings."""
    site_logo_url: str | None = Field(default=None, max_length=500)
    site_logo_display_height: int | None = Field(default=None, ge=24, le=120)
    site_logo_type: str | None = Field(default=None, max_length=20)
    site_logo_text: str | None = Field(default=None, max_length=200)


def _ensure_dirs():
    SITE_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HERO_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    COMMUNITY_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    BENEFIT_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    SUBJECT_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    TESTIMONIAL_AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)


def _load_settings() -> dict:
    _ensure_dirs()
    all_defaults = {**BRAND_DEFAULTS, **HERO_DEFAULTS, **COMMUNITY_DEFAULTS, **MILESTONES_DEFAULTS, **BENEFITS_DEFAULTS, **SUBJECTS_DEFAULTS, **TESTIMONIALS_DEFAULTS, **DASHBOARD_DEFAULTS, **FOOTER_DEFAULTS}
    if not SITE_SETTINGS_FILE.exists():
        return all_defaults
    try:
        data = json.load(open(SITE_SETTINGS_FILE, "r"))
        for k, v in all_defaults.items():
            if k not in data:
                data[k] = v
        return data
    except Exception:
        return all_defaults


def _save_settings(data: dict) -> None:
    _ensure_dirs()
    with open(SITE_SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


@router.get("/site-settings")
async def get_site_settings() -> dict:
    """Get site settings (public, no auth). Used by frontend for hero icon URL."""
    return _load_settings()


@router.patch("/site-settings/hero", status_code=status.HTTP_200_OK)
async def update_hero_settings(
    payload: HeroSettingsUpdate,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Update hero section text, links, etc. (admin only)."""
    settings = _load_settings()
    updates = payload.model_dump(exclude_none=True)
    for k, v in updates.items():
        settings[k] = v
    _save_settings(settings)
    return JSONResponse(content={"message": "Hero section updated successfully", **settings})


@router.patch("/site-settings/community", status_code=status.HTTP_200_OK)
async def update_community_settings(
    payload: CommunitySettingsUpdate,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Update community section text (admin only)."""
    settings = _load_settings()
    updates = payload.model_dump(exclude_none=True)
    for k, v in updates.items():
        settings[k] = v
    _save_settings(settings)
    return JSONResponse(content={"message": "Community section updated successfully", **settings})


@router.patch("/site-settings/milestones", status_code=status.HTTP_200_OK)
async def update_milestones_settings(
    payload: MilestonesSettingsUpdate,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Update milestones section items (admin only)."""
    settings = _load_settings()
    updates = payload.model_dump(exclude_none=True)
    for k, v in updates.items():
        if k == "milestones_items" and v is not None:
            settings[k] = [{"value": i["value"], "label": i["label"]} for i in v]
        else:
            settings[k] = v
    _save_settings(settings)
    return JSONResponse(content={"message": "Milestones section updated successfully", **settings})


@router.patch("/site-settings/benefits", status_code=status.HTTP_200_OK)
async def update_benefits_settings(
    payload: BenefitsSettingsUpdate,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Update benefits section (admin only)."""
    settings = _load_settings()
    updates = payload.model_dump(exclude_none=True)
    for k, v in updates.items():
        if k == "benefits_items" and v is not None:
            settings[k] = [
                {
                    "title": i["title"],
                    "description": i["description"],
                    "icon_url": i.get("icon_url"),
                    "background_color": i.get("background_color", "#E53935"),
                }
                for i in v
            ]
        else:
            settings[k] = v
    _save_settings(settings)
    return JSONResponse(content={"message": "Benefits section updated successfully", **settings})


@router.post("/site-settings/benefit-icon", status_code=status.HTTP_200_OK)
async def upload_benefit_icon(
    file: UploadFile = File(...),
    index: int = 0,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Upload icon for a benefit card (admin only). Index = card position (0-based)."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError("Invalid file type. Only JPEG, PNG, and WebP images are allowed.")
    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise AppError(f"File size exceeds maximum allowed size of {MAX_IMAGE_SIZE // 1024 // 1024}MB")
    import secrets
    ext = Path(file.filename).suffix or ".png"
    unique_filename = f"benefit_{index}_{secrets.token_hex(8)}{ext}"
    file_path = BENEFIT_ICONS_DIR / unique_filename
    _ensure_dirs()
    with open(file_path, "wb") as f:
        f.write(contents)
    relative_url = f"/uploads/benefit_icons/{unique_filename}"
    settings = _load_settings()
    items = settings.get("benefits_items", BENEFITS_DEFAULTS["benefits_items"])
    if isinstance(items, list) and 0 <= index < len(items):
        items = list(items)
        items[index] = {**items[index], "icon_url": relative_url}
        settings["benefits_items"] = items
        _save_settings(settings)
    return JSONResponse(content={"icon_url": relative_url, "index": index, "message": "Benefit icon updated"})


@router.patch("/site-settings/subjects", status_code=status.HTTP_200_OK)
async def update_subjects_settings(
    payload: SubjectsSettingsUpdate,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Update subjects section (admin only)."""
    settings = _load_settings()
    updates = payload.model_dump(exclude_none=True)
    for k, v in updates.items():
        if k == "subjects_items" and v is not None:
            settings[k] = [
                {
                    "title": i["title"],
                    "subtitle": i["subtitle"],
                    "icon_url": i.get("icon_url"),
                    "background_color": i.get("background_color", "#E53935"),
                }
                for i in v
            ]
        else:
            settings[k] = v
    _save_settings(settings)
    return JSONResponse(content={"message": "Subjects section updated successfully", **settings})


@router.post("/site-settings/subject-icon", status_code=status.HTTP_200_OK)
async def upload_subject_icon(
    file: UploadFile = File(...),
    index: int = 0,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Upload icon for a subject card (admin only). Index = card position (0-based)."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError("Invalid file type. Only JPEG, PNG, and WebP images are allowed.")
    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise AppError(f"File size exceeds maximum allowed size of {MAX_IMAGE_SIZE // 1024 // 1024}MB")
    import secrets
    ext = Path(file.filename).suffix or ".png"
    unique_filename = f"subject_{index}_{secrets.token_hex(8)}{ext}"
    file_path = SUBJECT_ICONS_DIR / unique_filename
    _ensure_dirs()
    with open(file_path, "wb") as f:
        f.write(contents)
    relative_url = f"/uploads/subject_icons/{unique_filename}"
    settings = _load_settings()
    items = settings.get("subjects_items", SUBJECTS_DEFAULTS["subjects_items"])
    if isinstance(items, list) and 0 <= index < len(items):
        items = list(items)
        items[index] = {**items[index], "icon_url": relative_url}
        settings["subjects_items"] = items
        _save_settings(settings)
    return JSONResponse(content={"icon_url": relative_url, "index": index, "message": "Subject icon updated"})


@router.patch("/site-settings/testimonials", status_code=status.HTTP_200_OK)
async def update_testimonials_settings(
    payload: TestimonialsSettingsUpdate,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Update testimonials section (admin only)."""
    settings = _load_settings()
    updates = payload.model_dump(exclude_none=True)
    for k, v in updates.items():
        if k == "testimonials_items" and v is not None:
            settings[k] = [
                {
                    "testimonial_text": i["testimonial_text"],
                    "author_name": i["author_name"],
                    "author_title": i["author_title"],
                    "author_avatar_url": i.get("author_avatar_url"),
                }
                for i in v
            ]
        else:
            settings[k] = v
    _save_settings(settings)
    return JSONResponse(content={"message": "Testimonials section updated successfully", **settings})


@router.post("/site-settings/testimonial-avatar", status_code=status.HTTP_200_OK)
async def upload_testimonial_avatar(
    file: UploadFile = File(...),
    index: int = 0,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Upload avatar for a testimonial (admin only). Index = testimonial position (0-based)."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError("Invalid file type. Only JPEG, PNG, and WebP images are allowed.")
    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise AppError(f"File size exceeds maximum allowed size of {MAX_IMAGE_SIZE // 1024 // 1024}MB")
    import secrets
    ext = Path(file.filename).suffix or ".png"
    unique_filename = f"testimonial_{index}_{secrets.token_hex(8)}{ext}"
    file_path = TESTIMONIAL_AVATARS_DIR / unique_filename
    _ensure_dirs()
    with open(file_path, "wb") as f:
        f.write(contents)
    relative_url = f"/uploads/testimonial_avatars/{unique_filename}"
    settings = _load_settings()
    items = settings.get("testimonials_items", TESTIMONIALS_DEFAULTS["testimonials_items"])
    if isinstance(items, list) and 0 <= index < len(items):
        items = list(items)
        items[index] = {**items[index], "author_avatar_url": relative_url}
        settings["testimonials_items"] = items
        _save_settings(settings)
    return JSONResponse(content={"author_avatar_url": relative_url, "index": index, "message": "Testimonial avatar updated"})


@router.patch("/site-settings/dashboard", status_code=status.HTTP_200_OK)
async def update_dashboard_settings(
    payload: DashboardSettingsUpdate,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Update student dashboard section (admin only)."""
    settings = _load_settings()
    updates = payload.model_dump(exclude_none=True)
    for k, v in updates.items():
        if k == "dashboard_friends_items" and v is not None:
            settings[k] = [
                {"name": i["name"], "role": i["role"], "avatar_url": i.get("avatar_url")}
                for i in v
            ]
        else:
            settings[k] = v
    _save_settings(settings)
    return JSONResponse(content={"message": "Dashboard section updated successfully", **settings})


@router.patch("/site-settings/footer", status_code=status.HTTP_200_OK)
async def update_footer_settings(
    payload: FooterSettingsUpdate,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Update footer section (admin only)."""
    settings = _load_settings()
    updates = payload.model_dump(exclude_none=True)
    for k, v in updates.items():
        if k == "footer_contacts" and v is not None:
            settings[k] = [{"type": i["type"], "value": i.get("value", "")} for i in v]
        elif k == "footer_social_links" and v is not None:
            settings[k] = [{"platform": i["platform"], "url": i.get("url", "")} for i in v]
        elif k == "footer_legal_links" and v is not None:
            settings[k] = [{"label": i["label"], "url": i.get("url", "")} for i in v]
        else:
            settings[k] = v
    _save_settings(settings)
    return JSONResponse(content={"message": "Footer updated successfully", **settings})


@router.post("/site-settings/community-image", status_code=status.HTTP_200_OK)
async def upload_community_image(
    file: UploadFile = File(...),
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Upload community section image (admin only)."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError("Invalid file type. Only JPEG, PNG, and WebP images are allowed.")
    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise AppError(f"File size exceeds maximum allowed size of {MAX_IMAGE_SIZE // 1024 // 1024}MB")
    import secrets
    ext = Path(file.filename).suffix or ".png"
    unique_filename = f"community_{secrets.token_hex(8)}{ext}"
    file_path = COMMUNITY_IMAGES_DIR / unique_filename
    _ensure_dirs()
    with open(file_path, "wb") as f:
        f.write(contents)
    relative_url = f"/uploads/community_images/{unique_filename}"
    settings = _load_settings()
    settings["community_image_url"] = relative_url
    _save_settings(settings)
    return JSONResponse(content={"community_image_url": relative_url, "message": "Community image updated successfully"})


@router.post("/site-settings/hero-icon", status_code=status.HTTP_200_OK)
async def upload_hero_icon(
    file: UploadFile = File(...),
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Upload and set hero section icon (admin only)."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError("Invalid file type. Only JPEG, PNG, and WebP images are allowed.")

    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise AppError(f"File size exceeds maximum allowed size of {MAX_IMAGE_SIZE // 1024 // 1024}MB")

    import secrets
    ext = Path(file.filename).suffix or ".png"
    unique_filename = f"hero_icon_{secrets.token_hex(8)}{ext}"
    file_path = HERO_ICONS_DIR / unique_filename

    _ensure_dirs()
    with open(file_path, "wb") as f:
        f.write(contents)

    relative_url = f"/uploads/hero_icons/{unique_filename}"
    settings = _load_settings()
    settings["hero_icon_url"] = relative_url
    _save_settings(settings)

    return JSONResponse(
        content={"hero_icon_url": relative_url, "message": "Hero icon updated successfully"}
    )


@router.patch("/site-settings/brand", status_code=status.HTTP_200_OK)
async def update_brand_settings(
    payload: BrandSettingsUpdate,
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Update site logo URL or display height (admin only)."""
    settings = _load_settings()
    for k, v in payload.model_dump(exclude_unset=True).items():
        if k == "site_logo_type" and v is not None and v not in ("image", "text"):
            raise AppError("site_logo_type must be 'image' or 'text'")
        settings[k] = v
    _save_settings(settings)
    return JSONResponse(content={"message": "Brand settings updated successfully", **settings})


@router.post("/site-settings/logo", status_code=status.HTTP_200_OK)
async def upload_site_logo(
    file: UploadFile = File(...),
    admin_user: User = Depends(get_admin_user),
) -> JSONResponse:
    """Upload and set site logo (admin only)."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError("Invalid file type. Only JPEG, PNG, and WebP images are allowed.")

    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise AppError(f"File size exceeds maximum allowed size of {MAX_IMAGE_SIZE // 1024 // 1024}MB")

    import secrets
    ext = Path(file.filename).suffix or ".png"
    unique_filename = f"site_logo_{secrets.token_hex(8)}{ext}"
    file_path = LOGOS_DIR / unique_filename

    _ensure_dirs()
    with open(file_path, "wb") as f:
        f.write(contents)

    relative_url = f"/uploads/logos/{unique_filename}"
    settings = _load_settings()
    settings["site_logo_url"] = relative_url
    _save_settings(settings)

    return JSONResponse(
        content={"site_logo_url": relative_url, "message": "Site logo updated successfully"}
    )

"""Published-course facts for the public course page.

Lesson files and assignment instructions stay behind enrollment.
"""

from __future__ import annotations

from app.repositories.archival import record_is_active
from app.schemas.course import (
    CourseDecisionPublic,
    CourseInstructorSummary,
    CourseLessonSummary,
    CoursePracticalSummary,
)
from app.utils.exceptions import NotFoundError


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


async def build_course_decision(
    course,
    *,
    instructors,
    users,
    materials,
    assignments,
) -> CourseDecisionPublic:
    """Assemble instructor, lesson titles, and practical work for a published course."""
    if not course.is_published:
        raise NotFoundError("Course not found")

    instructor = await _instructor_summary(course.instructor_id, instructors, users)
    # The public course page returns every published lesson and practical title.
    # Those lists are the response, so this read stays complete and is paged internally.
    lessons = await materials.get_by_course(course.id, published_only=True)
    practical = await assignments.get_by_course(course.id, published_only=True)
    lesson_total = len(lessons)
    practical_total = len(practical)
    return CourseDecisionPublic(
        instructor=instructor,
        lessons=[
            CourseLessonSummary(
                title=item.title,
                description=_clean(item.description),
                material_type=item.material_type,
                order=item.order,
                duration_minutes=item.duration_minutes,
                is_required=bool(item.is_required),
            )
            for item in lessons
        ],
        lesson_total=lesson_total,
        practical_work=[
            CoursePracticalSummary(
                title=item.title,
                description=item.description,
                assignment_type=item.assignment_type,
            )
            for item in practical
        ],
        practical_total=practical_total,
    )


async def _instructor_summary(instructor_id: str | None, instructors, users) -> CourseInstructorSummary | None:
    if not instructor_id:
        return None
    record = await instructors.get_by_id(instructor_id)
    if not record or not record_is_active(record):
        return None
    user = await users.get_by_id(record.user_id) if record.user_id else None
    if user is not None and not record_is_active(user):
        return None
    name = _clean(user.full_name) if user is not None else None
    summary = CourseInstructorSummary(
        name=name,
        specialization=_clean(record.specialization),
        bio=_clean(record.bio),
        years_of_experience=record.years_of_experience,
    )
    if (
        summary.name is None
        and summary.specialization is None
        and summary.bio is None
        and summary.years_of_experience is None
    ):
        return None
    return summary

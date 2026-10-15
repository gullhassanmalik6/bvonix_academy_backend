from __future__ import annotations

from fastapi import Depends

from app.db.mongodb import mongodb
from app.repositories.announcement_repository import AnnouncementRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.assignment_repository import AssignmentRepository, AssignmentSubmissionRepository
from app.repositories.attendance_correction_repository import AttendanceCorrectionRepository
from app.repositories.attendance_claim_repository import AttendanceClaimRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.calendar_event_repository import CalendarEventRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.certificate_repository import CertificateRepository
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.forum_repository import ForumPostRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.live_session_repository import LiveSessionRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.scholarship_repository import ScholarshipRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.services.announcement_service import AnnouncementService
from app.services.audit_service import AuditService
from app.services.assignment_service import AssignmentService
from app.services.auth_service import AuthService
from app.services.attendance_correction_service import AttendanceCorrectionService
from app.services.attendance_claim_service import AttendanceClaimService
from app.services.attendance_service import AttendanceService
from app.services.calendar_event_service import CalendarEventService
from app.services.notification_service import NotificationService
from app.services.course_material_service import CourseMaterialService
from app.services.course_service import CourseService
from app.services.forum_service import ForumService
from app.services.instructor_service import InstructorService
from app.services.live_session_service import LiveSessionService
from app.services.payment_service import PaymentService
from app.services.scholarship_service import ScholarshipService
from app.services.student_service import StudentService
from app.services.user_service import UserService


def get_user_repository() -> UserRepository:
    return UserRepository(mongodb.db)


def get_course_repository() -> CourseRepository:
    return CourseRepository(mongodb.db)


def get_instructor_repository() -> InstructorRepository:
    return InstructorRepository(mongodb.db)


def get_student_repository() -> StudentRepository:
    return StudentRepository(mongodb.db)


def get_session_repository() -> SessionRepository:
    return SessionRepository(mongodb.db)


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
    sessions: SessionRepository = Depends(get_session_repository),
) -> AuthService:
    return AuthService(users, sessions)


def get_audit_repository() -> AuditLogRepository:
    return AuditLogRepository(mongodb.db)


def get_audit_service(audits: AuditLogRepository = Depends(get_audit_repository)) -> AuditService:
    return AuditService(audits)


def get_user_service(
    users: UserRepository = Depends(get_user_repository),
    audit: AuditService = Depends(get_audit_service),
    sessions: SessionRepository = Depends(get_session_repository),
) -> UserService:
    return UserService(users, audit=audit, sessions=sessions)


def get_course_service(
    courses: CourseRepository = Depends(get_course_repository),
    audit: AuditService = Depends(get_audit_service),
) -> CourseService:
    return CourseService(courses, audit=audit)


def get_instructor_service(
    instructors: InstructorRepository = Depends(get_instructor_repository),
    audit: AuditService = Depends(get_audit_service),
) -> InstructorService:
    return InstructorService(instructors, audit=audit)


def get_student_service(
    students: StudentRepository = Depends(get_student_repository),
    audit: AuditService = Depends(get_audit_service),
) -> StudentService:
    return StudentService(students, audit=audit)


def get_enrollment_repository() -> EnrollmentRepository:
    return EnrollmentRepository(mongodb.db)


def get_require_verified_enrollment():
    """
    Require one admin-verified active or completed enrollment.
    Use: verified_data: tuple = Depends(get_require_verified_enrollment())
    Returns (student, None). Course checks use get_access_enrollment.
    Raises ForbiddenError when no eligible enrollment exists.
    """
    from app.core.auth import get_current_user
    from app.utils.exceptions import ForbiddenError

    async def _require_verified_enrollment(
        current_user=Depends(get_current_user),
        enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
        student_repo: StudentRepository = Depends(get_student_repository),
    ) -> tuple:
        student = await student_repo.get_by_user_id(current_user.id)
        if not student:
            raise ForbiddenError(
                "LMS access requires enrollment in a course. Please enroll in a course and wait for admin payment verification."
            )
        # Existence only. Course and enrollment checks use find_one in the route.
        if not await enrollment_repo.has_verified_enrollment(student.id):
            raise ForbiddenError(
                "LMS access requires admin-verified payment. Please complete your enrollment, upload your payment receipt, and wait for admin verification."
            )
        return (student, None)

    return _require_verified_enrollment


def get_student_portal():
    """Signed-in student profile. Fee pages stay available before verification."""
    from app.core.auth import get_current_user

    async def _student_portal(
        current_user=Depends(get_current_user),
        student_repo: StudentRepository = Depends(get_student_repository),
    ):
        student = await student_repo.get_by_user_id(current_user.id)
        return (student, None)

    return _student_portal


def get_result_repository() -> ResultRepository:
    return ResultRepository(mongodb.db)


def get_attendance_repository() -> AttendanceRepository:
    return AttendanceRepository(mongodb.db)


def get_certificate_repository() -> CertificateRepository:
    return CertificateRepository(mongodb.db)


def get_scholarship_repository() -> ScholarshipRepository:
    return ScholarshipRepository(mongodb.db)


def get_notification_repository() -> NotificationRepository:
    return NotificationRepository(mongodb.db)


def get_notification_service(
    notifications: NotificationRepository = Depends(get_notification_repository),
    users: UserRepository = Depends(get_user_repository),
    students: StudentRepository = Depends(get_student_repository),
) -> NotificationService:
    return NotificationService(notifications, users, students)


def get_scholarship_service(
    scholarships: ScholarshipRepository = Depends(get_scholarship_repository),
    notifications: NotificationService = Depends(get_notification_service),
    students: StudentRepository = Depends(get_student_repository),
    courses: CourseRepository = Depends(get_course_repository),
    audit: AuditService = Depends(get_audit_service),
) -> ScholarshipService:
    return ScholarshipService(scholarships, notifications, students, courses, audit=audit)


def get_attendance_service(
    attendances: AttendanceRepository = Depends(get_attendance_repository),
    scholarships: ScholarshipRepository = Depends(get_scholarship_repository),
    scholarship_service: ScholarshipService = Depends(get_scholarship_service),
    audit: AuditService = Depends(get_audit_service),
) -> AttendanceService:
    return AttendanceService(attendances, scholarships, scholarship_service, audit=audit)


def get_attendance_claim_repository() -> AttendanceClaimRepository:
    return AttendanceClaimRepository(mongodb.db)


def get_attendance_claim_service(
    claims: AttendanceClaimRepository = Depends(get_attendance_claim_repository),
    attendances: AttendanceService = Depends(get_attendance_service),
    audit: AuditService = Depends(get_audit_service),
) -> AttendanceClaimService:
    return AttendanceClaimService(claims, attendances, audit=audit)


def get_attendance_correction_repository() -> AttendanceCorrectionRepository:
    return AttendanceCorrectionRepository(mongodb.db)


def get_attendance_correction_service(
    corrections: AttendanceCorrectionRepository = Depends(get_attendance_correction_repository),
    attendance: AttendanceService = Depends(get_attendance_service),
    courses: CourseRepository = Depends(get_course_repository),
    audit: AuditService = Depends(get_audit_service),
) -> AttendanceCorrectionService:
    return AttendanceCorrectionService(corrections, attendance, courses=courses, audit=audit)


def get_course_material_repository() -> CourseMaterialRepository:
    return CourseMaterialRepository(mongodb.db)


def get_assignment_repository() -> AssignmentRepository:
    return AssignmentRepository(mongodb.db)


def get_assignment_submission_repository() -> AssignmentSubmissionRepository:
    return AssignmentSubmissionRepository(mongodb.db)


def get_live_session_repository() -> LiveSessionRepository:
    return LiveSessionRepository(mongodb.db)


def get_announcement_repository() -> AnnouncementRepository:
    return AnnouncementRepository(mongodb.db)


def get_payment_repository() -> PaymentRepository:
    return PaymentRepository(mongodb.db)


def get_forum_repository() -> ForumPostRepository:
    return ForumPostRepository(mongodb.db)


def get_course_material_service(
    materials: CourseMaterialRepository = Depends(get_course_material_repository),
    courses: CourseRepository = Depends(get_course_repository),
    audit: AuditService = Depends(get_audit_service),
) -> CourseMaterialService:
    return CourseMaterialService(materials, courses=courses, audit=audit)


def get_assignment_service(
    assignments: AssignmentRepository = Depends(get_assignment_repository),
    submissions: AssignmentSubmissionRepository = Depends(get_assignment_submission_repository),
    courses: CourseRepository = Depends(get_course_repository),
    audit: AuditService = Depends(get_audit_service),
) -> AssignmentService:
    return AssignmentService(assignments, submissions, courses=courses, audit=audit)


def get_live_session_service(
    sessions: LiveSessionRepository = Depends(get_live_session_repository),
    courses: CourseRepository = Depends(get_course_repository),
    audit: AuditService = Depends(get_audit_service),
) -> LiveSessionService:
    return LiveSessionService(sessions, courses=courses, audit=audit)


def get_announcement_service(
    announcements: AnnouncementRepository = Depends(get_announcement_repository),
    courses: CourseRepository = Depends(get_course_repository),
    audit: AuditService = Depends(get_audit_service),
) -> AnnouncementService:
    return AnnouncementService(announcements, courses=courses, audit=audit)


def get_payment_service(
    payments: PaymentRepository = Depends(get_payment_repository),
    audit: AuditService = Depends(get_audit_service),
) -> PaymentService:
    return PaymentService(payments, audit=audit)


def get_forum_service(
    posts: ForumPostRepository = Depends(get_forum_repository),
    users: UserRepository = Depends(get_user_repository),
    courses: CourseRepository = Depends(get_course_repository),
) -> ForumService:
    return ForumService(posts, users, courses=courses)


def get_calendar_event_repository() -> CalendarEventRepository:
    return CalendarEventRepository(mongodb.db)


def get_calendar_event_service(
    events: CalendarEventRepository = Depends(get_calendar_event_repository),
    courses: CourseRepository = Depends(get_course_repository),
) -> CalendarEventService:
    return CalendarEventService(events, courses=courses)


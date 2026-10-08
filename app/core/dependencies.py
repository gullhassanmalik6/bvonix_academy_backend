from __future__ import annotations

from fastapi import Depends

from app.db.mongodb import mongodb
from app.repositories.announcement_repository import AnnouncementRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.assignment_repository import AssignmentRepository, AssignmentSubmissionRepository
from app.repositories.attendance_correction_repository import AttendanceCorrectionRepository
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


def get_course_service(courses: CourseRepository = Depends(get_course_repository)) -> CourseService:
    return CourseService(courses)


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
    Returns a dependency that requires the current user to have at least one admin-verified enrollment.
    Use: verified_data: tuple = Depends(get_require_verified_enrollment())
    Returns (student, verified_enrollments). Raises ForbiddenError if none.
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
        verified = await enrollment_repo.get_verified_by_student(student.id)
        if not verified:
            raise ForbiddenError(
                "LMS access requires admin-verified payment. Please complete your enrollment, upload your payment receipt, and wait for admin verification."
            )
        return (student, verified)

    return _require_verified_enrollment


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


def get_attendance_correction_repository() -> AttendanceCorrectionRepository:
    return AttendanceCorrectionRepository(mongodb.db)


def get_attendance_correction_service(
    corrections: AttendanceCorrectionRepository = Depends(get_attendance_correction_repository),
    attendance: AttendanceService = Depends(get_attendance_service),
    audit: AuditService = Depends(get_audit_service),
) -> AttendanceCorrectionService:
    return AttendanceCorrectionService(corrections, attendance, audit=audit)


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
) -> CourseMaterialService:
    return CourseMaterialService(materials)


def get_assignment_service(
    assignments: AssignmentRepository = Depends(get_assignment_repository),
    submissions: AssignmentSubmissionRepository = Depends(get_assignment_submission_repository),
    audit: AuditService = Depends(get_audit_service),
) -> AssignmentService:
    return AssignmentService(assignments, submissions, audit=audit)


def get_live_session_service(
    sessions: LiveSessionRepository = Depends(get_live_session_repository),
) -> LiveSessionService:
    return LiveSessionService(sessions)


def get_announcement_service(
    announcements: AnnouncementRepository = Depends(get_announcement_repository),
) -> AnnouncementService:
    return AnnouncementService(announcements)


def get_payment_service(
    payments: PaymentRepository = Depends(get_payment_repository),
    audit: AuditService = Depends(get_audit_service),
) -> PaymentService:
    return PaymentService(payments, audit=audit)


def get_forum_service(
    posts: ForumPostRepository = Depends(get_forum_repository),
    users: UserRepository = Depends(get_user_repository),
) -> ForumService:
    return ForumService(posts, users)


def get_calendar_event_repository() -> CalendarEventRepository:
    return CalendarEventRepository(mongodb.db)


def get_calendar_event_service(
    events: CalendarEventRepository = Depends(get_calendar_event_repository),
) -> CalendarEventService:
    return CalendarEventService(events)


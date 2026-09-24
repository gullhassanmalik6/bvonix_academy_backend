"""
Admin panel routes.

Why: Separate admin routes for managing courses, users, instructors, and students.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.admin import get_admin_user
from app.core.dependencies import (
    get_announcement_service,
    get_assignment_service,
    get_attendance_service,
    get_course_material_service,
    get_course_repository,
    get_course_service,
    get_enrollment_repository,
    get_forum_service,
    get_instructor_repository,
    get_instructor_service,
    get_live_session_service,
    get_notification_service,
    get_payment_service,
    get_scholarship_repository,
    get_scholarship_service,
    get_student_repository,
    get_student_service,
    get_user_repository,
    get_user_service,
)
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginatedResponse
from app.schemas.announcement import AnnouncementCreate, AnnouncementPublic, AnnouncementUpdate
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentPublic,
    AssignmentSubmissionPublic,
    AssignmentUpdate,
)
from app.schemas.attendance import AttendanceCreate, AttendancePublic, AttendanceUpdate
from app.schemas.course import CourseCreate, CoursePublic, CourseUpdate
from app.schemas.course_material import CourseMaterialCreate, CourseMaterialPublic, CourseMaterialUpdate
from app.schemas.instructor import InstructorCreate, InstructorPublic, InstructorUpdate
from app.schemas.live_session import LiveSessionCreate, LiveSessionPublic, LiveSessionUpdate
from app.schemas.payment import PaymentCreate, PaymentPublic, PaymentUpdate
from app.schemas.enrollment import (
    EnrollmentCardForm,
    EnrollmentCardFormUpdate,
    EnrollmentPublic,
    EnrollmentUpdate,
)
from app.schemas.scholarship import ScholarshipCreate, ScholarshipPublic, ScholarshipUpdate
from app.schemas.student import StudentCreate, StudentPublic, StudentUpdate
from app.schemas.user import UserPublic, UserUpdate
from app.services.announcement_service import AnnouncementService
from app.services.assignment_service import AssignmentService
from app.services.attendance_service import AttendanceService
from app.services.course_material_service import CourseMaterialService
from app.services.course_service import CourseService
from app.services.forum_service import ForumService
from app.services.instructor_service import InstructorService
from app.services.live_session_service import LiveSessionService
from app.services.notification_service import NotificationService
from app.services.payment_service import PaymentService
from app.services.scholarship_service import ScholarshipService
from app.services.student_service import StudentService
from app.services.user_service import UserService

router = APIRouter()


# ==================== Course Management ====================

@router.get("/courses", response_model=PaginatedResponse[CoursePublic])
async def admin_list_courses(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    published_only: bool = Query(default=False),
    service: CourseService = Depends(get_course_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[CoursePublic]:
    """List all courses (admin only)."""
    if published_only:
        courses, total = await service.list_published_courses(skip=skip, limit=limit)
    else:
        courses, total = await service.list_courses(skip=skip, limit=limit)
    
    return PaginatedResponse(
        items=[
            CoursePublic(
                id=c.id,
                title=c.title,
                description=c.description,
                instructor_id=c.instructor_id,
                duration_hours=c.duration_hours,
                price=c.price,
                is_published=c.is_published,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in courses
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/courses", response_model=CoursePublic, status_code=status.HTTP_201_CREATED)
async def admin_create_course(
    payload: CourseCreate,
    service: CourseService = Depends(get_course_service),
    admin_user: User = Depends(get_admin_user),
) -> CoursePublic:
    """Create a new course (admin only)."""
    course = await service.create_course(payload)
    return CoursePublic(
        id=course.id,
        title=course.title,
        description=course.description,
        instructor_id=course.instructor_id,
        duration_hours=course.duration_hours,
        price=course.price,
        is_published=course.is_published,
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


@router.patch("/courses/{course_id}", response_model=CoursePublic)
async def admin_update_course(
    course_id: str,
    payload: CourseUpdate,
    service: CourseService = Depends(get_course_service),
    admin_user: User = Depends(get_admin_user),
) -> CoursePublic:
    """Update a course (admin only)."""
    course = await service.update_course(course_id, payload)
    return CoursePublic(
        id=course.id,
        title=course.title,
        description=course.description,
        instructor_id=course.instructor_id,
        duration_hours=course.duration_hours,
        price=course.price,
        is_published=course.is_published,
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


@router.delete("/courses/{course_id}")
async def admin_delete_course(
    course_id: str,
    service: CourseService = Depends(get_course_service),
    admin_user: User = Depends(get_admin_user),
) -> Response:
    """Delete a course (admin only)."""
    await service.delete_course(course_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==================== User Management ====================

@router.get("/users", response_model=PaginatedResponse[UserPublic])
async def admin_list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: UserService = Depends(get_user_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[UserPublic]:
    """List all users (admin only)."""
    users, total = await service.list_users(skip=skip, limit=limit)
    
    return PaginatedResponse(
        items=[
            UserPublic(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                is_active=u.is_active,
                role=u.role,
                created_at=u.created_at,
            )
            for u in users
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.patch("/users/{user_id}", response_model=UserPublic)
async def admin_update_user(
    user_id: str,
    payload: UserUpdate,
    service: UserService = Depends(get_user_service),
    admin_user: User = Depends(get_admin_user),
) -> UserPublic:
    """Update a user (admin only)."""
    user = await service.update_user(user_id, payload)
    return UserPublic(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        role=user.role,
        created_at=user.created_at,
    )


@router.delete("/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    service: UserService = Depends(get_user_service),
    admin_user: User = Depends(get_admin_user),
) -> Response:
    """Delete a user (admin only)."""
    await service.delete_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==================== Instructor Management ====================

@router.get("/instructors", response_model=PaginatedResponse[InstructorPublic])
async def admin_list_instructors(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: InstructorService = Depends(get_instructor_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[InstructorPublic]:
    """List all instructors (admin only)."""
    instructors, total = await service.list_instructors(skip=skip, limit=limit)
    
    return PaginatedResponse(
        items=[
            InstructorPublic(
                id=i.id,
                user_id=i.user_id,
                bio=i.bio,
                specialization=i.specialization,
                years_of_experience=i.years_of_experience,
                is_active=i.is_active,
                created_at=i.created_at,
                updated_at=i.updated_at,
            )
            for i in instructors
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/instructors", response_model=InstructorPublic, status_code=status.HTTP_201_CREATED)
async def admin_create_instructor(
    payload: InstructorCreate,
    service: InstructorService = Depends(get_instructor_service),
    admin_user: User = Depends(get_admin_user),
) -> InstructorPublic:
    """Create a new instructor (admin only)."""
    instructor = await service.create_instructor(payload)
    return InstructorPublic(
        id=instructor.id,
        user_id=instructor.user_id,
        bio=instructor.bio,
        specialization=instructor.specialization,
        years_of_experience=instructor.years_of_experience,
        is_active=instructor.is_active,
        created_at=instructor.created_at,
        updated_at=instructor.updated_at,
    )


@router.patch("/instructors/{instructor_id}", response_model=InstructorPublic)
async def admin_update_instructor(
    instructor_id: str,
    payload: InstructorUpdate,
    service: InstructorService = Depends(get_instructor_service),
    admin_user: User = Depends(get_admin_user),
) -> InstructorPublic:
    """Update an instructor (admin only)."""
    instructor = await service.update_instructor(instructor_id, payload)
    return InstructorPublic(
        id=instructor.id,
        user_id=instructor.user_id,
        bio=instructor.bio,
        specialization=instructor.specialization,
        years_of_experience=instructor.years_of_experience,
        is_active=instructor.is_active,
        created_at=instructor.created_at,
        updated_at=instructor.updated_at,
    )


@router.delete("/instructors/{instructor_id}")
async def admin_delete_instructor(
    instructor_id: str,
    service: InstructorService = Depends(get_instructor_service),
    admin_user: User = Depends(get_admin_user),
) -> Response:
    """Delete an instructor (admin only)."""
    await service.delete_instructor(instructor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==================== Student Management ====================

@router.get("/students", response_model=PaginatedResponse[StudentPublic])
async def admin_list_students(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: StudentService = Depends(get_student_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[StudentPublic]:
    """List all students (admin only)."""
    students, total = await service.list_students(skip=skip, limit=limit)
    
    return PaginatedResponse(
        items=[
            StudentPublic(
                id=s.id,
                user_id=s.user_id,
                enrollment_date=s.enrollment_date,
                enrolled_courses=s.enrolled_courses,
                is_active=s.is_active,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in students
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/students", response_model=StudentPublic, status_code=status.HTTP_201_CREATED)
async def admin_create_student(
    payload: StudentCreate,
    service: StudentService = Depends(get_student_service),
    admin_user: User = Depends(get_admin_user),
) -> StudentPublic:
    """Create a new student (admin only)."""
    student = await service.create_student(payload)
    return StudentPublic(
        id=student.id,
        user_id=student.user_id,
        enrollment_date=student.enrollment_date,
        enrolled_courses=student.enrolled_courses,
        is_active=student.is_active,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


@router.patch("/students/{student_id}", response_model=StudentPublic)
async def admin_update_student(
    student_id: str,
    payload: StudentUpdate,
    service: StudentService = Depends(get_student_service),
    admin_user: User = Depends(get_admin_user),
) -> StudentPublic:
    """Update a student (admin only)."""
    student = await service.update_student(student_id, payload)
    return StudentPublic(
        id=student.id,
        user_id=student.user_id,
        enrollment_date=student.enrollment_date,
        enrolled_courses=student.enrolled_courses,
        is_active=student.is_active,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


@router.delete("/students/{student_id}")
async def admin_delete_student(
    student_id: str,
    service: StudentService = Depends(get_student_service),
    admin_user: User = Depends(get_admin_user),
) -> Response:
    """Delete a student (admin only)."""
    await service.delete_student(student_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==================== Scholarship Management ====================

@router.get("/scholarships", response_model=PaginatedResponse[ScholarshipPublic])
async def admin_list_scholarships(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    student_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    service: ScholarshipService = Depends(get_scholarship_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[ScholarshipPublic]:
    """List all scholarships (admin only)."""
    scholarships, total = await service.list_scholarships(
        skip=skip,
        limit=limit,
        student_id=student_id,
        status=status,
    )
    
    return PaginatedResponse(
        items=[
            ScholarshipPublic(
                id=s.id,
                student_id=s.student_id,
                course_id=s.course_id,
                enrollment_id=s.enrollment_id,
                scholarship_type=s.scholarship_type,
                amount=s.amount,
                status=s.status,
                start_date=s.start_date,
                end_date=s.end_date,
                termination_reason=s.termination_reason,
                terminated_at=s.terminated_at,
                terminated_by=s.terminated_by,
                max_absences_per_month=s.max_absences_per_month,
                current_month_absences=s.current_month_absences,
                current_month_start=s.current_month_start,
                notes=s.notes,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in scholarships
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/scholarships", response_model=ScholarshipPublic, status_code=status.HTTP_201_CREATED)
async def admin_create_scholarship(
    payload: ScholarshipCreate,
    service: ScholarshipService = Depends(get_scholarship_service),
    admin_user: User = Depends(get_admin_user),
) -> ScholarshipPublic:
    """Create a new scholarship (admin only)."""
    scholarship = await service.create_scholarship(payload)
    return ScholarshipPublic(
        id=scholarship.id,
        student_id=scholarship.student_id,
        course_id=scholarship.course_id,
        enrollment_id=scholarship.enrollment_id,
        scholarship_type=scholarship.scholarship_type,
        amount=scholarship.amount,
        status=scholarship.status,
        start_date=scholarship.start_date,
        end_date=scholarship.end_date,
        termination_reason=scholarship.termination_reason,
        terminated_at=scholarship.terminated_at,
        terminated_by=scholarship.terminated_by,
        max_absences_per_month=scholarship.max_absences_per_month,
        current_month_absences=scholarship.current_month_absences,
        current_month_start=scholarship.current_month_start,
        notes=scholarship.notes,
        created_at=scholarship.created_at,
        updated_at=scholarship.updated_at,
    )


@router.patch("/scholarships/{scholarship_id}", response_model=ScholarshipPublic)
async def admin_update_scholarship(
    scholarship_id: str,
    payload: ScholarshipUpdate,
    service: ScholarshipService = Depends(get_scholarship_service),
    admin_user: User = Depends(get_admin_user),
) -> ScholarshipPublic:
    """Update a scholarship (admin only)."""
    scholarship = await service.update_scholarship(scholarship_id, payload)
    return ScholarshipPublic(
        id=scholarship.id,
        student_id=scholarship.student_id,
        course_id=scholarship.course_id,
        enrollment_id=scholarship.enrollment_id,
        scholarship_type=scholarship.scholarship_type,
        amount=scholarship.amount,
        status=scholarship.status,
        start_date=scholarship.start_date,
        end_date=scholarship.end_date,
        termination_reason=scholarship.termination_reason,
        terminated_at=scholarship.terminated_at,
        terminated_by=scholarship.terminated_by,
        max_absences_per_month=scholarship.max_absences_per_month,
        current_month_absences=scholarship.current_month_absences,
        current_month_start=scholarship.current_month_start,
        notes=scholarship.notes,
        created_at=scholarship.created_at,
        updated_at=scholarship.updated_at,
    )


@router.post("/scholarships/{scholarship_id}/terminate", response_model=ScholarshipPublic)
async def admin_terminate_scholarship(
    scholarship_id: str,
    reason: str = Query(..., description="Termination reason"),
    service: ScholarshipService = Depends(get_scholarship_service),
    admin_user: User = Depends(get_admin_user),
) -> ScholarshipPublic:
    """Terminate a scholarship (admin only)."""
    scholarship = await service.terminate_scholarship(scholarship_id, reason, admin_user.id)
    return ScholarshipPublic(
        id=scholarship.id,
        student_id=scholarship.student_id,
        course_id=scholarship.course_id,
        enrollment_id=scholarship.enrollment_id,
        scholarship_type=scholarship.scholarship_type,
        amount=scholarship.amount,
        status=scholarship.status,
        start_date=scholarship.start_date,
        end_date=scholarship.end_date,
        termination_reason=scholarship.termination_reason,
        terminated_at=scholarship.terminated_at,
        terminated_by=scholarship.terminated_by,
        max_absences_per_month=scholarship.max_absences_per_month,
        current_month_absences=scholarship.current_month_absences,
        current_month_start=scholarship.current_month_start,
        notes=scholarship.notes,
        created_at=scholarship.created_at,
        updated_at=scholarship.updated_at,
    )


@router.delete("/scholarships/{scholarship_id}")
async def admin_delete_scholarship(
    scholarship_id: str,
    service: ScholarshipService = Depends(get_scholarship_service),
    admin_user: User = Depends(get_admin_user),
) -> Response:
    """Delete a scholarship (admin only)."""
    await service.delete_scholarship(scholarship_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==================== Attendance Management ====================

@router.post("/attendance", response_model=AttendancePublic, status_code=status.HTTP_201_CREATED)
async def admin_create_attendance(
    payload: AttendanceCreate,
    service: AttendanceService = Depends(get_attendance_service),
    admin_user: User = Depends(get_admin_user),
) -> AttendancePublic:
    """Mark attendance for a student (admin only)."""
    attendance = await service.create_attendance(payload)
    return AttendancePublic(
        id=attendance.id,
        student_id=attendance.student_id,
        course_id=attendance.course_id,
        enrollment_id=attendance.enrollment_id,
        date=attendance.date,
        status=attendance.status,
        marked_by=attendance.marked_by,
        notes=attendance.notes,
        absence_reason=attendance.absence_reason,
        absence_reason_submitted_at=attendance.absence_reason_submitted_at,
        is_excused=attendance.is_excused,
        created_at=attendance.created_at,
        updated_at=attendance.updated_at,
    )


@router.patch("/attendance/{attendance_id}", response_model=AttendancePublic)
async def admin_update_attendance(
    attendance_id: str,
    payload: AttendanceUpdate,
    service: AttendanceService = Depends(get_attendance_service),
    admin_user: User = Depends(get_admin_user),
) -> AttendancePublic:
    """Update attendance record (admin only)."""
    attendance = await service.update_attendance(attendance_id, payload)
    return AttendancePublic(
        id=attendance.id,
        student_id=attendance.student_id,
        course_id=attendance.course_id,
        enrollment_id=attendance.enrollment_id,
        date=attendance.date,
        status=attendance.status,
        marked_by=attendance.marked_by,
        notes=attendance.notes,
        absence_reason=attendance.absence_reason,
        absence_reason_submitted_at=attendance.absence_reason_submitted_at,
        is_excused=attendance.is_excused,
        created_at=attendance.created_at,
        updated_at=attendance.updated_at,
    )
# ==================== Course Materials Management ====================

@router.get("/courses/{course_id}/materials", response_model=PaginatedResponse[CourseMaterialPublic])
async def admin_list_materials(
    course_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: CourseMaterialService = Depends(get_course_material_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[CourseMaterialPublic]:
    """List all materials for a course (admin only)."""
    materials = await service.get_course_materials(course_id, published_only=False)
    total = len(materials)
    paginated = materials[skip:skip + limit]
    
    return PaginatedResponse(
        items=[
            CourseMaterialPublic(
                id=m.id,
                course_id=m.course_id,
                title=m.title,
                description=m.description,
                material_type=m.material_type,
                content_url=m.content_url,
                file_path=m.file_path,
                file_size=m.file_size,
                duration_minutes=m.duration_minutes,
                order=m.order,
                is_published=m.is_published,
                is_required=m.is_required,
                created_by=m.created_by,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
            for m in paginated
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/materials", response_model=CourseMaterialPublic, status_code=status.HTTP_201_CREATED)
async def admin_create_material(
    payload: CourseMaterialCreate,
    service: CourseMaterialService = Depends(get_course_material_service),
    admin_user: User = Depends(get_admin_user),
) -> CourseMaterialPublic:
    """Create a new course material (admin only)."""
    material = await service.create_material(payload, admin_user.id)
    return CourseMaterialPublic(
        id=material.id,
        course_id=material.course_id,
        title=material.title,
        description=material.description,
        material_type=material.material_type,
        content_url=material.content_url,
        file_path=material.file_path,
        file_size=material.file_size,
        duration_minutes=material.duration_minutes,
        order=material.order,
        is_published=material.is_published,
        is_required=material.is_required,
        created_by=material.created_by,
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


@router.patch("/materials/{material_id}", response_model=CourseMaterialPublic)
async def admin_update_material(
    material_id: str,
    payload: CourseMaterialUpdate,
    service: CourseMaterialService = Depends(get_course_material_service),
    admin_user: User = Depends(get_admin_user),
) -> CourseMaterialPublic:
    """Update a course material (admin only)."""
    material = await service.update_material(material_id, payload)
    return CourseMaterialPublic(
        id=material.id,
        course_id=material.course_id,
        title=material.title,
        description=material.description,
        material_type=material.material_type,
        content_url=material.content_url,
        file_path=material.file_path,
        file_size=material.file_size,
        duration_minutes=material.duration_minutes,
        order=material.order,
        is_published=material.is_published,
        is_required=material.is_required,
        created_by=material.created_by,
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


@router.delete("/materials/{material_id}")
async def admin_delete_material(
    material_id: str,
    service: CourseMaterialService = Depends(get_course_material_service),
    admin_user: User = Depends(get_admin_user),
) -> Response:
    """Delete a course material (admin only)."""
    await service.delete_material(material_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==================== Assignment Management ====================

@router.get("/courses/{course_id}/assignments", response_model=PaginatedResponse[AssignmentPublic])
async def admin_list_assignments(
    course_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: AssignmentService = Depends(get_assignment_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[AssignmentPublic]:
    """List all assignments for a course (admin only)."""
    assignments = await service.get_course_assignments(course_id, published_only=False)
    total = len(assignments)
    paginated = assignments[skip:skip + limit]
    
    return PaginatedResponse(
        items=[
            AssignmentPublic(
                id=a.id,
                course_id=a.course_id,
                title=a.title,
                description=a.description,
                instructions=a.instructions,
                due_date=a.due_date,
                max_marks=a.max_marks,
                assignment_type=a.assignment_type,
                is_published=a.is_published,
                created_by=a.created_by,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in paginated
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/assignments", response_model=AssignmentPublic, status_code=status.HTTP_201_CREATED)
async def admin_create_assignment(
    payload: AssignmentCreate,
    service: AssignmentService = Depends(get_assignment_service),
    admin_user: User = Depends(get_admin_user),
) -> AssignmentPublic:
    """Create a new assignment (admin only)."""
    assignment = await service.create_assignment(payload, admin_user.id)
    return AssignmentPublic(
        id=assignment.id,
        course_id=assignment.course_id,
        title=assignment.title,
        description=assignment.description,
        instructions=assignment.instructions,
        due_date=assignment.due_date,
        max_marks=assignment.max_marks,
        assignment_type=assignment.assignment_type,
        is_published=assignment.is_published,
        created_by=assignment.created_by,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


@router.patch("/assignments/{assignment_id}", response_model=AssignmentPublic)
async def admin_update_assignment(
    assignment_id: str,
    payload: AssignmentUpdate,
    service: AssignmentService = Depends(get_assignment_service),
    admin_user: User = Depends(get_admin_user),
) -> AssignmentPublic:
    """Update an assignment (admin only)."""
    assignment = await service.update_assignment(assignment_id, payload)
    return AssignmentPublic(
        id=assignment.id,
        course_id=assignment.course_id,
        title=assignment.title,
        description=assignment.description,
        instructions=assignment.instructions,
        due_date=assignment.due_date,
        max_marks=assignment.max_marks,
        assignment_type=assignment.assignment_type,
        is_published=assignment.is_published,
        created_by=assignment.created_by,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


@router.get("/assignments/{assignment_id}/submissions", response_model=list[AssignmentSubmissionPublic])
async def admin_get_submissions(
    assignment_id: str,
    service: AssignmentService = Depends(get_assignment_service),
    admin_user: User = Depends(get_admin_user),
) -> list[AssignmentSubmissionPublic]:
    """Get all submissions for an assignment (admin only)."""
    submissions = await service.get_assignment_submissions(assignment_id)
    return [
        AssignmentSubmissionPublic(
            id=s.id,
            assignment_id=s.assignment_id,
            student_id=s.student_id,
            course_id=s.course_id,
            enrollment_id=s.enrollment_id,
            submission_text=s.submission_text,
            file_urls=s.file_urls,
            submitted_at=s.submitted_at,
            status=s.status,
            marks_obtained=s.marks_obtained,
            feedback=s.feedback,
            graded_by=s.graded_by,
            graded_at=s.graded_at,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in submissions
    ]


@router.post("/submissions/{submission_id}/grade", response_model=AssignmentSubmissionPublic)
async def admin_grade_submission(
    submission_id: str,
    marks_obtained: float = Query(..., ge=0),
    feedback: str | None = Query(default=None),
    service: AssignmentService = Depends(get_assignment_service),
    admin_user: User = Depends(get_admin_user),
) -> AssignmentSubmissionPublic:
    """Grade an assignment submission (admin only)."""
    submission = await service.grade_submission(submission_id, marks_obtained, feedback, admin_user.id)
    return AssignmentSubmissionPublic(
        id=submission.id,
        assignment_id=submission.assignment_id,
        student_id=submission.student_id,
        course_id=submission.course_id,
        enrollment_id=submission.enrollment_id,
        submission_text=submission.submission_text,
        file_urls=submission.file_urls,
        submitted_at=submission.submitted_at,
        status=submission.status,
        marks_obtained=submission.marks_obtained,
        feedback=submission.feedback,
        graded_by=submission.graded_by,
        graded_at=submission.graded_at,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


@router.delete("/assignments/{assignment_id}")
async def admin_delete_assignment(
    assignment_id: str,
    service: AssignmentService = Depends(get_assignment_service),
    admin_user: User = Depends(get_admin_user),
) -> Response:
    """Delete an assignment (admin only)."""
    await service.delete_assignment(assignment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==================== Live Sessions Management ====================

@router.get("/courses/{course_id}/sessions", response_model=PaginatedResponse[LiveSessionPublic])
async def admin_list_sessions(
    course_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: LiveSessionService = Depends(get_live_session_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[LiveSessionPublic]:
    """List all sessions for a course (admin only)."""
    sessions = await service.get_course_sessions(course_id)
    total = len(sessions)
    paginated = sessions[skip:skip + limit]
    
    return PaginatedResponse(
        items=[
            LiveSessionPublic(
                id=s.id,
                course_id=s.course_id,
                title=s.title,
                description=s.description,
                session_type=s.session_type,
                start_time=s.start_time,
                end_time=s.end_time,
                meeting_link=s.meeting_link,
                location=s.location,
                instructor_id=s.instructor_id,
                max_participants=s.max_participants,
                recording_url=s.recording_url,
                is_recorded=s.is_recorded,
                status=s.status,
                created_by=s.created_by,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in paginated
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/sessions", response_model=LiveSessionPublic, status_code=status.HTTP_201_CREATED)
async def admin_create_session(
    payload: LiveSessionCreate,
    service: LiveSessionService = Depends(get_live_session_service),
    admin_user: User = Depends(get_admin_user),
) -> LiveSessionPublic:
    """Create a new live session (admin only)."""
    session = await service.create_session(payload, admin_user.id)
    return LiveSessionPublic(
        id=session.id,
        course_id=session.course_id,
        title=session.title,
        description=session.description,
        session_type=session.session_type,
        start_time=session.start_time,
        end_time=session.end_time,
        meeting_link=session.meeting_link,
        location=session.location,
        instructor_id=session.instructor_id,
        max_participants=session.max_participants,
        recording_url=session.recording_url,
        is_recorded=session.is_recorded,
        status=session.status,
        created_by=session.created_by,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.patch("/sessions/{session_id}", response_model=LiveSessionPublic)
async def admin_update_session(
    session_id: str,
    payload: LiveSessionUpdate,
    service: LiveSessionService = Depends(get_live_session_service),
    admin_user: User = Depends(get_admin_user),
) -> LiveSessionPublic:
    """Update a live session (admin only)."""
    session = await service.update_session(session_id, payload)
    return LiveSessionPublic(
        id=session.id,
        course_id=session.course_id,
        title=session.title,
        description=session.description,
        session_type=session.session_type,
        start_time=session.start_time,
        end_time=session.end_time,
        meeting_link=session.meeting_link,
        location=session.location,
        instructor_id=session.instructor_id,
        max_participants=session.max_participants,
        recording_url=session.recording_url,
        is_recorded=session.is_recorded,
        status=session.status,
        created_by=session.created_by,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete("/sessions/{session_id}")
async def admin_delete_session(
    session_id: str,
    service: LiveSessionService = Depends(get_live_session_service),
    admin_user: User = Depends(get_admin_user),
) -> Response:
    """Delete a live session (admin only)."""
    await service.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==================== Announcement Management ====================

@router.get("/announcements", response_model=PaginatedResponse[AnnouncementPublic])
async def admin_list_announcements(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    course_id: str | None = Query(default=None),
    service: AnnouncementService = Depends(get_announcement_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[AnnouncementPublic]:
    """List all announcements (admin only)."""
    announcements = await service.get_course_announcements(course_id, published_only=False)
    total = len(announcements)
    paginated = announcements[skip:skip + limit]
    
    return PaginatedResponse(
        items=[
            AnnouncementPublic(
                id=a.id,
                course_id=a.course_id,
                title=a.title,
                content=a.content,
                priority=a.priority,
                is_published=a.is_published,
                published_at=a.published_at,
                expires_at=a.expires_at,
                created_by=a.created_by,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in paginated
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/announcements", response_model=AnnouncementPublic, status_code=status.HTTP_201_CREATED)
async def admin_create_announcement(
    payload: AnnouncementCreate,
    service: AnnouncementService = Depends(get_announcement_service),
    admin_user: User = Depends(get_admin_user),
) -> AnnouncementPublic:
    """Create a new announcement (admin only)."""
    announcement = await service.create_announcement(payload, admin_user.id)
    return AnnouncementPublic(
        id=announcement.id,
        course_id=announcement.course_id,
        title=announcement.title,
        content=announcement.content,
        priority=announcement.priority,
        is_published=announcement.is_published,
        published_at=announcement.published_at,
        expires_at=announcement.expires_at,
        created_by=announcement.created_by,
        created_at=announcement.created_at,
        updated_at=announcement.updated_at,
    )


@router.patch("/announcements/{announcement_id}", response_model=AnnouncementPublic)
async def admin_update_announcement(
    announcement_id: str,
    payload: AnnouncementUpdate,
    service: AnnouncementService = Depends(get_announcement_service),
    admin_user: User = Depends(get_admin_user),
) -> AnnouncementPublic:
    """Update an announcement (admin only)."""
    announcement = await service.update_announcement(announcement_id, payload)
    return AnnouncementPublic(
        id=announcement.id,
        course_id=announcement.course_id,
        title=announcement.title,
        content=announcement.content,
        priority=announcement.priority,
        is_published=announcement.is_published,
        published_at=announcement.published_at,
        expires_at=announcement.expires_at,
        created_by=announcement.created_by,
        created_at=announcement.created_at,
        updated_at=announcement.updated_at,
    )


@router.delete("/announcements/{announcement_id}")
async def admin_delete_announcement(
    announcement_id: str,
    service: AnnouncementService = Depends(get_announcement_service),
    admin_user: User = Depends(get_admin_user),
) -> Response:
    """Delete an announcement (admin only)."""
    await service.delete_announcement(announcement_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==================== Payment Management ====================

@router.get("/payments", response_model=PaginatedResponse[PaymentPublic])
async def admin_list_payments(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    student_id: str | None = Query(default=None),
    course_id: str | None = Query(default=None),
    service: PaymentService = Depends(get_payment_service),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[PaymentPublic]:
    """List all payments (admin only)."""
    payments, total = await service.list_payments(
        skip=skip,
        limit=limit,
        student_id=student_id,
        course_id=course_id,
    )
    
    return PaginatedResponse(
        items=[
            PaymentPublic(
                id=p.id,
                student_id=p.student_id,
                course_id=p.course_id,
                enrollment_id=p.enrollment_id,
                amount=p.amount,
                currency=p.currency,
                payment_method=p.payment_method,
                payment_status=p.payment_status,
                transaction_id=p.transaction_id,
                invoice_number=p.invoice_number,
                invoice_url=p.invoice_url,
                payment_date=p.payment_date,
                due_date=p.due_date,
                scholarship_discount=p.scholarship_discount,
                notes=p.notes,
                created_by=p.created_by,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in payments
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/payments", response_model=PaymentPublic, status_code=status.HTTP_201_CREATED)
async def admin_create_payment(
    payload: PaymentCreate,
    service: PaymentService = Depends(get_payment_service),
    admin_user: User = Depends(get_admin_user),
) -> PaymentPublic:
    """Create a new payment record (admin only)."""
    payment = await service.create_payment(payload, admin_user.id)
    return PaymentPublic(
        id=payment.id,
        student_id=payment.student_id,
        course_id=payment.course_id,
        enrollment_id=payment.enrollment_id,
        amount=payment.amount,
        currency=payment.currency,
        payment_method=payment.payment_method,
        payment_status=payment.payment_status,
        transaction_id=payment.transaction_id,
        invoice_number=payment.invoice_number,
        invoice_url=payment.invoice_url,
        payment_date=payment.payment_date,
        due_date=payment.due_date,
        scholarship_discount=payment.scholarship_discount,
        notes=payment.notes,
        created_by=payment.created_by,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


@router.patch("/payments/{payment_id}", response_model=PaymentPublic)
async def admin_update_payment(
    payment_id: str,
    payload: PaymentUpdate,
    service: PaymentService = Depends(get_payment_service),
    admin_user: User = Depends(get_admin_user),
) -> PaymentPublic:
    """Update a payment (admin only)."""
    payment = await service.update_payment(payment_id, payload)
    return PaymentPublic(
        id=payment.id,
        student_id=payment.student_id,
        course_id=payment.course_id,
        enrollment_id=payment.enrollment_id,
        amount=payment.amount,
        currency=payment.currency,
        payment_method=payment.payment_method,
        payment_status=payment.payment_status,
        transaction_id=payment.transaction_id,
        invoice_number=payment.invoice_number,
        invoice_url=payment.invoice_url,
        payment_date=payment.payment_date,
        due_date=payment.due_date,
        scholarship_discount=payment.scholarship_discount,
        notes=payment.notes,
        created_by=payment.created_by,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


# ==================== Enrollment Verification ====================

@router.patch("/enrollments/{enrollment_id}/verify", response_model=EnrollmentPublic)
async def admin_verify_enrollment(
    enrollment_id: str,
    admin_user: User = Depends(get_admin_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    notification_service: NotificationService = Depends(get_notification_service),
) -> EnrollmentPublic:
    """Verify enrollment payment and generate enrollment card (admin only)."""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"[VERIFY] Starting verification for enrollment {enrollment_id} by admin {admin_user.id}")
        
        from datetime import datetime, timezone
        # EnrollmentCardService import removed - causes NumPy/PIL crash on Windows
        # from app.services.enrollment_card_service import EnrollmentCardService
        
        # Get enrollment
        logger.info(f"[VERIFY] Step 1: Fetching enrollment {enrollment_id}")
        enrollment = await enrollment_repo.get_by_id(enrollment_id)
        if not enrollment:
            logger.error(f"[VERIFY] Enrollment {enrollment_id} not found")
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("Enrollment not found")
        logger.info(f"[VERIFY] Step 1: Success - Enrollment found: {enrollment.id}")
        
        # Check if payment receipt is uploaded
        logger.info(f"[VERIFY] Step 2: Checking payment receipt")
        if not enrollment.payment_receipt_url:
            logger.warning(f"[VERIFY] No payment receipt URL for enrollment {enrollment_id}")
            from app.utils.exceptions import AppError
            raise AppError("Cannot verify enrollment. Payment receipt must be uploaded by the student first.")
        logger.info(f"[VERIFY] Step 2: Success - Payment receipt found: {enrollment.payment_receipt_url}")
        
        # If payment status is not paid, automatically set it to paid when verifying
        # (Admin verification implies payment confirmation)
        logger.info(f"[VERIFY] Step 3: Processing payment status")
        payment_status = enrollment.payment_status
        payment_date = enrollment.payment_date
        if payment_status != "paid":
            logger.info(f"[VERIFY] Payment status is {payment_status}, setting to paid")
            payment_status = "paid"
            payment_date = datetime.now(timezone.utc)
        logger.info(f"[VERIFY] Step 3: Success - Payment status: {payment_status}")
        
        # Get course and student user info
        logger.info(f"[VERIFY] Step 4: Fetching course {enrollment.course_id}")
        course = await course_repo.get_by_id(enrollment.course_id)
        if not course:
            logger.error(f"[VERIFY] Course {enrollment.course_id} not found")
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("Course not found")
        logger.info(f"[VERIFY] Step 4: Success - Course found: {course.title}")
        
        logger.info(f"[VERIFY] Step 5: Fetching student {enrollment.student_id}")
        student = await student_repo.get_by_id(enrollment.student_id)
        if not student:
            logger.error(f"[VERIFY] Student {enrollment.student_id} not found")
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("Student not found")
        logger.info(f"[VERIFY] Step 5: Success - Student found: {student.id}")
        
        logger.info(f"[VERIFY] Step 6: Fetching user {student.user_id}")
        student_user = await user_repo.get_by_id(student.user_id)
        if not student_user:
            logger.error(f"[VERIFY] User {student.user_id} not found")
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("User not found")
        logger.info(f"[VERIFY] Step 6: Success - User found: {student_user.email}")
        
        # Generate enrollment card PDF with student photo and details
        logger.info(f"[VERIFY] Step 7: Generating enrollment card")
        card_path = None
        try:
            from app.services.enrollment_card_service import EnrollmentCardService

            card_service = EnrollmentCardService()
            card_path, _ = card_service.generate_enrollment_card(
                enrollment=enrollment,
                student=student_user,
                course=course,
            )
            logger.info(f"[VERIFY] Step 7: Card generated at {card_path}")
        except Exception as card_err:
            logger.error(f"[VERIFY] Step 7: Card generation failed (verification continues): {card_err}", exc_info=True)
            card_path = None
        
        # Update enrollment with verification
        logger.info(f"[VERIFY] Step 8: Preparing update data")
        now = datetime.now(timezone.utc)
        from bson import ObjectId
        try:
            admin_user_id_obj = ObjectId(admin_user.id)
            logger.info(f"[VERIFY] Step 8: Admin user ID converted to ObjectId: {admin_user_id_obj}")
        except Exception as e:
            logger.error(f"[VERIFY] Step 8: Failed to convert admin_user.id to ObjectId: {admin_user.id}, error: {e}")
            raise
        
        update_data = {
            "verified_by_admin": True,
            "verified_at": now,
            "verified_by": admin_user_id_obj,
            "status": "active",  # Activate enrollment after verification
            "payment_status": payment_status,  # Set to paid if not already
            "payment_date": payment_date,  # Set payment date if marking as paid
            "updated_at": now,
        }
        
        # Only set card URL if generation was successful
        if card_path:
            update_data["enrollment_card_url"] = card_path
        
        logger.info(f"[VERIFY] Step 9: Updating enrollment in database")
        logger.info(f"[VERIFY] Step 9: Update data keys: {list(update_data.keys())}")
        updated = await enrollment_repo.update(enrollment_id, update_data)
        if not updated:
            logger.error(f"[VERIFY] Step 9: Failed to update enrollment {enrollment_id}")
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("Enrollment not found")
        logger.info(f"[VERIFY] Step 9: Success - Enrollment updated")
        
        # Reload to get updated data
        logger.info(f"[VERIFY] Step 10: Reloading enrollment data")
        enrollment = await enrollment_repo.get_by_id(enrollment_id)
        if not enrollment:
            logger.error(f"[VERIFY] Step 10: Failed to reload enrollment {enrollment_id}")
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("Failed to reload enrollment")
        logger.info(f"[VERIFY] Step 10: Success - Enrollment reloaded")

        # Notify student that enrollment is verified
        try:
            await notification_service.create_enrollment_verified_notification(
                user_id=student_user.id,
                enrollment_id=enrollment.id,
                course_title=course.title,
            )
        except Exception as notify_err:
            logger.warning(f"[VERIFY] Failed to send verification notification: {notify_err}")

        logger.info(f"[VERIFY] Step 11: Building response")
        try:
            response = EnrollmentPublic(
                id=enrollment.id,
                student_id=enrollment.student_id,
                course_id=enrollment.course_id,
                enrollment_date=enrollment.enrollment_date,
                status=enrollment.status,
                payment_status=enrollment.payment_status,
                payment_date=enrollment.payment_date,
                completion_date=enrollment.completion_date,
                progress_percentage=enrollment.progress_percentage,
                class_type=enrollment.class_type,
                phone_number=enrollment.phone_number,
                address=enrollment.address,
                emergency_contact_name=enrollment.emergency_contact_name,
                emergency_contact_phone=enrollment.emergency_contact_phone,
                profile_image_url=enrollment.profile_image_url,
                enrollment_card_number=enrollment.enrollment_card_number,
                enrollment_card_url=enrollment.enrollment_card_url,
                payment_receipt_url=enrollment.payment_receipt_url,
                verified_by_admin=enrollment.verified_by_admin,
                verified_at=enrollment.verified_at,
                verified_by=enrollment.verified_by,
                created_at=enrollment.created_at,
                updated_at=enrollment.updated_at,
            )
            logger.info(f"[VERIFY] Step 11: Success - Response built")
            logger.info(f"[VERIFY] Verification completed successfully for enrollment {enrollment_id}")
            return response
        except Exception as response_error:
            logger.error(f"[VERIFY] Step 11: Failed to build response: {response_error}", exc_info=True)
            raise
    except Exception as e:
        logger.error(f"[VERIFY] CRITICAL ERROR in verification endpoint: {e}", exc_info=True)
        logger.error(f"[VERIFY] Enrollment ID: {enrollment_id}, Admin ID: {admin_user.id if admin_user else 'None'}")
        # Re-raise to let FastAPI handle it
        raise


@router.post("/enrollments/{enrollment_id}/generate-card", response_model=EnrollmentPublic)
async def admin_generate_enrollment_card(
    enrollment_id: str,
    admin_user: User = Depends(get_admin_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
) -> EnrollmentPublic:
    """Generate enrollment card PDF (admin only)."""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"[CARD] Starting card generation for enrollment {enrollment_id} by admin {admin_user.id}")
        
        # Get enrollment
        enrollment = await enrollment_repo.get_by_id(enrollment_id)
        if not enrollment:
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("Enrollment not found")
        
        # Check if enrollment is verified
        if not enrollment.verified_by_admin:
            from app.utils.exceptions import AppError
            raise AppError("Enrollment must be verified before generating card")
        
        # Get course and student user info
        course = await course_repo.get_by_id(enrollment.course_id)
        if not course:
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("Course not found")
        
        student = await student_repo.get_by_id(enrollment.student_id)
        if not student:
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("Student not found")
        
        student_user = await user_repo.get_by_id(student.user_id)
        if not student_user:
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("User not found")
        
        # Generate default card: replace student/academy/enrollment info (uses prefilled/edited data from card-form)
        logger.info(f"[CARD] Attempting to generate card")
        card_path = None
        try:
            from app.services.enrollment_card_service import EnrollmentCardService

            card_service = EnrollmentCardService()
            card_path, _ = card_service.generate_enrollment_card(
                enrollment=enrollment,
                student=student_user,
                course=course,
            )
            logger.info(f"[CARD] Success - Card generated at: {card_path}")
        except Exception as e:
            logger.error(f"[CARD] Failed to generate card: {e}", exc_info=True)
            from app.utils.exceptions import AppError
            raise AppError(detail=f"Failed to generate enrollment card: {str(e)}", status_code=500)
        
        # Update enrollment with card URL
        from datetime import datetime, timezone
        from bson import ObjectId
        update_data = {
            "enrollment_card_url": card_path,
            "updated_at": datetime.now(timezone.utc),
        }
        
        updated = await enrollment_repo.update(enrollment_id, update_data)
        if not updated:
            from app.utils.exceptions import NotFoundError
            raise NotFoundError("Failed to update enrollment")
        
        # Reload to get updated data
        enrollment = await enrollment_repo.get_by_id(enrollment_id)
        
        return EnrollmentPublic(
            id=enrollment.id,
            student_id=enrollment.student_id,
            course_id=enrollment.course_id,
            enrollment_date=enrollment.enrollment_date,
            status=enrollment.status,
            payment_status=enrollment.payment_status,
            payment_date=enrollment.payment_date,
            completion_date=enrollment.completion_date,
            progress_percentage=enrollment.progress_percentage,
            class_type=enrollment.class_type,
            phone_number=enrollment.phone_number,
            address=enrollment.address,
            emergency_contact_name=enrollment.emergency_contact_name,
            emergency_contact_phone=enrollment.emergency_contact_phone,
            profile_image_url=enrollment.profile_image_url,
            enrollment_card_number=enrollment.enrollment_card_number,
            enrollment_card_url=enrollment.enrollment_card_url,
            payment_receipt_url=enrollment.payment_receipt_url,
            verified_by_admin=enrollment.verified_by_admin,
            verified_at=enrollment.verified_at,
            verified_by=enrollment.verified_by,
            created_at=enrollment.created_at,
            updated_at=enrollment.updated_at,
        )
    except Exception as e:
        logger.error(f"[CARD] CRITICAL ERROR in card generation endpoint: {e}", exc_info=True)
        raise


@router.get("/enrollments/{enrollment_id}/card-form", response_model=EnrollmentCardForm)
async def admin_get_enrollment_card_form(
    enrollment_id: str,
    admin_user: User = Depends(get_admin_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
) -> EnrollmentCardForm:
    """Get enrollment card form data (prefill). Student-entered info plus blanks for admin to fill (admin only)."""
    from app.utils.exceptions import NotFoundError

    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if not enrollment:
        raise NotFoundError("Enrollment not found")

    course = await course_repo.get_by_id(enrollment.course_id)
    student = await student_repo.get_by_id(enrollment.student_id)
    student_user = await user_repo.get_by_id(student.user_id) if student else None

    return EnrollmentCardForm(
        enrollment_id=enrollment.id,
        student_id=enrollment.student_id,
        student_full_name=student_user.full_name if student_user else None,
        student_email=student_user.email if student_user else "",
        phone_number=enrollment.phone_number,
        address=enrollment.address,
        emergency_contact_name=enrollment.emergency_contact_name,
        emergency_contact_phone=enrollment.emergency_contact_phone,
        father_guardian_name=enrollment.father_guardian_name,
        date_of_birth=enrollment.date_of_birth,
        gender=enrollment.gender,
        profile_image_url=enrollment.profile_image_url,
        enrollment_card_number=enrollment.enrollment_card_number,
        course_id=enrollment.course_id,
        course_title=course.title if course else "",
        class_type=enrollment.class_type,
        enrollment_date=enrollment.enrollment_date,
        verified_at=enrollment.verified_at,
        enrollment_card_url=enrollment.enrollment_card_url,
        verified_by_admin=enrollment.verified_by_admin,
    )


@router.patch("/enrollments/{enrollment_id}/card-form", response_model=EnrollmentPublic)
async def admin_update_enrollment_card_form(
    enrollment_id: str,
    payload: EnrollmentCardFormUpdate,
    admin_user: User = Depends(get_admin_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
) -> EnrollmentPublic:
    """Update enrollment card info (student name, phone, address, emergency contact, profile image). Admin can add/fill missing info before generating card (admin only)."""
    from datetime import datetime, timezone

    from app.utils.exceptions import NotFoundError

    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if not enrollment:
        raise NotFoundError("Enrollment not found")

    update_data: dict = {"updated_at": datetime.now(timezone.utc)}
    if payload.phone_number is not None:
        update_data["phone_number"] = payload.phone_number
    if payload.address is not None:
        update_data["address"] = payload.address
    if payload.emergency_contact_name is not None:
        update_data["emergency_contact_name"] = payload.emergency_contact_name
    if payload.emergency_contact_phone is not None:
        update_data["emergency_contact_phone"] = payload.emergency_contact_phone
    if payload.father_guardian_name is not None:
        update_data["father_guardian_name"] = payload.father_guardian_name
    if payload.date_of_birth is not None:
        update_data["date_of_birth"] = payload.date_of_birth
    if payload.gender is not None:
        update_data["gender"] = payload.gender
    if payload.profile_image_url is not None:
        update_data["profile_image_url"] = payload.profile_image_url

    if update_data:
        updated = await enrollment_repo.update(enrollment_id, update_data)
        if not updated:
            raise NotFoundError("Enrollment not found")
        enrollment = updated

    if payload.student_full_name is not None:
        student = await student_repo.get_by_id(enrollment.student_id)
        if student:
            await user_repo.update(student.user_id, {"full_name": payload.student_full_name})
            enrollment = await enrollment_repo.get_by_id(enrollment_id) or enrollment

    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if not enrollment:
        raise NotFoundError("Enrollment not found")

    return EnrollmentPublic(
        id=enrollment.id,
        student_id=enrollment.student_id,
        course_id=enrollment.course_id,
        enrollment_date=enrollment.enrollment_date,
        status=enrollment.status,
        payment_status=enrollment.payment_status,
        payment_date=enrollment.payment_date,
        completion_date=enrollment.completion_date,
        progress_percentage=enrollment.progress_percentage,
        class_type=enrollment.class_type,
        phone_number=enrollment.phone_number,
        address=enrollment.address,
        emergency_contact_name=enrollment.emergency_contact_name,
        emergency_contact_phone=enrollment.emergency_contact_phone,
        profile_image_url=enrollment.profile_image_url,
        enrollment_card_number=enrollment.enrollment_card_number,
        enrollment_card_url=enrollment.enrollment_card_url,
        payment_receipt_url=enrollment.payment_receipt_url,
        verified_by_admin=enrollment.verified_by_admin,
        verified_at=enrollment.verified_at,
        verified_by=enrollment.verified_by,
        created_at=enrollment.created_at,
        updated_at=enrollment.updated_at,
    )


@router.get("/enrollments", response_model=PaginatedResponse[EnrollmentPublic])
async def admin_list_enrollments(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    status: str | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    verified: bool | None = Query(default=None),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    admin_user: User = Depends(get_admin_user),
) -> PaginatedResponse[EnrollmentPublic]:
    """List all enrollments (admin only)."""
    filter_dict: dict[str, any] = {}
    if status:
        filter_dict["status"] = status
    if payment_status:
        filter_dict["payment_status"] = payment_status
    if verified is not None:
        filter_dict["verified_by_admin"] = verified
    
    # Use collection directly for filtering
    cursor = enrollment_repo.collection.find(filter_dict).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    enrollments = [enrollment_repo._to_model(doc) for doc in docs]
    total = await enrollment_repo.count(filter=filter_dict)
    
    return PaginatedResponse(
        items=[
            EnrollmentPublic(
                id=e.id,
                student_id=e.student_id,
                course_id=e.course_id,
                enrollment_date=e.enrollment_date,
                status=e.status,
                payment_status=e.payment_status,
                payment_date=e.payment_date,
                completion_date=e.completion_date,
                progress_percentage=e.progress_percentage,
                class_type=e.class_type,
                phone_number=e.phone_number,
                address=e.address,
                emergency_contact_name=e.emergency_contact_name,
                emergency_contact_phone=e.emergency_contact_phone,
                profile_image_url=e.profile_image_url,
                enrollment_card_number=e.enrollment_card_number,
                enrollment_card_url=e.enrollment_card_url,
                payment_receipt_url=e.payment_receipt_url,
                verified_by_admin=e.verified_by_admin,
                verified_at=e.verified_at,
                verified_by=e.verified_by,
                created_at=e.created_at,
                updated_at=e.updated_at,
            )
            for e in enrollments
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.patch("/enrollments/{enrollment_id}/cancel", response_model=EnrollmentPublic)
async def admin_cancel_enrollment(
    enrollment_id: str,
    admin_user: User = Depends(get_admin_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
) -> EnrollmentPublic:
    """Cancel a student enrollment (admin only). Sets status to cancelled and removes course from student's enrolled list."""
    from datetime import datetime, timezone

    from app.utils.exceptions import ConflictError, NotFoundError

    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if not enrollment:
        raise NotFoundError("Enrollment not found")
    if enrollment.status == "cancelled":
        raise ConflictError("Enrollment is already cancelled")

    updated = await enrollment_repo.update(
        enrollment_id,
        {
            "status": "cancelled",
            "updated_at": datetime.now(timezone.utc),
        },
    )
    if not updated:
        raise NotFoundError("Enrollment not found")

    await student_repo.unenroll_from_course(enrollment.student_id, enrollment.course_id)

    return EnrollmentPublic(
        id=updated.id,
        student_id=updated.student_id,
        course_id=updated.course_id,
        enrollment_date=updated.enrollment_date,
        status=updated.status,
        payment_status=updated.payment_status,
        payment_date=updated.payment_date,
        completion_date=updated.completion_date,
        progress_percentage=updated.progress_percentage,
        class_type=updated.class_type,
        phone_number=updated.phone_number,
        address=updated.address,
        emergency_contact_name=updated.emergency_contact_name,
        emergency_contact_phone=updated.emergency_contact_phone,
        profile_image_url=updated.profile_image_url,
        enrollment_card_number=updated.enrollment_card_number,
        enrollment_card_url=updated.enrollment_card_url,
        payment_receipt_url=updated.payment_receipt_url,
        verified_by_admin=updated.verified_by_admin,
        verified_at=updated.verified_at,
        verified_by=updated.verified_by,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )

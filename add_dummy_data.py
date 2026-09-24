"""
Comprehensive script to add dummy data to the database.

This script adds:
1. Courses (if not already added)
2. Additional instructors
3. Multiple students
4. Enrollments
5. Results (assessments)
6. Attendance records
7. Certificates
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.core.security import hash_password
from app.repositories.user_repository import UserRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.certificate_repository import CertificateRepository


# Dummy instructors data
INSTRUCTORS_DATA = [
    {
        "email": "john.doe@bvonix.academy",
        "password": "Instructor123!",
        "full_name": "John Doe",
        "bio": "Senior Full Stack Developer with 8 years of experience in web development and cloud technologies.",
        "specialization": "Full Stack Development, Cloud Computing",
        "years_of_experience": 8,
    },
    {
        "email": "sarah.smith@bvonix.academy",
        "password": "Instructor123!",
        "full_name": "Sarah Smith",
        "bio": "AI/ML Engineer specializing in chatbot development and AI integrations. 6 years of industry experience.",
        "specialization": "AI Development, Machine Learning, Chatbot Development",
        "years_of_experience": 6,
    },
    {
        "email": "michael.chen@bvonix.academy",
        "password": "Instructor123!",
        "full_name": "Michael Chen",
        "bio": "Mobile app developer and entrepreneur. Expert in Android development and app monetization strategies.",
        "specialization": "Android Development, App Monetization, Entrepreneurship",
        "years_of_experience": 7,
    },
    {
        "email": "emily.johnson@bvonix.academy",
        "password": "Instructor123!",
        "full_name": "Emily Johnson",
        "bio": "Digital marketing expert with expertise in SEO, social media marketing, and analytics.",
        "specialization": "Digital Marketing, SEO, Social Media Marketing",
        "years_of_experience": 5,
    },
]

# Dummy students data
STUDENTS_DATA = [
    {"email": "student1@example.com", "password": "Student123!", "full_name": "Alice Williams"},
    {"email": "student2@example.com", "password": "Student123!", "full_name": "Bob Martinez"},
    {"email": "student3@example.com", "password": "Student123!", "full_name": "Charlie Brown"},
    {"email": "student4@example.com", "password": "Student123!", "full_name": "Diana Prince"},
    {"email": "student5@example.com", "password": "Student123!", "full_name": "Edward Norton"},
    {"email": "student6@example.com", "password": "Student123!", "full_name": "Fiona Green"},
    {"email": "student7@example.com", "password": "Student123!", "full_name": "George Wilson"},
    {"email": "student8@example.com", "password": "Student123!", "full_name": "Hannah Lee"},
    {"email": "student9@example.com", "password": "Student123!", "full_name": "Ian Taylor"},
    {"email": "student10@example.com", "password": "Student123!", "full_name": "Julia Roberts"},
]


async def create_instructors(db, user_repo, instructor_repo):
    """Create dummy instructors."""
    print("\n" + "=" * 60)
    print("Creating Instructors...")
    print("=" * 60)
    
    created_count = 0
    skipped_count = 0
    
    for instructor_data in INSTRUCTORS_DATA:
        email = instructor_data["email"]
        
        # Check if user exists
        existing_user = await user_repo.get_by_email(email)
        if existing_user:
            print(f"[SKIP] Instructor already exists: {email}")
            skipped_count += 1
            continue
        
        try:
            # Create user
            user = await user_repo.create_user(
                email=email,
                full_name=instructor_data["full_name"],
                hashed_password=hash_password(instructor_data["password"]),
                role="user",  # Regular user, instructor profile will be created separately
            )
            
            # Create instructor profile
            instructor = await instructor_repo.create_instructor(
                user_id=user.id,
                bio=instructor_data["bio"],
                specialization=instructor_data["specialization"],
                years_of_experience=instructor_data["years_of_experience"],
            )
            
            print(f"[OK] Created instructor: {instructor_data['full_name']} ({email})")
            created_count += 1
        except Exception as e:
            print(f"[ERROR] Failed to create instructor {email}: {e}")
    
    print(f"\nSummary: Created {created_count}, Skipped {skipped_count}")
    return created_count + skipped_count


async def create_students(db, user_repo, student_repo):
    """Create dummy students."""
    print("\n" + "=" * 60)
    print("Creating Students...")
    print("=" * 60)
    
    created_count = 0
    skipped_count = 0
    student_ids = []
    
    for student_data in STUDENTS_DATA:
        email = student_data["email"]
        
        # Check if user exists
        existing_user = await user_repo.get_by_email(email)
        if existing_user:
            print(f"[SKIP] Student already exists: {email}")
            # Get existing student profile
            existing_student = await student_repo.get_by_user_id(existing_user.id)
            if existing_student:
                student_ids.append(existing_student.id)
            skipped_count += 1
            continue
        
        try:
            # Create user
            user = await user_repo.create_user(
                email=email,
                full_name=student_data["full_name"],
                hashed_password=hash_password(student_data["password"]),
                role="user",
            )
            
            # Create student profile
            student = await student_repo.create_student(
                user_id=user.id,
                enrollment_date=datetime.now(timezone.utc) - timedelta(days=random.randint(1, 180)),
            )
            
            print(f"[OK] Created student: {student_data['full_name']} ({email})")
            student_ids.append(student.id)
            created_count += 1
        except Exception as e:
            print(f"[ERROR] Failed to create student {email}: {e}")
    
    print(f"\nSummary: Created {created_count}, Skipped {skipped_count}")
    return student_ids


async def create_enrollments(db, student_ids, course_ids, enrollment_repo):
    """Create dummy enrollments."""
    print("\n" + "=" * 60)
    print("Creating Enrollments...")
    print("=" * 60)
    
    if not student_ids or not course_ids:
        print("[SKIP] No students or courses available for enrollment")
        return []
    
    enrollment_ids = []
    created_count = 0
    skipped_count = 0
    
    # Each student enrolls in 2-4 random courses
    for student_id in student_ids:
        num_enrollments = random.randint(2, 4)
        selected_courses = random.sample(course_ids, min(num_enrollments, len(course_ids)))
        
        for course_id in selected_courses:
            # Check if enrollment already exists
            existing = await enrollment_repo.get_by_student_and_course(student_id, course_id)
            if existing:
                enrollment_ids.append(existing.id)
                skipped_count += 1
                continue
            
            try:
                # Random enrollment date (last 6 months)
                enrollment_date = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 180))
                
                # Random status
                statuses = ["active", "completed", "pending"]
                weights = [0.6, 0.2, 0.2]  # Most are active
                status = random.choices(statuses, weights=weights)[0]
                
                # Payment status
                payment_statuses = ["paid", "pending"]
                payment_status = random.choices(payment_statuses, weights=[0.8, 0.2])[0]
                
                # Progress (0-100%)
                if status == "completed":
                    progress = 100.0
                    completion_date = enrollment_date + timedelta(days=random.randint(30, 120))
                elif status == "active":
                    progress = random.uniform(10.0, 90.0)
                    completion_date = None
                else:
                    progress = random.uniform(0.0, 10.0)
                    completion_date = None
                
                # Create enrollment with basic fields
                enrollment = await enrollment_repo.create_enrollment(
                    student_id=student_id,
                    course_id=course_id,
                    payment_status=payment_status,
                )
                
                # Update with additional fields
                update_data = {
                    "enrollment_date": enrollment_date,
                    "status": status,
                    "progress_percentage": progress,
                    "updated_at": datetime.now(timezone.utc),
                }
                if completion_date:
                    update_data["completion_date"] = completion_date
                if payment_status == "paid":
                    update_data["payment_date"] = enrollment_date + timedelta(days=random.randint(0, 7))
                
                await enrollment_repo.update(enrollment.id, update_data)
                
                enrollment_ids.append(enrollment.id)
                created_count += 1
            except Exception as e:
                print(f"[ERROR] Failed to create enrollment: {e}")
    
    print(f"\nSummary: Created {created_count}, Skipped {skipped_count}")
    return enrollment_ids


async def create_results(db, enrollments, result_repo):
    """Create dummy assessment results."""
    print("\n" + "=" * 60)
    print("Creating Results...")
    print("=" * 60)
    
    if not enrollments:
        print("[SKIP] No enrollments available for results")
        return
    
    created_count = 0
    
    assessment_types = ["quiz", "assignment", "midterm", "final", "project"]
    
    for enrollment in enrollments:
        # Only create results for active or completed enrollments
        if enrollment.status not in ["active", "completed"]:
            continue
        
        # Create 2-4 assessments per enrollment
        num_assessments = random.randint(2, 4)
        selected_types = random.sample(assessment_types, min(num_assessments, len(assessment_types)))
        
        for assessment_type in selected_types:
            try:
                # Random marks (out of 100)
                marks_obtained = random.uniform(50.0, 100.0)
                total_marks = 100.0
                
                # Random assessment name
                assessment_names = {
                    "quiz": ["Quiz 1", "Quiz 2", "Weekly Quiz", "Module Quiz"],
                    "assignment": ["Assignment 1", "Project Assignment", "Homework Assignment"],
                    "midterm": ["Midterm Exam", "Midterm Assessment"],
                    "final": ["Final Exam", "Final Assessment"],
                    "project": ["Final Project", "Capstone Project", "Course Project"],
                }
                assessment_name = random.choice(assessment_names.get(assessment_type, ["Assessment"]))
                
                # Random feedback
                feedbacks = [
                    "Excellent work!",
                    "Good effort, keep it up!",
                    "Well done!",
                    "Great progress!",
                    "Needs improvement in some areas.",
                ]
                feedback = random.choice(feedbacks)
                
                # Get admin user ID for issuing results
                user_repo = UserRepository(db)
                admin_user = await user_repo.get_by_email("admin@bvonix.academy")
                issued_by = admin_user.id if admin_user else None
                
                if not issued_by:
                    continue
                
                await result_repo.create_result(
                    student_id=enrollment.student_id,
                    course_id=enrollment.course_id,
                    enrollment_id=enrollment.id,
                    assessment_type=assessment_type,
                    assessment_name=assessment_name,
                    marks_obtained=marks_obtained,
                    total_marks=total_marks,
                    feedback=feedback,
                    issued_by=issued_by,
                )
                
                created_count += 1
            except Exception as e:
                print(f"[ERROR] Failed to create result: {e}")
    
    print(f"\nSummary: Created {created_count} results")


async def create_attendance(db, enrollments, attendance_repo):
    """Create dummy attendance records."""
    print("\n" + "=" * 60)
    print("Creating Attendance Records...")
    print("=" * 60)
    
    if not enrollments:
        print("[SKIP] No enrollments available for attendance")
        return
    
    created_count = 0
    
    # Get admin user ID for marking attendance
    user_repo = UserRepository(db)
    admin_user = await user_repo.get_by_email("admin@bvonix.academy")
    marked_by = admin_user.id if admin_user else None
    
    if not marked_by:
        print("[WARNING] Admin user not found, skipping attendance records")
        return
    
    for enrollment in enrollments:
        # Only create attendance for active or completed enrollments
        if enrollment.status not in ["active", "completed"]:
            continue
        
        # Create 5-15 attendance records per enrollment
        num_records = random.randint(5, 15)
        
        for i in range(num_records):
            try:
                # Random date within last 3 months
                date = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 90))
                
                # Status (mostly present)
                statuses = ["present", "absent", "late", "excused"]
                weights = [0.7, 0.15, 0.1, 0.05]
                status = random.choices(statuses, weights=weights)[0]
                
                # Random notes (sometimes)
                notes = None
                if random.random() < 0.3:  # 30% chance
                    notes = random.choice([
                        "Participated actively in class",
                        "Asked good questions",
                        "Needs to improve participation",
                    ])
                
                await attendance_repo.create_attendance(
                    student_id=enrollment.student_id,
                    course_id=enrollment.course_id,
                    enrollment_id=enrollment.id,
                    date=date,
                    status=status,
                    marked_by=marked_by,
                    notes=notes,
                )
                
                created_count += 1
            except Exception as e:
                # Skip duplicate attendance errors
                if "duplicate" not in str(e).lower():
                    print(f"[ERROR] Failed to create attendance: {e}")
    
    print(f"\nSummary: Created {created_count} attendance records")


async def create_certificates(db, enrollments, certificate_repo):
    """Create dummy certificates for completed courses."""
    print("\n" + "=" * 60)
    print("Creating Certificates...")
    print("=" * 60)
    
    if not enrollments:
        print("[SKIP] No enrollments available for certificates")
        return
    
    created_count = 0
    
    # Get admin user ID for issuing certificates
    user_repo = UserRepository(db)
    admin_user = await user_repo.get_by_email("admin@bvonix.academy")
    issued_by = admin_user.id if admin_user else None
    
    if not issued_by:
        print("[WARNING] Admin user not found, skipping certificates")
        return
    
    # Only create certificates for completed enrollments
    completed_enrollments = [e for e in enrollments if e.status == "completed"]
    
    for enrollment in completed_enrollments:
        try:
            # Get course completion date (enrollment date + some days)
            completion_date = enrollment.enrollment_date + timedelta(days=random.randint(30, 120))
            issue_date = completion_date + timedelta(days=random.randint(1, 7))
            
            # Random grade
            grades = ["A+", "A", "A-", "B+", "B", "B-"]
            grade = random.choice(grades)
            
            # Generate certificate
            certificate = await certificate_repo.create_certificate(
                student_id=enrollment.student_id,
                course_id=enrollment.course_id,
                enrollment_id=enrollment.id,
                completion_date=completion_date,
                grade=grade,
                issued_by=issued_by,
                certificate_url=None,  # Can be added later
            )
            
            print(f"[OK] Created certificate: {certificate.certificate_number}")
            created_count += 1
        except Exception as e:
            print(f"[ERROR] Failed to create certificate: {e}")
    
    print(f"\nSummary: Created {created_count} certificates")


async def add_dummy_data():
    """Main function to add all dummy data."""
    settings = get_settings()
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongodb_db]
    
    try:
        print("=" * 60)
        print("BvoniX Academy - Dummy Data Seeding Script")
        print("=" * 60)
        
        # Initialize repositories
        user_repo = UserRepository(db)
        instructor_repo = InstructorRepository(db)
        student_repo = StudentRepository(db)
        course_repo = CourseRepository(db)
        enrollment_repo = EnrollmentRepository(db)
        result_repo = ResultRepository(db)
        attendance_repo = AttendanceRepository(db)
        certificate_repo = CertificateRepository(db)
        
        # 1. Create instructors
        await create_instructors(db, user_repo, instructor_repo)
        
        # 2. Create students
        student_ids = await create_students(db, user_repo, student_repo)
        
        # 3. Get all courses
        all_courses = await course_repo.list(skip=0, limit=1000)
        course_ids = [course.id for course in all_courses]
        
        if not course_ids:
            print("\n[WARNING] No courses found. Please run 'python add_courses.py' first.")
            print("Continuing with other data...")
        else:
            print(f"\n[INFO] Found {len(course_ids)} courses for enrollment")
        
        # 4. Create enrollments
        enrollment_ids = await create_enrollments(db, student_ids, course_ids, enrollment_repo)
        
        # 5. Get enrollment objects for results/attendance/certificates
        enrollments = []
        # Get all enrollments from the database
        all_enrollments = await enrollment_repo.list(skip=0, limit=1000)
        # Filter to only include the ones we just created
        enrollment_id_set = set(enrollment_ids)
        enrollments = [e for e in all_enrollments if e.id in enrollment_id_set]
        
        # 6. Create results
        await create_results(db, enrollments, result_repo)
        
        # 7. Create attendance
        await create_attendance(db, enrollments, attendance_repo)
        
        # 8. Create certificates
        await create_certificates(db, enrollments, certificate_repo)
        
        print("\n" + "=" * 60)
        print("[SUCCESS] Dummy data seeding completed!")
        print("=" * 60)
        print("\nYou can now:")
        print("  - Login as admin: admin@bvonix.academy / Admin123!")
        print("  - Login as student: student1@example.com / Student123!")
        print("  - Login as instructor: john.doe@bvonix.academy / Instructor123!")
        
    except Exception as e:
        print(f"\n[ERROR] Failed to seed dummy data: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(add_dummy_data())

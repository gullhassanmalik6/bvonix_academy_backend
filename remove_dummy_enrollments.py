"""
Script to remove dummy enrollment data from the database.

This script removes enrollments for students with emails matching:
- student*@example.com pattern
- Or any email containing '@example.com'
"""

import asyncio
from bson import ObjectId

from app.core.config import get_settings
from app.db.mongodb import make_client
from app.repositories.user_repository import UserRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.certificate_repository import CertificateRepository


async def remove_dummy_enrollments():
    """Remove dummy enrollments and related data."""
    settings = get_settings()
    client = make_client(settings)
    db = client[settings.mongodb_db]
    
    try:
        print("=" * 80)
        print("BvoniX Academy - Remove Dummy Enrollments")
        print("=" * 80)
        
        # Initialize repositories
        user_repo = UserRepository(db)
        student_repo = StudentRepository(db)
        enrollment_repo = EnrollmentRepository(db)
        result_repo = ResultRepository(db)
        attendance_repo = AttendanceRepository(db)
        certificate_repo = CertificateRepository(db)
        
        # Find all users with @example.com emails (dummy users)
        print("\n[1] Finding dummy users (@example.com)...")
        all_users = await user_repo.list(skip=0, limit=10000)
        dummy_users = [u for u in all_users if '@example.com' in u.email.lower()]
        
        if not dummy_users:
            print("  No dummy users found.")
            return
        
        print(f"  Found {len(dummy_users)} dummy users:")
        for user in dummy_users:
            print(f"    - {user.email} (ID: {user.id})")
        
        # Get student IDs for these users
        print("\n[2] Finding students for dummy users...")
        dummy_student_ids = []
        dummy_user_ids = [u.id for u in dummy_users]
        
        # Get all students and check their user_id
        all_students = await student_repo.list(skip=0, limit=10000)
        for student in all_students:
            if student.user_id in dummy_user_ids:
                dummy_student_ids.append(student.id)
                # Find the user
                user = next((u for u in dummy_users if u.id == student.user_id), None)
                print(f"    - Student ID: {student.id} (User: {user.email if user else 'Unknown'})")
        
        # Also find orphaned enrollments (where student doesn't exist)
        print("\n[2b] Finding orphaned enrollments (student not found)...")
        all_enrollments = await enrollment_repo.list(skip=0, limit=10000)
        orphaned_enrollments = []
        valid_enrollments = []
        
        for enrollment in all_enrollments:
            try:
                student = await student_repo.get_by_id(enrollment.student_id)
                if student:
                    user = await user_repo.get_by_id(student.user_id)
                    if user and '@example.com' in user.email.lower():
                        # This is a dummy enrollment
                        orphaned_enrollments.append(enrollment)
                    else:
                        valid_enrollments.append(enrollment)
                else:
                    # Student not found - orphaned enrollment
                    orphaned_enrollments.append(enrollment)
            except Exception:
                # Error finding student - consider orphaned
                orphaned_enrollments.append(enrollment)
        
        if not dummy_student_ids and not orphaned_enrollments:
            print("  No dummy or orphaned enrollments found.")
            print(f"  Found {len(valid_enrollments)} valid enrollments.")
            return
        
        # Combine dummy and orphaned enrollments (deduplicate by ID)
        dummy_enrollments = [e for e in all_enrollments if e.student_id in dummy_student_ids] if dummy_student_ids else []
        enrollment_ids_seen = set()
        all_dummy_enrollments = []
        for enrollment in dummy_enrollments + orphaned_enrollments:
            if enrollment.id not in enrollment_ids_seen:
                enrollment_ids_seen.add(enrollment.id)
                all_dummy_enrollments.append(enrollment)
        
        print(f"\n  Found {len(orphaned_enrollments)} orphaned enrollments")
        if dummy_enrollments:
            print(f"  Found {len(dummy_enrollments)} enrollments for dummy students")
        print(f"  Total to delete: {len(all_dummy_enrollments)}")
        print(f"  Valid enrollments to keep: {len(valid_enrollments)}")
        
        if not all_dummy_enrollments:
            print("  No enrollments to delete.")
            return
        
        # Delete related data
        print("\n[3] Deleting related data...")
        deleted_counts = {
            'results': 0,
            'attendance': 0,
            'certificates': 0,
            'enrollments': 0
        }
        
        for enrollment in all_dummy_enrollments:
            enrollment_id = enrollment.id
            
            # Delete results
            try:
                results = await result_repo.collection.find({"enrollment_id": ObjectId(enrollment_id)}).to_list(length=1000)
                for result in results:
                    await result_repo.delete(result["_id"])
                    deleted_counts['results'] += 1
            except Exception as e:
                print(f"    Error deleting results for {enrollment_id}: {e}")
            
            # Delete attendance
            try:
                attendance_records = await attendance_repo.collection.find({"enrollment_id": ObjectId(enrollment_id)}).to_list(length=1000)
                for record in attendance_records:
                    await attendance_repo.delete(record["_id"])
                    deleted_counts['attendance'] += 1
            except Exception as e:
                print(f"    Error deleting attendance for {enrollment_id}: {e}")
            
            # Delete certificates
            try:
                certificates = await certificate_repo.collection.find({"enrollment_id": ObjectId(enrollment_id)}).to_list(length=1000)
                for cert in certificates:
                    await certificate_repo.delete(cert["_id"])
                    deleted_counts['certificates'] += 1
            except Exception as e:
                print(f"    Error deleting certificates for {enrollment_id}: {e}")
            
            # Delete enrollment
            try:
                if await enrollment_repo.delete(enrollment_id):
                    deleted_counts['enrollments'] += 1
                    print(f"    Deleted enrollment: {enrollment_id}")
            except Exception as e:
                print(f"    Error deleting enrollment {enrollment_id}: {e}")
        
        print("\n" + "=" * 80)
        print("[SUCCESS] Dummy enrollment cleanup completed!")
        print("=" * 80)
        print(f"\nSummary:")
        print(f"  - Enrollments deleted: {deleted_counts['enrollments']}")
        print(f"  - Results deleted: {deleted_counts['results']}")
        print(f"  - Attendance records deleted: {deleted_counts['attendance']}")
        print(f"  - Certificates deleted: {deleted_counts['certificates']}")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n[ERROR] Failed to remove dummy enrollments: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(remove_dummy_enrollments())

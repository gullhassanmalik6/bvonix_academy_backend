"""
Disposable demo cleanup. Not a production purge.

Deletes enrollments, results, attendance, and certificates that belong to
@example.com accounts, plus enrollments whose student record is missing.
Refuses to run when APP_ENV is production or prod.
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


async def _purge_matching(repo, query: dict) -> int:
    """Delete every matching document in batches. A stuck row stops the script."""
    removed = 0
    while True:
        docs = await repo.collection.find(query).sort([("_id", 1)]).limit(100).to_list(length=100)
        if not docs:
            return removed
        progressed = 0
        for doc in docs:
            if await repo.purge_document(str(doc["_id"])):
                removed += 1
                progressed += 1
        if progressed == 0:
            raise RuntimeError("Matching rows could not be removed")


async def remove_dummy_enrollments():
    """Remove dummy enrollments and related data."""
    settings = get_settings()
    if settings.app_env.lower() in {"production", "prod"}:
        raise SystemExit(
            "Refusing to delete demo rows while APP_ENV is production. "
            "This script only removes @example.com fixture data."
        )
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
        
        # Find users with @example.com emails (dummy users), one page at a time.
        print("\n[1] Finding dummy users (@example.com)...")
        dummy_users = await user_repo.collect(
            {"email": {"$regex": "@example\\.com", "$options": "i"}},
            sort=[("email", 1)],
        )
        
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
        
        for user in dummy_users:
            student = await student_repo.get_by_user_id(user.id)
            if student is None or student.user_id not in dummy_user_ids:
                continue
            dummy_student_ids.append(student.id)
            print(f"    - Student ID: {student.id} (User: {user.email})")
        
        # Walk every enrollment in bounded pages. Keep only disposable rows.
        print("\n[2b] Finding orphaned enrollments (student not found)...")
        orphaned_enrollments = []
        valid_count = 0
        skip = 0
        while True:
            page, total = await enrollment_repo.find_page(None, skip=skip, limit=100, sort=[("_id", 1)])
            if not page:
                break
            for enrollment in page:
                try:
                    student = await student_repo.get_by_id(enrollment.student_id)
                    if student:
                        user = await user_repo.get_by_id(student.user_id)
                        example_account = bool(user and "@example.com" in user.email.lower())
                        if example_account or enrollment.student_id in dummy_student_ids:
                            orphaned_enrollments.append(enrollment)
                        else:
                            valid_count += 1
                    else:
                        orphaned_enrollments.append(enrollment)
                except Exception:
                    orphaned_enrollments.append(enrollment)
            skip += len(page)
            if skip >= total:
                break
        
        if not dummy_student_ids and not orphaned_enrollments:
            print("  No dummy or orphaned enrollments found.")
            print(f"  Found {valid_count} valid enrollments.")
            return
        
        # Combine dummy and orphaned enrollments (deduplicate by ID)
        dummy_enrollments = [e for e in orphaned_enrollments if e.student_id in dummy_student_ids] if dummy_student_ids else []
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
        print(f"  Valid enrollments to keep: {valid_count}")
        
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
        
        failures = 0
        for enrollment in all_dummy_enrollments:
            enrollment_id = enrollment.id
            try:
                deleted_counts["results"] += await _purge_matching(
                    result_repo, {"enrollment_id": ObjectId(enrollment_id)}
                )
                deleted_counts["attendance"] += await _purge_matching(
                    attendance_repo, {"enrollment_id": ObjectId(enrollment_id)}
                )
                deleted_counts["certificates"] += await _purge_matching(
                    certificate_repo, {"enrollment_id": ObjectId(enrollment_id)}
                )
                if await enrollment_repo.purge_document(enrollment_id):
                    deleted_counts["enrollments"] += 1
                    print(f"    Deleted enrollment: {enrollment_id}")
                else:
                    failures += 1
                    print(f"    Error deleting enrollment {enrollment_id}: row was not removed")
            except Exception as e:
                failures += 1
                print(f"    Error deleting data for {enrollment_id}: {e}")

        if failures:
            raise RuntimeError(
                f"Cleanup stopped with {failures} enrollment(s) that were not fully removed"
            )
        
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
        raise SystemExit(1) from e
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(remove_dummy_enrollments())

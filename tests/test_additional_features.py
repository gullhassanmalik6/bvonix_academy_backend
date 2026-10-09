"""Fee history, receipts, cash installments, overdue locks, attendance claims, and course images."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError
from types import SimpleNamespace

from app.models.attendance_claim import AttendanceClaim
from app.models.payment import Payment
from app.routes.lms import _payment_public, get_my_payments
from app.routes.uploads import download_private_upload, image_suffix
from app.schemas.attendance_claim import AttendanceCheckIn, AttendanceClaimDecision
from app.schemas.course import CourseCreate, course_to_public
from app.schemas.enrollment import AccessExceptionRequest
from app.schemas.payment import PaymentCreate
from app.services.attendance_claim_service import AttendanceClaimService, official_percentage, session_day
from app.services.fee_access import is_learning_restricted, normalize_fee_due_date, outstanding_balance
from app.services.instructor_names import MISSING_INSTRUCTOR, display_name, names_by_instructor_id
from app.services.payment_service import PaymentService
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError
from tests.test_pagination import NOW, _run


def _payment(**overrides):
    values = dict(
        id="pay-1",
        student_id="student-1",
        course_id="course-1",
        enrollment_id="enroll-1",
        amount=5000.0,
        currency="PKR",
        payment_method="cash",
        payment_status="completed",
        transaction_id=None,
        invoice_number=None,
        invoice_url=None,
        payment_date=NOW,
        due_date=None,
        scholarship_discount=0.0,
        notes=None,
        created_by="admin-1",
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(overrides)
    return Payment(**values)


def _enrollment(**overrides):
    values = dict(
        id="enroll-1",
        student_id="student-1",
        course_id="course-1",
        payment_status="pending",
        status="active",
        fee_due_date=NOW - timedelta(days=1),
        access_exception=None,
        review_state=None,
        verified_by_admin=True,
        payment_receipt_url=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class Ledger(unittest.TestCase):
    def test_installments_use_only_confirmed_payments(self):
        payments = [
            _payment(id="a", amount=5000, payment_status="completed"),
            _payment(id="b", amount=4000, payment_status="completed"),
            _payment(id="c", amount=6000, payment_status="pending"),
            _payment(id="d", amount=1000, payment_status="failed"),
            _payment(id="e", amount=1000, payment_status="refunded"),
        ]
        self.assertEqual(float(outstanding_balance(15000, payments)), 6000.0)
        payments[2] = _payment(id="c", amount=6000, payment_status="completed")
        self.assertEqual(float(outstanding_balance(15000, payments)), 0.0)

    def test_overdue_rules(self):
        now = NOW
        owed = [_payment(payment_status="pending", amount=15000)]
        paid = [_payment(payment_status="completed", amount=15000)]
        self.assertFalse(is_learning_restricted(_enrollment(fee_due_date=None), owed, now, 15000))
        self.assertFalse(is_learning_restricted(_enrollment(fee_due_date=now + timedelta(days=1)), owed, now, 15000))
        self.assertFalse(is_learning_restricted(_enrollment(), paid, now, 15000))
        self.assertFalse(is_learning_restricted(_enrollment(), owed, now, 15000))
        self.assertTrue(is_learning_restricted(_enrollment(), [_payment(payment_status="pending", amount=1000)], now, 15000))
        self.assertFalse(is_learning_restricted(
            _enrollment(access_exception={"reason": "Family emergency", "expires_at": now + timedelta(days=2)}),
            [],
            now,
            15000,
        ))
        self.assertTrue(is_learning_restricted(
            _enrollment(access_exception={"reason": "Expired", "expires_at": now - timedelta(hours=1)}),
            [],
            now,
            15000,
        ))
        self.assertFalse(is_learning_restricted(
            _enrollment(verified_by_admin=False, payment_receipt_url="/uploads/payment_receipts/waiting.jpg"),
            [],
            now,
            15000,
        ))
        self.assertEqual(MISSING_INSTRUCTOR, "Instructor not assigned")


class PaymentLedger(unittest.TestCase):
    def _service(self, prior=None):
        store = SimpleNamespace(rows=list(prior or []), requests={})

        class Repo:
            async def find_by_client_request(self, key):
                return store.requests.get(key)

            async def for_enrollment(self, enrollment_id):
                return [item for item in store.rows if item.enrollment_id == enrollment_id]

            async def create_payment(self, **kwargs):
                payment = _payment(
                    id=f"pay-{len(store.rows) + 1}",
                    amount=kwargs["amount"],
                    payment_method=kwargs["payment_method"],
                    payment_status=kwargs["payment_status"],
                    payment_date=kwargs.get("payment_date"),
                    created_by=kwargs.get("created_by"),
                    notes=kwargs.get("notes"),
                    client_request_id=kwargs.get("client_request_id"),
                    student_id=kwargs["student_id"],
                    enrollment_id=kwargs.get("enrollment_id"),
                )
                store.rows.append(payment)
                if payment.client_request_id:
                    store.requests[payment.client_request_id] = payment
                return payment

        return PaymentService(Repo()), store

    def test_cash_is_completed_without_changing_enrollment_payment_status(self):
        service, store = self._service()
        enrollment = _enrollment()

        class Enrollments:
            async def get_by_id(self, _enrollment_id):
                return enrollment

        class Courses:
            async def get_by_id(self, _course_id):
                return SimpleNamespace(price=15000)

        created = _run(service.create_payment(
            PaymentCreate(
                student_id="student-1",
                course_id="course-1",
                enrollment_id="enroll-1",
                amount=5000,
                payment_method="cash",
                record_as_received=True,
                notes="Received at the front desk",
                client_request_id="cash-1",
            ),
            "admin-1",
            actor_role="admin",
            courses=Courses(),
            enrollments=Enrollments(),
        ))
        self.assertEqual(created.payment_status, "completed")
        self.assertIsNone(created.receipt_url)
        self.assertEqual(created.created_by, "admin-1")
        self.assertEqual(enrollment.payment_status, "pending")
        self.assertFalse(hasattr(enrollment, "replaced"))
        again = _run(service.create_payment(
            PaymentCreate(
                student_id="student-1",
                enrollment_id="enroll-1",
                amount=5000,
                payment_method="cash",
                record_as_received=True,
                client_request_id="cash-1",
            ),
            "admin-1",
            actor_role="admin",
            courses=Courses(),
            enrollments=Enrollments(),
        ))
        self.assertEqual(again.id, created.id)
        self.assertEqual(len(store.rows), 1)

    def test_amount_cannot_exceed_the_balance_and_students_cannot_record_cash(self):
        service, _store = self._service([_payment(amount=14000, payment_status="completed")])

        class Enrollments:
            async def get_by_id(self, _enrollment_id):
                return _enrollment()

        class Courses:
            async def get_by_id(self, _course_id):
                return SimpleNamespace(price=15000)

        with self.assertRaises(ConflictError):
            _run(service.create_payment(
                PaymentCreate(student_id="student-1", enrollment_id="enroll-1", amount=2000, payment_method="cash", record_as_received=True),
                "admin-1",
                actor_role="admin",
                courses=Courses(),
                enrollments=Enrollments(),
            ))
        with self.assertRaises(ForbiddenError):
            _run(service.create_payment(
                PaymentCreate(student_id="student-1", amount=100, payment_method="cash", record_as_received=True),
                "student-user",
                actor_role="user",
            ))
        with self.assertRaises(ForbiddenError):
            _run(service.create_payment(
                PaymentCreate(student_id="student-1", amount=100, payment_method="bank_transfer"),
                "manager",
                actor_role="academic_manager",
            ))
        with self.assertRaises(ConflictError):
            _run(service.create_payment(
                PaymentCreate(student_id="student-1", amount=100, payment_method="online", record_as_received=True),
                "admin-1",
                actor_role="super_admin",
            ))

    def test_a_duplicate_insert_still_marks_a_covered_fee_paid(self):
        enrollment = _enrollment(payment_date=None, verified_by_admin=False)
        existing = _payment(amount=15000, payment_status="completed", client_request_id="cash-race")
        lookups = {"count": 0, "inserted": False}
        written = {}

        class Repo:
            async def find_by_client_request(self, key):
                lookups["count"] += 1
                if key != "cash-race" or lookups["count"] == 1:
                    return None
                return existing

            async def for_enrollment(self, _enrollment_id):
                return [existing] if lookups["inserted"] else []

            async def create_payment(self, **_kwargs):
                lookups["inserted"] = True
                raise DuplicateKeyError("duplicate client_request_id")

        class Enrollments:
            async def get_by_id(self, _enrollment_id):
                return enrollment

            async def update(self, _enrollment_id, values):
                written.update(values)
                for key, value in values.items():
                    setattr(enrollment, key, value)
                return enrollment

        class Courses:
            async def get_by_id(self, _course_id):
                return SimpleNamespace(price=15000)

        created = _run(PaymentService(Repo()).create_payment(
            PaymentCreate(
                student_id="student-1",
                enrollment_id="enroll-1",
                amount=15000,
                payment_method="cash",
                record_as_received=True,
                client_request_id="cash-race",
            ),
            "admin-1",
            actor_role="admin",
            courses=Courses(),
            enrollments=Enrollments(),
        ))
        self.assertEqual(created.id, existing.id)
        self.assertEqual(written["payment_status"], "paid")
        self.assertNotIn("verified_by_admin", written)
        self.assertNotIn("access_exception", written)
        self.assertFalse(enrollment.verified_by_admin)

    def test_a_ledger_refund_reopens_the_balance_without_erasing_the_payment(self):
        from app.schemas.payment import PaymentUpdate

        verified = _enrollment(payment_status="paid", verified_by_admin=True, payment_date=NOW)
        unverified = _enrollment(payment_status="paid", verified_by_admin=False, payment_date=NOW)
        ledger = [
            _payment(id="kept", amount=15000, payment_status="completed"),
        ]

        class Payments:
            async def get_by_id(self, _payment_id):
                return ledger[0]

            async def update(self, _payment_id, values):
                for key, value in values.items():
                    setattr(ledger[0], key, value)
                return ledger[0]

            async def for_enrollment(self, _enrollment_id):
                return list(ledger)

        def enrollments_for(enrollment):
            class Enrollments:
                async def get_by_id(self, _enrollment_id):
                    return enrollment

                async def update(self, _enrollment_id, values):
                    for key, value in values.items():
                        setattr(enrollment, key, value)
                    return enrollment

            return Enrollments()

        class Courses:
            async def get_by_id(self, _course_id):
                return SimpleNamespace(price=15000)

        service = PaymentService(Payments())
        refunded = _run(service.update_payment(
            "kept",
            PaymentUpdate(payment_status="refunded"),
            actor_role="admin",
            actor_id="admin-1",
            courses=Courses(),
            enrollments=enrollments_for(verified),
        ))
        self.assertEqual(refunded.payment_status, "refunded")
        self.assertEqual(refunded.amount, 15000)
        self.assertEqual(verified.payment_status, "paid")
        self.assertTrue(verified.verified_by_admin)
        self.assertEqual(float(outstanding_balance(15000, ledger)), 15000.0)
        self.assertTrue(is_learning_restricted(verified, ledger, NOW, 15000))

        ledger[0] = _payment(id="kept", amount=15000, payment_status="completed")
        _run(service.update_payment(
            "kept",
            PaymentUpdate(payment_status="refunded"),
            actor_role="admin",
            actor_id="admin-1",
            courses=Courses(),
            enrollments=enrollments_for(unverified),
        ))
        self.assertEqual(unverified.payment_status, "pending")
        self.assertFalse(unverified.verified_by_admin)
        self.assertEqual(ledger[0].payment_status, "refunded")
        self.assertTrue(is_learning_restricted(unverified, ledger, NOW, 15000))

    def test_reconciliation_repairs_a_covered_fee_without_adding_a_payment(self):
        enrollment = _enrollment(payment_status="pending", verified_by_admin=False, payment_date=None)
        rows = [
            _payment(id="first", amount=5000, payment_status="completed"),
            _payment(id="second", amount=10000, payment_status="completed"),
        ]
        attempts = {"count": 0}

        class Payments:
            async def for_enrollment(self, _enrollment_id):
                return list(rows)

        class Enrollments:
            async def get_by_id(self, _enrollment_id):
                return enrollment

            async def update(self, _enrollment_id, values):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise RuntimeError("enrollment write failed")
                for key, value in values.items():
                    setattr(enrollment, key, value)
                return enrollment

        class Courses:
            async def get_by_id(self, _course_id):
                return SimpleNamespace(price=15000)

        service = PaymentService(Payments())
        _run(service.reconcile_enrollment(
            "enroll-1",
            courses=Courses(),
            enrollments=Enrollments(),
            actor_id="admin-1",
            actor_role="admin",
        ))
        self.assertEqual(enrollment.payment_status, "pending")
        self.assertEqual(len(rows), 2)
        repaired = _run(service.reconcile_enrollment(
            "enroll-1",
            courses=Courses(),
            enrollments=Enrollments(),
            actor_id="admin-1",
            actor_role="admin",
        ))
        self.assertEqual(repaired.payment_status, "paid")
        self.assertEqual(len(rows), 2)
        self.assertEqual(float(outstanding_balance(15000, rows)), 0.0)
        self.assertFalse(is_learning_restricted(repaired, rows, NOW, 15000))


class FeeCoverage(unittest.TestCase):
    def test_only_a_covering_confirmed_payment_marks_the_enrollment_paid(self):
        from app.routes.admin import admin_set_fee_due_date
        from app.schemas.enrollment import FeeDueUpdate

        service, store = PaymentLedger()._service()
        enrollment = _enrollment(payment_date=None)
        saved = {}

        class Enrollments:
            async def get_by_id(self, _enrollment_id):
                return enrollment

            async def update(self, _enrollment_id, values):
                self_values = dict(values)
                saved.update(self_values)
                for key, value in self_values.items():
                    setattr(enrollment, key, value)
                return enrollment

        class Courses:
            async def get_by_id(self, _course_id):
                return SimpleNamespace(price=15000)

        pending = _run(service.create_payment(
            PaymentCreate(student_id="student-1", enrollment_id="enroll-1", amount=15000, payment_method="cash"),
            "admin-1",
            actor_role="admin",
            courses=Courses(),
            enrollments=Enrollments(),
        ))
        self.assertEqual(pending.payment_status, "pending")
        self.assertEqual(enrollment.payment_status, "pending")
        self.assertNotIn("payment_status", saved)

        _run(service.create_payment(
            PaymentCreate(
                student_id="student-1",
                enrollment_id="enroll-1",
                amount=5000,
                payment_method="cash",
                record_as_received=True,
                client_request_id="part-1",
            ),
            "admin-1",
            actor_role="admin",
            courses=Courses(),
            enrollments=Enrollments(),
        ))
        self.assertEqual(enrollment.payment_status, "pending")
        self.assertEqual(float(outstanding_balance(15000, store.rows)), 10000.0)

        _run(service.create_payment(
            PaymentCreate(
                student_id="student-1",
                enrollment_id="enroll-1",
                amount=10000,
                payment_method="cash",
                record_as_received=True,
                client_request_id="part-2",
            ),
            "admin-1",
            actor_role="admin",
            courses=Courses(),
            enrollments=Enrollments(),
        ))
        self.assertEqual(enrollment.payment_status, "paid")
        self.assertEqual(saved["payment_status"], "paid")
        self.assertNotIn("verified_by_admin", saved)
        self.assertNotIn("access_exception", saved)
        self.assertEqual(float(outstanding_balance(15000, store.rows)), 0.0)

        refunded = _enrollment(payment_status="refunded")
        service, _store = PaymentLedger()._service()

        class Refunded:
            async def get_by_id(self, _enrollment_id):
                return refunded

            async def update(self, *_args, **_kwargs):
                raise AssertionError("a refunded enrollment must not be rewritten")

        _run(service.create_payment(
            PaymentCreate(
                student_id="student-1",
                enrollment_id="enroll-1",
                amount=1,
                payment_method="cash",
                record_as_received=True,
                client_request_id="refunded-fee",
            ),
            "admin-1",
            actor_role="admin",
            courses=Courses(),
            enrollments=Refunded(),
        ))

    def test_due_date_update_keeps_payment_data_and_rejects_an_invented_range(self):
        from app.routes.admin import admin_set_fee_due_date
        from app.schemas.enrollment import FeeDueUpdate

        enrollment = SimpleNamespace(
            id="enroll-1",
            student_id="student-1",
            course_id="course-1",
            enrollment_date=NOW,
            status="active",
            payment_status="pending",
            payment_date=None,
            completion_date=None,
            progress_percentage=0,
            class_type="physical",
            phone_number=None,
            address=None,
            emergency_contact_name=None,
            emergency_contact_phone=None,
            father_guardian_name=None,
            date_of_birth=None,
            gender=None,
            profile_image_url=None,
            enrollment_card_number=None,
            enrollment_card_url=None,
            payment_receipt_url=None,
            verified_by_admin=False,
            verified_at=None,
            verified_by=None,
            review_state=None,
            fee_due_date=None,
            access_exception={"reason": "Keep this exception", "approved_by": "admin-1"},
            created_at=NOW,
            updated_at=NOW,
        )
        written = {}

        class Repo:
            async def get_by_id(self, _enrollment_id):
                return enrollment

            async def update(self, _enrollment_id, values):
                written.clear()
                written.update(values)
                for key, value in values.items():
                    setattr(enrollment, key, value)
                return enrollment

        due = datetime(2026, 11, 1, tzinfo=timezone.utc)
        updated = _run(admin_set_fee_due_date(
            "enroll-1",
            FeeDueUpdate(fee_due_date=due),
            Repo(),
            None,
            SimpleNamespace(id="admin-1", role="admin"),
        ))
        self.assertEqual(set(written), {"fee_due_date", "updated_at"})
        self.assertEqual(updated.payment_status, "pending")
        self.assertEqual(updated.access_exception["reason"], "Keep this exception")
        self.assertEqual(updated.fee_due_date, due)
        self.assertFalse(is_learning_restricted(updated, [], due + timedelta(days=1), 15000))
        self.assertTrue(is_learning_restricted(_enrollment(fee_due_date=due, access_exception=None), [], due + timedelta(days=1), 15000))
        self.assertFalse(is_learning_restricted(_enrollment(fee_due_date=None), [], due + timedelta(days=1), 15000))
        self.assertIsNone(normalize_fee_due_date(None))
        with self.assertRaises(ConflictError):
            normalize_fee_due_date(datetime(1990, 1, 1, tzinfo=timezone.utc))


class ReceiptAccess(unittest.TestCase):
    def test_student_history_is_limited_to_that_student(self):
        mine = _payment(id="mine", receipt_url="/uploads/payment_receipts/mine.jpg")
        other = _payment(id="other", student_id="student-2")

        class Service:
            async def list_payments(self, _skip, _limit, student_id=None, **_kwargs):
                rows = [item for item in (mine, other) if item.student_id == student_id]
                return rows, len(rows)

        page = _run(get_my_payments(0, 100, (SimpleNamespace(id="student-1"), None), Service(), object(), object()))
        self.assertEqual([item.id for item in page.items], ["mine"])
        self.assertTrue(page.items[0].receipt_available)

    def test_receipt_link_survives_verification_status(self):
        public = _payment_public(
            _payment(payment_status="completed", receipt_url=None),
            receipt_url="/uploads/payment_receipts/paid.jpg",
            verification_status="active",
            course_title="Web Development",
        )
        self.assertTrue(public.receipt_available)
        self.assertEqual(public.course_title, "Web Development")
        self.assertEqual(public.verification_status, "active")

    def test_another_student_cannot_open_a_receipt(self):
        class Enrollments:
            async def find_by_stored_file(self, _field, _url):
                return SimpleNamespace(student_id="student-2", enrollment_id="enroll-2")

            async def get_by_id(self, _enrollment_id):
                return None

        class Students:
            async def get_by_user_id(self, _user_id):
                return SimpleNamespace(id="student-1")

        class Payments:
            async def find_by_receipt_url(self, _url):
                return None

        with self.assertRaises(ForbiddenError):
            _run(download_private_upload(
                "payment-receipts",
                "receipt.jpg",
                SimpleNamespace(id="user-1", role="user"),
                Enrollments(),
                Students(),
                Payments(),
            ))
        with self.assertRaises(NotFoundError):
            _run(download_private_upload(
                "payment-receipts",
                "../secret.jpg",
                SimpleNamespace(id="user-1", role="admin"),
                Enrollments(),
                Students(),
                Payments(),
            ))


class AttendanceClaims(unittest.TestCase):
    def _service(self):
        claims = {}
        official = []

        class Claims:
            async def find_for_session(self, student_id, course_id, session_date):
                return claims.get((student_id, course_id, session_date))

            async def create_claim(self, **kwargs):
                claim = AttendanceClaim(
                    id=f"claim-{len(claims) + 1}",
                    status="pending_verification",
                    reviewed_by=None,
                    reviewed_at=None,
                    review_reason=None,
                    attendance_id=None,
                    created_at=NOW,
                    updated_at=NOW,
                    **kwargs,
                )
                claims[(claim.student_id, claim.course_id, claim.session_date)] = claim
                return claim

            async def get_by_id(self, claim_id):
                return next((item for item in claims.values() if item.id == claim_id), None)

            async def update(self, claim_id, values):
                current = await self.get_by_id(claim_id)
                for key, value in values.items():
                    setattr(current, key, value)
                return current

        class Attendances:
            async def get_attendance_by_session(self, *_args):
                return None

            async def create_attendance(self, payload):
                row = SimpleNamespace(id=f"att-{len(official) + 1}", status=payload.status, marked_by=payload.marked_by)
                official.append(row)
                return row

        return AttendanceClaimService(Claims(), Attendances()), official

    def test_check_in_stays_pending_and_cannot_be_approved_by_the_student(self):
        service, official = self._service()
        enrollment = _enrollment()
        claim = _run(service.submit_check_in(student_id="student-1", course_id="course-1", enrollment=enrollment, now=NOW))
        self.assertEqual(claim.status, "pending_verification")
        self.assertEqual(official, [])
        with self.assertRaises(ConflictError):
            _run(service.submit_check_in(student_id="student-1", course_id="course-1", enrollment=enrollment, now=NOW))
        with self.assertRaises(ForbiddenError):
            _run(service.submit_check_in(student_id="student-2", course_id="course-1", enrollment=enrollment, now=NOW))
        with self.assertRaises(ForbiddenError):
            _run(service.decide(claim.id, action="approve", reason=None, actor_id="student-1", actor_role="user"))
        with self.assertRaises(ConflictError):
            _run(service.decide(claim.id, action="reject", reason="  ", actor_id="admin-1", actor_role="admin"))
        rejected = _run(service.decide(claim.id, action="reject", reason="Not in class", actor_id="admin-1", actor_role="admin"))
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(official, [])
        self.assertEqual(official_percentage([SimpleNamespace(status="pending_verification"), SimpleNamespace(status="rejected")]), 0.0)

    def test_approval_counts_and_pending_does_not(self):
        service, official = self._service()
        claim = _run(service.submit_check_in(student_id="student-1", course_id="course-1", enrollment=_enrollment(), now=NOW))
        approved = _run(service.decide(claim.id, action="approve", reason="Seen in class", actor_id="admin-1", actor_role="academic_manager"))
        self.assertEqual(approved.status, "approved")
        self.assertEqual(official[0].status, "present")
        self.assertEqual(official[0].marked_by, "admin-1")
        records = [SimpleNamespace(status="present") for _ in range(8)]
        records.extend(SimpleNamespace(status="absent") for _ in range(2))
        records.append(SimpleNamespace(status="pending_verification"))
        self.assertEqual(official_percentage(records), 80.0)
        AttendanceClaimDecision(action="approve", reason="Seen")
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            AttendanceCheckIn.model_validate({"course_id": "course-1", "session_date": "2020-01-01T00:00:00Z"})
        local_evening = datetime(2026, 10, 10, 4, 0, tzinfo=timezone(timedelta(hours=5)))
        self.assertEqual(session_day(local_evening), datetime(2026, 10, 9, tzinfo=timezone.utc))
        service, _official = self._service()
        first = _run(service.submit_check_in(
            student_id="student-9",
            course_id="course-9",
            enrollment=_enrollment(student_id="student-9", course_id="course-9"),
            now=local_evening,
        ))
        self.assertEqual(first.session_date, datetime(2026, 10, 9, tzinfo=timezone.utc))
        self.assertEqual(first.status, "pending_verification")
        with self.assertRaises(ConflictError):
            _run(service.submit_check_in(
                student_id="student-9",
                course_id="course-9",
                enrollment=_enrollment(student_id="student-9", course_id="course-9"),
                now=datetime(2026, 10, 9, 23, 0, tzinfo=timezone.utc),
            ))


class CoursePresentation(unittest.TestCase):
    def test_image_bytes_and_instructor_fallback(self):
        self.assertEqual(image_suffix(b"\xff\xd8\xff rest"), ".jpg")
        self.assertEqual(image_suffix(b"\x89PNG\r\n\x1a\n rest"), ".png")
        self.assertEqual(image_suffix(b"RIFF1234WEBP"), ".webp")
        self.assertIsNone(image_suffix(b"%PDF-1.7"))
        self.assertIsNone(image_suffix(b"GIF89a"))
        course = SimpleNamespace(
            id="course-1",
            title="Web Development",
            description="Build sites",
            instructor_id="ins-1",
            duration_hours=40,
            price=15000,
            is_published=True,
            image_url="/uploads/course_images/safe.jpg",
            created_at=NOW,
            updated_at=NOW,
        )
        named = course_to_public(course, "Muhammad Ahmed")
        self.assertEqual(named.instructor_name, "Muhammad Ahmed")
        self.assertEqual(named.instructor_id, "ins-1")
        self.assertEqual(named.image_url, "/uploads/course_images/safe.jpg")
        self.assertIsNone(course_to_public(course, None).instructor_name)
        self.assertIsNone(display_name(None))
        self.assertIsNone(display_name(SimpleNamespace(full_name="Hidden", archived_at=NOW)))
        self.assertEqual(display_name(SimpleNamespace(full_name="Muhammad Ahmed", archived_at=None)), "Muhammad Ahmed")
        with self.assertRaises(ConflictError):
            from app.services.course_service import CourseService

            class Courses:
                async def create_course(self, **_kwargs):
                    raise AssertionError("invalid image must not be stored")

            _run(CourseService(Courses()).create_course(CourseCreate(
                title="Web Development",
                description="A complete course description",
                instructor_id="ins-1",
                duration_hours=10,
                price=100,
                image_url="blob:preview",
            )))

    def test_instructor_names_are_loaded_together(self):
        class Instructors:
            async def load_by_ids(self, ids):
                return {"ins-1": SimpleNamespace(user_id="user-1", archived_at=None)} if "ins-1" in ids else {}

        class Users:
            async def load_by_ids(self, ids):
                return {"user-1": SimpleNamespace(full_name="Muhammad Ahmed", archived_at=None)} if "user-1" in ids else {}

        names = _run(names_by_instructor_id(["ins-1", "ins-1", ""], Instructors(), Users()))
        self.assertEqual(names["ins-1"], "Muhammad Ahmed")


class AccessException(unittest.TestCase):
    def test_exception_does_not_mark_the_fee_paid(self):
        from app.routes.admin import admin_grant_access_exception

        enrollment = SimpleNamespace(
            id="enroll-1",
            student_id="student-1",
            course_id="course-1",
            enrollment_date=NOW,
            status="active",
            payment_status="pending",
            payment_date=None,
            completion_date=None,
            progress_percentage=0,
            class_type="physical",
            phone_number=None,
            address=None,
            emergency_contact_name=None,
            emergency_contact_phone=None,
            father_guardian_name=None,
            date_of_birth=None,
            gender=None,
            profile_image_url=None,
            enrollment_card_number=None,
            enrollment_card_url=None,
            payment_receipt_url=None,
            verified_by_admin=True,
            verified_at=NOW,
            verified_by="admin-1",
            review_state=None,
            fee_due_date=NOW - timedelta(days=2),
            access_exception=None,
            created_at=NOW,
            updated_at=NOW,
        )

        class Repo:
            async def get_by_id(self, _enrollment_id):
                return enrollment

            async def update(self, _enrollment_id, values):
                for key, value in values.items():
                    setattr(enrollment, key, value)
                return enrollment

        updated = _run(admin_grant_access_exception(
            "enroll-1",
            AccessExceptionRequest(reason="Temporary access while the family pays"),
            Repo(),
            None,
            SimpleNamespace(id="admin-1", role="admin"),
        ))
        self.assertEqual(updated.payment_status, "pending")
        self.assertEqual(enrollment.access_exception["approved_by"], "admin-1")
        self.assertFalse(is_learning_restricted(enrollment, [], NOW, 15000))


if __name__ == "__main__":
    unittest.main()

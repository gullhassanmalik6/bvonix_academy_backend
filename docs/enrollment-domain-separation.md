# Enrollment domain separation

This is an audit and a staged plan. It does not split collections, copy production data, or change API response fields.

The current enrollment document is the registration record and also stores profile details used on the card, the receipt, the review decision, and the issued card. A separate `payments` collection exists and is not updated by enrollment verification. A separate `students` collection stores the account link and a course-id list, not the card profile.

## Current data model

| Responsibility | Collection / model | Important fields | Source of truth | Readers and writers | Relationships | Indexes | Archival | Risk of changing it |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Enrollment lifecycle | `enrollments` / `Enrollment` | `student_id`, `course_id`, `status` (`pending`, `active`, `completed`, `cancelled`), `progress_percentage`, `enrollment_date`, `completion_date` | Enrollment document | `POST /lms/enroll/{course_id}`, admin verify, transition, cancel, progress update, LMS access checks | `student_id` → `students._id`, `course_id` → `courses._id` | Unique `(student_id, course_id)`; `(student_id, verified_by_admin, status, enrollment_date)` | No `archived_at`. `delete()` returns false. History is `status` | Access, dashboard, and duplicate prevention all read these fields |
| Card profile captured at enrollment | Same enrollment document | `class_type`, `phone_number`, `address`, `emergency_contact_name`, `emergency_contact_phone`, `father_guardian_name`, `date_of_birth`, `gender`, `profile_image_url` | Enrollment document. `Student` does not store them. `User` stores name and email | Written by `POST /lms/enroll`. Read by card generation and `EnrollmentPublic` | Belong to one enrollment, not the student account | Searched with card number, phone, class type, and guardian name on the admin enrollment list | Kept on the enrollment row after cancellation | Moving them now would change the card and the public enrollment response unless an adapter copies them |
| Payment gate on the enrollment | Same enrollment document | `payment_status` (`pending`, `paid`, `refunded`), `payment_date`, `payment_receipt_url` | Enrollment document. This is not the `payments` collection | Receipt upload sets the URL. Verify and the `active` / `approved` transitions set `paid`. Refund sets `refunded` | One enrollment. No required `payments._id` | `(payment_status, created_at)` | Kept after cancellation | LMS access does not read this field directly. It reads `verified_by_admin` and `status` |
| Payment review | Same enrollment document | `review_state`, `verified_by_admin`, `verified_at`, `verified_by` | Derived by `workflow_state()` from these fields plus receipt and status. `review_state` is stored only when the other fields cannot express the step | Admin `POST /enrollments/{id}/transition` and `PATCH /enrollments/{id}/verify` | Reviewer is `verified_by` → user id | `(review_state)` | A cancelled enrollment keeps the last review fields | There is no review-history collection. Replacing `review_state` would drop rejection and resubmission |
| Enrollment card | Same enrollment document | `enrollment_card_number`, `enrollment_card_url` | Number is generated in `create_enrollment` before verification. URL is written when a PDF is generated | Student download, admin generate, public `GET /public/verify/{card_number}` | Number is unique per enrollment. Sparse unique index | Unique sparse `enrollment_card_number` | Number remains after cancellation. Public verify still finds it | The number is already issued on existing cards. Regenerating it would invalidate printed QR codes |
| Student account link | `students` / `Student` | `user_id`, `enrollment_date`, `enrolled_courses`, `is_active` | Student document for the account. `enrolled_courses` is a cache of non-cancelled enrollment course ids | Created on first LMS enroll if missing. Create, cancel, and the management membership routes rebuild the list from enrollments | `user_id` → `users._id`, unique. `enrolled_courses` holds course ids, not enrollment ids | Unique `user_id` | `archived_at` / `archived_by`. Active reads use `with_active` | The list write is still a second document write. A failed write is retried. The list is not access control |
| Payment ledger | `payments` / `Payment` | `student_id`, `course_id`, `enrollment_id`, `amount`, `currency`, `payment_method`, `payment_status` (`pending`, `completed`, `failed`, `refunded`), invoice and transaction fields | Payment document for admin-entered payments only | `POST/PATCH /admin/payments`. Student `GET /lms/payments` reads this collection | Optional `enrollment_id`. Not created by receipt upload or enrollment verify | `student_id`, `course_id`, `payment_status`, `transaction_id` | `archived_at`. `get_by_id` hides archived rows | Status vocabulary differs from enrollment `paid`. Syncing them blindly would rename a stored value |
| User identity | `users` / `User` | `email`, `full_name`, `role` | User document | Card PDF and public verify read the name | Student points at `user_id` | Existing user indexes | Users can be archived | Card name is not copied onto the enrollment |

Fields that mix responsibilities on one enrollment document:

- Profile: phone, address, contacts, guardian, date of birth, gender, profile image, class type.
- Payment gate: `payment_status`, `payment_date`, `payment_receipt_url`.
- Review: `review_state`, `verified_by_admin`, `verified_at`, `verified_by`.
- Card: `enrollment_card_number`, `enrollment_card_url`.
- Registration: `status`, progress, dates, `student_id`, `course_id`.

`payments.payment_status` and `enrollments.payment_status` are different fields. `completed` on a payment is not `paid` on an enrollment. Neither write updates the other.

`students.enrolled_courses` is a second list of course ids. The enrollment collection is the registration source. The list is a cache rebuilt from non-cancelled enrollments.

`students.enrollment_date` is the date the student profile was created. `enrollments.enrollment_date` is the date of that course registration. They are not duplicates.

## Workflows and write order

No route starts a MongoDB session or multi-document transaction.

1. New enrollment, `POST /lms/enroll/{course_id}`.
   - Load the course first. A missing or archived course returns 404 and does not create a student profile. Publication is not required.
   - Load the student by the authenticated user. If missing, insert one `students` row. A duplicate `user_id` from a concurrent create loads the existing profile instead of inserting another.
   - `find_one` on `(student_id, course_id)`, then the unique index. A non-cancelled row whose course is already on the compatibility list returns 409. A non-cancelled row whose list entry is missing is reconciled and returned, so a retry does not insert a second enrollment. A cancelled row stays cancelled and returns 409. The unique index is unchanged.
   - Insert the enrollment: `status=pending`, `payment_status=pending`, `verified_by_admin=false`, a new `ENR-…` card number, profile fields from the body, `review_state=null`.
   - Replace `students.enrolled_courses` with the course ids of this student's non-cancelled enrollments. A list-write failure returns an error and does not report success. The same request can be retried.

2. Student profile.
   - First enrollment creates `user_id`, `enrollment_date`, `enrolled_courses=[]`, `is_active=true`.
   - `POST /students` can create a profile for the signed-in user, or for any user when the caller is management.
   - `PATCH /students/{id}` and `PATCH /admin/students/{id}` are management-only. `is_active` is stored on the student. A submitted `enrolled_courses` value is not stored. The list is rebuilt from that student's non-cancelled enrollments.
   - `POST /students/{id}/enroll/{course_id}` checks that the course exists, then rebuilds the list. It does not insert an enrollment.
   - `POST /students/{id}/unenroll/{course_id}` rebuilds the list. It does not cancel an enrollment. Cancellation remains `PATCH /admin/enrollments/{id}/cancel`.
   - Profile fields used on the card are not written here. They are written on the enrollment.

3. Payment submission.
   - The student uploads a receipt file, then `POST /lms/enrollments/{id}/payment-receipt` with the URL.
   - The route checks the enrollment belongs to the authenticated student.
   - One enrollment update stores `payment_receipt_url`, `status=pending`, `verified_by_admin=false`, and clears `review_state`.
   - No `payments` row is inserted.

4. Payment review.
   - `POST /admin/enrollments/{id}/transition` requires a payment admin (`admin` or `super_admin`).
   - One enrollment update applies `enrollment_transition_updates`. Examples: `under_review` sets `review_state`; `approved` sets `payment_status=paid` and leaves `verified_by_admin=false`; `rejected` and `resubmission_required` clear verification; `refunded` sets enrollment `payment_status=refunded`.
   - `PATCH /admin/payments/{id}` changes a ledger row only (`pending` → `completed` or `failed`, `completed` → `refunded`). It does not change the enrollment.

5. Admin verification.
   - `PATCH /admin/enrollments/{id}/verify` requires a receipt and an allowed transition to `active`.
   - It loads course, student, and user. An archived or missing course returns 404 before the update.
   - It tries to generate the PDF. Generation failure is logged and verification continues with no URL.
   - One update sets `status=active`, `payment_status=paid`, `verified_by_admin=true`, `verified_at`, `verified_by`, and the card URL when generation succeeded.
   - Notification failure is logged after the update. The `payments` collection is not written.
   - Partial failure: a PDF file can exist when the enrollment update fails. A successful update can exist when notification fails.

6. Card generation.
   - The card number already exists from step 1.
   - Admin `POST /admin/enrollments/{id}/generate-card` requires `verified_by_admin`, writes a new PDF, then stores `enrollment_card_url`.
   - Student `GET /lms/enrollments/{id}/card` checks ownership and verification, regenerates the PDF, then stores the new URL.
   - Partial failure: the file can be written and the URL update can fail, leaving the previous URL.

7. Card verification.
   - Public `GET /public/verify/{card_number}` loads the enrollment by card number, then the student, user, and course, including an archived course name.
   - A card that is missing, cancelled, refunded, pending, or not verified returns one generic invalid response. The student name and course title stay empty.
   - There is no separate card-status field. Issued means the number exists. Verified means `verified_by_admin` together with an active or completed enrollment.

8. Student dashboard.
   - `GET /lms/dashboard` loads the student from the authenticated user, then verified enrollments with `status=active`.
   - Cards whose course is archived are omitted. `total` counts verified active enrollments, including those omitted cards.
   - `GET /lms/has-access` is true when one verified `active` or `completed` enrollment exists.

9. Cancellation.
   - `PATCH /admin/enrollments/{id}/cancel` is management.
   - The enrollment update to `status=cancelled` and `review_state=cancelled` is the authoritative write. The row is not deleted. Payments and the card number stay.
   - `students.enrolled_courses` is then replaced from non-cancelled enrollments. A list-write failure returns an error. Repeating the cancel reconciles the list and returns the cancelled enrollment.
   - Course access still depends on a verified active or completed enrollment, so a stale list entry does not grant access.

10. Archival and history.
    - Courses, payments, students, and learning content use `archived_at`.
    - Enrollments are not archived. Cancelled, completed, and active rows stay in `enrollments`.
    - `GET /lms/results` returns the authenticated student's stored results, including rows for cancelled enrollments.
    - Course-scoped learning routes require a verified `active` or `completed` enrollment and do not treat cancelled or pending as access.
    - Public card verify and performance titles can still read an archived course name.

11. Duplicate prevention.
    - Application `find_one` on `(student_id, course_id)`, then the unique index.
    - The check does not ignore cancelled rows. A cancelled pair cannot be enrolled again through this route.
    - Card numbers use a sparse unique index. Profile creation uses unique `user_id`.

12. Retry and failure.
    - Receipt upload, review transition, and verify are single-document updates.
    - Enrollment create and cancel still write the enrollment and then `enrolled_courses` separately. There is no transaction. A failed list update returns an error, and repeating the request reconciles the list without inserting or deleting an enrollment.
    - Card generation is a file write followed by a document update.
    - Payment ledger updates never repair the enrollment, and enrollment verification never repairs the ledger.

## Target boundaries

These boundaries match the code. They are not a schema to apply now.

- Enrollment keeps course registration, `status`, progress, dates, and the link `student_id` + `course_id`.
- Student profile stays the `students` row plus the user account. Card fields can later be copied from the enrollment, but the enrollment copy remains until every card and API reader uses the profile.
- Payment stays the `payments` ledger. Enrollment `payment_status=paid` remains the gate used by verification. Do not rename `paid` to `completed`.
- Payment review stays the enrollment review fields until a history collection is filled by a tested dual-write. There is no review event log today, so a new collection would be empty for past decisions unless it is derived once from the current fields.
- Enrollment card keeps the existing number and URL on the enrollment. A later card row would reference `enrollment_id` and the same number. The number is not regenerated.

Stable links to keep: `enrollments._id`, `students._id`, `users._id`, `courses._id`, and `payments.enrollment_id` when a ledger row exists.

API responses that must stay the same: `EnrollmentPublic` (including profile, receipt, card, verification, and `review_state`), `PaymentPublic`, `StudentPublic`, and `StudentCardVerifyResponse`.

## Migration and rollback

Do not run a production migration as part of this plan. No dual-write is introduced.

1. Add models and indexes only after a later task proves the read shape. No behavior change. Rollback: drop only indexes created by that task, and only on a non-production database.
2. An idempotent copy, if written later, must support dry-run, print counts rather than documents, and refuse `APP_ENV` of production or prod and database names `bvonix_academy`, `production`, `prod`, or any name containing `prod`. It must match `enrollment_id` and card number rather than insert a second copy. Rollback: stop the script. Do not delete source enrollment fields.
3. Reconciliation before any further write-path change is read-only. `scripts/registration_consistency_report.py` counts students, enrollments, list entries with no non-cancelled enrollment, non-cancelled enrollments missing from the list, cancelled enrollments still listed, duplicate non-cancelled pairs, and invalid relationship ids. `scripts/payment_consistency_report.py` counts ledger disagreements. Neither script selects a default database, and `--write` is refused. Conflicting rows are reported, not overwritten. There is still no card collection to count.
4. Validate ObjectId references and unique `(student_id, course_id)` plus unique card numbers. Abort the copy on a conflict.
5. Dual-write starts only after steps 3 and 4 have been run on a dedicated test database and the failure tests exist. It is not part of this task.
6. Compatibility reads keep returning enrollment fields. Adapters may fill a new row from the enrollment, and readers still prefer the enrollment until parity is recorded.
7. Switch one workflow at a time: ledger creation, then review history, then card URL updates, then profile edits. Dashboard, access checks, and public verify stay on the enrollment until that workflow's parity check passes.
8. Legacy enrollment fields stay. Removing them is a later task with its own contract test.
9. Rollback for a switched workflow is to read and write the enrollment field again. Do not drop the new rows during rollback. They can be rebuilt.

## Authorization notes

`GET /lms/results` and `GET /lms/results/{course_id}` take the student id from the authenticated profile. The course route also requires an eligible enrollment in that course. A result stored for another student is not returned. The regression test is `ResultOwnershipTests`.

`GET /courses`, `GET /courses/{id}`, `GET /courses/instructor/{instructor_id}/courses`, and course search used to return unpublished courses to any signed-in user. Non-management accounts now receive published courses. Management still receives drafts. The instructor linked to that profile still receives that profile's drafts. Another instructor id does not grant those drafts or `PATCH /courses/{id}`. The regression tests are `UnpublishedCourseAccessTests`.

Instructor workspace routes are still deferred. Instructor remains a profile linked by `user_id`, not a login role. Create, delete, and payment approval stay on the existing management and admin dependencies.

## Compatibility list

`students.enrolled_courses` remains on the student document. Its application writer is `EnrollmentRegistration.repair_course_list`, which copies course ids from enrollments whose status is not `cancelled`. LMS create and cancel already used that rebuild. Management `PATCH` with `enrolled_courses`, `POST /students/{id}/enroll/{course_id}`, and `POST /students/{id}/unenroll/{course_id}` now use it too.

The response shape is still `StudentPublic`, including `enrolled_courses`. The value in that field is the rebuilt list, including when the request asked for a different list. `is_active` is still stored. A profile update that does not mention `enrolled_courses` does not rebuild the list. LMS access does not read the list.

These two writes are not one transaction. If the enrollment row is already correct and the list write fails, the route returns an error and the enrollment is unchanged. Repeating the request rebuilds the list. Repeating it after the list already matches does not insert an enrollment and does not cancel one. A missing course on the enroll route returns 404 before the list write. An ordinary user is rejected by `get_management_user` before either write.

The read-only report includes archived students. It returns record ids only, capped at 100 per class. It does not return phone numbers, addresses, guardian names, or receipt URLs. It does not repair rows.

`scripts/reconcile_enrolled_courses.py` is the explicit repair command. With no `--write` flag it is a dry run. Both modes require `--uri` and `--database`. There is no default database and the application `MONGODB_URI` is not read. The command refuses `APP_ENV` of production or prod, the names `bvonix_academy`, `production`, and `prod`, any name containing `prod`, and any name that does not start with `bvonix_test`. That check happens before a client is opened.

An enrollment whose `status` is missing is not cancelled, so its course id is included. That is the same rule as `registration_course_ids`. A cancelled enrollment is omitted unless another non-cancelled enrollment for that student and course exists. Duplicate course ids are collapsed and the stored list is sorted. An invalid student or course id is counted and does not create a student, course, or enrollment. A missing course document does not remove the enrollment or invent a course.

Archived students are included. The write sets `enrolled_courses` and `updated_at` only, including on an archived student. `archived_at`, `is_active`, and profile fields stay as they are. Application routes still use the active-student list write, so an archived profile is not rebuilt by those routes.

The command reads in pages of 100. One student write failure is counted, that student id is returned, and the command continues with the remaining students. `completed` is false and the process exits 1. Rows already rebuilt stay rebuilt. Repeating `--write` updates the remaining drift and does not change an enrollment. A second run after every list matches updates nothing. The command does not change payment rows or review history.

Rollback for the management routes is to let those three routes write `enrolled_courses` directly again. Rollback for the repair command is to stop passing `--write`. Lists already rebuilt match non-cancelled enrollments and can stay. Enrollment rows do not need to be restored, because neither path creates or cancels them. No index was added. No collection was added.

## Collections that stay where they are

No new collection is part of this increment.

| Future record | Why it was not created | What would have to be true first |
| --- | --- | --- |
| `payment_reviews` | The audit log is the decision history. `audit_pending` on the enrollment or payment document recovers one failed history insert without a second collection. | Not required for the current recovery path. |
| Enrollment card collection | The card number and URL already live on the enrollment. Public verify and the PDF writer read those fields. | A dry-run copy keyed by `enrollment_id` and the existing card number, with readers still preferring the enrollment until parity is recorded. |
| Student profile copy of card fields | Phone, address, guardian, and date of birth are captured per enrollment. `StudentPublic` does not return them. | Every card and `EnrollmentPublic` reader can fall back to the enrollment copy. |

Before any production copy: run both read-only reports against a dedicated test database, refuse `APP_ENV` of production or prod, and refuse database names `bvonix_academy`, `production`, `prod`, or any name containing `prod`. Do not delete enrollment fields during rollback.

Clients that still read the current fields: `EnrollmentPublic` from LMS and admin enrollment routes, `StudentPublic` from `/students` and `/admin/students` (the admin student screen shows the course count only), `PaymentPublic`, and `StudentCardVerifyResponse`. The student enrollment wizard calls `POST /lms/enroll/{course_id}`. It does not call the management enroll route.

## Remaining issues

1. Reduced in this pass: create, cancel, and the management membership routes still use a separate list write because this deployment does not use multi-document transactions. A failed list update is retryable, and the enrollment row remains the registration record. A profile update that does not mention `enrolled_courses` leaves existing drift until a membership route, create, cancel, or `scripts/reconcile_enrolled_courses.py --write`. The repository no longer has list append or pull methods. The only list write is `set_enrolled_courses`.
2. Still separate by design: enrollment `payment_status` (`pending`, `paid`, `refunded`) and the ledger `payment_status` (`pending`, `completed`, `failed`, `refunded`) are not the same field. Verification does not create or complete a ledger row. A ledger update does not verify an enrollment. `docs/payment-consistency.md` records the lifecycle, and a read-only report counts disagreements.
3. Review history is the audit log, not a `payment_reviews` collection. The latest `review_state` stays on the enrollment. A required decision writes `audit_pending` in the same document update, then inserts the audit row. Retry completes that pending row. Older decisions that have no marker are not reconstructed. See `docs/payment-consistency.md`.
4. Fixed in this pass: an assigned instructor can no longer change `instructor_id` or `is_published` through `PATCH /courses/{id}`. Those changes require a management role, and a new instructor id must match an active instructor record.
5. Fixed in this pass: public card verification returns one generic invalid response, without a student name or course title, unless the card is verified and the enrollment is still active or completed.
6. Low: a cancelled enrollment still occupies the unique `(student_id, course_id)` pair, so the same student cannot enroll in that course again through the current route.
7. Low: card PDF generation can leave a file behind when the enrollment update fails.

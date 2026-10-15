# Payment consistency

Enrollment payment fields and the `payments` collection are separate records. This pass does not make them one record and does not copy status from one to the other.

## What each field means

| Record | Field | Values | Meaning in the current workflow |
| --- | --- | --- | --- |
| Enrollment | `payment_status` | `pending`, `paid`, `refunded` | Registration payment flag. Create sets `pending`. Approval and verification set `paid`. The refund transition sets `refunded`. |
| Enrollment | `payment_receipt_url` | URL or empty | The student uploaded a receipt. A receipt is not a completed ledger payment. |
| Enrollment | `review_state` | review name or empty | Latest review step. A new review replaces it. There is no review-history collection. |
| Enrollment | `verified_by_admin`, `verified_at`, `verified_by` | set by verification | An admin verified the enrollment after a receipt was present. This does not create a ledger row. |
| Payment | `payment_status` | `pending`, `completed`, `failed`, `refunded` | Ledger status. Admin create starts at `pending`. `pending` can become `completed` or `failed`. `completed` can become `refunded`. |
| Payment | `amount`, `payment_method` | admin-supplied | Not derived from the enrollment. Verification does not change them. |

`paid` and `completed` are not interchangeable. A verified enrollment may have no ledger row. A ledger row may have no enrollment id. Several ledger rows may point at one enrollment. Those states are counted, not rewritten.

## Who can change them

Payment create, status change, and refund require `admin` or `super_admin`. An ordinary user and an academic manager cannot change a ledger payment. A student can upload a receipt only for their own enrollment. That upload does not change a ledger row. Student payment lists use the authenticated student id.

## Failure behavior

Ledger status update is one document write. That write includes `audit_pending` when an audit service is present. If the payment document is not returned, no audit record is stored and the caller gets an error. Verification updates the enrollment, including the same kind of pending marker. A notification failure does not undo that update and does not create a payment. There is no multi-document transaction. The pending marker and the business fields are one document write. The audit-log insert is a second write.

## Review history

The audit log is the history of a review decision. The enrollment stores only the latest `review_state`. There is no `payment_reviews` collection.

An administrator can reconstruct a decision when the audit row exists. The row has `actor_id`, `actor_role`, `action`, `entity_type`, `entity_id` (the enrollment or payment id), `created_at`, `previous_state`, and `new_state`. Those states keep `review_state`, `payment_status`, and `verified_by_admin`. They do not keep a reason: the workflow has no reason field. Snapshots redact receipt URLs, invoice URLs, transaction ids, phone numbers, addresses, guardian names, emergency contacts, date of birth, and profile image URLs.

Known behavior:

- Decisions made before a pending marker existed are not backfilled. A retry does not invent that history.
- The business change and `audit_pending` are stored together. The audit insert uses `operation_id`. If the insert fails, the response says the history was not recorded. Repeating the same decision finds the marker, writes one history row, and does not change the business state again. If the insert succeeded and clearing the marker failed, the repeat finds the existing `operation_id` and only clears the marker.
- Uploading the same receipt again, or setting a ledger status that is already stored and has no pending marker, does not add another decision.
- A different receipt URL is a new receipt event and is audited.
- Notification failure does not remove the enrollment decision or its audit row.
- Ledger creation still uses a best-effort audit write. A failed create audit does not roll back the payment and does not leave `audit_pending`.
- Ordinary repository update and purge refuse to change an audit row. There is no HTTP route that edits audit history.

A future `payment_reviews` collection would be append-only and would store only `enrollment_id`, actor, previous state, new state, decision, and `created_at`. It would not store receipts or profile fields. It would not get a unique index until repeated legitimate decisions, such as two rejections of the same enrollment, are accounted for. Existing audit rows would stay. New events would be written going forward; old decisions would not be invented. Rollback would be to stop writing that collection and keep using the audit log. That collection is not implemented.

Enrollment fields stay as they are: `review_state`, `verified_by_admin`, `verified_at`, `verified_by`, and enrollment `payment_status`. `audit_pending` is not part of the public response. API response fields are otherwise unchanged. No production rows are copied or rewritten. There is no job that fills historical audit rows from the current enrollment. A decision that never stored `audit_pending` cannot be reconstructed.

## Read-only report

`app/services/payment_consistency.py` counts:

- enrollments with no ledger row
- ledger rows whose enrollment id does not match an enrollment
- enrollments with more than one ledger row
- enrollments marked `paid` whose ledger is missing or has no `completed` row
- `completed` ledger rows whose enrollment is not `paid` or `refunded`
- `refunded` ledger rows whose enrollment is not `refunded`
- ledger rows with an invalid student, course, or enrollment id

The script `scripts/payment_consistency_report.py` prints those counts. It has no default database. `--write` is refused.

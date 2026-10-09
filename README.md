# BvoniX Academy backend

FastAPI and MongoDB API for the existing academy application. The frontend is the sibling `bvonix_academy_frontend` project. Instructor workspace screens are not part of this launch.

## Setup

From `bvonix_academy_backend`:

```text
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `env.example.txt` to `.env`. Do not commit `.env`.

Required values:

| Variable | Role |
| --- | --- |
| `APP_ENV` | `development` locally. `production` or `prod` turns on startup checks. |
| `MONGODB_URI` | Database URI. Production must not disable TLS certificate checks. |
| `MONGODB_DB` | Database name. The application default is `bvonix_academy`. Test scripts refuse that name. |
| `JWT_SECRET` | HS256 signing secret. Production rejects an empty value, a known placeholder, and a secret shorter than 32 bytes. |
| `JWT_ALGORITHM` | `HS256`. Production rejects any other algorithm. |
| `ALLOWED_ORIGINS` | Comma-separated frontend origins. Credentials are allowed. |

`env.example.txt` uses a local MongoDB URI and a placeholder secret so development can start. Production startup fails if that placeholder is still set. The process does not print the secret.

## Run

```text
.\.venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- `GET /health/live` reports the process only. It does not ping MongoDB.
- `GET /health/ready` returns 503 when the database or upload storage is down.
- `GET /api/health` remains `{status: ok}`.
- Interactive docs: `http://localhost:8000/docs`.

Production (`APP_ENV=production` or `prod`) refuses to start when MongoDB does not answer, when `JWT_SECRET` is unusable, when `ALLOWED_ORIGINS` is empty, or when the URI disables TLS certificate validation. Other environments keep running and expose a database failure on `/health/ready`. Index creation errors are logged and do not abort startup. A failed unique or other integrity index makes `/health/ready` return `not_ready`. Performance-index failures stay in the log and do not change readiness by themselves.

## Authentication

Access tokens are bearer tokens. Refresh tokens are an HttpOnly, Secure, SameSite=None cookie named `bvonix_refresh` on `{API_PREFIX}/auth`. Archived or inactive accounts cannot log in, refresh, or use an old access token. Role checks run on the server. Login roles are `user`, `academic_manager`, `admin`, and `super_admin`. Instructor is a profile linked to a user, not a login role.

## Uploads

Public site assets are served from `/uploads/logos`, `/uploads/hero_icons`, `/uploads/community_images`, `/uploads/benefit_icons`, `/uploads/subject_icons`, `/uploads/testimonial_avatars`, and `/uploads/academy_logo.png` when that file exists.

Receipts, profile images, and enrollment-card PDFs are not on those mounts. An authenticated client downloads them from `GET /api/uploads/private/{kind}/{filename}`. The student who owns the enrollment, or a management role, may read the file. Another student receives 403. A missing file, an unknown name, or a path that leaves the directory returns 404 with `File not found`. Errors do not include the filesystem path.

## Enrollment, payments, and audit

Enrollment lifecycle and ledger payments stay separate. `paid` is an enrollment payment status. `completed` is a ledger status. Uploading a receipt or verifying an enrollment does not create or complete a ledger row.

Required decisions (review transition, verification, receipt upload, cancellation, and ledger status change) store `audit_pending` on the same document as the business change, then insert one audit row keyed by `operation_id`. If the insert fails, the response is HTTP 500: `The decision was saved, but the review history was not recorded.` Repeating that same decision writes the missing row and does not apply the business change again. A later different decision is still a new event. History that never received a pending marker is not invented. Audit rows cannot be updated or purged through the repository. Ledger creation remains best-effort.

`students.enrolled_courses` is a compatibility list rebuilt from enrollments that are not cancelled. A cancelled enrollment still occupies the unique `(student_id, course_id)` pair.

Read-only reports, with `--uri` and `--database` required:

```text
.\.venv\Scripts\python.exe scripts\payment_consistency_report.py --uri <uri> --database <name>
.\.venv\Scripts\python.exe scripts\registration_consistency_report.py --uri <uri> --database <name>
.\.venv\Scripts\python.exe scripts\reconcile_enrolled_courses.py --uri <uri> --database <name>
```

`--write` on the reconcile command is refused for production-like names and for any database whose name does not start with `bvonix_test`. Do not point these commands at production.

## Tests

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Live MongoDB checks run only when `MONGODB_TEST_URI` and `MONGODB_TEST_DB` name a dedicated database whose name starts with `bvonix_test`. They are skipped otherwise.

## More detail

- `docs/enrollment-domain-separation.md`
- `docs/payment-consistency.md`
- `docs/final-release-readiness.md`

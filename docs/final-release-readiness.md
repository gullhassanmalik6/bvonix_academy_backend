# Final release readiness

This pass changed the application. It records what the code and the commands below actually show. Historical audit rows that were never written were not reconstructed. The instructor workspace remains deferred.

## Verdict

READY WITH WARNINGS.

This verification pass re-ran the backend suite, frontend lint, and frontend production build. Production startup still refuses an unusable `JWT_SECRET`. An empty production `ALLOWED_ORIGINS` now fails startup instead of falling back to localhost. Private receipts, profile images, and enrollment cards stay off the public `/uploads` mount. Required review, verification, receipt, cancellation, and ledger-status decisions can recover one missing audit row from the stored marker, including in a new service instance. A failed required unique index no longer leaves `/health/ready` reporting ready. Live MongoDB was not configured. During that verification pass, `npm ci` failed with `EPERM`. A later dependency-remediation pass updated `package-lock.json` only, and `npm ci` then succeeded. Frontend findings remain. No staging deployment was performed. Production data was not modified.

## Changes in this pass

- `app/core/security_config.py` rejects a production `JWT_SECRET` that is empty, a known placeholder, shorter than 32 bytes, or not used with `HS256`. Development and test environments are unchanged. The failure text does not include the secret. `app/main.py` runs this check during startup. Mongo connection errors are logged without the exception text, so a URI is not written to the log.
- `app/main.py` mounts only the public site directories and `/uploads/academy_logo.png`. `GET /api/uploads/private/{kind}/{filename}` streams a receipt, profile image, or enrollment card after checking the enrollment owner or a management role. The frontend opens those files with the bearer token.
- Required decisions store `audit_pending` on the same enrollment or payment document as the business change, then insert an audit row with `operation_id`. A retry finishes that row and does not apply the business change again. Audit repository update and purge refuse. Ledger creation stays best-effort.
- `README.md`, `env.example.txt`, `docs/enrollment-domain-separation.md`, and `docs/payment-consistency.md` match that behavior.

## Files touched in this pass

Backend:

- `app/core/security_config.py`
- `app/main.py`
- `app/db/mongodb.py`
- `app/models/enrollment.py`
- `app/models/payment.py`
- `app/repositories/audit_log_repository.py`
- `app/repositories/enrollment_repository.py`
- `app/repositories/payment_repository.py`
- `app/routes/admin.py`
- `app/routes/lms.py`
- `app/routes/uploads.py`
- `app/services/audit_service.py`
- `app/services/enrollment_registration.py`
- `app/services/payment_service.py`
- `tests/test_audit_log.py`
- `tests/test_private_uploads.py`
- `tests/test_review_history.py`
- `tests/test_security_config.py`
- `README.md`
- `env.example.txt`
- `docs/enrollment-domain-separation.md`
- `docs/payment-consistency.md`
- `docs/final-release-readiness.md`

Frontend:

- `src/services/api.js`
- `src/services/adminService.js`
- `src/services/courseService.js`
- `src/services/lmsService.js`
- `src/pages/StudentLMS.jsx`
- `src/components/admin/AdminEnrollmentManagement.jsx`
- `src/components/cards/CardWrapper.jsx`
- `src/components/enrollment/EnrollmentWizard.jsx`
- `src/utils/cardPreviewPdf.jsx`

The backend working tree already contained earlier uncommitted work. That work was kept.

## Verification on this pass

Backend, from `bvonix_academy_backend`:

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Result: `Ran 199 tests in 2.429s` — `OK (skipped=1)`. Failed: 0.

The skipped test is `test_mongo_integration.LiveMongoIntegrationTests.test_pagination_archive_filter_count_aggregation_and_index`, reason `Set MONGODB_TEST_URI and MONGODB_TEST_DB to run live MongoDB integration tests.` `MONGODB_TEST_URI` and `MONGODB_TEST_DB` were unset. `MongoIntegrationSafetyTests` ran and do not open a client. The live test reads only those two variables, refuses `APP_ENV` of production or prod, refuses database names `bvonix_academy`, `production`, `prod`, any name containing `prod`, and any name that does not start with `bvonix_test`. Cleanup drops only the collection created for that test.

No ruff, mypy, or black configuration exists, so those commands were not run. No staging server was deployed.

Frontend, from `bvonix_academy_frontend`:

- `npm ci` failed with `EPERM` while unlinking `node_modules\@esbuild\.win32-x64-R0GrB8qZ\esbuild.exe`. That is not a clean install. `package-lock.json` and `package.json` were not modified.
- `npm install` was then used only to restore packages the failed `npm ci` had removed. It completed and audited 407 packages. It is not a substitute for `npm ci`.
- `npm run lint` passed.
- `npm run build` passed (`vite build`, 587 modules). Vite printed the existing warning that `@import './design-system.css'` follows other statements. The build still wrote `dist/`.
- `package.json` has no test script. No frontend test command was added.

## Defects fixed in this verification

- A failed required unique index used to be logged while `/health/ready` still returned ready. Integrity indexes (user email, student and instructor user id, enrollment student/course and card number, attendance date, one open attendance correction, certificate number and student/course, assignment submission, audit `operation_id`, and session token hash) now mark readiness `not_ready`. Performance-only index failures stay in the log and do not, by themselves, change readiness. Startup still continues. The index-failure log no longer includes the exception text.
- Production startup now rejects an empty `ALLOWED_ORIGINS`. Development may still start with an empty list, and the development CORS fallback to localhost remains.

## Audit recovery checked

These are not a multi-document transaction.

| Scenario | Result |
| --- | --- |
| Business write succeeds and the audit insert fails | PASS. HTTP 500, marker kept, secrets redacted, retry writes one row and does not change the business state again. |
| Audit insert succeeds and clearing the marker fails | PASS. Retry finds `operation_id` and does not insert a second row. |
| Recovery in a new repository and audit-service instance | PASS. The marker is read from the stored document. |
| No pending marker | PASS. No audit row is invented. |
| Repository update and purge of an audit row | PASS. Both refuse. |

Ledger creation remains best-effort. A crash after the business write and before the process can retry still leaves `audit_pending` until the same decision is repeated. That window is not closed without a transaction or an external worker.

## Security guarantees

- Production and prod refuse to start when `JWT_SECRET` is missing, blank, `CHANGE_ME`, `CHANGE_ME_TO_A_LONG_RANDOM_SECRET`, `secret`, `password`, `jwt_secret`, shorter than 32 bytes, or not paired with `HS256`.
- Access tokens still require a valid signature, expiry, issuer, audience, and access type. Archived and inactive users cannot log in, refresh, or keep using an old access token. Those checks were already covered and still pass.
- Refresh cookie remains HttpOnly, Secure, and SameSite=None.
- TLS certificate checks stay on outside development.
- Receipts, profile images, and enrollment-card files are not served by the public static mount. Download requires authentication. The owner or a management role may read the linked file. Another student receives 403. Missing and traversing paths return 404 with `File not found`.
- Public logos, hero icons, community images, benefit icons, subject icons, testimonial avatars, and `academy_logo.png` stay public.
- Error logs for Mongo client creation no longer include the exception string.
- Audit snapshots still redact receipt URLs, invoice URLs, transaction ids, phone numbers, addresses, guardian names, emergency contacts, dates of birth, and profile image URLs. `audit_pending` is omitted from snapshots and from public enrollment responses.

## Audit recovery guarantee

This is not a multi-document transaction. Standalone MongoDB is not assumed to support one.

For review transition, verification, receipt upload, cancellation, and ledger status change:

1. The business fields and `audit_pending` are written in one document update. The marker holds `operation_id`, action, actor, entity, and the redacted previous state.
2. The audit insert uses that `operation_id`. A sparse unique index on `operation_id` is created with the other audit indexes.
3. The marker is then cleared.
4. Success is returned only after the audit row exists and the marker clear returns the document.
5. If the insert fails, the HTTP 500 detail remains `The decision was saved, but the review history was not recorded.` Retry of the same decision writes one row and does not change the business state again.
6. If the insert succeeded and the clear failed, retry finds the existing `operation_id` and only clears the marker.
7. A document with no marker does not get an invented history row.
8. A second successful decision, with no marker left, remains a conflict and does not add a duplicate row.
9. Ledger creation still uses best-effort `write_audit`. A failed create audit does not roll back the payment.
10. A failed required index, including `operation_id`, makes `/health/ready` return `not_ready`. Startup does not abort. Until that index exists, a concurrent duplicate audit insert is not rejected by the database. The application still looks up `operation_id` before insert.

Enrollment `payment_status` and ledger `payment_status` stay separate. Reports stay read-only. A cancelled enrollment still occupies `(student_id, course_id)`.

## Database verification

Not run against a live server. `MONGODB_TEST_URI` and `MONGODB_TEST_DB` were unset. The application database settings were not used. Production data was not modified. Do not point the suite at `MONGODB_URI` or the `bvonix_academy` database.

To run the skipped test later, set both variables to an isolated database whose name starts with `bvonix_test`, then run the same unittest command. The guard refuses `production`, `prod`, `bvonix_academy`, and any name containing `prod`.

## Deployment checklist

1. Set `APP_ENV=production` only on the production process.
2. Set `MONGODB_URI` to a TLS URI that does not disable certificate checks. Set `MONGODB_DB` explicitly.
3. Set `JWT_SECRET` to a random value of at least 32 bytes. Leave `JWT_ALGORITHM=HS256`. Startup fails if the example placeholder is still set.
4. Set `ALLOWED_ORIGINS` to the deployed frontend origins.
5. Start with `uvicorn app.main:app --host 0.0.0.0 --port 8000` from `bvonix_academy_backend` after `pip install -r requirements.txt`.
6. Confirm `GET /health/live` is alive and `GET /health/ready` is ready. Ready includes the database, upload storage, and required indexes. Live does not ping MongoDB. `indexes: down` means a required unique index was not created.
7. Confirm the startup log says indexes were created. If it reports index failures, `/health/ready` stays `not_ready` until the required indexes exist. Repair them before sending traffic.
8. From `bvonix_academy_frontend`, run `npm ci` and then `npm run build`, and serve `dist/`. The dependency-remediation pass completed `npm ci`. If a later `npm ci` hits `EPERM` on a native binary, close programs locking `node_modules` and retry `npm ci`.
9. Run the read-only reports against a copy or a `bvonix_test*` database. Do not pass `--write` against production.

```text
.\.venv\Scripts\python.exe scripts\payment_consistency_report.py --uri <uri> --database <name>
.\.venv\Scripts\python.exe scripts\registration_consistency_report.py --uri <uri> --database <name>
.\.venv\Scripts\python.exe scripts\reconcile_enrolled_courses.py --uri <uri> --database <name>
```

## Rollback

Redeploy the previous backend and frontend builds. This pass did not migrate data, did not add a collection, and did not drop an index. New audit documents may contain `operation_id`. Older audit documents remain valid because the index is sparse. Enrollment and payment documents may contain `audit_pending` until a retry clears it. Leaving that field in place does not change public responses.

Do not delete audit logs, enrollments, payments, attendance, results, or certificates to undo this release. Do not run `scripts/reconcile_enrolled_courses.py --write` against production.

## Staging smoke test

Not performed. Before production, on an isolated staging process:

1. Start with production settings and a non-production database.
2. `GET /health/live` returns alive. `GET /health/ready` returns ready, with database, storage, and indexes up.
3. Log in, refresh, and confirm an archived account cannot refresh.
4. Open one receipt and one profile image as the owner and as an admin. Confirm another student receives 403, and an anonymous `GET /uploads/payment_receipts/...` receives 404.
5. Confirm a public logo under `/uploads/logos/` still loads.
6. Upload a receipt and verify an enrollment. Confirm no ledger row was created by those actions.
7. Run the three read-only report commands against the staging database. Do not pass `--write`.

## Frontend dependency remediation

This pass changed only `bvonix_academy_frontend/package-lock.json`. `package.json` ranges were already wide enough, so they were not edited. Application source was not edited. No dependency override was added. `npm audit fix --force` was not used. Tailwind CSS stayed at 3.4.19. Vite stayed at 5.4.21.

The frontend is not vulnerability-free.

| Audit | Before | After |
| --- | --- | --- |
| `npm audit` | 27 (1 low, 8 moderate, 18 high, 0 critical) | 11 (0 low, 5 moderate, 6 high, 0 critical) |
| `npm audit --omit=dev` | 6 (4 moderate, 2 high) | 2 (2 moderate, 0 high) |

Production findings that remain:

- `react-router@6.30.6` and `react-router-dom@6.30.6` are still inside `>=6.0.0 <7.18.0` / `>=6.4.0 <7.18.0`. The open-redirect advisory is [GHSA-wrjc-x8rr-h8h6](https://github.com/advisories/GHSA-wrjc-x8rr-h8h6). The constructor-injection advisory is [GHSA-337j-9hxr-rhxg](https://github.com/advisories/GHSA-337j-9hxr-rhxg) and applies to React Router SSR error deserialization. The audit's fix is `react-router-dom@7.18.4`, which is a major upgrade and was not applied.

Development-only findings that remain:

- `braces@3.0.3` ([GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm), versions `<=3.0.3`). 3.0.3 is the newest published release. `micromatch@4.0.8`, `chokidar@3.6.0`, `fast-glob@3.3.3`, and `tailwindcss@3.4.19` depend on that chain. There is no compatible patched `braces` to override to.
- `esbuild@0.21.5` ([GHSA-67mh-4wv8-2f99](https://github.com/advisories/GHSA-67mh-4wv8-2f99), versions `<=0.24.2`). Vite 5 depends on `esbuild ^0.21.3`. This is a development-server issue.
- `vite@5.4.21` is inside `<=6.4.2`: path traversal in optimized dependency source maps ([GHSA-4w7w-66w2-5vf9](https://github.com/advisories/GHSA-4w7w-66w2-5vf9)), NTLMv2 disclosure through `launch-editor` on Windows ([GHSA-v6wh-96g9-6wx3](https://github.com/advisories/GHSA-v6wh-96g9-6wx3)), and `server.fs.deny` bypass on Windows alternate paths ([GHSA-fx2h-pf6j-xcff](https://github.com/advisories/GHSA-fx2h-pf6j-xcff)). These affect the development server. The audit's only offered fix is `vite@8.3.4`.
- `postcss-selector-parser@6.1.4` is still `<7.1.6` ([GHSA-rj75-hqrm-r3gf](https://github.com/advisories/GHSA-rj75-hqrm-r3gf)). Tailwind 3.4.19 requires `^6.1.2`, and `postcss-nested@6.2.0` requires `^6.1.1`. Parser 7.1.6 is outside those ranges. `postcss-nested@8` can take parser 7, and Tailwind 3 cannot.

Resolved by the lockfile update, inside the existing major versions:

- `axios` 1.13.2 → 1.20.0, which also moved `follow-redirects` to 1.16.1 and `form-data` to 4.0.6.
- `react-router-dom` 6.30.3 → 6.30.6, `react-router` 6.30.3 → 6.30.6, and `@remix-run/router` 1.23.2 → 1.23.4. That clears the 6.30.2–6.30.5 open-redirect advisory and the router advisory below 1.23.3. It does not clear the 7.18.0 advisories above.
- `postcss` 8.5.6 → 8.5.29.
- `@babel/core` 7.28.6 → 7.29.7, `ajv` 6.12.6 → 6.15.0, `baseline-browser-mapping` 2.9.17 → 2.11.28, `brace-expansion` 1.1.12 → 1.1.21, `browserslist` 4.28.1 → 4.29.3, `flatted` 3.3.3 → 3.4.4, `js-yaml` 4.1.1 → 4.3.2, `minimatch` 3.1.2 → 3.1.5, `nanoid` 3.3.11 → 3.3.20, `picomatch` 2.3.1 → 2.3.2 and 4.0.3 → 4.0.7, `postcss-selector-parser` 6.1.2 → 6.1.4, `rollup` 4.56.0 → 4.64.3, and `source-map-js` 1.2.1 → 1.2.2.

`npm audit fix` (without `--force`) proposed those updates in a dry run. The dry run did not select Tailwind 4 or Vite 8. The same command was then applied. `axios@1.20.0` also replaced `proxy-from-env@1.1.0` with `proxy-from-env@2.1.0` because that is the range axios 1.20 declares.

Install scripts were not approved. `ignore-scripts` is false and `allow-scripts` is empty, so npm still warns that `core-js@3.50.0` and `esbuild@0.21.5` are outside `allowScripts`. `core-js`'s postinstall only prints a funding banner. `esbuild`'s postinstall links the platform binary. After `npm ci`, `node_modules\@esbuild\win32-x64\esbuild.exe` was present and `node node_modules\esbuild\bin\esbuild --version` printed `0.21.5`. The production build used that binary, so no extra script approval was required.

Checks on this pass:

- `npm ci`: PASS. Exit 0. Added 408 packages and audited 409. The lockfile was not rewritten by `npm ci`.
- `npm run lint`: PASS.
- `npm run build`: PASS. Vite 5.4.21 transformed 592 modules and wrote `dist/`. The existing `@import` ordering warning and the large-chunk warning were still printed.
- `npm audit` and `npm audit --omit=dev`: PASS as commands. Both still exit 1 because findings remain. Counts are in the table above.
- Vite major: PASS, still 5.4.21. Tailwind major: PASS, still 3.4.19.

A separate migration would be required to clear the rest: React Router 7.18 or newer for the two production advisories, Tailwind CSS 4 to leave the `braces` chain and to allow `postcss-selector-parser` 7.1.6, and Vite 8.3.4 as the audit's offered fix for `vite` and `esbuild`. Those upgrades were not mixed into this pass.

## Remaining limits

- Live pagination, archive filters, counts, and index creation were not executed against MongoDB.
- No staging deployment was tested.
- The verification pass did not complete `npm ci` (`EPERM` on `esbuild.exe`). The later dependency-remediation pass did. See that section for the remaining audit findings.
- The frontend is not vulnerability-free. Eleven findings remain: two moderate production findings in React Router 6, and nine development-tool findings that need a Tailwind 4 or Vite 8 migration.
- The Vite build warns that a CSS `@import` follows other rules. The stylesheet still built.
- The business write and the audit insert are not one transaction. Recovery depends on retrying the same decision.
- Ledger creation can succeed without an audit row.
- Create, cancel, and compatibility-list repair are still separate writes.
- A cancelled enrollment still holds the unique student and course pair.
- Card PDF generation can leave a file if the enrollment update fails after the file is written.
- Decisions that never stored `audit_pending` are not backfilled.
- The instructor workspace is not implemented.
- There is no frontend unit-test script.
- Unauthenticated private-file rejection was verified through the route dependency and `get_current_user`. This environment does not have the `httpx2` package Starlette’s test client requires, so that check was not an HTTP call.

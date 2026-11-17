# Diesel Desk

Diesel Desk is being migrated in phases to a React/Vite frontend and a
FastAPI-backed local database. The legacy HTML/CSS/JavaScript files remain in
the repository while the replacement is verified.

## Run the development app

These commands use a Bash-compatible shell (macOS/Linux). Do not commit the
local `.env` file, SQLite database, or uploaded files.

Start the FastAPI backend in one terminal:

```bash
cd Fuel_App
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`: set a fresh `FUEL_AUTH_SECRET` (at least 32 characters), your
initial administrator email and name. Generate a secret with:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Load the local values and initialize the database and first administrator:

```bash
set -a
. ./.env
set +a
python -m alembic upgrade head
python -m backend.app.cli bootstrap-admin
python -m uvicorn main:app --reload
```

For an explicit local run against Neon instead of SQLite, load the local
settings first and then let Neon's values override the database URLs:

```bash
set -a
. ./.env
. ./.env.local
set +a
python -m alembic upgrade head
python -m uvicorn main:app --reload
```

The app uses pooled `DATABASE_URL`; Alembic uses `DATABASE_URL_UNPOOLED` when
available. Leave `.env.local` unloaded for normal SQLite development.

The administrator command prompts for a password. It is only needed once for a
new local database. For local photo OCR with Tesseract, install the Tesseract
system application as described in Phase 7 below.

In a second terminal, from the project root, install and start the React/Vite
frontend:

```bash
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite (normally [http://localhost:5173](http://localhost:5173)).
Vite proxies API and logo requests to FastAPI on port 8000. FastAPI's API
documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Cloud deployment preparation

Deployment configuration is prepared on the `deployment/cloud-hosting` branch.
No cloud resources are created by this repository and no company data is
imported. The Render start command applies schema-only Alembic upgrades.

### Configuration

- **Cloudflare Pages:** set the project root to `frontend`, build with
  `npm ci && npm run build`, and use `dist` as the build output directory.
  Choose a Pages project name to reserve its stable
  `https://<project-name>.pages.dev` production URL. Vite's output is a static
  React build; Pages handles SPA route fallback.
- **Same-origin API proxy:** `frontend/functions/api/[[path]].js` forwards
  `/api/*` requests to the `API_ORIGIN` Pages Function environment variable.
  Set `API_ORIGIN` to the Render service's HTTPS origin in the production
  environment. Leave previews disconnected from production data, or use a
  separate backend and allowlist for preview testing. This keeps
  the HttpOnly session cookie on the Pages domain instead of relying on
  cross-site cookies. Keep `VITE_API_BASE_URL` empty for this setup.
- **Render:** create the backend Web Service from this branch using
  [`render.yaml`](./render.yaml). Production OCR uses Google Cloud Vision;
  configure `GOOGLE_CLOUD_VISION_API_KEY` as a secret in Render. The Docker
  image also installs Tesseract for local or explicitly selected Tesseract
  deployments. The service starts with `python -m alembic upgrade head` before
  Uvicorn. The blueprint disables standalone manual meter entry in production;
  employees can still correct OCR readings after uploading a photo. Configure
  every `sync: false` variable in Render's environment settings.
- **CORS:** set `FUEL_CORS_ORIGINS` on Render to the exact production Pages
  origin (for example `https://diesel-desk.pages.dev`), without a trailing
  slash. Do not use a wildcard or a preview URL for production.
- **Database:** create a Neon PostgreSQL database and set Render's
  `DATABASE_URL` to Neon's pooled PostgreSQL connection string with SSL
  enabled. Set `DATABASE_URL_UNPOOLED` to Neon's direct connection string for
  Alembic migrations; the backend selects it only for migrations and keeps the
  pooled URL for application requests. SQLAlchemy converts PostgreSQL URLs to
  the installed psycopg driver. Local development continues to default to
  SQLite. To opt into Neon locally, load the variables generated in `.env.local`
  into the shell before starting the backend; do not source that file for
  routine SQLite development.
- **Photo storage:** create a private Cloudflare R2 Standard bucket, keep
  public access disabled, and create an R2 token scoped to that bucket. Set
  Render's `FUEL_PHOTO_STORAGE=r2`, `R2_ACCOUNT_ID`, `R2_BUCKET_NAME`,
  `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`. The backend stores only a
  generated object key and photo metadata in PostgreSQL; private photo reads
  pass through authenticated API endpoints. Do not configure an object
  lifecycle rule that deletes fuel photos.
- **Secrets:** put database credentials, R2 credentials, `FUEL_AUTH_SECRET`,
  and `GOOGLE_CLOUD_VISION_API_KEY` only in Render's backend environment. For
  an existing manually created Render service, set
  `FUEL_OCR_PROVIDER=google_vision` and add a restricted Vision API key there,
  Production OCR is configured to use Google Cloud Vision; add a restricted
  Vision API key in Render before deploying. Then redeploy. Never prefix a
  secret with `VITE_`. Pages needs only `API_ORIGIN`.
- **Administrator:** after Render has applied migrations, bootstrap the first
  admin once from a trusted local shell using the production Neon URL and the
  existing `python -m backend.app.cli bootstrap-admin` command. It prompts for
  the password without echoing it. Do not run demo seed/reset commands against
  PostgreSQL; those commands are restricted to local SQLite.

### Manual deployment sequence

1. Review and commit the deployment changes on `deployment/cloud-hosting`.
   Push only after approving the push:

   ```bash
   git push -u origin deployment/cloud-hosting
   ```

2. In Cloudflare Pages, create a Git-connected project from
   `deployment/cloud-hosting`, choose its permanent project name, and enter the
   build settings above. Set `API_ORIGIN` to the HTTPS Render service origin
   after that service exists. The Pages URL is the exact origin to enter in
   Render's `FUEL_CORS_ORIGINS`.
3. In Neon, create a PostgreSQL project/database and copy both its pooled and
   direct connection strings. Use the pooled URL for Render's `DATABASE_URL`
   and the direct URL for `DATABASE_URL_UNPOOLED`; keep both backend-only. Do not
   point local SQLite commands at these URLs.
4. In Cloudflare R2, create a private Standard bucket and a scoped S3 API
   token. Copy the account ID, bucket name, access key, and secret key to the
   matching Render environment variables. Do not enable public bucket access.
5. In Render, create the Web Service from the pushed branch using
   `render.yaml`. Set both database URLs, the exact Pages `FUEL_CORS_ORIGINS`,
   and all R2 variables. Confirm the generated `FUEL_AUTH_SECRET` is present
   and the deploy health check passes at `/healthz`.
6. From a trusted local terminal, set the production Neon URL,
   `FUEL_ADMIN_EMAIL`, and `FUEL_ADMIN_NAME` for one command, then run
   `python -m backend.app.cli bootstrap-admin`. The command prompts for a new
   admin password. Clear the temporary production URL from that shell after
   the command completes.
7. Set Pages' production `API_ORIGIN` to the Render service's HTTPS origin and
   redeploy Pages. Verify login, logout, role restrictions, an employee's
   photo upload/retrieval, and an Admin/Boss photo view with test data before
   entering company data.
8. Use a disposable Neon database and private test bucket first. Back up
   production before future schema changes. The Render start command runs only
   additive Alembic upgrades; it does not reset or delete database rows.

### Free-tier and readiness limitations

- Render Free Web Services sleep after 15 minutes without traffic; waking can
  take about a minute. Their filesystem is ephemeral and is lost on restart,
  sleep, or deploy, so SQLite and local uploads are not production storage.
  Render documents 750 free instance-hours per workspace/month, usage limits
  for bandwidth/build minutes, and warns that Free services are not for
  production. Review current [Render Free limits](https://render.com/docs/free)
  and billing settings before use.
- Neon Free currently includes 100 compute-hours per project, scale-to-zero
  after five minutes, and 1 GB of database storage per project (20 GB total per
  account). Monitor limits and costs; paid Launch usage is metered. See
  [Neon pricing](https://neon.com/pricing).
- Cloudflare R2 Standard currently includes 10 GB-month storage, 1 million
  Class A requests, and 10 million Class B requests monthly; standard Internet
  egress is free. Above the included usage, Standard storage is currently
  $0.015/GB-month, Class A is $4.50/million requests, and Class B is
  $0.36/million requests. Since Diesel Desk intentionally does not delete old
  meter photos, storage usage grows over time. See
  [R2 pricing](https://developers.cloudflare.com/r2/pricing/).
- Cloudflare Pages Free currently allows 500 builds/month, 20,000 static files,
  and a 25 MiB maximum per asset. Pages Functions share the Workers Free quota
  of 100,000 requests/day and 10 ms CPU per invocation. Workers Paid currently
  starts at $5/month if more capacity is needed. See
  [Pages limits](https://developers.cloudflare.com/pages/platform/limits/) and
  [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/).
- These changes have not been deployed or tested against real Neon or R2
  resources. Local SQLite, local photo storage, and mocked R2 behavior can be
  tested from the repository; actual cloud persistence, billing, and the full
  live deployment flow still require manual setup and verification.

## Phase 2 status

- The React/Vite interface preserves the existing layout, responsive styling,
  history, JSON exports, email drafts, and company logo assets. The original
  stylesheet remains in place while a copy is used by the React app.
- No production Supabase configuration is present in this project; none has
  been added or changed.

## Phase 3 status

- SQLAlchemy persistence is separated into backend models, schemas,
  repositories, services, and API routers.
- Alembic owns the schema at `data/diesel-desk-dev.sqlite`; run
  `python -m alembic upgrade head` before starting FastAPI.
- SQLite connections enable foreign-key enforcement. Demo rows are created only
  by the explicit local seed command. Fuel submissions remain gated on verified
  meter readings and the vehicle/odometer checks below.

## Phase 4 status

- Employee login uses Argon2 password hashes and a short-lived HttpOnly,
  SameSite=Strict cookie. Set `FUEL_AUTH_SECRET` to a random secret of at least
  32 characters before starting FastAPI. Set `FUEL_COOKIE_SECURE=true` when
  serving over HTTPS.
- Login accepts either the employee username or email. Random session tokens
  expire after 30 minutes; only their SHA-256 hashes are stored, and logout
  revokes the session. Login is limited to five attempts per client in 15
  minutes.
- Bootstrap the first administrator once with `FUEL_ADMIN_EMAIL` and
  `FUEL_ADMIN_NAME` set; the CLI prompts for the password without echoing it.
  The admin can then create employee accounts and add registered vehicles.
- A registered vehicle can be assigned to multiple employees from the Registry.
  The assignment list displays how many employees share each vehicle.
- The Registry supports Diesel, AdBlue, and Petrol fuel types when registering a
  vehicle or creating an employee with a new vehicle. Fuel type and tank capacity
  must be configured before that vehicle can record a fill.
- Authenticated employees can look up vehicles available to them by registration.
  Boss accounts can search all active registered vehicles for a fuel entry. The
  registries start empty; sample identities and vehicles are created only when the
  explicit local demo seed command is run.
- Fuel-record reads now require authentication. Fuel-record submissions require
  either verified meter-photo readings or confirmed manual readings, along with
  server-side vehicle ownership checks. Reads return only the authenticated
  employee's records.

## Phase 5 status

- Authenticated `GET /api/dashboard` and `GET /api/inventory` endpoints expose
  only an explicit "source not configured" status. The inventory response has
  an empty item list; no metrics or stock figures are fabricated.
- The React dashboard and inventory views display the same no-data state.
- No inventory schema, inventory rows, or stock updates were added. A verified
  local source is required before implementing real inventory figures.

## Phase 6 status

- Admins can issue or rotate an opaque vehicle QR token. Only its SHA-256 hash
  is stored in SQLite; the QR payload is shown once in the admin UI. Rotation
  invalidates the previously printed code.
- The photo flow creates a one-use session bound to the authenticated employee
  and vehicle. Employees are limited to assigned vehicles; Boss accounts can
  select another active vehicle from the fleet. Vehicles may be shared by multiple
  employees. Sessions expire after 10 minutes; the QR-session API remains
  available for QR-based clients.
- Meter-photo uploads accept verified JPEG/PNG images up to 10 MB. Files are
  written with private local permissions under `uploads/meter-photos/`; the
  directory is not mounted or served as static content. SQLite stores only
  photo metadata and a private storage key.

## Phase 7: PIUSI meter readings

- After login, employee and vehicle details are retrieved from their existing
  SQLite rows. Vehicle responses include the most recently recorded odometer.
  Employee IDs are taken from the authenticated session; only Boss accounts may
  submit a vehicle ID, and the backend verifies it against the selected meter
  photo and active vehicle record.
- The filling action offers Automatic OCR and Manual entry. Manual entry is
  enabled by default and can be controlled with
  `FUEL_MANUAL_METER_ENTRY_ENABLED=false`. It works without OCR or internet
  connectivity for local development; a supporting photo is optional. The
  Render blueprint disables this standalone mode in production. Photo-backed
  OCR corrections remain available and retain the original photo as evidence.
- In the photo workflow, a private meter photo is stored. The backend applies
  EXIF orientation, locates and rectifies the green LCD area, crops its two rows
  separately, and uses OpenCV to classify seven-segment digits. It preserves
  the two rows' raw digits separately. The bottom-row recognizer also checks
  locally adaptive grayscale masks for lighting/color variation and requires
  six digits with matching mask results; otherwise it asks for manual review.
  Google Cloud Vision
  remains the primary production OCR provider; the backend requests both
  `TEXT_DETECTION` and `DOCUMENT_TEXT_DETECTION`, uses their text/bounds as
  additional evidence, and compares Vision digits with the independent segment
  result. Tesseract remains an optional local OCR provider.
- Both rows' raw digits are interpreted as integer milli-litres with three
  fractional decimal places (`22032` = `22.032 L`, `77001` = `77.001 L`,
  `100000` = `100.000 L`, and TOTAL `261563` = `261.563 L`). The row-specific
  decimal positions are retained for presentation. Original raw digit strings,
  including leading zeros, are preserved. Exact integer milli-litres are used
  for calculations; compatibility float fields are for display only.
- When the global-total difference is valid and within the fill limit, it is the
  transaction fill quantity. The top-row reading is stored separately as evidence.
  A valid first reading with a top-row fill is saved as a transaction and
  establishes the global baseline. Other suspicious but usable readings wait in
  the Admin Meter Review queue; neither a fuel record nor a global-total update
  occurs until an administrator approves them.
- The employee reviews the original photo and confirms the displayed digits.
  If the top row is unavailable, the app can calculate the fill from the
  positive difference between global totals and asks the employee to confirm
  the calculated amount. Manual and OCR values use the same validation.
- Clean reconciled readings and valid first-baseline readings are saved directly
  and appear in Admin Summary on its next refresh (automatic every 15 seconds
  while open, or via **Refresh summary**). Readings with warnings are held for
  Admin Meter Review. An administrator must inspect the original photo and add a
  review note before approval; stale readings cannot be approved after the
  global total changes.
  Zero/negative fills, fills over 100 L without a valid top-row value, missing
  fill amounts, unchanged totals, and duplicate submissions must be corrected
  by the employee before saving. Decreased totals and other suspicious but
  usable readings are saved with warnings without changing the shared total.
- A labeled reference image and dataset instructions are in
  [`tests/datasets/piusi_k600_3`](./tests/datasets/piusi_k600_3). The reference
  fixture labels the display's raw digits as `22032` and `261563`. This single
  photo does not establish general accuracy. Add further independently labeled,
  non-transaction photos there before assessing accuracy.
- The Render blueprint sets
  `FUEL_OCR_PROVIDER=google_vision`. Add `GOOGLE_CLOUD_VISION_API_KEY` as a
  secret in the Render backend environment. Local development defaults to
  Tesseract; to use Google Vision locally, set:

  ```bash
  export FUEL_OCR_PROVIDER=google_vision
  export GOOGLE_CLOUD_VISION_API_KEY="your restricted API key"
  ```

  Keep the key out of source control and the frontend; restrict it to the Vision
  API and your backend's use. In this mode, each meter photo is sent from FastAPI
  to Google as three OCR images (the full display and two digit-row crops). When
  the TOTAL crop is unreadable or low-confidence, the backend uses Vision's
  detected word bounds to crop and enlarge that exact row for a fourth pass.
  Google lists the first 1,000 Vision units per month as free; review the
  [current pricing](https://cloud.google.com/vision/pricing), enable quota/billing
  alerts, and get approval before sending company photos.
  When an LCD is detected, Vision receives a rectified display image and
  separate enhanced row crops. If the TOTAL crop is unreadable or low-confidence,
  the backend uses Vision's detected word bounds to crop and enlarge that exact
  row for a fourth pass. The Render configuration and Google key remain
  backend-only. Keep the key out of source control and the frontend; restrict it
  to the Vision API and your backend's use. Google lists the first 1,000 Vision
  units per month as free; review the
  [current pricing](https://cloud.google.com/vision/pricing), enable quota/billing
  alerts, and get approval before sending company photos. Local development
  automatically uses Google Vision when
  `GOOGLE_CLOUD_VISION_API_KEY` is configured, unless `FUEL_OCR_PROVIDER` is
  explicitly set to another provider.
  When `FUEL_ENV=production` and no provider is explicitly set, the backend
  defaults to Google Vision. If the key is missing, OCR reports that Vision is
  unavailable instead of silently falling back to local Tesseract.
- Install Tesseract only when using the local provider. On Windows, install
  `UB-Mannheim.TesseractOCR` with `winget install --id UB-Mannheim.TesseractOCR`;
  the backend detects the standard install location automatically. On macOS, use
  `brew install tesseract` or `sudo port install tesseract tesseract-eng`.
  Install Python dependencies with `python -m pip install -r requirements.txt`.
  Local OCR tries a centered, enlarged display crop with grayscale and thresholded
  variants, then retries the full photo if needed.
  If the backend does not inherit the MacPorts path, set
  `TESSERACT_CMD=/opt/local/bin/tesseract`; common MacPorts and Homebrew paths
  are also detected automatically.
- `FUEL_METER_TOLERANCE_LITRES` configures the reconciliation tolerance and
  defaults to `0.10 L`. `FUEL_METER_REVIEW_THRESHOLD_LITRES` flags larger
  cumulative increases and defaults to `100 L`; larger increases wait for
  administrator review.
- The additive `0016_piusi_exact_readings_and_reviews` migration adds exact
  integer/raw-digit columns and the administrator review queue. Migration
  `0018_global_total_millilitres` uses raw-digit evidence to normalize stored
  whole-digit readings, backfills exact values when they are precise to a
  thousandth of a litre, and keeps a rollback copy of changed compatibility
  values. Ambiguous historic values are preserved rather than guessed; if the
  active global total cannot be represented exactly, new fuel submissions are
  blocked until an administrator resolves it.
- Employees enter the current vehicle odometer in miles (to one decimal place)
  in the transaction form. Readings are stored and sent through the API in
  miles. Existing kilometre readings are converted to the nearest tenth of a
  mile by the odometer-units migration. A reading below
  the vehicle's latest recorded odometer is blocked unless an administrator
  authorizes that exact lower value for one-time use, with a reason. The
  authorization is tied to the vehicle, previous reading, employee, and
  resulting transaction.
- The additive Alembic migration preserves existing records. It backfills the
  new current-fill field from transaction quantity and cumulative totals only
  from the explicitly named legacy cumulative field; ambiguous legacy
  `current_fuel_reading` values are not copied.
- Employee and assigned-vehicle histories remain scoped to the authenticated
  employee. All new submission and meter-photo verification endpoints enforce
  photo, vehicle, and employee ownership server-side.

## Phase 8: global cumulative meter

- The additive `0010_global_cumulative_meter` migration creates a singleton
  global meter state and an auditable reset/replacement event table. Existing
  fuel records are retained and used to initialize the state from the latest
  chronological non-negative finite cumulative reading. When timestamps are
  tied, the highest reading is used. No local database snapshot or reading is
  required in the repository.
- Only accepted or Admin-approved fills update the global state, in the same
  database transaction as the fuel record. Exact integer totals, raw digits,
  previous accepted total, source, and photo references are retained. Duplicate
  evidence cannot update twice, and compare-and-swap revision checks prevent
  simultaneous submissions or stale reviews from changing the total.
- The Global Cumulative Total card and cross-employee history are available
  only to Admin and Boss accounts. FastAPI returns HTTP 403 to employees on
  global meter state, history, reset/replacement, and photo endpoints.
- Demo-employee submissions are marked as demo/test records in SQLite and in
  management history. They update only the local SQLite database; this
  application has no production Supabase connection.

## Phase 9: Boss workspace and fleet summary

- Boss accounts open the responsive Fleet Intelligence dashboard after sign-in.
  It includes fleet metrics, analytics, vehicle search, activity, and NCT status.
  Executive data endpoints require the `admin` or `boss` role and return HTTP
  403 to employees.
- Admins can update an employee or Boss account's role from **Employees**.
  They can also deactivate or reactivate those accounts. Deactivation revokes
  active sessions and blocks sign-in while preserving fuel and audit history;
  Admin accounts cannot be changed with these controls.
- Boss and Admin executive dashboard summaries, charts, vehicle search,
  activity, and NCT status include seeded demo rows and vehicles so the sample
  fleet is visible. Both views exclude vehicles classified as personal. Fuel
  costs are shown in EUR only when recorded; missing prices are reported rather
  than estimated. Demo records remain marked **DEMO / TEST**; a cumulative
  meter value linked to a demo transaction is sample data, not a verified live
  reading.
- The executive dashboard includes a searchable employee directory with
  assigned company vehicles, activity summaries, and paginated fuel histories
  for each employee. Fuel histories default to the last five years and support
  quick date presets or custom inclusive start/end dates. Bosses can review
  seeded demo employees and records.
- Boss accounts can use the separate **New fill** dashboard tab to record fuel
  for an assigned vehicle or find another active vehicle by registration number.
  The registration field suggests active vehicle numbers on focus and filters
  suggestions as the Boss types. It reuses the employee photo-verification and
  mileage workflow; meter readings must be verified before submission. Admin
  executive view remains focused on fleet management.
- Migration `0013_company_personal_vehicles` classifies existing vehicles as
  company vehicles by default. Admins can mark a newly registered vehicle as
  personal in either Registry form. Bosses can also assign an unclaimed
  personal vehicle to themselves; this assignment is kept separate from
  company fleet totals.
- Notifications are derived from current NCT, meter-review, and cost-completeness
  data. Read state is stored in the signed-in browser; no separate notification
  records or fabricated activity are created.
- No Boss account or production data is created by this feature. Apply local
  migrations with `python -m alembic upgrade head` before starting the backend.

## Testing the demo employee workflow

1. Apply local migrations and start the backend/frontend using the commands
   above. Do not run the seed command again just to log in; the existing local
   demo users and vehicles are reused.
2. Log in using `Tommy1` and password `123456`. The account page should show
   Tommy1's database identity, `DD-TOMMY-001`, its stored vehicle details, and the
   latest odometer reading.
3. Repeat with `Tommy2` through `Tommy10`; registrations run from
   `DD-TOMMY-002` through `DD-TOMMY-010`. Each account sees only its own history
   and assigned vehicle. These shared demo credentials are for local testing.
4. Select **Open camera**, allow camera access, and capture the PIUSI display
   with both rows in focus. Review the raw top-row and TOTAL-row digits against
   the meter before confirming. For example, `22032` is a 22.032 L fill and
   `261563` is a 261.563 L cumulative total. Local development may use manual
   entry without OCR; production requires the photo workflow, and corrections
   retain the uploaded photo as evidence. If the top row is unavailable, the app
   shows the calculated difference and requires you to confirm it. Browser
   camera access requires HTTPS (localhost is exempt).
5. If an odometer decreases, an administrator must authorize the exact
   corrected odometer from the local registry panel before the employee retries.
6. Submit a fuel record and confirm it appears in the Admin **Summary** after
   refresh or within 15 seconds. If readings are flagged, they remain pending in
   the Admin **Meter review** tab until approved or rejected with a note. Admins
   and Boss accounts can view
   **Global meter**. It shows
   the latest reading, previous reading and difference, update time, employee,
   vehicle, meter photo when available, and shared history. Tommy1 through Tommy10
   do not have access to this management-only view or its API endpoints.
7. Keep demo testing isolated: do not upload private company meter photos or use
   live meter readings with demo accounts. New demo-account fills are marked
   **DEMO / TEST** in management history and affect that local database's meter
   baseline.

## Admin dashboard

- Admin accounts open on **Summary** and have **Employees**, **Registry**, and
  **NCT Expiry** for management tasks. Employee
  accounts handle assigned vehicles and fuel entries; the Admin account does
  not have a personal **My vehicle** tab. Employees lets an admin select any
  account and view its fuel history and meter photos.
- Summary starts with the current calendar month and supports any start/end
  date range or all available dates. It shows fill count, recorded litres,
  recorded fuel cost, and the most-filled vehicles. The app does not infer a
  currency; it displays the stored cost values as entered.
- Employee listing, employee fuel-history, and fleet-summary APIs require the
  Admin role in FastAPI. Employees and Boss accounts cannot use these endpoints.

## NCT expiry monitoring

- Migration `0011_vehicle_nct_expiry` adds a nullable SQLite date to each
  vehicle. Existing vehicle details are preserved; an unset date is shown as
  **NCT date not set**.
- Migration `0012_shared_vehicles` preserves existing assignments in an
  employee-to-vehicle association table and allows multiple employees to share
  one vehicle. NCT monitoring still lists each vehicle once and displays all
  assigned employee names.
- The Admin dashboard's **NCT Expiry Alerts** card summarizes vehicles due in
  30 days or less and expired vehicles. **NCT Expiry Monitoring** lists every
  vehicle and lets management update or clear its date. Dates are displayed in
  Irish `DD/MM/YYYY` format.
- The NCT tab highlights the seven vehicle expiry dates closest to today and
  provides fleet search by registration, make, model, assigned employees, or
  status. Selecting a highlighted vehicle filters the full editable list to it.
  Expiry dates display and can be entered in `DD/MM/YYYY` format without a
  calendar. Select **Save** to submit a valid date change.
- Alert status is calculated from the current `Europe/Dublin` date whenever
  the API is requested: over 30 days is no alert; day 30 is Upcoming; days
  1–29 are Urgent; day 0 expires today; earlier dates are Expired. The UI
  refreshes while the monitoring view is open, and alerts are derived rather
  than stored, so refreshes do not create duplicate alert records.
- `GET /api/admin/nct-alerts`, `GET /api/admin/vehicles/nct`, and
  `PATCH /api/admin/vehicles/{vehicle_id}/nct` are protected by the FastAPI
  management-role dependency. Admin and future Boss roles are allowed;
  employees receive HTTP 403. No Boss account is created by this feature.
- The local demo seed assigns relative NCT dates to Tommy1 through Tommy10
  (7, 15, 28, 60, 75, 90, 120, 150, 180, and 200 days from seed time). The
  operation is idempotent and only touches marked demo accounts and vehicles.
  Running the seed command also upserts the existing demo fuel records.

## Local demo accounts

After upgrading the local database, seed clearly marked demo employees, assigned
vehicles, and fuel history with:

```bash
python -m alembic upgrade head
python -m backend.app.cli seed-demo-data
```

The seed is repeatable and does not delete or overwrite non-demo employees,
vehicles, or fuel records. It creates 10 demo accounts (`Tommy1` through
`Tommy10`), one demo vehicle per account, and three synthetic fuel records per
account. Demo passwords are Argon2-hashed in SQLite.

To replace an older local demo cohort and its test activity, run this one-time
command instead of `seed-demo-data`:

```bash
python -m backend.app.cli reset-demo-data
```

It replaces only the known demo cohort and its test fuel/photo/meter data.
Admin, Boss, non-demo employees, vehicles, and fuel records are preserved.
The Tommy records are fictional and marked **DEMO / TEST**. Both Admin and
Boss executive dashboards include these records in their totals.

Use Tommy1 through Tommy10 as the demo usernames and `123456` as their shared
password. These
credentials and generated records are for local testing only; do not use them
outside local development. Fuel history is returned only for the authenticated
employee, and the session cookie is revoked on logout.

## Clear local history

To clear local fuel, meter, photo, QR-session, correction, and login-session
history while keeping employee accounts, vehicles, and their assignments, run:

```bash
python -m backend.app.cli clear-history
```

The command is restricted to `data/diesel-desk-dev.sqlite` with local photo
storage. It also clears the stored meter baseline and removes local meter-photo
files. All users must sign in again afterward.

## One-time production data reset

For a destructive, one-time reset of the deployed app, run this command from
the Render Shell (not from a deploy/start command):

```bash
python -m backend.app.cli reset-production-data
```

The command only runs when `FUEL_ENV=production`, the configured database is
PostgreSQL, R2 storage is enabled, and exactly one admin account exists. It
deletes all application data except that admin account, including other
accounts, vehicles, fuel and meter history, sessions, and R2 meter photos.
The database schema and migration history remain in place; the admin must sign
in again. It requires typing `RESET <admin-email>` and never runs automatically
during deployment. Confirm the displayed PostgreSQL database name and type
`RESET <admin-email> <database-name>` when prompted.

Pause app activity before running it to avoid concurrent writes. The reset is
irreversible; take a database backup first if you may need the data later. R2
photos are deleted before database rows, so if photo or database deletion
fails, retry the command after reviewing its output.

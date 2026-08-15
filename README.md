# PeerEval

Online group peer evaluation. Lecturer creates a course, uploads a groups
spreadsheet, and creates an evaluation with her own criteria and rating scale.
Students open a link or scan a QR code, identify themselves by ID or name,
and rate the rest of their group. Averages and totals are computed
automatically.

## Stack

- **Frontend:** static HTML/CSS/vanilla JS → GitHub Pages
- **Backend:** Flask API → Render (or any host that runs Python)
- **Database:** SQLite locally, [Turso](https://turso.tech) (libSQL) in
  production, via the `libsql` package (Turso's current, actively
  maintained Python SDK) — same client, same SQL, only the connection
  string changes

## Project layout

```
backend/
  app.py                 Flask app factory
  db.py                  DB connection (local SQLite / Turso, same code path)
  models.py              Schema (run directly to (re)create tables)
  auth.py 
  .env
  reqiurements.txt
  db/
    local.db               Lecturer auth: email/password + Google OAuth
  routes/
    courses.py
    groups.py             Excel upload/parse
    evaluations.py        Criteria + scale, creation, link/QR
    submissions.py        Student lookup, submit
    dashboard.py          Completion tracking, results
  utils/
    excel_parser.py  Groups spreadsheet parser
frontend/
  index.html
  lecturer/  
    course.html
    course.js
    dashboard.html
    dashboard.js
    login.html
    login.js
    results.html
    results.js
                 login, dashboard, course detail, results
  student/ 
    evaluate.html
    evaluate.js               evaluate.html
  css/style.css
  js/api.js               <- API_BASE lives here
```

## Running locally

### Backend (also serves the frontend locally, same-origin)

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # LOCAL_DEV=1 is already set — fill in SECRET_KEY
python3 app.py                 # http://127.0.0.1:5000
```

Open `http://127.0.0.1:5000/lecturer/login.html` directly — with `LOCAL_DEV=1`,
Flask serves `frontend/` itself, so the browser session cookie is same-origin
and just works without HTTPS. (Cross-origin cookies need `SameSite=None` +
`Secure`, which real browsers only honor over HTTPS — that's the actual
GH-Pages/Render production setup, just not convenient for local testing.)

The schema is created automatically on startup (`init_db()` in `app.py`).
To reset the local database, delete `backend/db/local.db` and restart.

### Frontend only (optional — for iterating on the frontend against a
### separately-hosted backend, e.g. once staging is deployed)

```bash
cd frontend
python3 -m http.server 5500
```
Set `LOCAL_DEV` unset/false on the backend in this case, and point
`frontend/js/api.js`'s `API_BASE` at that backend's URL.

## Groups spreadsheet format

Expected columns (header names matched loosely, case-insensitive):
`Group Number | Name | ID` (or `Student ID`). The group column can be
merged-cell style — filled only on each group's first row — the parser
forward-fills it. Group sizes can vary.

## Deploying

### A note on the `libsql` package

If you ever see `pip install libsql-client` mentioned anywhere (older
tutorials, Turso's older docs) — don't use it. That package is archived
and its HTTP transport has response-parsing bugs against Turso's current
protocol (`KeyError: 'result'` on writes like `DELETE`). This project uses
`libsql`, the actively maintained SDK, with a plain `sqlite3`-style API.

### 1. Database: move to Turso

```bash
turso db create peer-eval
turso db show peer-eval          # copy the URL
turso db tokens create peer-eval # copy the token
```

Set on your backend host:
```
DB_URL=libsql://peer-eval-<your-org>.turso.io
DB_AUTH_TOKEN=<token>
```
Nothing else changes — `db.py` uses the same client either way. Run
`python3 models.py` once against the new `DB_URL` to create the schema on
Turso (or just start the app; `init_db()` runs on boot).

### 2. Backend: deploy to Render

1. Push `backend/` to a GitHub repo (or a `backend/` subfolder of one repo).
2. New Web Service on Render → connect the repo.
3. Build command: `pip install -r requirements.txt`
   Start command: `gunicorn app:app` (add `gunicorn` to requirements.txt for
   production — the Flask dev server used locally isn't meant for this).
4. Set environment variables: `SECRET_KEY`, `DB_URL`, `DB_AUTH_TOKEN`,
   `FRONTEND_URL` (your GitHub Pages URL), `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (Render URL +
   `/auth/google/callback`). **Do not set `LOCAL_DEV`** in production —
   leaving it unset switches the session cookie back to the cross-origin
   `SameSite=None; Secure` config that GH-Pages + Render (both HTTPS) need.

### 3. Frontend: deploy to GitHub Pages

1. Push `frontend/` (as the repo root, or via a `docs/` folder / gh-pages
   branch — whichever GitHub Pages workflow you prefer).
2. Enable Pages on the repo, pointing at that folder/branch.
3. Update `frontend/js/api.js` → `API_BASE` to your Render URL, commit, push.

### 4. Google OAuth

Create credentials at
https://console.cloud.google.com/apis/credentials → OAuth client ID → Web
application. Authorized redirect URI: `<your Render URL>/auth/google/callback`.

## Notes on behavior

- **One submission per student per evaluation, no reset** — enforced by a DB
  unique constraint on `(evaluation_id, evaluator_student_id)`, not just
  app-level logic.
- **Criteria and scale are fully lecturer-defined** per evaluation — nothing
  is hardcoded, though the course-creation form starts you off with a
  reasonable default (editable/removable) based on the sample sheet.
- **An evaluation's title/criteria/scale can be edited** any time before its
  first submission comes in (`PATCH /courses/:id/evaluations/:id`, or the
  Edit button on the course page). Once a submission exists, editing is
  blocked — changing criteria or scale afterward would silently invalidate
  answers already tied to specific criterion IDs and score values.
- **Results can be exported as CSV** (`.../results/export.csv`, or the
  Export CSV button on the results page) — per-student averages first,
  then the full individual evaluator breakdown below it.
- **Results show both individual evaluator scores and aggregated averages**
  per the lecturer's request — see `routes/dashboard.py`.
- Re-uploading a groups spreadsheet for a course replaces the existing
  groups/students for that course.

## Not yet built (natural next steps)

- Bulk notification to students who haven't submitted
- Anything for a lecturer managing multiple concurrent evaluations at once
  beyond the per-course list shown today
- Deleting a course/evaluation outright (currently create/edit/close only)

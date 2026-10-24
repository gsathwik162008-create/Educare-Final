# Student Success Dashboard

A simple, clear dashboard for college faculty, administrators, and students.
Anyone can understand each screen in 5 seconds without data expertise.

---

## What This Platform Does

1. **Shows How Students Are Doing**: Calculates an overall **Success Score** out of 100 based on five areas (Studies 35%, Attendance 20%, Job readiness 20%, Online learning and activities 15%, Skills and feedback 10%).
2. **Spots Who Needs Help Early**: Clear status tags show **Needs attention: Urgent**, **Needs attention: Soon**, or **Needs attention: Doing fine**.
3. **Helps Advisors Take Action**: Recommends support steps ranked by who to help first, showing how many points the score can improve by.
4. **Protects Student Privacy**: Students never see risk flags or ranks; they see their strengths, focus areas, and next steps to grow.

---

## Account access

Students can submit an account request only for a student record already present
in the database. Requests remain pending until an administrator approves them;
public registration cannot create administrator or faculty accounts. Authorized
staff accounts must be provisioned through a trusted administrative process.
Do not use published or shared demo credentials in a deployment.

Signing out clears the browser's authenticated state and revokes the current
session token on the server. Google sign-in is not enabled: OAuth client
credentials and a verified server-side OpenID Connect callback are not currently
configured.

---

## Running the Platform Locally

1. Copy `.env.example` to `.env`, then generate a secret key:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   Set the generated value as `SECRET_KEY` in `.env`.
   Set `CORS_ALLOWED_ORIGINS` to a comma-separated list of trusted frontend origins
   (for example, `https://dashboard.example.edu`). The local defaults allow only
   `http://localhost:8000` and `http://127.0.0.1:8000`.
2. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the web server:
   ```bash
   python -m uvicorn app.main:app --reload --port 8000
   ```
4. Open your browser:
   ```
   http://127.0.0.1:8000/
   ```

## Local demo accounts (isolated database)

Demo data is synthetic and is never created automatically at application startup.
Initialize it only in a separate local database named `campus_demo.db`; the
initializer rejects `campus.db` and non-SQLite database URLs. In PowerShell:

```powershell
$env:EDUCARE_ENABLE_DEMO_SEED = "1"
python seed_demo.py --database-url sqlite:///./campus_demo.db
$env:DATABASE_URL = "sqlite:///./campus_demo.db"
python -m uvicorn app.main:app --reload --port 8000
```

The seed command is idempotent: rerunning it leaves the seven seeded accounts
and their sample records unchanged. If the target contains other or partial
records, the command stops rather than replacing them. Demo passwords can be
customized in `DEMO_ACCOUNTS` in `seed_demo.py` before the first initialization;
the initializer will not reset existing password hashes. These credentials are
for local development only and must never be reused in a deployment.

**ADMIN**

| Username | Local demo password |
| --- | --- |
| `demo_admin` | `EduCare-Admin-Demo-2026!` |

**FACULTY**

| Faculty profile | Username | Local demo password | Assigned cohort |
| --- | --- | --- | --- |
| Asha Mehta | `demo_faculty_cse` | `EduCare-Faculty-CSE-2026!` | CSE demo students |
| Rohan Iyer | `demo_faculty_ece` | `EduCare-Faculty-ECE-2026!` | ECE demo students |

**STUDENTS**

| Student | Roll number / username | Local demo password |
| --- | --- | --- |
| Nisha Kapoor | `DEMO-CSE-001` | `EduCare-Student-01-2026!` |
| Arjun Rao | `DEMO-CSE-002` | `EduCare-Student-02-2026!` |
| Meera Nair | `DEMO-ECE-001` | `EduCare-Student-03-2026!` |
| Kabir Shah | `DEMO-ECE-002` | `EduCare-Student-04-2026!` |

## Importing Student CSV Data

The admin upload screen supports two modes:

- **Partial update** (default): upload one or more sources for existing students. Values from files that were not uploaded, and blank cells in a partial upload, remain unchanged. Partial imports do not create students.
- **Full import**: upload all seven source files. Every source must contain the same student IDs; included student records are inserted or updated, and students absent from the upload are not deleted.

All files are validated before records change. Invalid columns, identifiers, numbers, or conflicting duplicate rows reject the import. Exact duplicate rows are ignored and counted. CSV files are limited to 8 MB each and 20 MB per request. Scores and recommendations are recomputed only after the database update succeeds. Template-only columns without a corresponding database field are validated and reported as not persisted in the upload result.

## ML risk prediction limitations

The next-semester model labels a transition positive when the next semester's GPA drops by more than 0.5 **or** its backlog count increases. Features use only the current and earlier semester history: latest GPA, change from the prior contiguous semester, attendance average to date, cumulative backlogs, and current credits earned. Invalid or missing feature values are excluded from training and make an individual prediction unavailable rather than being treated as zero.

Evaluation uses transitions through semester 5 for training and semester 6→7 / 7→8 transitions for a held-out time period. Training weights compensate for class imbalance; reported precision, recall, F1, ROC-AUC (when both test classes exist), class counts, and confusion matrix are held-out results, not cross-validation. Transitions from the same students can occur in both periods, and rare positive outcomes make current performance too uncertain to claim reliable predictive quality. Risk explanations remain based on observed metrics and documented rule thresholds; feature importance is not causal and does not explain an individual prediction. Intervention recommendations use observed metrics and score-based rules, not ML probability.

## Student activity history

Staff profiles show a timeline only for existing timestamped advisor-intervention
and mentor-message records. Historical semester, assignment, and LMS activity
timestamps are not currently available. When there are no recorded events, the
profile reports that activity history is unavailable. A metrics import/update
timestamp is labeled separately and is not treated as student activity.

## Production deployment requirements

The `Procfile` starts the web process but does not provide durable database storage. The default `DATABASE_URL` uses a workspace-relative SQLite file; on an ephemeral host, that data may be lost when the instance is replaced. Configure `DATABASE_URL` to a durable database or a SQLite file on a persistent mounted volume, and verify backups and restore procedures. Set a unique, generated `SECRET_KEY` and explicit trusted `CORS_ALLOWED_ORIGINS` in the deployment environment; do not deploy with the published demo credentials or seed accounts. `MODEL_CACHE_PATH` may point to a writable persistent cache location, but a missing cache is treated as unavailable and can be regenerated after analytics are recomputed.

---

## Running the Self-Test

To verify that all features, role boundaries, scoring calculations, and API endpoints work properly, run:

```bash
python selftest.py
```

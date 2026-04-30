# MediSafe — AI-Powered Care Home Safety System

> A multimodal AI assistant that helps carers prevent medication errors, detect room hazards, and monitor patient health — all from a single browser screen.

---

## What it does

MediSafe covers three clinical safety tasks that are prone to human error during busy care shifts:

| Sub-case | What it does |
|---|---|
| **Medication Check** | Photographs a medicine box → reads the label with AI → checks it against the patient's care plan → returns SAFE / WARNING / UNREGISTERED / NO_CARE_PLAN |
| **Hazard Detection** | Photographs a room → AI detects fall risks (loose rugs, poor lighting, clutter) → returns risk level + action list |
| **Nutrition Tracking** | Before + after plate photos → AI compares both → estimates % consumed → flags low intake to nurse |
| **Wound Monitoring** | Today's wound photo → automatically compared with last saved photo → assesses healing trend → flags infection signs |

Additional features:
- Role-based authentication — Admin, Doctor, Carer
- Automatic medication reminders from the care plan database (no manual setup)
- Real-time WebSocket push notifications 10 minutes before each dose

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, FastAPI, Uvicorn |
| Database | PostgreSQL (psycopg2-binary) |
| AI Vision | Groq API — `meta-llama/llama-4-scout-17b-16e-instruct` |
| Scheduler | APScheduler |
| Real-time | WebSocket |
| Frontend | HTML5 / CSS3 / Vanilla JavaScript |
| Dev server | VS Code Live Server |
| Auth | SHA-256 + secrets (no external library) |

---

## Project structure

```
project/
│
├── backend/
│   ├── main.py           ← FastAPI app, all endpoints
│   ├── database.py       ← All DB functions (fresh connection per call)
│   ├── auth.py           ← Register, login, session, logout
│   ├── llm.py            ← Sub-case 1: medication verification
│   ├── hazard_llm.py     ← Sub-case 2: hazard detection
│   ├── monitor_llm.py    ← Sub-case 3: nutrition + wound monitoring
│   ├── scheduler.py      ← Auto reminder system (APScheduler)
│   └── .env              ← API keys and DB credentials (create this)
│
└── frontend/
    ├── login.html        ← Sign in / sign up page
    ├── index.html        ← Main 4-tab app
    ├── style.css         ← All styles
    └── script.js         ← All frontend logic
```

---

## Prerequisites

- Python 3.13
- PostgreSQL (with an existing `healthcare_db` database)
- Node.js (not required — only if regenerating docs)
- VS Code with the **Live Server** extension
- A free [Groq API key](https://console.groq.com)

---

## Setup

### 1. Clone and create virtual environment

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# Mac / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install fastapi uvicorn psycopg2-binary python-dotenv groq apscheduler
```

> **Python 3.13 on Windows** — use the binary wheel to avoid build errors:
> ```bash
> pip install psycopg2-binary --only-binary=:all:
> ```

### 3. Create `.env` file

Create a file called `.env` inside the `backend/` folder:

```env
GROQ_API_KEY=your_groq_api_key_here

DB_NAME=healthcare_db
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_HOST=localhost
DB_PORT=5432
```

### 4. Check your database

Your PostgreSQL `healthcare_db` must have a `patients` table. The required columns are:

```sql
name       VARCHAR   -- patient's name
condition  VARCHAR   -- diagnosis or condition
care_plan  TEXT      -- comma-separated list of prescribed medicines
```

The system will automatically create these new tables on first startup:
- `users` + `sessions` — authentication
- `medication_times` — auto reminder schedule
- `wound_records` — wound image history (BYTEA)

### 5. Start the backend

```bash
cd backend
uvicorn main:app --reload
```

You should see:
```
[DB] medication_times table ready.
[DB] wound_records table ready (BYTEA).
[Auth] users + sessions tables ready.
[Startup] ✓ Default account created → username: admin  password: admin123
[Startup] 3 patient(s) found in existing database.
```

### 6. Open the frontend

In VS Code, right-click `frontend/login.html` → **Open with Live Server**.

This opens `http://127.0.0.1:5500/login.html` — the app is ready.

---

## Default login

On first run, a default admin account is created automatically:

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `admin123` |

Change this password after first login. You can register additional Doctor and Carer accounts from the sign-up page.

---

## How to use

### Medication Check
1. Sign in as any role
2. Go to **Medication Check** tab
3. Select a patient from the dropdown
4. Upload or photograph the medicine packaging
5. Click **Check this medicine**
6. If the result is UNREGISTERED, confirm with Yes/No whether the doctor prescribed it
7. If Yes, click **Update care plan** to save the new medicine directly to the database

### Hazard Check
1. Go to **Hazard Check** tab
2. Photograph the patient's room (show floor, walkways, lighting)
3. Click **Scan for hazards**
4. Review the risk level, hazards list, and recommended actions

### Nutrition Tracking
1. Go to **Patient Monitoring** → **Nutrition Tracking**
2. Select patient and meal type
3. Upload the **before** photo (full plate)
4. Upload the **after** photo (eaten plate)
5. Click **Compare & analyse**

### Wound Monitoring
1. Go to **Patient Monitoring** → **Wound Monitoring**
2. Select a patient — the system shows when the last wound photo was saved
3. Upload today's wound photo (the previous photo is fetched from the database automatically)
4. Optionally upload a previous photo manually to override the database version
5. Click **Assess & compare**

### Setting medication reminders (Doctor / Admin only)
1. Go to **Reminders** tab
2. Select a patient — the medicine dropdown auto-fills from their care plan
3. Set a dose time
4. Click **Set time**

The scheduler fires a WebSocket notification to all signed-in carers 10 minutes before each dose time — no manual setup needed on the carer's side.

---

## API endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | No | Create new user account |
| POST | `/auth/login` | No | Sign in, returns session token |
| POST | `/auth/logout` | Yes | Delete session token |
| GET | `/patients` | No | List all patients |
| POST | `/verify` | Yes | Medication verification |
| POST | `/scan_hazards` | Yes | Room hazard detection |
| POST | `/analyse_nutrition` | Yes | Nutrition before/after comparison |
| POST | `/analyse_wound` | Yes | Wound assessment and comparison |
| GET | `/wound_history` | Yes | Wound check history for a patient |
| GET | `/medication_times` | Yes | Full auto-reminder schedule |
| POST | `/medication_times` | Doctor/Admin | Set a dose time |
| DELETE | `/medication_times/{id}` | Doctor/Admin | Remove a dose time |
| POST | `/update_care_plan` | Yes | Append medicine to care plan |
| WS | `/ws/reminders` | No | WebSocket for push reminders |
| GET | `/debug/db` | No | Inspect table structure |

Full interactive API docs available at `http://127.0.0.1:8000/docs` when the server is running.

---

## Roles and permissions

| Action | Carer | Doctor | Admin |
|---|---|---|---|
| Medication check | ✓ | ✓ | ✓ |
| Hazard scan | ✓ | ✓ | ✓ |
| Nutrition tracking | ✓ | ✓ | ✓ |
| Wound monitoring | ✓ | ✓ | ✓ |
| View reminders | ✓ | ✓ | ✓ |
| Set / delete dose times | ✗ | ✓ | ✓ |
| Update care plans | ✓ | ✓ | ✓ |
| View all users | ✗ | ✗ | ✓ |

---

## Troubleshooting

**Server won't start — ImportError**
Make sure your `database.py` has all required functions. Run:
```bash
python -c "from database import get_all_patients, create_medication_times_table; print('OK')"
```

**Patient dropdown is empty**
Check what's in your database:
```
http://127.0.0.1:8000/debug/db
```
This shows your actual table columns and row counts. The `patients` table must have rows.

**Login returns 401**
The users table is empty — check terminal for `Default account created`. If not shown, the users table may already exist from a previous session. Use `admin` / `admin123` or register a new account.

**Nutrition shows 0%**
The two photos must be clearly different. Ensure the after photo shows a visibly emptier plate. The AI estimates REMAINING_VOLUME from the after photo alone — good lighting and a clear overhead angle give the best results.

**Wound shows "First check" even after multiple uploads**
The image was not saved correctly. Check terminal for `[DB] Wound saved for [patient], XXXX bytes`. If the size is 0 or missing, the BYTEA write failed — check PostgreSQL permissions and that `psycopg2.Binary()` is being used.

**Infinite loading on login page**
Clear browser localStorage: DevTools → Application → Local Storage → Clear all. Then sign in fresh.

**Live Server keeps loading**
Only open `login.html` in Live Server — not `index.html` directly. The redirects handle navigation between the two pages automatically.

---

## Environment variables reference

| Variable | Description | Example |
|---|---|---|
| `GROQ_API_KEY` | Groq API key from console.groq.com | `gsk_abc123...` |
| `DB_NAME` | PostgreSQL database name | `healthcare_db` |
| `DB_USER` | PostgreSQL username | `postgres` |
| `DB_PASSWORD` | PostgreSQL password | `yourpassword` |
| `DB_HOST` | Database host | `localhost` |
| `DB_PORT` | Database port | `5432` |

---

## Known limitations

- Deployed locally only — not on cloud infrastructure
- Groq free tier may rate-limit under heavy concurrent usage
- Nutrition accuracy depends on consistent photo angle and lighting
- Wound comparison requires photos taken at similar distance and focus

---
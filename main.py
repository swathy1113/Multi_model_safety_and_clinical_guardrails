from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect, Header
from fastapi.middleware.cors import CORSMiddleware
from database import (get_patient, get_all_patients, update_care_plan,
                      create_schedule_table, add_schedule_item, get_schedule_items,
                      save_wound_image, get_previous_wound, get_all_wound_records,
                      create_wound_table, create_medication_times_table,
                      get_all_medication_times, set_medication_time,
                      delete_medication_time, get_medication_times_for_patient)
from auth import create_users_table, register_user, login_user, get_session, logout_user, get_all_users
from llm import verify_medication_with_vision
from hazard_llm import detect_hazards
from monitor_llm import analyse_nutrition, analyse_wound
from scheduler import scheduler, connected_clients, add_reminder_to_memory
from pydantic import BaseModel
import asyncio
from typing import Optional

app = FastAPI(title="MediSafe API", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth helper ──────────────────────────────────────────────────
def require_auth(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").strip()
    user  = get_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in to continue")
    return user


@app.on_event("startup")
async def startup_event():
    import scheduler as sched_module
    sched_module.main_loop = asyncio.get_event_loop()
    print("[Startup] Event loop captured.")
    # Only create NEW tables that didn't exist before — never touch patients table
    create_schedule_table()
    create_wound_table()
    create_medication_times_table()
    create_users_table()
    
    from database import create_patients_table, seed_sample_patients
    create_patients_table()
    seed_sample_patients()

    # Create default admin only if users table is empty
    from database import get_conn
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
        cur.close()
        if count == 0:
            result = register_user("admin", "admin123", "Administrator", "admin")
            if result.get("success"):
                print("[Startup] ✓ Default account created → username: admin  password: admin123")
        else:
            print(f"[Startup] {count} registered user(s) found.")
        # Show patients count from existing DB
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM patients")
        pc = cur.fetchone()[0]
        cur.close()
        print(f"[Startup] {pc} patient(s) found in existing database.")
    except Exception as e:
        print(f"[Startup] {e}")
    finally:
        conn.close()


# ── Health ───────────────────────────────────────────────────────
@app.get("/debug/db")
def debug_db():
    """Shows actual table columns and row count — helps diagnose column name mismatches."""
    from database import get_conn
    conn = get_conn()
    info = {}
    try:
        cur = conn.cursor()
        for table in ["patients", "users", "medication_times", "wound_records"]:
            try:
                cur.execute("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = %s
                    ORDER BY ordinal_position
                """, (table,))
                cols = cur.fetchall()
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                info[table] = {
                    "columns": [{"name": c[0], "type": c[1]} for c in cols],
                    "row_count": count
                }
            except Exception as e:
                info[table] = {"error": str(e)}
        cur.close()
    except Exception as e:
        info["error"] = str(e)
    finally:
        conn.close()
    return info


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "5.0.0"}


# ══ AUTH ENDPOINTS ══════════════════════════════════════════════

class RegisterRequest(BaseModel):
    username:  str
    password:  str
    full_name: str
    role:      str = "carer"

@app.post("/auth/register")
def auth_register(req: RegisterRequest):
    result = register_user(req.username, req.password, req.full_name, req.role)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/auth/login")
def auth_login(req: LoginRequest):
    result = login_user(req.username, req.password)
    if "error" in result:
        print(f"[Login failed] username={req.username!r} reason={result['error']!r}")
        raise HTTPException(status_code=401, detail=result["error"])
    print(f"[Login OK] username={req.username!r} role={result.get('role')!r}")
    return result

@app.post("/auth/logout")
def auth_logout(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").strip()
    logout_user(token)
    return {"success": True}

@app.get("/auth/me")
def auth_me(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").strip()
    user  = get_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@app.get("/auth/users")
def auth_users(authorization: str = Header(default="")):
    user = require_auth(authorization)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return {"users": get_all_users()}


# ══ PATIENTS ════════════════════════════════════════════════════

@app.get("/patients")
def get_patients_endpoint():
    return {"patients": get_all_patients()}


# ══ MEDICATION TIMES (auto-reminder schedule) ════════════════════

class MedTimeRequest(BaseModel):
    patient_name: str
    medicine:     str
    dose_time:    str   # HH:MM

@app.get("/medication_times")
def get_medication_times(authorization: str = Header(default="")):
    """Get all medication times — used by reminders tab and scheduler."""
    require_auth(authorization)
    return {"schedule": get_all_medication_times()}

@app.get("/medication_times/{patient_name}")
def get_patient_medication_times(patient_name: str, authorization: str = Header(default="")):
    require_auth(authorization)
    return {"schedule": get_medication_times_for_patient(patient_name)}

@app.post("/medication_times")
def add_medication_time(req: MedTimeRequest, authorization: str = Header(default="")):
    user = require_auth(authorization)
    if user["role"] not in ("admin", "doctor"):
        raise HTTPException(status_code=403, detail="Only doctors and admins can set medication times")
    result = set_medication_time(req.patient_name, req.medicine, req.dose_time, user["username"])
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.delete("/medication_times/{record_id}")
def remove_medication_time(record_id: int, authorization: str = Header(default="")):
    user = require_auth(authorization)
    if user["role"] not in ("admin", "doctor"):
        raise HTTPException(status_code=403, detail="Only doctors and admins can remove medication times")
    result = delete_medication_time(record_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ══ VERIFY ══════════════════════════════════════════════════════

@app.post("/verify")
async def verify(
    file:          UploadFile = File(...),
    patient_name:  str        = Form(...),
    authorization: str        = Header(default="")
):
    require_auth(authorization)
    try:
        image_bytes = await file.read()
        patient     = get_patient(patient_name)
        if not patient:
            raise HTTPException(status_code=404, detail=f"Patient '{patient_name}' not found")
        result = verify_medication_with_vision(image_bytes, patient)
        return {
            "patient":      patient_name,
            "ocr_text":     result["ocr_text"],
            "result":       result["result"],
            "status":       result["status"],
            "treats":       result.get("treats", ""),
            "doctor_alert": result.get("doctor_alert", "")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══ HAZARD ══════════════════════════════════════════════════════

@app.post("/scan_hazards")
async def scan_hazards(file: UploadFile = File(...), authorization: str = Header(default="")):
    require_auth(authorization)
    try:
        return detect_hazards(await file.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══ NUTRITION ═══════════════════════════════════════════════════

@app.post("/analyse_nutrition")
async def nutrition_endpoint(
    before_file:   UploadFile = File(...),
    after_file:    UploadFile = File(...),
    meal_type:     str        = Form(default="meal"),
    patient_name:  str        = Form(default=""),
    authorization: str        = Header(default="")
):
    require_auth(authorization)
    try:
        before_bytes = await before_file.read()
        after_bytes  = await after_file.read()
        if not before_bytes or not after_bytes:
            raise HTTPException(status_code=400, detail="Both photos required")
        result = analyse_nutrition(before_bytes, after_bytes, meal_type)
        result["patient"] = patient_name
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══ WOUND ═══════════════════════════════════════════════════════

@app.post("/analyse_wound")
async def wound_endpoint(
    current_file:  UploadFile          = File(...),
    previous_file: Optional[UploadFile] = File(default=None),
    patient_name:  str                 = Form(...),
    notes:         str                 = Form(default=""),
    authorization: str                 = Header(default="")
):
    require_auth(authorization)
    try:
        current_bytes  = await current_file.read()
        previous_bytes = None
        previous_date  = ""
        source         = "none"

        if previous_file and previous_file.filename:
            previous_bytes = await previous_file.read()
            if previous_bytes:
                previous_date = "manually uploaded"
                source        = "manual"

        if not previous_bytes:
            prev = get_previous_wound(patient_name)
            if prev:
                previous_bytes = prev["image_bytes"]
                previous_date  = prev["recorded_at"]
                source         = "database"

        result = analyse_wound(current_bytes, patient_name, previous_bytes, previous_date)
        result["is_first_check"]      = (previous_bytes is None)
        result["comparison_source"]   = source
        result["previous_date"]       = previous_date if previous_bytes else None
        result["saved_to_db"]         = save_wound_image(patient_name, current_bytes, notes)
        result["history_count"]       = len(get_all_wound_records(patient_name))
        result["patient"]             = patient_name
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/wound_history")
def wound_history_get(patient_name: str = "", authorization: str = Header(default="")):
    require_auth(authorization)
    return {"patient": patient_name, "records": get_all_wound_records(patient_name) if patient_name else []}


# ══ UPDATE CARE PLAN ════════════════════════════════════════════

class CarePlanUpdate(BaseModel):
    patient_name: str
    new_medicine: str

@app.post("/update_care_plan")
def update_care_plan_endpoint(item: CarePlanUpdate, authorization: str = Header(default="")):
    require_auth(authorization)
    from database import update_care_plan
    result = update_care_plan(item.patient_name, item.new_medicine)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ══ SCHEDULE (legacy — kept for compat) ═════════════════════════

@app.get("/schedule")
def get_schedule(authorization: str = Header(default="")):
    require_auth(authorization)
    return {"schedule": get_all_medication_times()}


# ══ WEBSOCKET ════════════════════════════════════════════════════

@app.websocket("/ws/reminders")
async def websocket_reminders(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    print(f"[WS] Client connected. Total: {len(connected_clients)}")
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
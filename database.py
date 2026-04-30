import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",  "healthcare_db"),
    "user":     os.getenv("DB_USER",  "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host":     os.getenv("DB_HOST",  "localhost"),
    "port":     os.getenv("DB_PORT",  "5432"),
}

def get_conn():
    return psycopg2.connect(**DB_CONFIG)


# ─── Patients ─────────────────────────────────────────────────────

def create_patients_table():
    """Create patients table if it doesn't exist."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id         SERIAL PRIMARY KEY,
                name       VARCHAR(100) UNIQUE NOT NULL,
                condition  VARCHAR(200) DEFAULT '',
                care_plan  TEXT         DEFAULT ''
            )
        """)
        conn.commit()
        cur.close()
        print("[DB] patients table ready.")
    except Exception as e:
        conn.rollback()
        print(f"[DB create_patients_table] {e}")
    finally:
        conn.close()


def seed_sample_patients():
    """Insert sample patients if the table is empty."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM patients")
        count = cur.fetchone()[0]
        if count == 0:
            sample = [
                ("Priya",  "Fever",        "Paracetamol 500mg"),
                ("Suresh", "Diabetes",     "Metformin 500mg, Aspirin 75mg"),
                ("Aarthi", "Hypertension", "Amlodipine 5mg"),
                ("John",   "Arthritis",    "Ibuprofen 400mg"),
            ]
            cur.executemany(
                "INSERT INTO patients (name, condition, care_plan) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
                sample
            )
            conn.commit()
            print(f"[DB] Seeded {len(sample)} sample patients.")
        else:
            print(f"[DB] {count} patient(s) already in database.")
        cur.close()
    except Exception as e:
        conn.rollback()
        print(f"[DB seed_sample_patients] {e}")
    finally:
        conn.close()


def get_patient(name: str):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name, condition, care_plan FROM patients WHERE name=%s", (name,))
        data = cur.fetchone()
        cur.close()
        return data
    except Exception as e:
        print(f"[DB get_patient] {e}")
        return None
    finally:
        conn.close()


def get_all_patients():
    conn = get_conn()
    try:
        cur = conn.cursor()

        # Detect actual column names in existing DB — don't assume
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'patients' ORDER BY ordinal_position
        """)
        cols = [r[0] for r in cur.fetchall()]
        print(f"[DB] patients columns found: {cols}")

        if not cols:
            print("[DB] patients table not found or empty schema")
            cur.close()
            return []

        # Flexible column matching
        name_col      = next((c for c in cols if c in ("name","patient_name","full_name","patient")), cols[0])
        condition_col = next((c for c in cols if c in ("condition","diagnosis","illness","disease")), None)
        careplan_col  = next((c for c in cols if c in ("care_plan","careplan","medications","medication","prescription","medicines")), None)

        select_parts = [name_col]
        if condition_col: select_parts.append(condition_col)
        if careplan_col:  select_parts.append(careplan_col)

        query = f"SELECT {', '.join(select_parts)} FROM patients ORDER BY {name_col}"
        print(f"[DB] Running: {query}")
        cur.execute(query)
        rows = cur.fetchall()
        cur.close()
        print(f"[DB] get_all_patients: returned {len(rows)} rows")
        return [
            {
                "name":      str(r[0] or ""),
                "condition": str(r[1] or "") if len(r) > 1 else "",
                "care_plan": str(r[2] or "") if len(r) > 2 else ""
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[DB get_all_patients] ERROR: {e}")
        import traceback; traceback.print_exc()
        return []
    finally:
        conn.close()


def update_care_plan(patient_name: str, new_medicine: str) -> dict:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT care_plan FROM patients WHERE name=%s", (patient_name,))
        row = cur.fetchone()
        if not row:
            return {"error": f"Patient '{patient_name}' not found"}
        current = str(row[0] or "").strip()
        if current.startswith("[") or current.startswith("{"):
            try:
                import ast
                parsed = ast.literal_eval(current)
                if isinstance(parsed, list):
                    meds = []
                    for item in parsed:
                        if isinstance(item, dict):
                            meds.append(f"{item.get('name','')} {item.get('dosage','')}".strip())
                        else:
                            meds.append(str(item))
                    current = ", ".join(meds)
            except Exception:
                pass
        updated = f"{current}, {new_medicine}".strip(", ") if current else new_medicine
        cur.execute("UPDATE patients SET care_plan=%s WHERE name=%s", (updated, patient_name))
        conn.commit()
        cur.close()
        print(f"[DB] Care plan updated for {patient_name}: {updated}")
        return {"care_plan": updated, "message": "Care plan updated successfully"}
    except Exception as e:
        conn.rollback()
        print(f"[DB update_care_plan] {e}")
        return {"error": str(e)}
    finally:
        conn.close()


# ─── Schedule ─────────────────────────────────────────────────────

def create_schedule_table():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS medicine_schedule (
                id SERIAL PRIMARY KEY,
                patient_name VARCHAR(100) NOT NULL,
                medicine VARCHAR(200) NOT NULL,
                medicine_time TIME NOT NULL
            )
        """)
        conn.commit()
        cur.close()
        print("[DB] medicine_schedule table ready.")
    except Exception as e:
        conn.rollback()
        print(f"[DB create_schedule_table] {e}")
    finally:
        conn.close()


def add_schedule_item(patient_name: str, medicine: str, time: str) -> dict:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO medicine_schedule (patient_name, medicine, medicine_time) VALUES (%s,%s,%s::time)",
            (patient_name, medicine, time)
        )
        conn.commit()
        cur.close()
        return {"message": f"Reminder saved for {patient_name} at {time}"}
    except Exception as e:
        conn.rollback()
        print(f"[DB add_schedule_item] {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def create_medication_times_table():
    """
    medication_times stores when each patient should take each medicine.
    Doctor sets these — scheduler reads them to fire automatic reminders.
    Format: patient_name, medicine_name, time (HH:MM)
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS medication_times (
                id           SERIAL PRIMARY KEY,
                patient_name VARCHAR(100) NOT NULL,
                medicine     VARCHAR(200) NOT NULL,
                dose_time    TIME         NOT NULL,
                created_by   VARCHAR(100) DEFAULT '',
                UNIQUE(patient_name, medicine, dose_time)
            )
        """)
        conn.commit()
        cur.close()
        print("[DB] medication_times table ready.")
    except Exception as e:
        conn.rollback()
        print(f"[DB create_medication_times_table] {e}")
    finally:
        conn.close()


def get_all_medication_times() -> list:
    """
    Returns all scheduled medication times.
    Used by scheduler to fire automatic reminders.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT patient_name, medicine, dose_time
            FROM medication_times
            ORDER BY dose_time
        """)
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "patient":  r[0],
                "medicine": r[1],
                "time":     r[2].strftime("%H:%M") if hasattr(r[2], "strftime") else str(r[2])[:5]
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[DB get_all_medication_times] {e}")
        return []
    finally:
        conn.close()


def set_medication_time(patient_name: str, medicine: str, dose_time: str, created_by: str = "") -> dict:
    """Add or update a medication schedule time. Called by doctor/admin."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO medication_times (patient_name, medicine, dose_time, created_by)
            VALUES (%s, %s, %s::time, %s)
            ON CONFLICT (patient_name, medicine, dose_time) DO NOTHING
        """, (patient_name, medicine, dose_time, created_by))
        conn.commit()
        cur.close()
        print(f"[DB] Medication time set: {patient_name} - {medicine} at {dose_time}")
        return {"success": True}
    except Exception as e:
        conn.rollback()
        print(f"[DB set_medication_time] {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def delete_medication_time(record_id: int) -> dict:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM medication_times WHERE id=%s", (record_id,))
        conn.commit()
        cur.close()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}
    finally:
        conn.close()


def get_medication_times_for_patient(patient_name: str) -> list:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, medicine, dose_time FROM medication_times
            WHERE patient_name=%s ORDER BY dose_time
        """, (patient_name,))
        rows = cur.fetchall()
        cur.close()
        return [
            {"id": r[0], "medicine": r[1],
             "time": r[2].strftime("%H:%M") if hasattr(r[2], "strftime") else str(r[2])[:5]}
            for r in rows
        ]
    except Exception as e:
        print(f"[DB get_medication_times_for_patient] {e}")
        return []
    finally:
        conn.close()


def get_schedule_items() -> list:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT patient_name, medicine, medicine_time FROM medicine_schedule")
        rows = cur.fetchall()
        cur.close()
        return [
            {"patient": r[0], "medicine": r[1],
             "time": r[2].strftime("%H:%M") if hasattr(r[2], "strftime") else str(r[2])[:5]}
            for r in rows
        ]
    except Exception as e:
        print(f"[DB get_schedule_items] {e}")
        return []
    finally:
        conn.close()


# ─── Wound Records (BYTEA storage) ────────────────────────────────

def create_wound_table():
    """Creates wound_records with BYTEA image column. Auto-migrates from old TEXT version."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Check if old TEXT column exists → drop and recreate
        cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name='wound_records' AND column_name='image_data'
        """)
        row = cur.fetchone()
        if row and row[0] == 'text':
            print("[DB] Migrating wound_records TEXT→BYTEA, dropping old table")
            cur.execute("DROP TABLE wound_records")
            conn.commit()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wound_records (
                id           SERIAL PRIMARY KEY,
                patient_name VARCHAR(100) NOT NULL,
                image_data   BYTEA        NOT NULL,
                recorded_at  TIMESTAMP    DEFAULT NOW(),
                notes        TEXT         DEFAULT ''
            )
        """)
        conn.commit()
        cur.close()
        print("[DB] wound_records table ready (BYTEA).")
    except Exception as e:
        conn.rollback()
        print(f"[DB create_wound_table] {e}")
    finally:
        conn.close()


def save_wound_image(patient_name: str, image_bytes: bytes, notes: str = "") -> bool:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO wound_records (patient_name, image_data, notes) VALUES (%s,%s,%s)",
            (patient_name, psycopg2.Binary(image_bytes), notes)
        )
        conn.commit()
        cur.close()
        print(f"[DB] Wound saved for {patient_name}, {len(image_bytes)} bytes")
        return True
    except Exception as e:
        conn.rollback()
        print(f"[DB save_wound_image] {e}")
        import traceback; traceback.print_exc()
        return False
    finally:
        conn.close()


def get_previous_wound(patient_name: str) -> dict:
    """Get most recent wound record. Called BEFORE saving new image."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT image_data, recorded_at, notes
            FROM wound_records
            WHERE patient_name = %s
            ORDER BY recorded_at DESC
            LIMIT 1
        """, (patient_name,))
        row = cur.fetchone()
        cur.close()
        print(f"[DB get_previous_wound] patient={patient_name}, found={row is not None}")
        if not row:
            return None
        image_bytes = bytes(row[0])
        recorded_at = row[1].strftime("%d %b %Y %H:%M") if row[1] else "unknown date"
        print(f"[DB get_previous_wound] size={len(image_bytes)}, date={recorded_at}")
        return {"image_bytes": image_bytes, "recorded_at": recorded_at, "notes": row[2] or ""}
    except Exception as e:
        print(f"[DB get_previous_wound] {e}")
        import traceback; traceback.print_exc()
        return None
    finally:
        conn.close()


def get_all_wound_records(patient_name: str) -> list:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, recorded_at, notes FROM wound_records
            WHERE patient_name=%s ORDER BY recorded_at DESC
        """, (patient_name,))
        rows = cur.fetchall()
        cur.close()
        return [
            {"id": r[0],
             "recorded_at": r[1].strftime("%d %b %Y %H:%M") if r[1] else "",
             "notes": r[2] or ""}
            for r in rows
        ]
    except Exception as e:
        print(f"[DB get_all_wound_records] {e}")
        return []
    finally:
        conn.close()
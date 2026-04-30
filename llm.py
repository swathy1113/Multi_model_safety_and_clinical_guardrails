"""
llm.py — Medication Verification with Unknown Disease Handler

HANDLES 4 SCENARIOS:
─────────────────────────────────────────────────────────────────
1. SAFE        — Medicine matches patient's care plan exactly
2. WARNING     — Medicine doesn't match care plan (wrong med)
3. UNREGISTERED — Patient has care plan BUT scanned medicine is new/unknown
                  → AI identifies what condition the medicine treats
                  → Prompts carer to get doctor to update DB
4. NO_CARE_PLAN — Patient has no care plan at all in DB
                  → AI reads the medicine, flags for doctor review

WHY THIS MATTERS:
- A patient gets a new diagnosis mid-stay
- Doctor prescribes new medicine
- Carer scans it → old system says WARNING (false alarm)
- New system says UNREGISTERED + explains what it treats + alerts doctor
"""

import os
import base64
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = "meta-llama/llama-4-scout-17b-16e-instruct"


def verify_medication_with_vision(image_bytes: bytes, patient: tuple) -> dict:
    patient_name = patient[0]
    condition    = patient[1]
    raw_care_plan = str(patient[2] or "").strip()

    # ── FIX: Parse care_plan whether it's JSON or plain text ──────
    care_plan = _parse_care_plan(raw_care_plan)
    print(f"[LLM] Raw care_plan: {repr(raw_care_plan)}")
    print(f"[LLM] Parsed care_plan: {care_plan}")

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # ── STEP 1: Extract medicine from image ───────────────────────
    extracted = _extract_medicine(image_b64, image_bytes)
    scanned_medicine = extracted.get("medicine", "UNKNOWN")
    scanned_dosage   = extracted.get("dosage", "UNKNOWN")
    scanned_text     = f"{scanned_medicine} {scanned_dosage}".strip()

    print(f"[LLM] Extracted: {scanned_text}")

    # ── STEP 2: Handle no care plan in DB ─────────────────────────
    if not care_plan or care_plan.lower() in ("none", "null", "[]", "{}"):
        return _handle_no_care_plan(
            patient_name, condition,
            scanned_medicine, scanned_dosage, scanned_text
        )

    # ── STEP 3: Compare with care plan ────────────────────────────
    prescribed = [m.strip() for m in care_plan.split(",") if m.strip()]
    match_result = _compare_medicine(
        scanned_medicine, scanned_dosage, prescribed
    )

    status  = match_result.get("status", "WARNING")
    matched = match_result.get("matched", "none")

    print(f"[LLM] Match result status: {status}")

    # ── STEP 4: Handle unregistered medicine ──────────────────────
    if status == "UNREGISTERED":
        return _handle_unregistered(
            patient_name, condition, care_plan,
            scanned_medicine, scanned_dosage, scanned_text
        )

    # ── STEP 5: Return SAFE or WARNING ────────────────────────────
    message = match_result.get("message", "")

    ocr_display = (
        f"Detected: {scanned_text}\n"
        f"Prescribed: {care_plan}\n"
        f"Matched: {matched}"
    )

    return {
        "result":   f"{status}: {message}",
        "status":   status,
        "ocr_text": ocr_display
    }


# ── Helper: Parse care_plan from DB (handles JSON or plain text) ──
def _parse_care_plan(raw: str) -> str:
    """
    DB care_plan can be stored in different formats:
      Plain text:  "Metformin 500mg, Insulin 10 units"
      JSON list:   [{"name": "Metformin", "dosage": "500mg"}, ...]
      JSON string: '["Metformin 500mg"]'

    Always returns a clean comma-separated string like:
      "Metformin 500mg, Insulin 10 units"
    """
    raw = raw.strip()
    if not raw or raw in ("none", "null", "[]", "{}"):
        return ""

    # Try JSON parse if it looks like JSON
    if raw.startswith("[") or raw.startswith("{"):
        try:
            import json
            # Handle single-quoted JSON (Python dict repr) → double-quoted JSON
            import ast
            parsed = ast.literal_eval(raw)  # Safely parse Python list/dict literals
            medicines = []
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        name   = item.get("name", item.get("medicine", ""))
                        dosage = item.get("dosage", item.get("dose", ""))
                        if name:
                            medicines.append(f"{name} {dosage}".strip())
                    elif isinstance(item, str):
                        medicines.append(item.strip())
            elif isinstance(parsed, dict):
                name   = parsed.get("name", "")
                dosage = parsed.get("dosage", "")
                if name:
                    medicines.append(f"{name} {dosage}".strip())
            if medicines:
                return ", ".join(medicines)
        except Exception as e:
            print(f"[parse_care_plan] JSON parse failed: {e}, treating as plain text")

    # Plain text — return as-is
    return raw


# ── Helper: Extract medicine from image ───────────────────────────
def _extract_medicine(image_b64: str, image_bytes: bytes) -> dict:
    prompt = """Look at this medicine packaging image carefully.

Extract ONLY:
1. The medicine name (most prominent text on packaging)
2. The dosage/strength (number + unit like mg, ml, mcg)

Output format (exactly):
MEDICINE: <name>
DOSAGE: <strength>

If unreadable:
MEDICINE: UNREADABLE
DOSAGE: UNREADABLE"""

    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": prompt}
                ]
            }],
            max_tokens=100,
            temperature=0.1
        )
        text = res.choices[0].message.content.strip()
        result = {}
        for line in text.split("\n"):
            if line.upper().startswith("MEDICINE:"):
                result["medicine"] = line.split(":", 1)[1].strip()
            elif line.upper().startswith("DOSAGE:"):
                result["dosage"] = line.split(":", 1)[1].strip()
        return result
    except Exception as e:
        print(f"[Extract Error] {e}")
        return {"medicine": "UNREADABLE", "dosage": "UNREADABLE"}


# ── Helper: Compare medicine with care plan ───────────────────────
def _compare_medicine(scanned_medicine: str, scanned_dosage: str, prescribed: list) -> dict:
    prescribed_str = ", ".join(prescribed)

    # First do a simple rule-based check before calling LLM
    # This prevents LLM from defaulting to WARNING when it should be UNREGISTERED
    scanned_lower = scanned_medicine.lower().strip()
    name_found_in_plan = False
    for p in prescribed:
        p_name = p.split()[0].lower() if p.split() else ""  # First word = medicine name
        if p_name and (p_name in scanned_lower or scanned_lower in p_name):
            name_found_in_plan = True
            break

    print(f"[Compare] Scanned: '{scanned_medicine} {scanned_dosage}'")
    print(f"[Compare] Prescribed: {prescribed}")
    print(f"[Compare] Name found in plan: {name_found_in_plan}")

    prompt = f"""You are a medication safety checker. Give a ONE-WORD status only.

PRESCRIBED MEDICINES: {prescribed_str}

SCANNED MEDICINE: {scanned_medicine} {scanned_dosage}

DECISION:
- If the scanned medicine name matches ANY prescribed medicine AND dosage matches → reply SAFE
- If the scanned medicine name matches ANY prescribed medicine BUT dosage is different → reply WARNING  
- If the scanned medicine name does NOT match any prescribed medicine → reply UNREGISTERED
- If scanned medicine is UNREADABLE → reply WARNING

Reply with ONLY this format, nothing else:
STATUS: SAFE
MATCHED: <name or none>
MESSAGE: <one sentence>

Replace SAFE with WARNING or UNREGISTERED as appropriate."""

    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.0   # Zero temperature = most deterministic
        )
        text = res.choices[0].message.content.strip()
        print(f"[Compare LLM raw response]: {repr(text)}")

        result = {}
        for line in text.split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, val = line.partition(":")
                result[key.strip().upper()] = val.strip()

        llm_status = result.get("STATUS", "").upper().strip()
        print(f"[Compare] LLM status: '{llm_status}'")

        # Validate LLM returned one of the 3 expected values
        if llm_status not in ("SAFE", "WARNING", "UNREGISTERED"):
            # LLM gave unexpected output — use rule-based fallback
            print(f"[Compare] Unexpected status '{llm_status}' — using rule-based fallback")
            llm_status = "WARNING" if name_found_in_plan else "UNREGISTERED"

        return {
            "status":  llm_status,
            "matched": result.get("MATCHED", "none"),
            "message": result.get("MESSAGE", "")
        }
    except Exception as e:
        print(f"[Compare Error] {e}")
        # Fallback to rule-based when LLM fails
        status = "WARNING" if name_found_in_plan else "UNREGISTERED"
        return {"status": status, "matched": "none", "message": str(e)}


# ── Handler: Unregistered medicine (new condition) ────────────────
def _handle_unregistered(
    patient_name, condition, care_plan,
    scanned_medicine, scanned_dosage, scanned_text
) -> dict:
    """
    Patient has a care plan, but this medicine is not in it.
    AI identifies what the new medicine treats and flags for DB update.
    """
    prompt = f"""A carer scanned a medicine not in the patient's care plan.

PATIENT: {patient_name}
KNOWN CONDITION: {condition}
CURRENT CARE PLAN: {care_plan}

NEW/UNKNOWN MEDICINE SCANNED: {scanned_medicine} {scanned_dosage}

Your job:
1. Identify what medical condition or symptom {scanned_medicine} is typically used to treat
2. Check if it could be for a NEW condition the patient may have developed
3. Give a clear, calm message for the carer

Output format (exactly):
TREATS: <what condition/symptom this medicine typically treats>
NEW_CONDITION_LIKELY: yes or no
CARER_MESSAGE: <one clear sentence telling carer what to do>
DOCTOR_ALERT: <one sentence for the doctor about what to check/update>"""

    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250,
            temperature=0.2
        )
        text = res.choices[0].message.content.strip()

        parsed = {}
        for line in text.split("\n"):
            if ":" in line:
                key, _, val = line.partition(":")
                parsed[key.strip().upper()] = val.strip()

        treats         = parsed.get("TREATS", "unknown condition")
        carer_msg      = parsed.get("CARER_MESSAGE", "Please consult the doctor before administering.")
        doctor_alert   = parsed.get("DOCTOR_ALERT", f"Please review and update {patient_name}'s care plan.")
        new_likely     = parsed.get("NEW_CONDITION_LIKELY", "no").lower() == "yes"

        ocr_display = (
            f"Detected: {scanned_text}\n"
            f"Prescribed: {care_plan}\n"
            f"This medicine treats: {treats}\n"
            f"Status: NOT in care plan — possible new condition\n"
            f"Doctor alert: {doctor_alert}"
        )

        return {
            "result":         f"UNREGISTERED: {carer_msg}",
            "status":         "UNREGISTERED",
            "ocr_text":       ocr_display,
            "treats":         treats,
            "doctor_alert":   doctor_alert,
            "new_condition":  new_likely,
            "update_needed":  True
        }

    except Exception as e:
        print(f"[Unregistered Handler Error] {e}")
        return {
            "result":   f"UNREGISTERED: {scanned_medicine} is not in the care plan. Do NOT administer without doctor approval.",
            "status":   "UNREGISTERED",
            "ocr_text": f"Detected: {scanned_text}\nNot found in care plan: {care_plan}",
            "update_needed": True
        }


# ── Handler: No care plan at all ──────────────────────────────────
def _handle_no_care_plan(
    patient_name, condition,
    scanned_medicine, scanned_dosage, scanned_text
) -> dict:
    """
    Patient has no care plan in the database at all.
    AI reads the medicine and flags the entire record as needing setup.
    """
    prompt = f"""A patient has NO care plan in the system yet.

PATIENT: {patient_name}
KNOWN CONDITION (if any): {condition or 'Not recorded'}
MEDICINE SCANNED: {scanned_medicine} {scanned_dosage}

Tasks:
1. Identify what {scanned_medicine} treats
2. Give a message to the carer
3. Give an alert for the doctor/admin to set up the care plan

Output format (exactly):
TREATS: <what this medicine treats>
CARER_MESSAGE: <one sentence for carer>
SETUP_ALERT: <one sentence telling doctor/admin to create care plan>"""

    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.2
        )
        text = res.choices[0].message.content.strip()

        parsed = {}
        for line in text.split("\n"):
            if ":" in line:
                key, _, val = line.partition(":")
                parsed[key.strip().upper()] = val.strip()

        treats       = parsed.get("TREATS", "unknown")
        carer_msg    = parsed.get("CARER_MESSAGE", "No care plan found. Do not administer without doctor approval.")
        setup_alert  = parsed.get("SETUP_ALERT", f"Please create a care plan for {patient_name}.")

        return {
            "result":        f"NO_CARE_PLAN: {carer_msg}",
            "status":        "NO_CARE_PLAN",
            "ocr_text":      f"Detected: {scanned_text}\nTreats: {treats}\nNo care plan in DB\nAdmin alert: {setup_alert}",
            "doctor_alert":  setup_alert,
            "update_needed": True
        }

    except Exception as e:
        return {
            "result":        f"NO_CARE_PLAN: No care plan found for {patient_name}. Please contact the doctor.",
            "status":        "NO_CARE_PLAN",
            "ocr_text":      f"Detected: {scanned_text}\nNo care plan in database.",
            "update_needed": True
        }
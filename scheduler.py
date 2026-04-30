"""
scheduler.py — Medication Reminder System

FIXED: Removed hardcoded patient data (Priya, John, Aarthi).
       Schedule now comes ONLY from the database.
       If DB table is empty → reminder list is empty.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import json
import asyncio

scheduler       = BackgroundScheduler()
connected_clients = []
_memory_schedule  = []   # In-memory additions when DB save fails
main_loop         = None  # Set at FastAPI startup


def get_schedule_from_db() -> list:
    """Fetch schedule from DB only. Returns [] on any error — no fallback data."""
    try:
        from database import get_schedule_items
        return get_schedule_items()
    except Exception as e:
        print(f"[Scheduler] DB error: {e}")
        return []


def get_full_schedule() -> list:
    """DB schedule + any in-memory additions from this session."""
    return get_schedule_from_db() + _memory_schedule


def add_reminder_to_memory(patient_name: str, medicine: str, time: str):
    """Fallback: keep reminder in memory if DB save failed."""
    _memory_schedule.append({
        "patient":  patient_name,
        "medicine": medicine,
        "time":     time
    })


def check_reminders():
    """Runs every minute. Sends WebSocket alert 10 minutes before dose time."""
    now     = datetime.now()
    now_str = now.strftime("%H:%M")

    for item in get_full_schedule():
        try:
            med_time     = datetime.strptime(item["time"], "%H:%M")
            med_time     = now.replace(hour=med_time.hour, minute=med_time.minute, second=0, microsecond=0)
            remind_at    = (med_time - timedelta(minutes=10)).strftime("%H:%M")

            if now_str == remind_at:
                msg = {
                    "type":     "reminder",
                    "patient":  item["patient"],
                    "medicine": item["medicine"],
                    "due_time": item["time"],
                    "message":  f"Give {item['medicine']} to {item['patient']} in 10 minutes (due at {item['time']})"
                }
                print(f"[Reminder] {msg['message']}")
                broadcast(msg)
        except Exception as e:
            print(f"[Scheduler Error] {e}")


def broadcast(message: dict):
    """
    Push reminder to all connected WebSocket clients.
    Uses run_coroutine_threadsafe because this runs in a background thread,
    not the main FastAPI async event loop.
    """
    global main_loop
    if not main_loop:
        return

    dead = []
    for ws in connected_clients:
        try:
            fut = asyncio.run_coroutine_threadsafe(
                ws.send_text(json.dumps(message)), main_loop
            )
            fut.result(timeout=5)
        except Exception:
            dead.append(ws)

    for ws in dead:
        if ws in connected_clients:
            connected_clients.remove(ws)


scheduler.add_job(check_reminders, "interval", minutes=1, id="med_reminder")
scheduler.start()
print("[Scheduler] Started — schedule loaded from DB only.")
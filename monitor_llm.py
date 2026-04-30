"""
monitor_llm.py — Sub-case 3: Nutrition & Wound Monitoring

NUTRITION: Single LLM call with both images + explicit food-diff instructions
WOUND:     Manual upload of previous + current image, save current to DB for next time
"""

import os
import base64
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = "meta-llama/llama-4-scout-17b-16e-instruct"


# ─────────────────────────────────────────────────────────────────
# NUTRITION
# ─────────────────────────────────────────────────────────────────

def analyse_nutrition(before_bytes: bytes, after_bytes: bytes, meal_type: str = "meal") -> dict:
    before_b64 = base64.b64encode(before_bytes).decode("utf-8")
    after_b64  = base64.b64encode(after_bytes).decode("utf-8")

    # ── CALL 1: Describe the BEFORE plate ─────────────────────────
    before_prompt = """Look at this plate of food carefully.

List every food item you can see and estimate the quantity of each.
Also estimate the TOTAL food volume as a percentage (this plate = 100%).

Reply ONLY in this format:
ITEMS: <food1: quantity, food2: quantity, ...>
TOTAL_VOLUME: 100
DESCRIPTION: <one sentence describing what is on the plate>"""

    # ── CALL 2: Describe the AFTER plate ──────────────────────────
    after_prompt = """Look at this plate carefully.

This is a plate AFTER someone has eaten from it. Describe exactly what remains.

If the plate is empty (only utensils, crumbs, smears, or nothing) → REMAINING_VOLUME: 0
If a little food is left → REMAINING_VOLUME: 10 to 25
If about a quarter is left → REMAINING_VOLUME: 25
If about half is left → REMAINING_VOLUME: 50
If most food is still there → REMAINING_VOLUME: 70 to 85
If plate looks untouched → REMAINING_VOLUME: 100

Reply ONLY in this format:
ITEMS_LEFT: <list remaining food items, or "none - plate empty">
REMAINING_VOLUME: <single integer 0-100>
DESCRIPTION: <one sentence: is the plate empty, partially eaten, or mostly full?>"""

    try:
        # Call 1 — before plate
        r1 = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": before_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{before_b64}"}}
            ]}],
            max_tokens=200, temperature=0.0
        )
        before_text = r1.choices[0].message.content.strip()
        print(f"[Nutrition BEFORE]: {repr(before_text)}")

        # Call 2 — after plate
        r2 = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": after_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{after_b64}"}}
            ]}],
            max_tokens=200, temperature=0.0
        )
        after_text = r2.choices[0].message.content.strip()
        print(f"[Nutrition AFTER]: {repr(after_text)}")

        # ── Parse before ──────────────────────────────────────────
        before_parsed = {}
        for line in before_text.split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                before_parsed[k.strip().upper()] = v.strip()

        # ── Parse after ───────────────────────────────────────────
        after_parsed = {}
        for line in after_text.split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                after_parsed[k.strip().upper()] = v.strip()

        foods_served  = before_parsed.get("ITEMS", "not identified")
        before_desc   = before_parsed.get("DESCRIPTION", "")
        foods_left    = after_parsed.get("ITEMS_LEFT", "none")
        after_desc    = after_parsed.get("DESCRIPTION", "")

        # ── Calculate percent eaten ───────────────────────────────
        remaining_raw = after_parsed.get("REMAINING_VOLUME", "")
        try:
            digits    = "".join(c for c in remaining_raw if c.isdigit())
            remaining = max(0, min(100, int(digits[:3]))) if digits else None
        except Exception:
            remaining = None

        # Fallback: scan after text for any % number
        if remaining is None:
            import re
            nums = re.findall(r'\b(\d{1,3})\s*%', after_text)
            remaining = int(nums[0]) if nums else 50

        percent = max(0, min(100, 100 - remaining))

        # Derive status strictly from percent
        if percent >= 75:   status = "Good"
        elif percent >= 25: status = "Low"
        else:               status = "Very Low"

        observation = f"Before: {before_desc} After: {after_desc}"
        print(f"[Nutrition] remaining={remaining}% → eaten={percent}% — {status}")

        return {
            "type":           "nutrition",
            "percent":        percent,
            "status":         status,
            "item_breakdown": f"{remaining}% of food still remaining on plate",
            "foods_served":   [f.strip() for f in foods_served.split(",") if f.strip()],
            "foods_left":     [f.strip() for f in foods_left.split(",") if f.strip() and "none" not in f.lower()],
            "observations":   observation,
            "alert":          "Please monitor food intake — very low consumption." if percent < 25 else "No concerns",
            "needs_flag":     percent < 25
        }

    except Exception as e:
        print(f"[Nutrition LLM Error] {e}")
        return {
            "type": "nutrition", "percent": 0, "status": "Unknown",
            "item_breakdown": "", "foods_served": [], "foods_left": [],
            "observations": f"Could not analyse: {e}",
            "alert": "Please assess manually", "needs_flag": False
        }
# ─────────────────────────────────────────────────────────────────

def analyse_wound(
    current_bytes:  bytes,
    patient_name:   str   = "",
    previous_bytes: bytes = None,
    previous_date:  str   = ""
) -> dict:
    """
    Compare current wound photo with a previous one.
    previous_bytes comes from either:
    - Manual upload by carer (new approach, most reliable)
    - Auto-fetched from DB (fallback)
    """
    current_b64 = base64.b64encode(current_bytes).decode("utf-8")

    if previous_bytes:
        prev_b64      = base64.b64encode(previous_bytes).decode("utf-8")
        prev_label    = f"taken on {previous_date}" if previous_date else "previous check"

        prompt = f"""You are a care home wound assessment assistant.
You have TWO wound photos to compare.

PHOTO 1 = previous wound ({prev_label})
PHOTO 2 = today's wound (current check)
PATIENT: {patient_name or 'Not specified'}

Compare both photos carefully:
1. Has the wound SIZE changed? (smaller = healing, same/larger = concern)
2. Has the COLOUR changed? (pink/healthy = good, dark/yellow/green = concern)
3. Are there NEW signs of infection in PHOTO 2 not present in PHOTO 1?
4. Overall healing trend

HEALING STATUS options:
- Healing_Well: wound is clearly better in PHOTO 2 vs PHOTO 1
- Monitor: slight changes, not obviously better or worse
- Needs_Attention: worse in PHOTO 2, signs of infection or deterioration

Reply ONLY in this format:
HEALING_STATUS: Healing_Well or Monitor or Needs_Attention
CHANGE_SUMMARY: <one sentence directly comparing the two photos>
WOUND_TODAY: <description of wound in PHOTO 2>
CONCERNS: <comma list of concerns, or "none noted">
RECOMMENDATION: <one clear action for the carer>
ALERT_NURSE: yes or no"""

        content = [
            {"type": "text",      "text": f"PHOTO 1 — previous wound ({prev_label}):"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{prev_b64}"}},
            {"type": "text",      "text": "PHOTO 2 — today's wound:"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{current_b64}"}},
            {"type": "text",      "text": prompt}
        ]
        has_comparison = True

    else:
        prompt = f"""You are a care home wound assessment assistant.
This is the FIRST recorded wound photo for this patient.
PATIENT: {patient_name or 'Not specified'}

Assess the wound carefully:
- Appearance (colour, size estimate, edges)
- Any visible signs of infection (redness, swelling, discharge)
- Overall condition and what action the carer should take

HEALING STATUS:
- Healing_Well: wound looks clean, no immediate concerns
- Monitor: some concerns, watch closely
- Needs_Attention: signs of infection or serious concern

Reply ONLY in this format:
HEALING_STATUS: Healing_Well or Monitor or Needs_Attention
CHANGE_SUMMARY: First recorded check — no previous image to compare
WOUND_TODAY: <description>
CONCERNS: <comma list, or "none noted">
RECOMMENDATION: <one clear action>
ALERT_NURSE: yes or no"""

        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{current_b64}"}},
            {"type": "text",      "text": prompt}
        ]
        has_comparison = False

    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=300,
            temperature=0.1
        )
        text = res.choices[0].message.content.strip()
        print(f"[Wound LLM raw]: {repr(text)}")

        parsed = {}
        for line in text.split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, val = line.partition(":")
                parsed[key.strip().upper()] = val.strip()

        status         = parsed.get("HEALING_STATUS",  "Monitor").replace("_", " ")
        change         = parsed.get("CHANGE_SUMMARY",  "")
        appearance     = parsed.get("WOUND_TODAY",     "Unable to assess clearly")
        concerns_raw   = parsed.get("CONCERNS",        "none noted")
        recommendation = parsed.get("RECOMMENDATION",  "Have nurse review.")
        alert_nurse    = parsed.get("ALERT_NURSE",     "no").lower().strip() == "yes"

        concerns = [c.strip() for c in concerns_raw.split(",")
                    if c.strip() and c.strip().lower() != "none noted"]

        return {
            "type":            "wound",
            "healing_status":  status,
            "change_summary":  change,
            "appearance":      appearance,
            "concerns":        concerns,
            "recommendation":  recommendation,
            "alert_nurse":     alert_nurse,
            "has_comparison":  has_comparison
        }

    except Exception as e:
        print(f"[Wound LLM Error] {e}")
        return {
            "type":            "wound",
            "healing_status":  "Monitor",
            "change_summary":  "",
            "appearance":      f"Could not assess: {e}",
            "concerns":        ["Please assess manually"],
            "recommendation":  "Have nurse review.",
            "alert_nurse":     False,
            "has_comparison":  has_comparison
        }
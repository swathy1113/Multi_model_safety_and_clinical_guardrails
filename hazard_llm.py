"""
hazard_llm.py — Sub-case 2: Environmental Hazard Detection

Uses Groq Vision (Llama 4 Scout) to scan a room photo and detect
fall risks and safety hazards for care home residents.

DETECTS:
- Loose rugs / mats
- Wet floors
- Poor lighting
- Clutter in walking areas
- Obstacles near bed/walkway
- Trailing cables/wires
- Furniture blocking paths
- Missing grab rails

RETURNS:
- risk_level: LOW / MEDIUM / HIGH
- hazards: list of detected hazards
- recommendations: list of actions to take
- summary: one friendly sentence for the carer
"""

import os
import base64
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = "meta-llama/llama-4-scout-17b-16e-instruct"


def detect_hazards(image_bytes: bytes) -> dict:
    """
    Analyse a room photo for environmental fall/safety hazards.
    Returns structured result with risk level and specific hazards found.
    """
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = """You are a care home safety inspector. Look at this photo and list every hazard you can see.

RISK LEVELS:
HIGH = someone could fall right now
MEDIUM = potential hazard, fix soon
LOW = no hazards visible

OUTPUT FORMAT (use exactly these labels, one per line):
RISK_LEVEL: HIGH or MEDIUM or LOW
HAZARD_1: describe first hazard in plain English
HAZARD_2: describe second hazard (write NONE if no more)
HAZARD_3: describe third hazard (write NONE if no more)
HAZARD_4: describe fourth hazard (write NONE if no more)
HAZARD_5: describe fifth hazard (write NONE if no more)
ACTION_1: what carer should do about hazard 1
ACTION_2: what carer should do about hazard 2 (write NONE if no more)
ACTION_3: what carer should do about hazard 3 (write NONE if no more)
ACTION_4: what carer should do about hazard 4 (write NONE if no more)
ACTION_5: what carer should do about hazard 5 (write NONE if no more)
ALERT: one sentence telling the carer what to do immediately
SUMMARY: one overall sentence about the room safety"""

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
            max_tokens=600,
            temperature=0.1
        )

        text = res.choices[0].message.content.strip()
        print(f"[Hazard LLM raw]: {repr(text)}")

        # Parse key: value — join everything after the FIRST colon as the value
        parsed = {}
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                parsed[key.strip().upper()] = val.strip()

        risk_level = parsed.get("RISK_LEVEL", "MEDIUM").upper()
        if risk_level not in ("HIGH", "MEDIUM", "LOW"):
            risk_level = "MEDIUM"

        # Collect numbered hazards and actions
        hazards = []
        actions = []
        for i in range(1, 6):
            h = parsed.get(f"HAZARD_{i}", "").strip()
            a = parsed.get(f"ACTION_{i}", "").strip()
            skip = {"", "none", "n/a", "leave blank", "no more"}
            if h.lower() not in skip:
                hazards.append(h)
            if a.lower() not in skip:
                actions.append(a)

        alert   = parsed.get("ALERT", "Please review the environment carefully.")
        summary = parsed.get("SUMMARY", alert)

        print(f"[Hazard] risk={risk_level}, hazards={hazards}, actions={actions}")

        return {
            "risk_level":      risk_level,
            "hazards":         hazards,
            "recommendations": actions,
            "alert":           alert,
            "summary":         summary,
        }

    except Exception as e:
        print(f"[Hazard LLM Error] {e}")
        return {
            "risk_level":      "MEDIUM",
            "hazards":         ["Could not analyse image"],
            "recommendations": ["Please check the environment manually"],
            "alert":           f"Could not complete hazard scan. Please inspect the room manually.",
            "summary":         f"Could not complete hazard scan. Error: {str(e)}",
        }
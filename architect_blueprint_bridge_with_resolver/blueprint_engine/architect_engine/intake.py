
from __future__ import annotations
from datetime import datetime

def validate_intake(data: dict) -> dict:
    required = ["customer_name","birth_date","birth_location","birth_time_status"]
    missing=[k for k in required if not data.get(k)]
    if missing:
        return {"status":"INVALID","errors":[f"Missing {k}" for k in missing]}
    try:
        datetime.strptime(data["birth_date"], "%Y-%m-%d")
    except Exception:
        return {"status":"INVALID","errors":["birth_date must be YYYY-MM-DD"]}
    known = data["birth_time_status"] == "KNOWN"
    if known and not data.get("birth_time"):
        return {"status":"INVALID","errors":["KNOWN birth time requires birth_time"]}
    if data["birth_time_status"] not in ("KNOWN","UNKNOWN"):
        return {"status":"INVALID","errors":["birth_time_status must be KNOWN or UNKNOWN"]}
    mode = "FULL" if known else "PARTIAL"
    return {"status":"VALID","mode":mode,"errors":[]}

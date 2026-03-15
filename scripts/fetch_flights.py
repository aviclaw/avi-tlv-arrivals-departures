#!/usr/bin/env python3
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

HISTORICAL_URL = "https://aviation-edge.com/v2/public/flightsHistory"
LIVE_URL = "https://aviation-edge.com/v2/public/timetable"
AIRPORT_IATA = os.getenv("AIRPORT_IATA", "TLV")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "6"))
OUT_PATH = Path(os.getenv("OUT_PATH", "data/flights.json"))
API_KEY = os.getenv("AVIATION_EDGE_API_KEY")


def parse_day(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def fmt_time(value):
    if not value:
        return None
    return str(value).replace("t", " ").replace("T", " ")


def get_nested(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def choose_endpoint(day_str: str, as_of: date):
    historical_safe_max = as_of - timedelta(days=3)
    day_obj = parse_day(day_str)
    if day_obj <= historical_safe_max:
        return "historical", HISTORICAL_URL
    return "live", LIVE_URL


def build_params(day_str: str, flight_type: str, mode: str):
    if mode == "historical":
        return {
            "key": API_KEY,
            "code": AIRPORT_IATA,
            "type": flight_type,
            "date_from": day_str,
        }
    return {
        "key": API_KEY,
        "iataCode": AIRPORT_IATA,
        "type": flight_type,
    }


def fetch_day(day_str: str, flight_type: str, as_of: date):
    mode, url = choose_endpoint(day_str, as_of)
    params = build_params(day_str, flight_type, mode)

    try:
        r = requests.get(url, params=params, timeout=30)
        status_code = r.status_code
        try:
            data = r.json()
        except ValueError:
            data = {"error": f"invalid json response: {r.text[:300]}"}

        return {
            "mode": mode,
            "url": url,
            "status_code": status_code,
            "params": {k: ("***" if k == "key" else v) for k, v in params.items()},
            "data": data,
        }
    except requests.RequestException as e:
        return {
            "mode": mode,
            "url": url,
            "params": {k: ("***" if k == "key" else v) for k, v in params.items()},
            "status_code": None,
            "data": {"error": f"request failed: {e}"},
        }


def get_status(item):
    return (item.get("status") or "unknown").strip().lower()


def is_arrival_completed(item):
    status = get_status(item)
    if status == "landed":
        return True
    if get_nested(item, "arrival", "actualTime"):
        return True
    if get_nested(item, "arrival", "actualRunway"):
        return True
    return False


def is_departure_completed(item):
    status = get_status(item)
    if status in {"active", "departed"}:
        return True
    if get_nested(item, "departure", "actualTime"):
        return True
    if get_nested(item, "departure", "actualRunway"):
        return True
    return False


def classify_flight(item, flight_type):
    if flight_type == "arrival":
        return "completed" if is_arrival_completed(item) else "planned"
    return "completed" if is_departure_completed(item) else "planned"


def extract_flight(item):
    return {
        "airline": get_nested(item, "airline", "name", default="unknown airline"),
        "flight": get_nested(item, "flight", "iataNumber", default="unknown flight"),
        "status": get_status(item),
        "dep": (get_nested(item, "departure", "iataCode", default="???") or "???").upper(),
        "arr": (get_nested(item, "arrival", "iataCode", default="???") or "???").upper(),
        "scheduled_dep": fmt_time(get_nested(item, "departure", "scheduledTime")),
        "actual_dep": fmt_time(get_nested(item, "departure", "actualTime")),
        "scheduled_arr": fmt_time(get_nested(item, "arrival", "scheduledTime")),
        "actual_arr": fmt_time(get_nested(item, "arrival", "actualTime")),
    }


def summarize(data, flight_type):
    if isinstance(data, dict) and "error" in data:
        return {"error": data["error"]}

    if not isinstance(data, list):
        return {"error": f"unexpected response type: {type(data).__name__}"}

    category_counts = Counter()
    status_counts = Counter()

    completed_examples = []
    planned_examples = []

    for item in data:
        status = get_status(item)
        bucket = classify_flight(item, flight_type)
        category_counts[bucket] += 1
        status_counts[status] += 1

        flight = extract_flight(item)
        if bucket == "completed" and len(completed_examples) < 10:
            completed_examples.append(flight)
        elif bucket == "planned" and len(planned_examples) < 10:
            planned_examples.append(flight)

    return {
        "total": len(data),
        "counts": {
            "completed": category_counts.get("completed", 0),
            "planned": category_counts.get("planned", 0),
        },
        "status_counts": dict(status_counts.most_common()),
        "completed_examples": completed_examples,
        "planned_examples": planned_examples,
    }


def make_days(as_of: date, lookback_days: int):
    oldest = as_of - timedelta(days=lookback_days - 1)
    return [(oldest + timedelta(days=i)).isoformat() for i in range(lookback_days)]


def main():
    if not API_KEY:
        raise RuntimeError("AVIATION_EDGE_API_KEY is required as an environment variable")

    as_of = date.today()
    days = make_days(as_of, LOOKBACK_DAYS)

    payload = {
        "airport": AIRPORT_IATA,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "days": {},
    }

    for day_str in days:
        payload["days"][day_str] = {}
        for flight_type in ("arrival", "departure"):
            result = fetch_day(day_str, flight_type, as_of)
            summary = summarize(result["data"], flight_type)
            payload["days"][day_str][flight_type] = {
                "endpoint_mode": result["mode"],
                "status_code": result["status_code"],
                "summary": summary,
            }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()

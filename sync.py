#!/usr/bin/env python3
"""
Garmin -> Notion Sync
Pulls today's wellness stats from Garmin Connect and upserts them into two
Notion databases:
  - NOTION_WELLNESS_DB_ID  (steps, calories, sleep, stress, HRV, resting HR, etc.)
  - NOTION_STRAVA_DB_ID   (activities / workouts)

Required environment variables (set as GitHub Actions secrets):
  GARMIN_EMAIL
  GARMIN_PASSWORD
  GARMIN_TOKENS_JSON   (JSON-encoded OAuth tokens; preferred over email/password)
  NOTION_TOKEN
  NOTION_WELLNESS_DB_ID
  NOTION_STRAVA_DB_ID
"""

import os
import sys
import json
import pathlib
import tempfile
import datetime
import logging

from garminconnect import Garmin
from notion_client import Client

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GARMIN_EMAIL       = os.environ.get("GARMIN_EMAIL", "")
GARMIN_PASSWORD    = os.environ.get("GARMIN_PASSWORD", "")
GARMIN_TOKENS_JSON = os.environ.get("GARMIN_TOKENS_JSON", "")
NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
WELLNESS_DB_ID     = os.environ["NOTION_WELLNESS_DB_ID"]
STRAVA_DB_ID       = os.environ["NOTION_STRAVA_DB_ID"]

TODAY = datetime.date.today().isoformat()  # e.g. "2026-02-26"

# ---------------------------------------------------------------------------
# Garmin helpers
# ---------------------------------------------------------------------------

def connect_garmin():
    """Login using pre-stored OAuth tokens (GARMIN_TOKENS_JSON secret) or
    fall back to email/password if tokens are not available."""
    if GARMIN_TOKENS_JSON:
        # Write token files to a temp dir and load from there
        token_dir = pathlib.Path(tempfile.mkdtemp())
        try:
            token_data = json.loads(GARMIN_TOKENS_JSON)
        except json.JSONDecodeError as exc:
            log.error("GARMIN_TOKENS_JSON is not valid JSON: %s", exc)
            sys.exit(1)
        for filename, content in token_data.items():
            (token_dir / filename).write_text(content)
        log.info("Logging in to Garmin Connect via stored OAuth tokens ...")
        client = Garmin(tokenstore=str(token_dir))
        client.login()
    else:
        # Fallback: direct login (works only if Garmin does not require MFA)
        if not GARMIN_EMAIL or not GARMIN_PASSWORD:
            log.error(
                "No GARMIN_TOKENS_JSON and no GARMIN_EMAIL/GARMIN_PASSWORD set. "
                "Please configure at least one authentication method."
            )
            sys.exit(1)
        log.info("Logging in to Garmin Connect as %s (no token cache) ...", GARMIN_EMAIL)
        client = Garmin(email=GARMIN_EMAIL, password=GARMIN_PASSWORD,
                        is_cn=False, return_on_mfa=True)
        result1, result2 = client.login()
        if result1 == "needs_mfa":
            log.error(
                "Garmin requires MFA for this account. "
                "Please generate OAuth tokens locally and store them as "
                "the GARMIN_TOKENS_JSON GitHub Actions secret."
            )
            sys.exit(1)
    log.info("Garmin login OK")
    return client


def fetch_wellness(gc, date: str) -> dict:
    """Return a flat dict of wellness metrics for *date*."""
    data = {}

    try:
        stats = gc.get_stats(date)
        data["steps"]           = stats.get("totalSteps", 0)
        data["calories"]        = stats.get("totalKilocalories", 0)
        data["active_calories"] = stats.get("activeKilocalories", 0)
        data["distance_m"]      = stats.get("totalDistanceMeters", 0)
        data["floors_up"]       = stats.get("floorsAscended", 0)
        data["resting_hr"]      = stats.get("restingHeartRate", 0)
        data["avg_stress"]      = stats.get("averageStressLevel", 0)
        data["intensity_mins"]  = (
            (stats.get("moderateIntensityMinutes", 0) or 0) +
            (stats.get("vigorousIntensityMinutes", 0) or 0)
        )
    except Exception as exc:
        log.warning("Could not fetch daily stats: %s", exc)

    try:
        sleep = gc.get_sleep_data(date)
        daily = sleep.get("dailySleepDTO", {})
        data["sleep_seconds"]  = daily.get("sleepTimeSeconds", 0)
        data["sleep_score"]    = daily.get("sleepScores", {}).get("overall", {}).get("value", 0)
        data["hrv_weekly_avg"] = sleep.get("hrvSummary", {}).get("weeklyAvg", None)
        data["hrv_last_night"] = sleep.get("hrvSummary", {}).get("lastNight", None)
    except Exception as exc:
        log.warning("Could not fetch sleep data: %s", exc)

    try:
        body  = gc.get_body_composition(date)
        blist = body.get("dateWeightList", [])
        if blist:
            data["weight_kg"] = blist[-1].get("weight", None)
            if data["weight_kg"]:
                data["weight_kg"] = round(data["weight_kg"] / 1000, 2)  # g -> kg
    except Exception as exc:
        log.warning("Could not fetch body composition: %s", exc)

    return data


def fetch_activities(gc, date: str) -> list:
    """Return a list of activity dicts for *date*."""
    try:
        acts = gc.get_activities_by_date(date, date)
        return acts or []
    except Exception as exc:
        log.warning("Could not fetch activities: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

def notion_client() -> Client:
    return Client(auth=NOTION_TOKEN)


def safe_number(val):
    """Return a Notion number property or None."""
    try:
        v = float(val)
        return {"number": v}
    except (TypeError, ValueError):
        return {"number": None}


def find_page_by_date(notion: Client, db_id: str, date_str: str):
    """Find a Notion page in *db_id* whose 'Date' property == date_str."""
    results = notion.databases.query(
        database_id=db_id,
        filter={"property": "Date", "date": {"equals": date_str}}
    )
    pages = results.get("results", [])
    return pages[0] if pages else None


def upsert_wellness(notion: Client, wellness: dict, date: str):
    sleep_h = round((wellness.get("sleep_seconds", 0) or 0) / 3600, 2)

    props = {
        "Date":            {"date": {"start": date}},
        "Steps":           safe_number(wellness.get("steps")),
        "Calories":        safe_number(wellness.get("calories")),
        "Active Calories": safe_number(wellness.get("active_calories")),
        "Distance (km)":   safe_number(round((wellness.get("distance_m", 0) or 0) / 1000, 2)),
        "Floors":          safe_number(wellness.get("floors_up")),
        "Resting HR":      safe_number(wellness.get("resting_hr")),
        "Avg Stress":      safe_number(wellness.get("avg_stress")),
        "Intensity Mins":  safe_number(wellness.get("intensity_mins")),
        "Sleep (h)":       safe_number(sleep_h),
        "Sleep Score":     safe_number(wellness.get("sleep_score")),
        "HRV Last Night":  safe_number(wellness.get("hrv_last_night")),
        "HRV Weekly Avg":  safe_number(wellness.get("hrv_weekly_avg")),
    }
    if wellness.get("weight_kg"):
        props["Weight (kg)"] = safe_number(wellness["weight_kg"])

    existing = find_page_by_date(notion, WELLNESS_DB_ID, date)
    if existing:
        notion.pages.update(page_id=existing["id"], properties=props)
        log.info("Updated wellness page for %s", date)
    else:
        notion.pages.create(parent={"database_id": WELLNESS_DB_ID}, properties=props)
        log.info("Created wellness page for %s", date)


def upsert_activities(notion: Client, activities: list, date: str):
    for act in activities:
        name     = act.get("activityName", "Workout")
        act_type = act.get("activityType", {}).get("typeKey", "unknown")
        duration = round((act.get("duration", 0) or 0) / 60, 1)    # s -> min
        distance = round((act.get("distance", 0) or 0) / 1000, 2)  # m -> km
        calories = act.get("calories", 0)
        avg_hr   = act.get("averageHR", None)
        act_id   = str(act.get("activityId", ""))

        props = {
            "Name":           {"title": [{"text": {"content": name}}]},
            "Date":           {"date": {"start": date}},
            "Type":           {"select": {"name": act_type}},
            "Duration (min)": safe_number(duration),
            "Distance (km)":  safe_number(distance),
            "Calories":       safe_number(calories),
            "Garmin ID":      {"rich_text": [{"text": {"content": act_id}}]},
        }
        if avg_hr:
            props["Avg HR"] = safe_number(avg_hr)

        # Check for existing by Garmin ID
        results = notion.databases.query(
            database_id=STRAVA_DB_ID,
            filter={"property": "Garmin ID", "rich_text": {"equals": act_id}}
        )
        existing = results.get("results", [])
        if existing:
            notion.pages.update(page_id=existing[0]["id"], properties=props)
            log.info("Updated activity '%s' (%s)", name, act_id)
        else:
            notion.pages.create(parent={"database_id": STRAVA_DB_ID}, properties=props)
            log.info("Created activity '%s' (%s)", name, act_id)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("=== Garmin -> Notion Sync | date: %s ===", TODAY)

    gc     = connect_garmin()
    notion = notion_client()

    log.info("--- Wellness ---")
    wellness = fetch_wellness(gc, TODAY)
    log.info("Wellness data: %s", json.dumps(wellness, indent=2))
    upsert_wellness(notion, wellness, TODAY)

    log.info("--- Activities ---")
    activities = fetch_activities(gc, TODAY)
    log.info("Found %d activit(ies)", len(activities))
    upsert_activities(notion, activities, TODAY)

    log.info("=== Sync complete ===")


if __name__ == "__main__":
    main()

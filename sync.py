#!/usr/bin/env python3
"""
Garmin -> Notion Sync
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

GARMIN_EMAIL       = os.environ.get("GARMIN_EMAIL", "")
GARMIN_PASSWORD    = os.environ.get("GARMIN_PASSWORD", "")
GARMIN_TOKENS_JSON = os.environ.get("GARMIN_TOKENS_JSON", "")
NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
WELLNESS_DB_ID     = os.environ["NOTION_WELLNESS_DB_ID"]
STRAVA_DB_ID       = os.environ["NOTION_STRAVA_DB_ID"]

TODAY = datetime.date.today().isoformat()


def connect_garmin():
    if GARMIN_TOKENS_JSON:
        token_dir = pathlib.Path(tempfile.mkdtemp())
        try:
            token_data = json.loads(GARMIN_TOKENS_JSON)
        except json.JSONDecodeError as exc:
            log.error("GARMIN_TOKENS_JSON is not valid JSON: %s", exc)
            sys.exit(1)
        for filename, content in token_data.items():
            (token_dir / filename).write_text(content)
        log.info("Logging in to Garmin Connect via stored OAuth tokens ...")
        client = Garmin()
        client.login(tokenstore=str(token_dir))
    else:
        if not GARMIN_EMAIL or not GARMIN_PASSWORD:
            log.error("No GARMIN_TOKENS_JSON and no GARMIN_EMAIL/GARMIN_PASSWORD set.")
            sys.exit(1)
        log.info("Logging in to Garmin Connect as %s ...", GARMIN_EMAIL)
        client = Garmin(
            email=GARMIN_EMAIL, password=GARMIN_PASSWORD,
            is_cn=False, return_on_mfa=True
        )
        result1, result2 = client.login()
        if result1 == "needs_mfa":
            log.error("Garmin requires MFA. Store tokens as GARMIN_TOKENS_JSON secret.")
            sys.exit(1)
    log.info("Garmin login OK")
    return client


def fetch_wellness(gc, date):
    data = {}
    try:
        stats = gc.get_stats(date)
        data["steps"] = stats.get("totalSteps", 0)
        data["avg_stress"] = stats.get("averageStressLevel", 0)
        data["intensity_mins"] = (
            (stats.get("moderateIntensityMinutes", 0) or 0)
            + (stats.get("vigorousIntensityMinutes", 0) or 0)
        )
        data["resting_hr"] = stats.get("restingHeartRate", 0)
    except Exception as exc:
        log.warning("Could not fetch daily stats: %s", exc)
    try:
        sleep = gc.get_sleep_data(date)
        daily = sleep.get("dailySleepDTO", {})
        data["sleep_score"] = (
            daily.get("sleepScores", {}).get("overall", {}).get("value", 0)
        )
        data["deep_sleep_min"] = round((daily.get("deepSleepSeconds", 0) or 0) / 60)
        data["light_sleep_min"] = round((daily.get("lightSleepSeconds", 0) or 0) / 60)
        data["rem_sleep_min"] = round((daily.get("remSleepSeconds", 0) or 0) / 60)
        data["awake_min"] = round((daily.get("awakeSleepSeconds", 0) or 0) / 60)
    except Exception as exc:
        log.warning("Could not fetch sleep data: %s", exc)
    try:
        body = gc.get_body_composition(date)
        blist = body.get("dateWeightList", [])
        if blist:
            data["weight_kg"] = blist[-1].get("weight", None)
            if data["weight_kg"]:
                data["weight_kg"] = round(data["weight_kg"] / 1000, 2)
    except Exception as exc:
        log.warning("Could not fetch body composition: %s", exc)
    return data


def fetch_activities(gc, date):
    try:
        acts = gc.get_activities_by_date(date, date)
        return acts or []
    except Exception as exc:
        log.warning("Could not fetch activities: %s", exc)
        return []


def notion_client():
    return Client(auth=NOTION_TOKEN)


def safe_number(val):
    try:
        return {"number": float(val)}
    except (TypeError, ValueError):
        return {"number": None}


def find_page_by_date(notion, db_id, date_str):
    results = notion.databases.query(
        database_id=db_id,
        filter={"property": "Date", "date": {"equals": date_str}}
    )
    pages = results.get("results", [])
    return pages[0] if pages else None


def dump_db_schema(notion, db_id, label):
    """Print the actual property names and types in a Notion database."""
    log.info("--- Schema dump: %s (id=%s) ---", label, db_id)
    try:
        db = notion.databases.retrieve(database_id=db_id)
        props = db.get("properties", {})
        for name, prop in sorted(props.items()):
            log.info("  PROP: %r  type=%s", name, prop.get("type"))
    except Exception as exc:
        log.error("  Could not retrieve schema: %s", exc)


def upsert_wellness(notion, wellness, date):
    props = {
        "Date": {"date": {"start": date}},
        "Steps": safe_number(wellness.get("steps")),
        "Avg Stress": safe_number(wellness.get("avg_stress")),
        "Active Minutes": safe_number(wellness.get("intensity_mins")),
        "Resting Heart Rate": safe_number(wellness.get("resting_hr")),
        "Sleep Score": safe_number(wellness.get("sleep_score")),
        "Deep Sleep (min)": safe_number(wellness.get("deep_sleep_min")),
        "Light Sleep (min)": safe_number(wellness.get("light_sleep_min")),
        "REM Sleep (min)": safe_number(wellness.get("rem_sleep_min")),
        "Awake (min)": safe_number(wellness.get("awake_min")),
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


def main():
    log.info("=== Garmin -> Notion Sync | date: %s ===", TODAY)
    gc = connect_garmin()
    notion = notion_client()

    log.info("--- Wellness ---")
    wellness = fetch_wellness(gc, TODAY)
    log.info("Wellness data: %s", json.dumps(wellness, indent=2))
    upsert_wellness(notion, wellness, TODAY)

    log.info("--- Schema Diagnostics ---")
    dump_db_schema(notion, WELLNESS_DB_ID, "Wellness DB")
    dump_db_schema(notion, STRAVA_DB_ID, "Strava/Activities DB")

    log.info("=== Sync complete ===")


if __name__ == "__main__":
    main()

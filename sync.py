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

GARMIN_EMAIL        = os.environ.get("GARMIN_EMAIL", "")
GARMIN_PASSWORD     = os.environ.get("GARMIN_PASSWORD", "")
GARMIN_TOKENS_JSON  = os.environ.get("GARMIN_TOKENS_JSON", "")
NOTION_TOKEN        = os.environ["NOTION_TOKEN"]
WELLNESS_DB_ID      = os.environ["NOTION_WELLNESS_DB_ID"]
STRAVA_DB_ID        = os.environ["NOTION_STRAVA_DB_ID"]

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
        client = Garmin(email=GARMIN_EMAIL, password=GARMIN_PASSWORD, is_cn=False, return_on_mfa=True)
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
                data["sleep_score"] = daily.get("sleepScores", {}).get("overall", {}).get("value", 0)
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


def upsert_activities(notion, activities, date):
        for act in activities:
                    name = act.get("activityName", "Workout")
                    act_type = act.get("activityType", {}).get("typeKey", "unknown")
                    duration = round((act.get("duration", 0) or 0) / 60, 1)
                    distance = round((act.get("distance", 0) or 0) / 1000, 2)
                    calories = act.get("calories", 0)
                    avg_hr = act.get("averageHR", None)
                    act_id = str(act.get("activityId", ""))
                    props = {
                        "Name": {"title": [{"text": {"content": name}}]},
                        "Date": {"date": {"start": date}},
                        "Type": {"select": {"name": act_type}},
                        "Duration (min)": safe_number(duration),
                        "Distance (km)": safe_number(distance),
                        "Calories": safe_number(calories),
                        "Garmin ID": {"rich_text": [{"text": {"content": act_id}}]},
                    }
                    if avg_hr:
                                    props["Avg HR"] = safe_number(avg_hr)
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


def main():
        log.info("=== Garmin -> Notion Sync | date: %s ===", TODAY)
    gc = connect_garmin()
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

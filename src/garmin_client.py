import json
import logging
import os
import pathlib
import sys
import tempfile

from garminconnect import Garmin

log = logging.getLogger(__name__)

GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "")
GARMIN_TOKENS_JSON = os.environ.get("GARMIN_TOKENS_JSON", "")


def connect_garmin() -> Garmin:
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
        log.info("Garmin login OK")
        return client

    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        log.error("GARMIN_EMAIL and GARMIN_PASSWORD must be set.")
        sys.exit(1)

    log.info("Logging in to Garmin Connect as %s ...", GARMIN_EMAIL)
    client = Garmin(
        email=GARMIN_EMAIL,
        password=GARMIN_PASSWORD,
        is_cn=False,
        return_on_mfa=True,
    )
    result1, _ = client.login()
    if result1 == "needs_mfa":
        log.error("Garmin requires MFA. Set GARMIN_TOKENS_JSON for token-based login.")
        sys.exit(1)

    log.info("Garmin login OK")
    return client


def fetch_wellness(client: Garmin, date: str) -> dict:
    data: dict = {}

    try:
        stats = client.get_stats(date)
        data["steps"] = stats.get("totalSteps", 0)
        data["avg_stress"] = stats.get("averageStressLevel", 0)
        data["intensity_mins"] = (stats.get("moderateIntensityMinutes", 0) or 0) + (
            stats.get("vigorousIntensityMinutes", 0) or 0
        )
        data["resting_hr"] = stats.get("restingHeartRate", 0)
    except Exception as exc:
        log.warning("Could not fetch daily stats: %s", exc)

    try:
        sleep = client.get_sleep_data(date)
        daily = sleep.get("dailySleepDTO", {})
        data["sleep_score"] = daily.get("sleepScores", {}).get("overall", {}).get("value", 0)
        data["deep_sleep_min"] = round((daily.get("deepSleepSeconds", 0) or 0) / 60)
        data["light_sleep_min"] = round((daily.get("lightSleepSeconds", 0) or 0) / 60)
        data["rem_sleep_min"] = round((daily.get("remSleepSeconds", 0) or 0) / 60)
        data["awake_min"] = round((daily.get("awakeSleepSeconds", 0) or 0) / 60)
    except Exception as exc:
        log.warning("Could not fetch sleep data: %s", exc)

    try:
        body = client.get_body_composition(date)
        weights = body.get("dateWeightList", [])
        if weights:
            weight_grams = weights[-1].get("weight", None)
            if weight_grams:
                data["weight_kg"] = round(weight_grams / 1000, 2)
    except Exception as exc:
        log.warning("Could not fetch body composition: %s", exc)

    return data


def fetch_activities(client: Garmin, date: str) -> list[dict]:
    try:
        return client.get_activities_by_date(date, date) or []
    except Exception as exc:
        log.warning("Could not fetch activities: %s", exc)
        return []

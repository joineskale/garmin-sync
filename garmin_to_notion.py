#!/usr/bin/env python3
import datetime
import json
import logging

from src.activity_sync import upsert_activities
from src.garmin_client import connect_garmin, fetch_activities, fetch_wellness
from src.notion_client import create_notion_client
from src.wellness_sync import upsert_wellness

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    today = datetime.date.today().isoformat()
    log.info("=== Garmin -> Notion Sync | date: %s ===", today)

    garmin = connect_garmin()
    notion = create_notion_client()

    wellness = fetch_wellness(garmin, today)
    log.info("Wellness data: %s", json.dumps(wellness, indent=2))
    upsert_wellness(notion, wellness, today)

    activities = fetch_activities(garmin, today)
    log.info("Fetched %s activities", len(activities))
    upsert_activities(notion, activities, today)

    log.info("=== Sync complete ===")


if __name__ == "__main__":
    main()

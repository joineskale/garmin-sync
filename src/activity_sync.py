import datetime

from notion_client import Client

from src.notion_client import NOTION_STRAVA_DB_ID, find_page_by_date, safe_number


def _duration_minutes(activity: dict) -> float:
    seconds = activity.get("duration", 0) or 0
    return round(float(seconds) / 60, 2)


def upsert_activities(notion: Client, activities: list[dict], date: str) -> None:
    if not NOTION_STRAVA_DB_ID:
        raise ValueError("NOTION_STRAVA_DB_ID must be set.")

    for index, activity in enumerate(activities, start=1):
        activity_name = activity.get("activityName") or f"Activity {index}"
        activity_type = activity.get("activityType", {}).get("typeKey", "unknown")
        distance_meters = activity.get("distance", 0) or 0
        distance_km = round(float(distance_meters) / 1000, 3)

        unique_date = date
        if len(activities) > 1:
            unique_date = (datetime.date.fromisoformat(date) + datetime.timedelta(days=index - 1)).isoformat()

        properties = {
            "Date": {"date": {"start": unique_date}},
            "Activity": {"title": [{"text": {"content": activity_name}}]},
            "Type": {"rich_text": [{"text": {"content": activity_type}}]},
            "Distance (km)": safe_number(distance_km),
            "Duration (min)": safe_number(_duration_minutes(activity)),
            "Calories": safe_number(activity.get("calories")),
        }

        existing = find_page_by_date(notion, NOTION_STRAVA_DB_ID, unique_date)
        if existing:
            notion.pages.update(page_id=existing["id"], properties=properties)
        else:
            notion.pages.create(parent={"database_id": NOTION_STRAVA_DB_ID}, properties=properties)

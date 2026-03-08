from notion_client import Client

from src.notion_client import NOTION_STRAVA_DB_ID, safe_number


def upsert_activities(notion: Client, activities: list[dict]) -> None:
    if not NOTION_STRAVA_DB_ID:
        raise ValueError("NOTION_STRAVA_DB_ID must be set.")

    for activity in activities:
        name = activity.get("activityName", "Workout")
        activity_type = activity.get("activityType", {}).get("typeKey", "unknown")
        duration_min = round((activity.get("duration", 0) or 0) / 60, 1)
        distance_km = round((activity.get("distance", 0) or 0) / 1000, 2)
        calories = activity.get("calories", 0)
        avg_hr = activity.get("averageHR", None)
        start_time = activity.get("startTimeLocal") or activity.get("startTimeGMT")

        properties = {
            "Name": {"title": [{"text": {"content": name}}]},
            "Date": {"date": {"start": start_time}},
            "Activity Type": {"select": {"name": activity_type}},
            "Duration (min)": safe_number(duration_min),
            "Distance (km)": safe_number(distance_km),
            "Calories": safe_number(calories),
        }
        if avg_hr:
            properties["Avg HR"] = safe_number(avg_hr)

        notion.pages.create(parent={"database_id": NOTION_STRAVA_DB_ID}, properties=properties)

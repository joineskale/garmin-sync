from notion_client import Client

from src.notion_client import NOTION_WELLNESS_DB_ID, find_page_by_date, safe_number


def upsert_wellness(notion: Client, wellness: dict, date: str) -> None:
    if not NOTION_WELLNESS_DB_ID:
        raise ValueError("NOTION_WELLNESS_DB_ID must be set.")

    properties = {
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
        properties["Weight (kg)"] = safe_number(wellness["weight_kg"])

    existing = find_page_by_date(notion, NOTION_WELLNESS_DB_ID, date)
    if existing:
        notion.pages.update(page_id=existing["id"], properties=properties)
    else:
        notion.pages.create(parent={"database_id": NOTION_WELLNESS_DB_ID}, properties=properties)

import os

from notion_client import Client

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_WELLNESS_DB_ID = os.environ.get("NOTION_WELLNESS_DB_ID", "")
NOTION_STRAVA_DB_ID = os.environ.get("NOTION_STRAVA_DB_ID", "")


def create_notion_client() -> Client:
    if not NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN must be set.")
    return Client(auth=NOTION_TOKEN)


def safe_number(value):
    try:
        return {"number": float(value)}
    except (TypeError, ValueError):
        return {"number": None}


def find_page_by_date(notion: Client, db_id: str, date_str: str):
    results = notion.databases.query(
        database_id=db_id,
        filter={"property": "Date", "date": {"equals": date_str}},
    )
    pages = results.get("results", [])
    return pages[0] if pages else None

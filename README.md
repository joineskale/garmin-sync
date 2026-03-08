# Garmin ↔ Notion Sync

This repository syncs Garmin wellness and activity data to Notion databases.

## Project structure

```text
src/
  garmin_client.py
  notion_client.py
  activity_sync.py
  wellness_sync.py
garmin_to_notion.py
```

## Required environment variables

- `GARMIN_EMAIL`
- `GARMIN_PASSWORD`
- `NOTION_TOKEN`
- `NOTION_WELLNESS_DB_ID`
- `NOTION_STRAVA_DB_ID`

## Run locally

```bash
pip install -r requirements.txt
python garmin_to_notion.py
```

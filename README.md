# Chores

A mobile-first chore reminder app — add chores, get browser push notifications, track streaks and daily activity.

## Stack
- Flask + SQLAlchemy (SQLite)
- Web Push (VAPID) for notifications, service worker for delivery
- APScheduler for checking due reminders every minute

## Local development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

VAPID keys for push notifications are read from `vapid_private.pem` / `vapid_public_key.txt` locally, or from the `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` env vars in production.

## Deploying to Render

This repo includes a `render.yaml` blueprint. In the Render dashboard: New → Blueprint → point at this repo. You'll need to manually set the `VAPID_PRIVATE_KEY` and `VAPID_PUBLIC_KEY` env vars (not committed to git) using the values from your local `vapid_private.pem` / `vapid_public_key.txt`.

Note: SQLite data only persists across deploys if the Render service has a persistent disk attached (see `disk` in `render.yaml`, requires a paid plan).

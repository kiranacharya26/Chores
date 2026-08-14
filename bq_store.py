"""
BigQuery-backed data layer for the Chores app.

Follows the same pattern as finstatement: BigQuery's free tier blocks DML
(UPDATE/DELETE/INSERT statements) without a billing account, but load jobs
(WRITE_APPEND) are allowed. So every write here — create, done, undone,
delete — is an appended *event*, never a mutation. Current state is derived
by taking the latest event per row.

Trade-off: each write is a BigQuery load job, which takes a few seconds to
land (unlike a normal instant DB write). Once billing is enabled on the GCP
project, this can be swapped for plain INSERT/UPDATE/DELETE for instant
writes — the query functions below would simplify a lot.
"""
import io
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from google.cloud import bigquery

PROJECT_ID = "chores-app-kiran"
DATASET = "chores_app"

_client = None


def _get_client():
    """Lazy singleton so credentials set by app.py at startup are picked up,
    regardless of import order."""
    global _client
    if _client is None:
        _client = bigquery.Client(project=PROJECT_ID)
    return _client


def _table(name):
    return f"{PROJECT_ID}.{DATASET}.{name}"


def _append_rows(table_name, rows):
    """Append rows via a load job (allowed without billing, unlike DML)."""
    buf = io.StringIO("\n".join(json.dumps(r) for r in rows))
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        autodetect=False,
    )
    job = _get_client().load_table_from_file(buf, _table(table_name), job_config=job_config)
    job.result()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


FREQUENCIES = ["daily", "weekly", "monthly"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _is_due_today(chore, today: date) -> bool:
    freq = chore["frequency"]
    if freq == "daily":
        return True
    if freq == "weekly":
        return chore["weekday"] == today.weekday()
    if freq == "monthly":
        return chore["day_of_month"] == today.day
    return False


def _previous_due_date(chore, from_date: date) -> date:
    freq = chore["frequency"]
    if freq == "weekly":
        d = from_date - timedelta(days=1)
        while d.weekday() != chore["weekday"]:
            d -= timedelta(days=1)
        return d
    if freq == "monthly":
        d = from_date.replace(day=1) - timedelta(days=1)
        target_day = min(chore["day_of_month"], d.day)
        return d.replace(day=target_day)
    return from_date - timedelta(days=1)


def _compute_streak(chore, done_dates: set, today: date) -> int:
    pointer = today if _is_due_today(chore, today) else _previous_due_date(chore, today + timedelta(days=1))
    if pointer == today and today.isoformat() not in done_dates:
        pointer = _previous_due_date(chore, today)

    streak = 0
    guard = 0
    while pointer.isoformat() in done_dates and guard < 3650:
        streak += 1
        pointer = _previous_due_date(chore, pointer)
        guard += 1
    return streak


def _latest_chores():
    """Current chore state: latest event per chore_id, excluding deleted."""
    query = f"""
        WITH ranked AS (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY chore_id ORDER BY created_at DESC) rn
          FROM `{_table('chore_events')}`
        )
        SELECT chore_id, name, frequency, weekday, day_of_month, reminder_time
        FROM ranked
        WHERE rn = 1 AND event_type != 'delete'
        ORDER BY created_at ASC
    """
    return [dict(row) for row in _get_client().query(query).result()]


def _done_dates_by_chore():
    """For every chore, the set of dates whose latest event that day is 'done'."""
    query = f"""
        WITH ranked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY chore_id, event_date ORDER BY created_at DESC
          ) rn
          FROM `{_table('completion_events')}`
        )
        SELECT chore_id, event_date
        FROM ranked
        WHERE rn = 1 AND event_type = 'done'
    """
    result = {}
    for row in _get_client().query(query).result():
        result.setdefault(row["chore_id"], set()).add(row["event_date"])
    return result


def list_chores():
    today = date.today()
    chores = _latest_chores()
    done_map = _done_dates_by_chore()

    out = []
    for c in chores:
        done_dates = done_map.get(c["chore_id"], set())
        out.append({
            "id": c["chore_id"],
            "name": c["name"],
            "frequency": c["frequency"],
            "weekday": c["weekday"],
            "day_of_month": c["day_of_month"],
            "reminder_time": c["reminder_time"],
            "done_today": today.isoformat() in done_dates,
            "due_today": _is_due_today(c, today),
            "streak": _compute_streak(c, done_dates, today),
        })
    return out


def create_chore(name, frequency, weekday=None, day_of_month=None, reminder_time="09:00"):
    chore_id = uuid.uuid4().hex
    _append_rows("chore_events", [{
        "id": uuid.uuid4().hex,
        "chore_id": chore_id,
        "event_type": "create",
        "name": name,
        "frequency": frequency,
        "weekday": weekday,
        "day_of_month": day_of_month,
        "reminder_time": reminder_time,
        "created_at": _now_iso(),
    }])
    return chore_id


def delete_chore(chore_id):
    _append_rows("chore_events", [{
        "id": uuid.uuid4().hex,
        "chore_id": chore_id,
        "event_type": "delete",
        "name": None,
        "frequency": None,
        "weekday": None,
        "day_of_month": None,
        "reminder_time": None,
        "created_at": _now_iso(),
    }])


def mark_done(chore_id, on: bool):
    _append_rows("completion_events", [{
        "id": uuid.uuid4().hex,
        "chore_id": chore_id,
        "event_type": "done" if on else "undone",
        "event_date": date.today().isoformat(),
        "created_at": _now_iso(),
    }])


def week_progress():
    """Last 7 days (ending today): how many due chores were done each day."""
    chores = _latest_chores()
    done_map = _done_dates_by_chore()
    today = date.today()
    start = today - timedelta(days=6)

    result = []
    for i in range(7):
        d = start + timedelta(days=i)
        total = 0
        done = 0
        for c in chores:
            if _is_due_today(c, d):
                total += 1
                if d.isoformat() in done_map.get(c["chore_id"], set()):
                    done += 1
        result.append({
            "date": d.isoformat(),
            "weekday": d.weekday(),
            "done": done,
            "total": total,
        })
    return result


def reminder_state(chore_id):
    """Latest reminder event for this chore today, if any.

    Returns None if no reminder sent yet today. Otherwise a dict with
    'snoozed_until' (datetime or None) — if snoozed_until is in the past,
    the reminder should fire again.
    """
    today_iso = date.today().isoformat()
    query = f"""
        SELECT snoozed_until FROM `{_table('reminder_events')}`
        WHERE chore_id = @chore_id AND reminded_date = @today
        ORDER BY created_at DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("chore_id", "STRING", chore_id),
        bigquery.ScalarQueryParameter("today", "STRING", today_iso),
    ])
    rows = list(_get_client().query(query, job_config=job_config).result())
    if not rows:
        return None
    return {"snoozed_until": rows[0]["snoozed_until"]}


def should_send_reminder(chore_id):
    state = reminder_state(chore_id)
    if state is None:
        return True
    if state["snoozed_until"] is not None and datetime.now(timezone.utc) >= state["snoozed_until"]:
        return True
    return False


def mark_reminded(chore_id):
    _append_rows("reminder_events", [{
        "id": uuid.uuid4().hex,
        "chore_id": chore_id,
        "reminded_date": date.today().isoformat(),
        "snoozed_until": None,
        "created_at": _now_iso(),
    }])


def snooze_chore(chore_id, minutes):
    snoozed_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    _append_rows("reminder_events", [{
        "id": uuid.uuid4().hex,
        "chore_id": chore_id,
        "reminded_date": date.today().isoformat(),
        "snoozed_until": snoozed_until.isoformat(),
        "created_at": _now_iso(),
    }])


def _active_subscriptions():
    query = f"""
        WITH ranked AS (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY endpoint ORDER BY created_at DESC) rn
          FROM `{_table('subscription_events')}`
        )
        SELECT endpoint, subscription_json
        FROM ranked
        WHERE rn = 1 AND event_type = 'active'
    """
    return [dict(row) for row in _get_client().query(query).result()]


def list_active_subscriptions():
    return _active_subscriptions()


def add_subscription(endpoint, subscription_json):
    _append_rows("subscription_events", [{
        "id": uuid.uuid4().hex,
        "endpoint": endpoint,
        "event_type": "active",
        "subscription_json": subscription_json,
        "created_at": _now_iso(),
    }])


def revoke_subscription(endpoint):
    _append_rows("subscription_events", [{
        "id": uuid.uuid4().hex,
        "endpoint": endpoint,
        "event_type": "revoked",
        "subscription_json": None,
        "created_at": _now_iso(),
    }])

"""
BigQuery-backed data layer for the Chores app.

Data model is still an event log (every write is an appended event; current
state is derived by taking the latest event per row) — that part is kept
because it's a clean way to compute streaks/history. But writes now go
through plain parameterized INSERT statements instead of load jobs, since
billing is enabled on the project and DML is allowed. INSERT via query()
lands in well under a second, vs. several seconds for a load job.
"""
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


TABLE_SCHEMAS = {
    "chore_events": {
        "id": "STRING", "chore_id": "STRING", "event_type": "STRING",
        "name": "STRING", "frequency": "STRING", "weekday": "INT64",
        "day_of_month": "INT64", "interval_days": "INT64",
        "reminder_time": "STRING", "assigned_to": "STRING", "created_at": "TIMESTAMP",
    },
    "completion_events": {
        "id": "STRING", "chore_id": "STRING", "event_type": "STRING",
        "event_date": "STRING", "person": "STRING", "created_at": "TIMESTAMP",
    },
    "subscription_events": {
        "id": "STRING", "endpoint": "STRING", "event_type": "STRING",
        "subscription_json": "STRING", "person": "STRING", "created_at": "TIMESTAMP",
    },
    "reminder_events": {
        "id": "STRING", "chore_id": "STRING", "reminded_date": "STRING",
        "snoozed_until": "TIMESTAMP", "created_at": "TIMESTAMP",
    },
}


def _append_rows(table_name, rows):
    """Insert rows via a plain parameterized INSERT (instant, needs billing enabled)."""
    if not rows:
        return
    schema = TABLE_SCHEMAS[table_name]
    columns = list(schema.keys())
    value_groups = []
    params = []
    for i, row in enumerate(rows):
        placeholders = []
        for col in columns:
            pname = f"{col}_{i}"
            placeholders.append(f"@{pname}")
            params.append(bigquery.ScalarQueryParameter(pname, schema[col], row.get(col)))
        value_groups.append("(" + ", ".join(placeholders) + ")")

    query = f"INSERT INTO `{_table(table_name)}` ({', '.join(columns)}) VALUES {', '.join(value_groups)}"
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    _get_client().query(query, job_config=job_config).result()


def _now():
    return datetime.now(timezone.utc)


FREQUENCIES = ["daily", "weekly", "monthly", "interval"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _last_done_before(done_dates: set, before: date):
    """Most recent done date strictly before `before`, or None."""
    candidates = [datetime.strptime(d, "%Y-%m-%d").date() for d in done_dates if d < before.isoformat()]
    return max(candidates) if candidates else None


def _is_due_today(chore, today: date, done_dates: set = frozenset()) -> bool:
    freq = chore["frequency"]
    if freq == "daily":
        return True
    if freq == "weekly":
        return chore["weekday"] == today.weekday()
    if freq == "monthly":
        return chore["day_of_month"] == today.day
    if freq == "interval":
        # Due once interval_days have passed since the last completion —
        # a moving target based on actual behavior, not a fixed calendar
        # slot. Fixes the "everything shows overdue, you stop trusting the
        # badges" failure mode of rigid schedules.
        last_done = _last_done_before(done_dates, today + timedelta(days=1))
        if last_done is None:
            return True
        return (today - last_done).days >= chore["interval_days"]
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
    if chore["frequency"] == "interval":
        return _compute_interval_streak(chore, done_dates)

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


def _compute_interval_streak(chore, done_dates: set) -> int:
    """Consecutive completions each landing within interval_days of the
    previous one (a little slack for the day it's done on)."""
    dates_sorted = sorted(
        (datetime.strptime(d, "%Y-%m-%d").date() for d in done_dates), reverse=True
    )
    if not dates_sorted:
        return 0
    streak = 1
    for i in range(len(dates_sorted) - 1):
        gap = (dates_sorted[i] - dates_sorted[i + 1]).days
        if gap <= chore["interval_days"] + 1:
            streak += 1
        else:
            break
    return streak


def _latest_chores():
    """Current chore state: latest event per chore_id, excluding deleted."""
    query = f"""
        WITH ranked AS (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY chore_id ORDER BY created_at DESC) rn
          FROM `{_table('chore_events')}`
        )
        SELECT chore_id, name, frequency, weekday, day_of_month, interval_days, reminder_time, assigned_to
        FROM ranked
        WHERE rn = 1 AND event_type != 'delete'
        ORDER BY created_at ASC
    """
    return [dict(row) for row in _get_client().query(query).result()]


def _done_dates_by_chore():
    """For every chore: {date -> person who did it}, for dates whose latest
    event that day is 'done'."""
    query = f"""
        WITH ranked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY chore_id, event_date ORDER BY created_at DESC
          ) rn
          FROM `{_table('completion_events')}`
        )
        SELECT chore_id, event_date, person
        FROM ranked
        WHERE rn = 1 AND event_type = 'done'
    """
    result = {}
    for row in _get_client().query(query).result():
        result.setdefault(row["chore_id"], {})[row["event_date"]] = row["person"]
    return result


def list_chores():
    today = date.today()
    chores = _latest_chores()
    done_map = _done_dates_by_chore()

    out = []
    for c in chores:
        done_by_date = done_map.get(c["chore_id"], {})
        done_dates = set(done_by_date.keys())
        out.append({
            "id": c["chore_id"],
            "name": c["name"],
            "frequency": c["frequency"],
            "weekday": c["weekday"],
            "day_of_month": c["day_of_month"],
            "interval_days": c["interval_days"],
            "assigned_to": c["assigned_to"] or "unassigned",
            "reminder_time": c["reminder_time"],
            "done_today": today.isoformat() in done_dates,
            "done_by": done_by_date.get(today.isoformat()),
            "due_today": _is_due_today(c, today, done_dates),
            "streak": _compute_streak(c, done_dates, today),
        })
    return out


def create_chore(name, frequency, weekday=None, day_of_month=None, interval_days=None,
                  reminder_time="09:00", assigned_to="unassigned"):
    chore_id = uuid.uuid4().hex
    _append_rows("chore_events", [{
        "id": uuid.uuid4().hex,
        "chore_id": chore_id,
        "event_type": "create",
        "name": name,
        "frequency": frequency,
        "weekday": weekday,
        "day_of_month": day_of_month,
        "interval_days": interval_days,
        "reminder_time": reminder_time,
        "assigned_to": assigned_to,
        "created_at": _now(),
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
        "interval_days": None,
        "reminder_time": None,
        "created_at": _now(),
    }])


def mark_done(chore_id, on: bool, person=None):
    _append_rows("completion_events", [{
        "id": uuid.uuid4().hex,
        "chore_id": chore_id,
        "event_type": "done" if on else "undone",
        "event_date": date.today().isoformat(),
        "person": person if on else None,
        "created_at": _now(),
    }])


def get_chore(chore_id):
    for c in list_chores():
        if c["id"] == chore_id:
            return c
    return None


def claim_chore(chore_id, person):
    """Reassign a chore to `person`, carrying over all other current
    fields unchanged (mirrors how delete_chore/create_chore write a full
    row — the latest event's fields ARE the chore's current state)."""
    chore = get_chore(chore_id)
    if chore is None:
        return
    _append_rows("chore_events", [{
        "id": uuid.uuid4().hex,
        "chore_id": chore_id,
        "event_type": "update",
        "name": chore["name"],
        "frequency": chore["frequency"],
        "weekday": chore["weekday"],
        "day_of_month": chore["day_of_month"],
        "interval_days": chore["interval_days"],
        "reminder_time": chore["reminder_time"],
        "assigned_to": person,
        "created_at": _now(),
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
            done_dates = set(done_map.get(c["chore_id"], {}).keys())
            if _is_due_today(c, d, done_dates):
                total += 1
                if d.isoformat() in done_dates:
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
        "created_at": _now(),
    }])


def snooze_chore(chore_id, minutes):
    snoozed_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    _append_rows("reminder_events", [{
        "id": uuid.uuid4().hex,
        "chore_id": chore_id,
        "reminded_date": date.today().isoformat(),
        "snoozed_until": snoozed_until,
        "created_at": _now(),
    }])


def _active_subscriptions():
    query = f"""
        WITH ranked AS (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY endpoint ORDER BY created_at DESC) rn
          FROM `{_table('subscription_events')}`
        )
        SELECT endpoint, subscription_json, person
        FROM ranked
        WHERE rn = 1 AND event_type = 'active'
    """
    return [dict(row) for row in _get_client().query(query).result()]


def list_active_subscriptions():
    return _active_subscriptions()


def add_subscription(endpoint, subscription_json, person=None):
    _append_rows("subscription_events", [{
        "id": uuid.uuid4().hex,
        "endpoint": endpoint,
        "event_type": "active",
        "subscription_json": subscription_json,
        "person": person,
        "created_at": _now(),
    }])


def revoke_subscription(endpoint):
    _append_rows("subscription_events", [{
        "id": uuid.uuid4().hex,
        "endpoint": endpoint,
        "event_type": "revoked",
        "subscription_json": None,
        "created_at": _now(),
    }])

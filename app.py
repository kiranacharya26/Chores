import json
import os
import tempfile
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from pywebpush import webpush, WebPushException

import bq_store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# On Render, the service account key is passed as a JSON string env var
# (can't upload a file directly), so write it out and point the BigQuery
# client's default credential lookup at it.
_creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
if _creds_json:
    _creds_path = os.path.join(tempfile.gettempdir(), "bq-service-account.json")
    with open(_creds_path, "w") as f:
        f.write(_creds_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _creds_path
elif os.path.exists(os.path.join(BASE_DIR, "bq-service-account.json")):
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(BASE_DIR, "bq-service-account.json"))

app = Flask(__name__)


def _load_vapid_key(env_var, filename):
    value = os.environ.get(env_var)
    if value:
        return value.replace("\\n", "\n")
    path = os.path.join(BASE_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    raise RuntimeError(f"Missing VAPID key: set {env_var} env var or provide {filename}")


VAPID_PRIVATE_KEY = _load_vapid_key("VAPID_PRIVATE_KEY", "vapid_private.pem")
VAPID_PUBLIC_KEY = _load_vapid_key("VAPID_PUBLIC_KEY", "vapid_public_key.txt").strip()
VAPID_CLAIMS = {"sub": os.environ.get("VAPID_CONTACT_EMAIL", "mailto:kiran@nourishednaturalhealth.com")}

FREQUENCIES = bq_store.FREQUENCIES
WEEKDAYS = bq_store.WEEKDAYS


def send_push(endpoint, subscription_json, title, body, data=None):
    payload = {"title": title, "body": body}
    if data:
        payload.update(data)
    try:
        webpush(
            subscription_info=json.loads(subscription_json),
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=dict(VAPID_CLAIMS),
        )
    except WebPushException as ex:
        if ex.response is not None and ex.response.status_code in (404, 410):
            bq_store.revoke_subscription(endpoint)


def check_and_send_reminders():
    now = datetime.now()
    current_hm = now.strftime("%H:%M")
    subs = bq_store.list_active_subscriptions()
    if not subs:
        return
    chores = bq_store.list_chores()
    for chore in chores:
        if not chore["due_today"] or chore["done_today"]:
            continue

        state = bq_store.reminder_state(chore["id"])
        if state is None:
            if chore["reminder_time"] != current_hm:
                continue
        else:
            if state["snoozed_until"] is None:
                continue  # already reminded today, not snoozed — wait for tomorrow
            if datetime.now(timezone.utc) < state["snoozed_until"]:
                continue  # still snoozed

        for sub in subs:
            send_push(
                sub["endpoint"], sub["subscription_json"],
                "Chore reminder", f"Time to do: {chore['name']}",
                data={"chore_id": chore["id"]},
            )
        bq_store.mark_reminded(chore["id"])


scheduler = BackgroundScheduler()
scheduler.add_job(check_and_send_reminders, "interval", minutes=1, id="reminder_check")
scheduler.start()


def _asset_version():
    paths = [
        os.path.join(BASE_DIR, "static", "css", "app.css"),
        os.path.join(BASE_DIR, "static", "js", "app.js"),
    ]
    return str(int(max(os.path.getmtime(p) for p in paths)))


@app.route("/")
def index():
    return render_template(
        "index.html",
        vapid_public_key=VAPID_PUBLIC_KEY,
        weekdays=WEEKDAYS,
        asset_version=_asset_version(),
    )


@app.route("/api/chores", methods=["GET"])
def list_chores():
    return jsonify(bq_store.list_chores())


@app.route("/api/chores", methods=["POST"])
def create_chore():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    frequency = data.get("frequency", "daily")
    if not name:
        return jsonify({"error": "name is required"}), 400
    if frequency not in FREQUENCIES:
        return jsonify({"error": "invalid frequency"}), 400

    chore_id = bq_store.create_chore(
        name=name,
        frequency=frequency,
        weekday=data.get("weekday") if frequency == "weekly" else None,
        day_of_month=data.get("day_of_month") if frequency == "monthly" else None,
        reminder_time=data.get("reminder_time", "09:00"),
    )
    return jsonify({"id": chore_id}), 201


@app.route("/api/chores/<chore_id>", methods=["DELETE"])
def delete_chore(chore_id):
    bq_store.delete_chore(chore_id)
    return jsonify({"ok": True})


@app.route("/api/chores/<chore_id>/done", methods=["POST"])
def mark_done(chore_id):
    bq_store.mark_done(chore_id, on=True)
    return jsonify({"ok": True})


@app.route("/api/chores/<chore_id>/undone", methods=["POST"])
def mark_undone(chore_id):
    bq_store.mark_done(chore_id, on=False)
    return jsonify({"ok": True})


@app.route("/api/chores/<chore_id>/snooze", methods=["POST"])
def snooze_chore(chore_id):
    data = request.get_json(silent=True) or {}
    minutes = int(data.get("minutes", 60))
    bq_store.snooze_chore(chore_id, minutes)
    return jsonify({"ok": True})


@app.route("/api/week", methods=["GET"])
def week():
    return jsonify(bq_store.week_progress())


@app.route("/api/subscribe", methods=["POST"])
def subscribe():
    sub_data = request.get_json(force=True)
    endpoint = sub_data.get("endpoint")
    if not endpoint:
        return jsonify({"error": "invalid subscription"}), 400
    bq_store.add_subscription(endpoint, json.dumps(sub_data))
    return jsonify({"ok": True})


@app.route("/api/test-push", methods=["POST"])
def test_push():
    subs = bq_store.list_active_subscriptions()
    for sub in subs:
        send_push(sub["endpoint"], sub["subscription_json"], "Chore Builder", "Test notification — push is working!")
    return jsonify({"sent": len(subs)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5099))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port, use_reloader=False)

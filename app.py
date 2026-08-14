import json
import os
from datetime import datetime, date, timedelta

from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from pywebpush import webpush, WebPushException

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "chores.db"))

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


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

FREQUENCIES = ["daily", "weekly", "monthly"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Chore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    frequency = db.Column(db.String(20), nullable=False, default="daily")
    weekday = db.Column(db.Integer, nullable=True)  # 0=Mon..6=Sun, for weekly
    day_of_month = db.Column(db.Integer, nullable=True)  # for monthly
    reminder_time = db.Column(db.String(5), nullable=False, default="09:00")  # HH:MM
    last_done_date = db.Column(db.String(10), nullable=True)  # ISO date
    last_reminded_date = db.Column(db.String(10), nullable=True)  # ISO date, avoid duplicate sends
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_due_today(self, today: date) -> bool:
        if self.frequency == "daily":
            return True
        if self.frequency == "weekly":
            return self.weekday == today.weekday()
        if self.frequency == "monthly":
            return self.day_of_month == today.day
        return False

    def is_done_today(self, today: date) -> bool:
        return self.last_done_date == today.isoformat()

    def previous_due_date(self, from_date: date) -> date:
        """Most recent due date strictly before from_date."""
        if self.frequency == "daily":
            return from_date - timedelta(days=1)
        if self.frequency == "weekly":
            d = from_date - timedelta(days=1)
            while d.weekday() != self.weekday:
                d -= timedelta(days=1)
            return d
        if self.frequency == "monthly":
            d = from_date.replace(day=1) - timedelta(days=1)  # last day of prev month
            target_day = min(self.day_of_month, d.day)
            return d.replace(day=target_day)
        return from_date - timedelta(days=1)

    def compute_streak(self, today: date) -> int:
        done_dates = {
            c.completed_date for c in ChoreCompletion.query.filter_by(chore_id=self.id).all()
        }
        pointer = today if self.is_due_today(today) else self.previous_due_date(today + timedelta(days=1))
        if pointer == today and today.isoformat() not in done_dates:
            pointer = self.previous_due_date(today)

        streak = 0
        guard = 0
        while pointer.isoformat() in done_dates and guard < 3650:
            streak += 1
            pointer = self.previous_due_date(pointer)
            guard += 1
        return streak

    def to_dict(self):
        today = date.today()
        return {
            "id": self.id,
            "name": self.name,
            "frequency": self.frequency,
            "weekday": self.weekday,
            "day_of_month": self.day_of_month,
            "reminder_time": self.reminder_time,
            "done_today": self.is_done_today(today),
            "due_today": self.is_due_today(today),
            "streak": self.compute_streak(today),
        }


class ChoreCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chore_id = db.Column(db.Integer, db.ForeignKey("chore.id"), nullable=False)
    completed_date = db.Column(db.String(10), nullable=False)  # ISO date
    __table_args__ = (db.UniqueConstraint("chore_id", "completed_date", name="uq_chore_date"),)


class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.String(500), unique=True, nullable=False)
    subscription_json = db.Column(db.Text, nullable=False)


with app.app_context():
    db.create_all()


def send_push(subscription: PushSubscription, title: str, body: str):
    try:
        webpush(
            subscription_info=json.loads(subscription.subscription_json),
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=dict(VAPID_CLAIMS),
        )
    except WebPushException as ex:
        if ex.response is not None and ex.response.status_code in (404, 410):
            db.session.delete(subscription)
            db.session.commit()


def check_and_send_reminders():
    with app.app_context():
        now = datetime.now()
        today = now.date()
        current_hm = now.strftime("%H:%M")
        subs = PushSubscription.query.all()
        if not subs:
            return
        chores = Chore.query.all()
        for chore in chores:
            if not chore.is_due_today(today):
                continue
            if chore.is_done_today(today):
                continue
            if chore.reminder_time != current_hm:
                continue
            if chore.last_reminded_date == today.isoformat():
                continue
            for sub in subs:
                send_push(sub, "Chore reminder", f"Time to do: {chore.name}")
            chore.last_reminded_date = today.isoformat()
            db.session.commit()


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
    chores = Chore.query.order_by(Chore.created_at).all()
    return jsonify([c.to_dict() for c in chores])


@app.route("/api/chores", methods=["POST"])
def create_chore():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    frequency = data.get("frequency", "daily")
    if not name:
        return jsonify({"error": "name is required"}), 400
    if frequency not in FREQUENCIES:
        return jsonify({"error": "invalid frequency"}), 400

    chore = Chore(
        name=name,
        frequency=frequency,
        weekday=data.get("weekday") if frequency == "weekly" else None,
        day_of_month=data.get("day_of_month") if frequency == "monthly" else None,
        reminder_time=data.get("reminder_time", "09:00"),
    )
    db.session.add(chore)
    db.session.commit()
    return jsonify(chore.to_dict()), 201


@app.route("/api/chores/<int:chore_id>", methods=["DELETE"])
def delete_chore(chore_id):
    chore = Chore.query.get_or_404(chore_id)
    ChoreCompletion.query.filter_by(chore_id=chore.id).delete()
    db.session.delete(chore)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/chores/<int:chore_id>/done", methods=["POST"])
def mark_done(chore_id):
    chore = Chore.query.get_or_404(chore_id)
    today_iso = date.today().isoformat()
    chore.last_done_date = today_iso
    if not ChoreCompletion.query.filter_by(chore_id=chore.id, completed_date=today_iso).first():
        db.session.add(ChoreCompletion(chore_id=chore.id, completed_date=today_iso))
    db.session.commit()
    return jsonify(chore.to_dict())


@app.route("/api/chores/<int:chore_id>/undone", methods=["POST"])
def mark_undone(chore_id):
    chore = Chore.query.get_or_404(chore_id)
    today_iso = date.today().isoformat()
    chore.last_done_date = None
    ChoreCompletion.query.filter_by(chore_id=chore.id, completed_date=today_iso).delete()
    db.session.commit()
    return jsonify(chore.to_dict())


@app.route("/api/heatmap", methods=["GET"])
def heatmap():
    days = 84  # 12 weeks
    start = date.today() - timedelta(days=days - 1)
    rows = (
        db.session.query(ChoreCompletion.completed_date, db.func.count(ChoreCompletion.id))
        .filter(ChoreCompletion.completed_date >= start.isoformat())
        .group_by(ChoreCompletion.completed_date)
        .all()
    )
    counts = {d: c for d, c in rows}
    result = []
    for i in range(days):
        d = start + timedelta(days=i)
        result.append({"date": d.isoformat(), "count": counts.get(d.isoformat(), 0)})
    return jsonify(result)


@app.route("/api/subscribe", methods=["POST"])
def subscribe():
    sub_data = request.get_json(force=True)
    endpoint = sub_data.get("endpoint")
    if not endpoint:
        return jsonify({"error": "invalid subscription"}), 400
    existing = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if existing:
        existing.subscription_json = json.dumps(sub_data)
    else:
        db.session.add(PushSubscription(endpoint=endpoint, subscription_json=json.dumps(sub_data)))
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/test-push", methods=["POST"])
def test_push():
    subs = PushSubscription.query.all()
    for sub in subs:
        send_push(sub, "Chore Builder", "Test notification — push is working!")
    return jsonify({"sent": len(subs)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5099))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port, use_reloader=False)

"""GroupHub — MVP for group-travel agencies (Team 7, Lean Startup Lab 2026).

Run locally:   python app.py            -> http://localhost:5000
Production:    gunicorn app:app         (Render does this for you, see README.md)
"""
import os
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import quote as urlquote

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from analytics import KEY_EVENTS, pop_datalayer, track
from i18n import MONTHS, WEEKDAYS, translate
from models import (Activity, Agency, Announcement, ChecklistItem, Event,
                    ItineraryItem, Participant, ParticipantTask, QuoteVersion,
                    SupplierDeadline, Trip, User, db)

# ------------------------------------------------------------------ config
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
db_url = os.environ.get("DATABASE_URL", "sqlite:///grouphub.db")
if db_url.startswith("postgres://"):            # Neon/Render give postgres://, SQLAlchemy wants postgresql+psycopg://
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 280}
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=90)
APP_NAME = os.environ.get("APP_NAME", "GroupHub")
GTM_ID = os.environ.get("GTM_ID", "")            # e.g. GTM-XXXXXXX  (leave empty locally)
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")      # protects /admin/metrics

db.init_app(app)
with app.app_context():
    db.create_all()


# ------------------------------------------------------------------ helpers
def lang():
    return g.get("lang", "it")


def t(key, **kw):
    return translate(lang(), key, **kw)


def fmt_date(d, weekday=False):
    if not d:
        return ""
    s = f"{d.day} {MONTHS[lang()][d.month - 1]} {d.year}"
    return f"{WEEKDAYS[lang()][d.weekday()]} {s}" if weekday else s


def fmt_dt(dt):
    if not dt:
        return ""
    return f"{fmt_date(dt.date())}, {dt:%H:%M}"


def fmt_money(v):
    if v is None:
        return ""
    s = f"{v:,.2f}"
    if lang() == "it":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return "€ " + s


def rel_days(n):
    if n is None:
        return ""
    if n == 0:
        return t("today")
    if n < 0:
        return t("days_ago", n=-n)
    return t("days_left", n=n)


def parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def parse_money(s):
    if not s:
        return None
    s = s.replace("€", "").replace(" ", "")
    if "," in s:                      # Italian format: 1.900,50
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def log(trip, actor, kind, **params):
    db.session.add(Activity(trip_id=trip.id, actor=actor, kind=kind, params=params or None))


def current_user():
    uid = session.get("uid")
    return db.session.get(User, uid) if uid else None


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper


def get_trip_or_404(trip_id):
    trip = db.session.get(Trip, trip_id)
    if not trip or trip.agency_id != g.user.agency_id:   # authorization: only your agency's trips
        abort(404)
    return trip


def ensure_tasks(trip):
    """Make sure every participant has one task row per checklist item."""
    for p in trip.participants:
        have = {tk.item_id for tk in p.tasks}
        for it in trip.items:
            if it.id not in have:
                db.session.add(ParticipantTask(participant_id=p.id, item_id=it.id, status="todo"))
    db.session.commit()


def item_progress(item, participants):
    total = len(participants)
    done = sum(1 for p in participants if p.status_for(item.id) in ("submitted", "verified"))
    verified = sum(1 for p in participants if p.status_for(item.id) == "verified")
    missing = [p for p in participants if p.status_for(item.id) == "todo"]
    pct = round(100 * done / total) if total else 0
    return {"total": total, "done": done, "verified": verified, "missing": missing, "pct": pct}


def trip_completion(trip):
    cells = len(trip.participants) * len(trip.items)
    if not cells:
        return None
    done = sum(1 for p in trip.participants for tk in p.tasks if tk.status in ("submitted", "verified"))
    return round(100 * done / cells)


def merged_deadlines(trip, limit=None):
    rows = []
    parts = trip.participants
    for it in trip.items:
        if it.due_date:
            pr = item_progress(it, parts)
            if pr["done"] < pr["total"] or not pr["total"]:
                rows.append({"date": it.due_date, "label": it.title, "sub": f"{pr['done']}/{pr['total']}",
                             "kind": "checklist"})
    for d in trip.deadlines:
        if not d.done:
            rows.append({"date": d.due_date, "label": f"{d.supplier} · {d.what or ''}".strip(" ·"),
                         "sub": d.penalty or "", "kind": "supplier"})
    rows.sort(key=lambda r: r["date"])
    return rows[:limit] if limit else rows


def reminder_for(trip, item, prog):
    names = ", ".join(p.name for p in prog["missing"])
    due = t("reminder_due", d=fmt_date(item.due_date)) if item.due_date else ""
    link = url_for("join", token=trip.join_token, _external=True)
    text = t("reminder_text", trip=trip.title, item=item.title, due=due, names=names, link=link)
    return text, "https://wa.me/?text=" + urlquote(text)


# ------------------------------------------------------------------ request hooks
@app.before_request
def before():
    g.lang = request.cookies.get("lang", "it") if request.cookies.get("lang") in ("it", "en") else "it"
    g.user = current_user()
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(16)
    if request.method == "POST":
        sent = request.form.get("csrf") or request.headers.get("X-CSRF")
        if sent != session["csrf"]:
            abort(400, "CSRF token missing or wrong. Reload the page and try again.")
    # retention signal: first visit of the day by an agent
    if g.user and request.endpoint not in ("static",):
        today = date.today()
        if g.user.last_active_on != today:
            g.user.last_active_on = today
            db.session.commit()
            track("agent_session", "agent", agency_id=g.user.agency_id)


def act_text(a):
    params = dict(a.params or {})
    if "channel" in params:
        params["channel"] = t("ch_" + params["channel"])
    return t(a.kind, **params)


@app.context_processor
def inject():
    return dict(t=t, lang=lang(), act_text=act_text, fmt_date=fmt_date, fmt_dt=fmt_dt, fmt_money=fmt_money,
                rel_days=rel_days, APP_NAME=APP_NAME, GTM_ID=GTM_ID, csrf=session.get("csrf", ""),
                user=g.get("user"), today=date.today())


@app.after_request
def after(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"   # don't leak no-login tokens to other sites
    return resp


def render(tpl, **ctx):
    return render_template(tpl, datalayer=pop_datalayer(), **ctx)


# ------------------------------------------------------------------ public
@app.route("/")
def landing():
    if g.user:
        return redirect(url_for("trips"))
    track("landing_view", "visitor", ref=request.referrer or "", utm=request.args.get("utm_source", ""))
    return render("landing.html")


@app.route("/lang/<code>")
def set_lang(code):
    resp = redirect(request.referrer or url_for("landing"))
    if code in ("it", "en"):
        resp.set_cookie("lang", code, max_age=3600 * 24 * 365, samesite="Lax")
        track("language_switched", "visitor", to=code)
    return resp


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        f = request.form
        name, email, pw, agency = f.get("name", "").strip(), f.get("email", "").strip().lower(), f.get("password", ""), f.get("agency", "").strip()
        if not (name and email and pw and agency):
            flash(t("err_required"), "error")
        elif len(pw) < 8:
            flash(t("err_password_short"), "error")
        elif User.query.filter_by(email=email).first():
            flash(t("err_email_taken"), "error")
        else:
            ag = Agency(name=agency)
            db.session.add(ag)
            db.session.flush()
            u = User(agency_id=ag.id, name=name, email=email, pw_hash=generate_password_hash(pw, method="pbkdf2:sha256"))
            db.session.add(u)
            db.session.commit()
            session.clear()
            session.permanent = True
            session["uid"] = u.id
            track("sign_up", "agent", agency_id=ag.id, from_demo=bool(request.args.get("from_demo")))
            return redirect(url_for("trip_new"))
    return render("auth.html", mode="signup")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if u and check_password_hash(u.pw_hash, request.form.get("password", "")):
            session.clear()
            session.permanent = True
            session["uid"] = u.id
            track("login", "agent", agency_id=u.agency_id)
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("trips"))
        flash(t("err_login"), "error")
    return render("auth.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/demo")
def demo():
    from seed import create_demo_agency, purge_old_demos
    purge_old_demos()
    user, trip = create_demo_agency()
    session.clear()
    session["uid"] = user.id
    track("demo_started", "visitor", agency_id=user.agency_id)
    return redirect(url_for("trip_view", trip_id=trip.id))


# ------------------------------------------------------------------ agent: trips
@app.route("/trips")
@login_required
def trips():
    rows = Trip.query.filter_by(agency_id=g.user.agency_id).order_by(Trip.start_date.is_(None), Trip.start_date).all()
    return render("trips.html", trips=rows, completion=trip_completion)


@app.route("/trips/new", methods=["GET", "POST"])
@login_required
def trip_new():
    if request.method == "POST":
        f = request.form
        if not f.get("title", "").strip():
            flash(t("err_required"), "error")
            return render("trip_new.html")
        trip = Trip(agency_id=g.user.agency_id, title=f["title"].strip(), destination=f.get("destination", "").strip(),
                    start_date=parse_date(f.get("start_date")), end_date=parse_date(f.get("end_date")),
                    rep_name=f.get("rep_name", "").strip(), rep_email=f.get("rep_email", "").strip())
        db.session.add(trip)
        db.session.flush()
        log(trip, g.user.name, "act_trip_created")
        db.session.commit()
        track("trip_created", "agent", trip=trip)
        flash(t("fl_trip_created"), "ok")
        return redirect(url_for("trip_view", trip_id=trip.id))
    return render("trip_new.html")


TABS = ["overview", "quotes", "checklist", "participants", "info", "deadlines", "history"]


@app.route("/trips/<int:trip_id>")
@login_required
def trip_view(trip_id):
    trip = get_trip_or_404(trip_id)
    tab = request.args.get("tab", "overview")
    if tab not in TABS:
        tab = "overview"
    ensure_tasks(trip)
    progress = {it.id: item_progress(it, trip.participants) for it in trip.items}
    reminders = {it.id: reminder_for(trip, it, progress[it.id]) for it in trip.items}
    return render("trip.html", trip=trip, tab=tab, tabs=TABS, progress=progress, reminders=reminders,
                  completion=trip_completion(trip), deadlines=merged_deadlines(trip),
                  join_url=url_for("join", token=trip.join_token, _external=True),
                  rep_url=url_for("rep_page", token=trip.rep_token, _external=True))


def back(trip, tab):
    return redirect(url_for("trip_view", trip_id=trip.id, tab=tab))


# ---- quotes (US2)
@app.post("/trips/<int:trip_id>/quotes")
@login_required
def quote_add(trip_id):
    trip = get_trip_or_404(trip_id)
    f = request.form
    n = (max((q.version_no for q in trip.quotes), default=0)) + 1
    pax = f.get("pax", "").strip()
    q = QuoteVersion(trip_id=trip.id, version_no=n, title=f.get("title", "").strip(),
                     price_per_person=parse_money(f.get("price_per_person")),
                     pax=int(pax) if pax.isdigit() else None, changes=f.get("changes", "").strip(),
                     link_url=f.get("link_url", "").strip(), created_by=g.user.name, status="sent")
    db.session.add(q)
    log(trip, g.user.name, "act_quote_added", v=n)
    db.session.commit()
    track("quote_added", "agent", trip=trip, version=n)
    return back(trip, "quotes")


def approve_quote(trip, q, who, channel, note=""):
    for other in trip.quotes:
        if other.id != q.id and (other.version_no < q.version_no or other.status == "approved"):
            other.status = "superseded"
    q.status = "approved"
    q.approved_by, q.approved_at, q.approval_channel, q.approval_note = who, datetime.utcnow(), channel, note
    log(trip, who, "act_quote_approved", v=q.version_no, channel=channel)
    db.session.commit()


@app.post("/trips/<int:trip_id>/quotes/<int:qid>/approve")
@login_required
def quote_record_approval(trip_id, qid):
    trip = get_trip_or_404(trip_id)
    q = db.session.get(QuoteVersion, qid)
    if not q or q.trip_id != trip.id:
        abort(404)
    who = request.form.get("approved_by", "").strip() or trip.rep_name or "?"
    channel = request.form.get("channel", "email")
    approve_quote(trip, q, who, channel, request.form.get("note", "").strip())
    track("quote_approved", "agent", trip=trip, version=q.version_no, channel=channel)
    flash(t("fl_quote_approved", v=q.version_no), "ok")
    return back(trip, "quotes")


# ---- checklist (US3)
@app.post("/trips/<int:trip_id>/items")
@login_required
def item_add(trip_id):
    trip = get_trip_or_404(trip_id)
    f = request.form
    if not f.get("title", "").strip():
        flash(t("err_required"), "error")
        return back(trip, "checklist")
    it = ChecklistItem(trip_id=trip.id, kind=f.get("kind", "document"), title=f["title"].strip(),
                       description=f.get("description", "").strip(), amount=parse_money(f.get("amount")),
                       due_date=parse_date(f.get("due_date")))
    db.session.add(it)
    log(trip, g.user.name, "act_item_added", title=it.title)
    db.session.commit()
    track("checklist_item_created", "agent", trip=trip, kind=it.kind)
    return back(trip, "checklist")


@app.post("/trips/<int:trip_id>/items/<int:iid>/delete")
@login_required
def item_delete(trip_id, iid):
    trip = get_trip_or_404(trip_id)
    it = db.session.get(ChecklistItem, iid)
    if it and it.trip_id == trip.id:
        db.session.delete(it)
        db.session.commit()
    return back(trip, "checklist")


NEXT_STATUS = {"todo": "submitted", "submitted": "verified", "verified": "todo"}


@app.post("/trips/<int:trip_id>/tasks/<int:pid>/<int:iid>")
@login_required
def task_cycle(trip_id, pid, iid):
    trip = get_trip_or_404(trip_id)
    p = db.session.get(Participant, pid)
    if not p or p.trip_id != trip.id:
        abort(404)
    tk = p.task_for(iid)
    if not tk:
        abort(404)
    tk.status = NEXT_STATUS[tk.status]
    tk.updated_at = datetime.utcnow()
    if tk.status == "verified":
        log(trip, g.user.name, "act_task_verified", title=tk.item.title, name=p.name)
    db.session.commit()
    is_fetch = request.headers.get("X-Requested-With") == "fetch"
    track("task_verified" if tk.status == "verified" else "task_status_changed", "agent", trip=trip,
          queue=not is_fetch, status=tk.status)
    if is_fetch:
        return jsonify(status=tk.status, label=t("st_" + tk.status))
    return back(trip, "checklist")


@app.post("/trips/<int:trip_id>/track")
@login_required
def track_client(trip_id):
    """Small client-side events (copy buttons) that don't change data."""
    trip = get_trip_or_404(trip_id)
    name = request.form.get("event", "")
    if name in ("reminder_copied", "reminder_whatsapp", "invite_link_copied", "rep_link_copied", "personal_link_copied"):
        track(name, "agent", trip=trip, queue=False)
    return ("", 204)


# ---- participants
@app.post("/trips/<int:trip_id>/participants")
@login_required
def participants_add(trip_id):
    trip = get_trip_or_404(trip_id)
    n = 0
    for line in request.form.get("bulk", "").splitlines():
        parts = [x.strip() for x in line.replace("\t", ",").replace(";", ",").split(",")]
        if not parts or not parts[0]:
            continue
        email = next((x for x in parts[1:] if "@" in x), "")
        db.session.add(Participant(trip_id=trip.id, name=parts[0][:200], email=email[:200]))
        n += 1
    if n:
        log(trip, g.user.name, "act_participants_added", n=n)
        db.session.commit()
        track("participant_added", "agent", trip=trip, count=n)
        flash(t("fl_participants_added", n=n), "ok")
    return back(trip, "participants")


@app.post("/trips/<int:trip_id>/participants/<int:pid>/delete")
@login_required
def participant_delete(trip_id, pid):
    trip = get_trip_or_404(trip_id)
    p = db.session.get(Participant, pid)
    if p and p.trip_id == trip.id:
        db.session.delete(p)
        db.session.commit()
    return back(trip, "participants")


# ---- programme & announcements
@app.post("/trips/<int:trip_id>/itinerary")
@login_required
def itinerary_add(trip_id):
    trip = get_trip_or_404(trip_id)
    f = request.form
    if f.get("title", "").strip():
        db.session.add(ItineraryItem(trip_id=trip.id, day=parse_date(f.get("day")), time=f.get("time", "").strip(),
                                     title=f["title"].strip(), location=f.get("location", "").strip(),
                                     notes=f.get("notes", "").strip()))
        log(trip, g.user.name, "act_itinerary", title=f["title"].strip())
        db.session.commit()
        track("itinerary_item_added", "agent", trip=trip)
    return back(trip, "info")


@app.post("/trips/<int:trip_id>/itinerary/<int:xid>/delete")
@login_required
def itinerary_delete(trip_id, xid):
    trip = get_trip_or_404(trip_id)
    x = db.session.get(ItineraryItem, xid)
    if x and x.trip_id == trip.id:
        db.session.delete(x)
        db.session.commit()
    return back(trip, "info")


@app.post("/trips/<int:trip_id>/announcements")
@login_required
def announcement_add(trip_id):
    trip = get_trip_or_404(trip_id)
    body = request.form.get("body", "").strip()
    if body:
        db.session.add(Announcement(trip_id=trip.id, body=body, author=g.user.name))
        log(trip, g.user.name, "act_announcement")
        db.session.commit()
        track("announcement_published", "agent", trip=trip)
    return back(trip, "info")


@app.post("/trips/<int:trip_id>/announcements/<int:aid>/delete")
@login_required
def announcement_delete(trip_id, aid):
    trip = get_trip_or_404(trip_id)
    a = db.session.get(Announcement, aid)
    if a and a.trip_id == trip.id:
        db.session.delete(a)
        db.session.commit()
    return back(trip, "info")


# ---- supplier deadlines (US5)
@app.post("/trips/<int:trip_id>/deadlines")
@login_required
def deadline_add(trip_id):
    trip = get_trip_or_404(trip_id)
    f = request.form
    d = parse_date(f.get("due_date"))
    if not (f.get("supplier", "").strip() and d):
        flash(t("err_required"), "error")
        return back(trip, "deadlines")
    db.session.add(SupplierDeadline(trip_id=trip.id, supplier=f["supplier"].strip(), what=f.get("what", "").strip(),
                                    due_date=d, penalty=f.get("penalty", "").strip()))
    log(trip, g.user.name, "act_deadline_added", supplier=f["supplier"].strip())
    db.session.commit()
    track("supplier_deadline_added", "agent", trip=trip)
    return back(trip, "deadlines")


@app.post("/trips/<int:trip_id>/deadlines/<int:did>/toggle")
@login_required
def deadline_toggle(trip_id, did):
    trip = get_trip_or_404(trip_id)
    d = db.session.get(SupplierDeadline, did)
    if d and d.trip_id == trip.id:
        d.done = not d.done
        if d.done:
            log(trip, g.user.name, "act_deadline_done", supplier=d.supplier)
        db.session.commit()
    return back(trip, "deadlines")


@app.post("/trips/<int:trip_id>/deadlines/<int:did>/delete")
@login_required
def deadline_delete(trip_id, did):
    trip = get_trip_or_404(trip_id)
    d = db.session.get(SupplierDeadline, did)
    if d and d.trip_id == trip.id:
        db.session.delete(d)
        db.session.commit()
    return back(trip, "deadlines")


# ------------------------------------------------------------------ no-login pages (US4)
@app.route("/g/<token>", methods=["GET", "POST"])
def join(token):
    trip = Trip.query.filter_by(join_token=token).first()
    if not trip:
        return render("message.html", msg=t("link_not_found")), 404
    # returning visitor on the same phone -> straight to their page
    known = session.get("ptoken_" + str(trip.id))
    if request.method == "GET" and known and Participant.query.filter_by(token=known).first():
        return redirect(url_for("participant_page", token=known))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        if not name:
            flash(t("err_required"), "error")
        else:
            p = None
            if email:   # the agency may have pre-loaded this person: reuse their row
                p = Participant.query.filter_by(trip_id=trip.id, email=email).first()
            if not p:
                p = Participant(trip_id=trip.id, name=name[:200], email=email[:200], joined_via_link=True)
                db.session.add(p)
                db.session.flush()
                log(trip, name, "act_participant_joined")
            p.joined_via_link = True
            db.session.commit()
            session.permanent = True
            session["ptoken_" + str(trip.id)] = p.token
            track("participant_joined", "participant", trip=trip)
            flash(t("fl_welcome"), "ok")
            return redirect(url_for("participant_page", token=p.token))
    track("join_page_view", "participant", trip=trip)
    return render("join.html", trip=trip)


@app.route("/p/<token>")
def participant_page(token):
    p = Participant.query.filter_by(token=token).first()
    if not p:
        return render("message.html", msg=t("link_not_found")), 404
    trip = p.trip
    ensure_tasks(trip)
    p.last_seen_at = datetime.utcnow()
    db.session.commit()
    session["ptoken_" + str(trip.id)] = p.token
    track("participant_page_view", "participant", trip=trip)
    return render("participant.html", p=p, trip=trip)


@app.post("/p/<token>/task/<int:iid>")
def participant_task(token, iid):
    p = Participant.query.filter_by(token=token).first_or_404()
    tk = p.task_for(iid)
    if not tk:
        abort(404)
    if tk.status == "todo":
        tk.status = "submitted"
        log(p.trip, p.name, "act_task_done", title=tk.item.title)
        track("task_marked_done", "participant", trip=p.trip, kind=tk.item.kind)
    elif tk.status == "submitted":
        tk.status = "todo"
        track("task_unmarked", "participant", trip=p.trip)
    tk.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("participant_page", token=token) + "#todo")


@app.route("/r/<token>")
def rep_page(token):
    trip = Trip.query.filter_by(rep_token=token).first()
    if not trip:
        return render("message.html", msg=t("link_not_found")), 404
    ensure_tasks(trip)
    progress = {it.id: item_progress(it, trip.participants) for it in trip.items}
    decisions = [a for a in trip.activity if a.kind in ("act_quote_added", "act_quote_approved", "act_deadline_done")]
    track("rep_page_view", "rep", trip=trip)
    return render("rep.html", trip=trip, progress=progress, decisions=decisions,
                  deadlines=merged_deadlines(trip), join_url=url_for("join", token=trip.join_token, _external=True))


@app.post("/r/<token>/approve/<int:qid>")
def rep_approve(token, qid):
    trip = Trip.query.filter_by(rep_token=token).first_or_404()
    q = db.session.get(QuoteVersion, qid)
    if not q or q.trip_id != trip.id or q.status != "sent":
        abort(404)
    who = request.form.get("name", "").strip()
    if not who:
        flash(t("err_required"), "error")
        return redirect(url_for("rep_page", token=token))
    approve_quote(trip, q, who, "in_app")
    track("quote_approved", "rep", trip=trip, version=q.version_no, channel="in_app")
    flash(t("fl_quote_approved", v=q.version_no), "ok")
    return redirect(url_for("rep_page", token=token))


# ------------------------------------------------------------------ team-only metrics (L08)
@app.route("/admin/metrics")
def metrics():
    if not ADMIN_KEY or request.args.get("key") != ADMIN_KEY:
        abort(404)
    include_demo = request.args.get("demo") == "1"
    q = Event.query
    if not include_demo:
        q = q.filter(Event.is_demo.is_(False))
    events = q.all()

    # totals by event name
    totals = {}
    for e in events:
        totals[e.name] = totals.get(e.name, 0) + 1

    # weekly counts (ISO week) for the Metrics Tracker
    weeks = sorted({e.created_at.strftime("%G-W%V") for e in events})
    weekly = {}
    for e in events:
        wk = e.created_at.strftime("%G-W%V")
        weekly.setdefault(e.name, {}).setdefault(wk, 0)
        weekly[e.name][wk] += 1

    # agency funnel, by sign-up cohort week
    agencies = Agency.query.filter_by(is_demo=False).all() if not include_demo else Agency.query.all()
    by_agency = {}
    for e in events:
        if e.agency_id:
            by_agency.setdefault(e.agency_id, set()).add(e.name)
    cohorts = {}
    for ag in agencies:
        wk = ag.created_at.strftime("%G-W%V")
        c = cohorts.setdefault(wk, {"signed_up": 0, "trip": 0, "quote_or_item": 0, "shared": 0, "joined": 0, "approved": 0, "week2": 0})
        names = by_agency.get(ag.id, set())
        c["signed_up"] += 1
        c["trip"] += "trip_created" in names
        c["quote_or_item"] += bool(names & {"quote_added", "checklist_item_created"})
        c["shared"] += bool(names & {"invite_link_copied", "rep_link_copied", "reminder_copied", "reminder_whatsapp"})
        c["joined"] += "participant_joined" in names
        c["approved"] += "quote_approved" in names
        active_days = {e.created_at.date() for e in events if e.agency_id == ag.id and e.actor_type == "agent"}
        c["week2"] += any(d >= ag.created_at.date() + timedelta(days=7) for d in active_days)
    return render("metrics.html", totals=dict(sorted(totals.items(), key=lambda x: -x[1])), weeks=weeks,
                  weekly=weekly, cohorts=dict(sorted(cohorts.items())), key_events=KEY_EVENTS,
                  include_demo=include_demo, n_events=len(events))


@app.errorhandler(404)
def not_found(e):
    return render("message.html", msg="404 · " + t("link_not_found")), 404


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))

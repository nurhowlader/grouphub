"""Database models (the 'pantry' in L06 terms).

Every table here maps to a user story in docs/MVP_One_Pager.md.
"""
import secrets
from datetime import datetime, date

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def new_token(n: int = 16) -> str:
    """Unguessable token used for no-login links."""
    return secrets.token_urlsafe(n)


def utcnow():
    return datetime.utcnow()


# ---------------------------------------------------------------- agency side
class Agency(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    is_demo = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    users = db.relationship("User", backref="agency", lazy=True)
    trips = db.relationship("Trip", backref="agency", lazy=True)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    agency_id = db.Column(db.Integer, db.ForeignKey("agency.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    pw_hash = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_active_on = db.Column(db.Date)  # for the agent_session retention event


# ---------------------------------------------------------------- the trip (US1)
class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    agency_id = db.Column(db.Integer, db.ForeignKey("agency.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    destination = db.Column(db.String(200))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    rep_name = db.Column(db.String(200))
    rep_email = db.Column(db.String(200))
    join_token = db.Column(db.String(64), unique=True, default=new_token)  # link shared with the whole group
    rep_token = db.Column(db.String(64), unique=True, default=new_token)   # link only for the representative
    created_at = db.Column(db.DateTime, default=utcnow)

    participants = db.relationship("Participant", backref="trip", lazy=True,
                                   cascade="all, delete-orphan", order_by="Participant.name")
    quotes = db.relationship("QuoteVersion", backref="trip", lazy=True,
                             cascade="all, delete-orphan", order_by="QuoteVersion.version_no.desc()")
    items = db.relationship("ChecklistItem", backref="trip", lazy=True,
                            cascade="all, delete-orphan", order_by="ChecklistItem.due_date")
    itinerary = db.relationship("ItineraryItem", backref="trip", lazy=True,
                                cascade="all, delete-orphan",
                                order_by=lambda: [ItineraryItem.day, ItineraryItem.time])
    announcements = db.relationship("Announcement", backref="trip", lazy=True,
                                    cascade="all, delete-orphan",
                                    order_by="Announcement.created_at.desc()")
    deadlines = db.relationship("SupplierDeadline", backref="trip", lazy=True,
                                cascade="all, delete-orphan", order_by="SupplierDeadline.due_date")
    activity = db.relationship("Activity", backref="trip", lazy=True,
                               cascade="all, delete-orphan", order_by="Activity.created_at.desc()")

    @property
    def official_quote(self):
        return next((q for q in self.quotes if q.status == "approved"), None)

    @property
    def days_to_departure(self):
        return (self.start_date - date.today()).days if self.start_date else None


class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    token = db.Column(db.String(64), unique=True, default=new_token)  # personal no-login link
    joined_via_link = db.Column(db.Boolean, default=False)
    last_seen_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)
    tasks = db.relationship("ParticipantTask", backref="participant", lazy=True,
                            cascade="all, delete-orphan")

    def task_for(self, item_id):
        return next((t for t in self.tasks if t.item_id == item_id), None)

    def status_for(self, item_id):
        t = self.task_for(item_id)
        return t.status if t else "todo"


# ---------------------------------------------------------------- quotes (US2)
class QuoteVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    version_no = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200))
    price_per_person = db.Column(db.Numeric(10, 2))
    pax = db.Column(db.Integer)
    changes = db.Column(db.Text)          # "what changed vs previous version"
    link_url = db.Column(db.String(500))  # link to the PDF / quote in the agency's system
    status = db.Column(db.String(20), default="sent")  # sent | approved | superseded
    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=utcnow)
    approved_by = db.Column(db.String(200))
    approved_at = db.Column(db.DateTime)
    approval_channel = db.Column(db.String(30))  # in_app | email | whatsapp | phone
    approval_note = db.Column(db.Text)

    @property
    def total(self):
        if self.price_per_person is not None and self.pax:
            return self.price_per_person * self.pax
        return None


# ---------------------------------------------------------------- checklist (US3, US4)
class ChecklistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    kind = db.Column(db.String(20), default="document")  # document | payment | other
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    amount = db.Column(db.Numeric(10, 2))  # for payments
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=utcnow)
    tasks = db.relationship("ParticipantTask", backref="item", lazy=True,
                            cascade="all, delete-orphan")

    @property
    def is_overdue(self):
        return bool(self.due_date and self.due_date < date.today())


class ParticipantTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey("participant.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("checklist_item.id"), nullable=False)
    status = db.Column(db.String(20), default="todo")  # todo | submitted | verified
    updated_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("participant_id", "item_id"),)


# ---------------------------------------------------------------- information for the group
class ItineraryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    day = db.Column(db.Date)
    time = db.Column(db.String(10))
    title = db.Column(db.String(200), nullable=False)
    location = db.Column(db.String(300))
    notes = db.Column(db.Text)


class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=utcnow)


# ---------------------------------------------------------------- supplier deadlines (US5)
class SupplierDeadline(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    supplier = db.Column(db.String(200), nullable=False)
    what = db.Column(db.String(300))         # e.g. "Confirm final rooming list"
    due_date = db.Column(db.Date, nullable=False)
    penalty = db.Column(db.String(300))      # e.g. "After this date: 50% of room cost"
    done = db.Column(db.Boolean, default=False)

    @property
    def days_left(self):
        return (self.due_date - date.today()).days


# ---------------------------------------------------------------- history (US1) + analytics
class Activity(db.Model):
    """Human-readable history of the trip file: what was requested, quoted, changed, approved."""
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    actor = db.Column(db.String(200))
    kind = db.Column(db.String(40))   # i18n key, e.g. "act_quote_added" (rendered in the viewer's language)
    params = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utcnow)


class Event(db.Model):
    """Analytics event (mirrors what is pushed to GTM/GA4). Never shown to users."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), index=True, nullable=False)
    agency_id = db.Column(db.Integer, index=True)
    trip_id = db.Column(db.Integer, index=True)
    actor_type = db.Column(db.String(20))  # agent | rep | participant | visitor
    props = db.Column(db.JSON)
    is_demo = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)

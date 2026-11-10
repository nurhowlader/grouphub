"""Instrumentation (L08): every meaningful action is recorded twice.

1. In our own `event` table  -> exact numbers for the Metrics Tracker and /admin/metrics.
2. Pushed to the browser's dataLayer on the next page -> Google Tag Manager -> GA4.
"""
from flask import session, request

from models import db, Event, Agency

# Events that represent success; register them as "key events" in GA4.
KEY_EVENTS = {"sign_up", "trip_created", "participant_joined", "task_marked_done", "quote_approved"}


def track(name, actor_type="visitor", agency_id=None, trip=None, queue=True, **props):
    if trip is not None and agency_id is None:
        agency_id = trip.agency_id
    is_demo = False
    if agency_id:
        ag = db.session.get(Agency, agency_id)
        is_demo = bool(ag and ag.is_demo)
    ev = Event(name=name, actor_type=actor_type, agency_id=agency_id,
               trip_id=trip.id if trip is not None else None,
               props=props or None, is_demo=is_demo)
    db.session.add(ev)
    db.session.commit()

    # queue for GTM: rendered as dataLayer.push(...) on the next HTML page
    # (queue=False when the browser already pushed the event itself)
    if not queue:
        return
    params = {"actor_type": actor_type, "is_demo": is_demo, **props}
    if trip is not None:
        params["trip_id"] = trip.id
    if agency_id:
        params["agency_id"] = agency_id
    queue = session.get("dl", [])
    queue.append({"event": "app_event", "event_name": name, "event_params": params})
    session["dl"] = queue[-10:]


def pop_datalayer():
    q = session.pop("dl", [])
    return q

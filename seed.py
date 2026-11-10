"""Demo data. Every click on "Try the demo" gets its own private sandbox agency.

Also usable from the command line to fill a local database:
    python seed.py
"""
import random
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from werkzeug.security import generate_password_hash

from models import (Activity, Agency, Announcement, ChecklistItem, ItineraryItem,
                    Participant, ParticipantTask, QuoteVersion, SupplierDeadline,
                    Trip, User, db)

NAMES = ["Giulia Bianchi", "Marco Rossi", "Francesca Romano", "Luca Colombo", "Chiara Ricci",
         "Alessandro Marino", "Sara Greco", "Davide Bruno", "Elena Gallo", "Matteo Conti",
         "Valentina De Luca", "Simone Costa", "Martina Fontana", "Andrea Moretti", "Federica Barbieri",
         "Paolo Lombardi"]


FIXED_DEMO_EMAIL = "demo@grouphub.local"
FIXED_DEMO_PASSWORD = "demo1234"


def purge_old_demos(days=7):
    cutoff = datetime.utcnow() - timedelta(days=days)
    for ag in Agency.query.filter(Agency.is_demo.is_(True), Agency.created_at < cutoff).all():
        if any(u.email == FIXED_DEMO_EMAIL for u in ag.users):
            continue   # never purge the fixed demo login created by `python seed.py`
        for tr in ag.trips:
            db.session.delete(tr)
        for u in ag.users:
            db.session.delete(u)
        db.session.delete(ag)
    db.session.commit()


def create_demo_agency():
    ag = Agency(name="Agenzia Demo Viaggi", is_demo=True)
    db.session.add(ag)
    db.session.flush()
    u = User(agency_id=ag.id, name="Laura (agente demo)",
             email=f"demo-{secrets.token_hex(6)}@demo.local",
             pw_hash=generate_password_hash(secrets.token_urlsafe(12), method="pbkdf2:sha256"))
    db.session.add(u)
    db.session.flush()
    trip = build_demo_trip(ag, u)
    return u, trip


def build_demo_trip(ag, u):
    today = date.today()
    start = today + timedelta(days=68)
    now = datetime.utcnow()

    trip = Trip(agency_id=ag.id, title="Incentive Islanda 2027 – Rossi Auto",
                destination="Reykjavík, Islanda", start_date=start, end_date=start + timedelta(days=4),
                rep_name="Stefano Ferri", rep_email="s.ferri@rossiauto.example")
    db.session.add(trip)
    db.session.flush()

    def act(days_ago, actor, kind, **params):
        db.session.add(Activity(trip_id=trip.id, actor=actor, kind=kind, params=params or None,
                                created_at=now - timedelta(days=days_ago)))

    act(60, u.name, "act_trip_created")

    # --- quotes: v1, v2 superseded/approved, v3 awaiting approval (the rep can approve it in the demo)
    q1 = QuoteVersion(trip_id=trip.id, version_no=1, title="Proposta base 5 giorni / 4 notti",
                      price_per_person=Decimal("1690"), pax=50, status="superseded",
                      changes="Prima proposta: volo, hotel 4*, transfer, Golden Circle, cena di gala.",
                      created_by=u.name, created_at=now - timedelta(days=55))
    q2 = QuoteVersion(trip_id=trip.id, version_no=2, title="Hotel centro + whale watching",
                      price_per_person=Decimal("1780"), pax=50, status="approved",
                      changes="Hotel spostato in centro città; aggiunto whale watching il giorno 3.",
                      created_by=u.name, created_at=now - timedelta(days=40),
                      approved_by="Stefano Ferri", approved_at=now - timedelta(days=38),
                      approval_channel="in_app")
    q3 = QuoteVersion(trip_id=trip.id, version_no=3, title="Opzione escursione ghiacciaio",
                      price_per_person=Decimal("1845"), pax=52, status="sent",
                      changes="+2 partecipanti; escursione al ghiacciaio in alternativa al whale watching "
                              "(minimo 10 persone).",
                      created_by=u.name, created_at=now - timedelta(days=3))
    db.session.add_all([q1, q2, q3])
    act(55, u.name, "act_quote_added", v=1)
    act(40, u.name, "act_quote_added", v=2)
    act(38, "Stefano Ferri", "act_quote_approved", v=2, channel="in_app")
    act(3, u.name, "act_quote_added", v=3)

    # --- checklist
    items = [
        ChecklistItem(trip_id=trip.id, kind="document", title="Passaporto o carta d'identità valida",
                      description="Validità di almeno 3 mesi oltre la data di rientro. Invia una foto al referente.",
                      due_date=today + timedelta(days=18)),
        ChecklistItem(trip_id=trip.id, kind="payment", title="Acconto 30%", amount=Decimal("535.50"),
                      description="Bonifico all'agenzia, causale: nome e cognome + Islanda 2027.",
                      due_date=today - timedelta(days=4)),
        ChecklistItem(trip_id=trip.id, kind="other", title="Scelta escursione giorno 3",
                      description="Whale watching oppure ghiacciaio (minimo 10 persone). Comunicalo al referente.",
                      due_date=today + timedelta(days=6)),
        ChecklistItem(trip_id=trip.id, kind="payment", title="Saldo", amount=Decimal("1249.50"),
                      due_date=today + timedelta(days=38)),
    ]
    db.session.add_all(items)
    db.session.flush()
    for it in items:
        act(35, u.name, "act_item_added", title=it.title)

    # --- participants with a realistic spread of statuses
    rnd = random.Random(7)
    parts = []
    for i, n in enumerate(NAMES):
        p = Participant(trip_id=trip.id, name=n,
                        email=n.lower().replace(" ", ".") + "@example.com",
                        joined_via_link=i % 3 != 0,
                        last_seen_at=now - timedelta(days=rnd.randint(0, 12)) if i % 4 else None)
        db.session.add(p)
        parts.append(p)
    db.session.flush()
    act(33, u.name, "act_participants_added", n=len(parts))
    probs = [0.75, 0.85, 0.45, 0.0]  # chance of being done, per item
    for p in parts:
        for it, pr in zip(items, probs):
            r = rnd.random()
            st = "todo" if r > pr else ("verified" if r < pr * 0.6 else "submitted")
            db.session.add(ParticipantTask(participant_id=p.id, item_id=it.id, status=st))

    # --- programme
    prog = [
        (0, "06:15", "Ritrovo aeroporto Milano Malpensa T1", "Banco check-in compagnia aerea", "Portare passaporto."),
        (0, "15:30", "Transfer all'hotel e check-in", "Hotel 4* in centro città", ""),
        (0, "20:00", "Cena di benvenuto", "Ristorante tipico in centro", ""),
        (1, "08:30", "Golden Circle con guida", "Partenza dalla hall dell'hotel", "Scarpe da trekking e giacca impermeabile."),
        (2, "09:00", "Whale watching / escursione ghiacciaio", "Porto vecchio / ghiacciaio", "In base alla scelta fatta."),
        (2, "20:30", "Cena di gala", "Sala eventi sul porto", "Dress code elegante."),
        (3, "10:00", "Blue Lagoon", "Transfer dall'hotel", "Costume da bagno."),
        (4, "11:00", "Transfer in aeroporto e rientro", "Hall hotel", ""),
    ]
    for d, tm, title, loc, notes in prog:
        db.session.add(ItineraryItem(trip_id=trip.id, day=start + timedelta(days=d), time=tm,
                                     title=title, location=loc, notes=notes))
    act(20, u.name, "act_itinerary", title="Golden Circle con guida")

    db.session.add(Announcement(trip_id=trip.id, author=u.name, created_at=now - timedelta(days=2),
                                body="Novità: è disponibile l'escursione al ghiacciaio in alternativa al whale "
                                     "watching. Indicate la vostra scelta entro la scadenza nella vostra checklist."))
    db.session.add(Announcement(trip_id=trip.id, author=u.name, created_at=now - timedelta(days=15),
                                body="Il programma definitivo è online. Il volo di andata parte da Malpensa alle 8:40: "
                                     "ritrovo alle 6:15."))
    act(2, u.name, "act_announcement")

    # --- supplier deadlines
    sd = [
        ("Operatore whale watching", "Confermare numero partecipanti escursioni", 5,
         "Sotto i 10 iscritti l'escursione viene cancellata"),
        ("Hotel 4* centro città", "Rooming list definitiva", 12, "Dopo questa data penale del 30% sulle camere"),
        ("Sala eventi (cena di gala)", "Menu cena di gala e allergie", 25, "Variazioni menu non più garantite"),
        ("Compagnia aerea – ufficio gruppi", "Nomi definitivi per i biglietti", 40, "Cambio nome € 80 a persona"),
    ]
    for sup, what, days, pen in sd:
        db.session.add(SupplierDeadline(trip_id=trip.id, supplier=sup, what=what,
                                        due_date=today + timedelta(days=days), penalty=pen))
        act(30, u.name, "act_deadline_added", supplier=sup)

    db.session.commit()
    return trip


def reset_fixed_demo():
    """Create (or recreate) the fixed demo login. Safe to run more than once."""
    old = User.query.filter_by(email=FIXED_DEMO_EMAIL).first()
    if old:
        ag = old.agency
        for tr in ag.trips:
            db.session.delete(tr)
        for u in ag.users:
            db.session.delete(u)
        db.session.delete(ag)
        db.session.flush()
    user, trip = create_demo_agency()
    user.email = FIXED_DEMO_EMAIL
    user.pw_hash = generate_password_hash(FIXED_DEMO_PASSWORD, method="pbkdf2:sha256")
    db.session.commit()
    return user, trip


if __name__ == "__main__":
    from app import app
    with app.app_context():
        user, trip = reset_fixed_demo()
        print(f"Seeded. Log in with {FIXED_DEMO_EMAIL} / {FIXED_DEMO_PASSWORD}")
        print("Rep link:         /r/" + trip.rep_token)
        print("Group join link:  /g/" + trip.join_token)

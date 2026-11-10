# GroupHub: MVP (Team 7 · Travel · Lean Startup Lab 2026)

GroupHub is one shared space for a group trip, used by the **agency**, the **group representative** and the **participants**. It holds the quote versions with in-app approval, the document and payment checklist per participant, the programme and announcements behind a no-login link, and the supplier deadlines with their penalties.

The full requirements are in [`docs/MVP_One_Pager.md`](docs/MVP_One_Pager.md): the problem, 5 user stories, what is out of scope, the stack, and the funnel.

The course's code lane (L06) is **VS Code → GitHub → Render**, with the database on **Neon** and measurement through **GTM → GA4** (L08).

---

## 1 · Run it on your laptop (VS Code)

You need Python 3.11+ and Git.

```bash
cd grouphub
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000 and click **"Prova la demo"**. Locally the app uses a SQLite file, so you don't need to set anything up.
To get a fixed demo login, run `python seed.py`, then log in with `demo@grouphub.local` / `demo1234`.

### Where things are
| File | What it is (L06 terms) |
|---|---|
| `app.py` | Backend: every route/URL and the rules ("the kitchen") |
| `models.py` | Database tables ("the pantry") |
| `templates/*.html` | Frontend screens ("the dining room") |
| `static/style.css` | All styling |
| `i18n.py` | Every Italian/English text. Change wording here. |
| `analytics.py` | Event tracking (database + GTM dataLayer) |
| `seed.py` | Demo data |

### Pages
| URL | Who | Login? |
|---|---|---|
| `/` | Landing page with "Try the demo" | no |
| `/trips`, `/trips/<id>` | Agent workspace (7 tabs) | yes |
| `/g/<token>` | Group link: participant enters name + email | **no** |
| `/p/<token>` | Participant's personal page (programme, announcements, own to-dos) | **no** |
| `/r/<token>` | Representative: approve quotes, see who is missing what, deadlines | **no** |
| `/admin/metrics?key=ADMIN_KEY` | Team-only funnel and weekly numbers | key |

---

## 2 · Put the code on GitHub

1. Create an **empty** repository on github.com (e.g. `grouphub`). You can make it private.
2. In the VS Code terminal, inside the `grouphub` folder:
```bash
git init
git add .
git commit -m "GroupHub MVP v1"
git branch -M main
git remote add origin https://github.com/<your-user>/grouphub.git
git push -u origin main
```
Add your teammates under *Settings → Collaborators*.

## 3 · Create the database on Neon (free, doesn't expire)

> Why not Render's database? Render's free Postgres is **deleted 30 days after you create it**, which would be before Demo Day. Neon's free plan has no time limit.

1. Sign up at https://neon.com (GitHub login works). Create a project named `grouphub` and pick the **Europe (Frankfurt)** region.
2. On the dashboard click **Connect**, then copy the connection string (`postgresql://...neon.tech/neondb?sslmode=require`).
You don't need to create any tables: the app creates them the first time it starts.

## 4 · Deploy on Render

1. Sign up at https://render.com with GitHub.
2. **New → Blueprint**, select your `grouphub` repo. Render reads `render.yaml`.
3. When it asks for environment variables, enter:
   - `DATABASE_URL`: the Neon string from step 3
   - `ADMIN_KEY`: any password you choose, for the metrics page
   - `GTM_ID`: leave it empty for now; you'll fill it in at step 5
4. Click **Apply**. After 2–3 minutes you get a public URL like `https://grouphub-xxxx.onrender.com`. **That is the URL you submit.**

From then on, every `git push` to `main` redeploys automatically ("sync" on the L06 slide).

**Free plan sleep:** a free Render service goes to sleep after 15 minutes with no visits, and the next visit then takes about 50 seconds to load. Participants open the link once and expect it to be fast, so set up a free monitor at https://uptimerobot.com (or cron-job.org) that calls `https://<your-url>/health` every 10 minutes (not `/`, which would count as a landing visit in your metrics). One service running all month stays within Render's 750 free hours.

## 5 · Measurement: Google Tag Manager + GA4 (L08)

The app already pushes every action into the `dataLayer` as
`{event: 'app_event', event_name: '<name>', event_params: {...}}`, the same format shown in the L08 example.

1. **GA4:** at analytics.google.com, create a property and a Web data stream for your Render URL. Copy the **Measurement ID** (`G-...`).
2. **GTM:** at tagmanager.google.com, create a container (Web) and copy its **ID** (`GTM-...`). Put it in Render as `GTM_ID`, then save. Render redeploys.
3. In GTM:
   - **Tag "GA4 – config":** Google tag, ID = your `G-...`, trigger = *Initialization – All Pages*.
   - **Variables:** Data Layer Variables `event_name`, `event_params.actor_type`, `event_params.trip_id`, `event_params.is_demo`.
   - **Trigger "app_event":** Custom Event, event name `app_event`.
   - **Tag "GA4 – app events":** GA4 Event, event name = `{{event_name}}`, parameters `actor_type`, `trip_id`, `is_demo`; trigger = *app_event*.
   - Check in **Preview** mode, then **Submit / Publish**.
4. In GA4, **on day one** (GA4 doesn't apply these to data it already received):
   - Admin → Custom definitions: add `actor_type`, `trip_id`, `is_demo` as event-scoped dimensions.
   - Admin → Key events: mark `sign_up`, `trip_created`, `participant_joined`, `task_marked_done`, `quote_approved`.
5. Check that events arrive in **DebugView / Realtime**.

Ad-blockers hide some GA traffic, so every event is **also** saved in the app's own database. Open `/admin/metrics?key=<ADMIN_KEY>` for exact numbers per week and the funnel by sign-up cohort, ready to copy into the **4.1 Metrics Tracker**. Demo sandboxes are excluded by default.

### Events
| Stage | Events |
|---|---|
| Acquisition | `landing_view`, `demo_started`, `sign_up`, `login`, `language_switched` |
| Activation | `trip_created`, `quote_added`, `checklist_item_created`, `participant_added`, `invite_link_copied`, `rep_link_copied` |
| Engagement | `join_page_view`, `participant_joined`, `participant_page_view`, `task_marked_done`, `rep_page_view`, `quote_approved` |
| Retention | `agent_session` (first visit of the day), `task_verified`, `reminder_copied`, `reminder_whatsapp`, `announcement_published`, `supplier_deadline_added` |

## 6 · Changing things safely

- **Change wording:** edit `i18n.py`. Each string is written as `("Italian", "English")`.
- **Add a column to a table:** `db.create_all()` creates new tables but does **not** change existing ones. Either reset the database in Neon (*Branches → Reset*, only before you have real users), or add the column by hand in Neon's SQL editor, e.g. `ALTER TABLE trip ADD COLUMN notes TEXT;`
- Test locally (`python app.py`), then `git push`. Render redeploys.
- **Privacy:** the app does not store passport scans; participants confirm and the agent verifies. Keep it that way until you have a privacy notice and a data processing agreement (DPA) with the agencies.

# Univoy — MVP One-Pager (PRD)

Team 7 · Industry: Travel · Version 1.0 · 10 Nov 2026

> This page is the input for Template 3.1 (MVP One-Pager). Following L06, it is also the "first prompt" of the build: every feature in the code maps to one user story below.

---

## 1 · The problem, in the customer's words

Group trips (5 to 150+ people) are negotiated over months, by email, WhatsApp and phone, between **one agent** and **one group representative**, who then has to relay everything to the participants.

- *"Organizing a group trip can take months… numerous quotes, emails, WhatsApp messages and phone calls are exchanged… it becomes difficult to reconstruct the decisions made and the conditions agreed upon."* (Interview #2, Il Salotto del Viaggio)
- *"A system that automatically logged the various quote versions, modifications, and client-approved decisions would… ensure we always know which version is the official, final one."* (Interview #5)
- *"Collecting documents is definitely one of the tasks that requires the most follow-ups. With large groups, it becomes difficult to keep track of who has submitted everything and who is still pending."* (Interview #5)
- *"Deposits and payment deadlines must match the suppliers."* (Interview #4) · *"Hotels have cancellation penalties, and the closer you get to the departure date, the higher those penalties become."* (Interview #1)
- *"If it requires a login or a new app, many drop out; a link that takes two minutes might work."* (Interview #4)
- *"We can provide the contact person with all the correct and updated information, but we cannot control how it is subsequently passed on to the participants."* (Interview #5)

Validated problem assumptions carried into the MVP: **A1** (scattered communication and quote versions), **A2** (documents and deadlines need endless reminders), **A3** (case knowledge stuck with one person), **A5** (penalties grow toward departure).

**Quantitative signal (survey, 9 agencies, usefulness from 1 to 5):** Quote log 3.78 · Read-only itinerary 3.78 · Payments & supplier deadlines 3.78 · Document checklist 3.44 · AI chatbot 3.11 · Supplier comparison 3.12 · AI surveys 2.89 · Team notes 2.89.
Most-voted "highest priority": Payments & deadlines (5 of 9), Quote log (4), Document checklist (3), Read-only itinerary (3). 8 of 9 agencies answered *"Maybe, I'd like to see a demo/prototype first"*, so the MVP doubles as that demo.

## 2 · Target user

- **Paying customer and primary user:** the travel agent/project manager at a small or medium Italian agency who runs group, incentive or custom trips as a core part of the business. Early adopters are the 6 survey respondents who left an email address.
- **Secondary users, who never pay or register:** the **group representative** (referente), who approves quotes and follows the group's progress, and the **participants**, who see the programme and their own to-dos.

## 3 · Must-have user stories (5) and acceptance criteria

| # | User story | Acceptance criteria (Given / When / Then) | Tests |
|---|---|---|---|
| US1 | As an **agent**, I want each group trip to have **one workspace** (overview, quotes, participants, checklist, itinerary, deadlines, history) so that any colleague can pick up the file and see everything that was requested, quoted, changed and approved. | Given I am logged in, when I create a trip, then it gets its own workspace and every action (quote added, approval, announcement, item verified) is written to a dated **activity history** visible to all colleagues of the agency. | A1, A3, S1 |
| US2 | As an **agent**, I want to log every **quote version** and have the **representative approve one in-app** so that there is a single official version and a dated record of who approved what. | Given a trip with quote versions, when the rep opens their link and clicks "Approve" on a version (typing their name), then that version becomes **Approved/Official**, every earlier version becomes **Superseded**, and the approval (name, date and time, channel) is shown in the decision log. The agent can also record an approval received by email, WhatsApp or phone. | A1, S1 |
| US3 | As an **agent**, I want a **checklist of documents and payments with deadlines**, and a **participant × item matrix with progress bars** (e.g. "42/50 passports"), so that I see at a glance who is missing what, and can send one reminder. | Given checklist items and participants, when a participant marks an item done, then the matrix shows it as *submitted*; the agent can set it to *verified*; each item shows "X/Y done" and is flagged *overdue* after its deadline; "Copy reminder" produces a ready-to-send message (or a WhatsApp link) addressed to only the people still missing. | A2, S3 |
| US4 | As a **participant**, I want to open **one link without creating an account** and see the programme, announcements and **my own to-do list** so that I always have the official information and know what I still have to do. | Given the group's join link, when I enter my name and email, then within 2 minutes I land on my personal page (with no password) showing the itinerary, the latest announcements and only my own checklist with deadlines, and I can mark items as done. I never see other participants' data. | A2, Interview #4 |
| US5 | As an **agent and representative**, I want a **deadline timeline** of supplier deadlines with the penalty that applies after each date so that the group decides in time and avoids penalties. | Given supplier deadlines entered by the agent, when the agent or the rep opens the trip, then the deadlines are shown in date order with the days remaining and the penalty text, and those within 14 days are highlighted. | A5, S5 |

## 4 · Explicitly OUT of scope (for this MVP)

AI chatbot / emergency filter (rated 3.11) · AI survey summary (2.89) · Supplier comparison & margin calculator (3.12) · Internal team chat (2.89; the shared activity history covers the handover problem) · Uploading passport/visa scans (it creates a GDPR liability before we have a DPA; participants confirm and the agent verifies instead) · Online payments (we only track status) · Automatic email/SMS reminders (the agent copies a pre-written message or WhatsApp link instead) · Supplier booking APIs (Booking, airlines) · Native mobile app · Agency billing/subscriptions.

## 5 · Stack, and why

Following the L06 code lane (**VS Code → GitHub → Render**):

| Layer | Choice | Why |
|---|---|---|
| Frontend | Server-rendered HTML (Jinja templates) + one CSS file | No build step; works on any phone browser, which participants need. |
| Backend | Python 3 + Flask | Small, readable and quick to change between iterations. |
| Database | PostgreSQL on **Neon** (free); SQLite locally | Render's free Postgres is deleted after 30 days, which would be before Demo Day. Neon's free plan doesn't expire. |
| Hosting | **Render** free web service, auto-deploy from GitHub | The course's deploy target. |
| Measurement | **Google Tag Manager → GA4** (dataLayer events, as in L08) + our own `events` table and `/admin/metrics` page | GA4 for the funnel explorations; the events table gives exact, cohort-able numbers for the Metrics Tracker even when ad-blockers hide GA. |

## 6 · Funnel and events (instrumented from day one)

| AARRR stage | Event(s) | Key metric |
|---|---|---|
| Acquisition | `landing_view`, `demo_started`, `sign_up` | visits → sign-ups |
| Activation | `trip_created`, `quote_added`, `checklist_item_created`, `participant_added` | **% of new agencies that create a trip AND share a link within 7 days** ★ |
| Engagement (network) | `participant_joined`, `participant_page_view`, `task_marked_done`, `rep_page_view`, `quote_approved` | % participants who complete ≥1 task; % trips with an in-app approval ★ |
| Retention | `agent_session` (an agent's visit on a new day), `task_verified`, `reminder_copied` | % agencies active in week 2+ |
| Referral / Revenue | `invite_link_copied`; "preview" interest | (Phase 2) |

★ = GA4 key events.

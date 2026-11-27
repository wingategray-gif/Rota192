# Crew rota

A web app for running a workshop crew rota. It covers who is on site, rotations, cover planning, training records, accommodation, offers of extra work, and improvement ideas. Engineers, managers and the owner each sign in with their email and see what their level allows.

Live site: https://wingategray-gif.github.io/Rota192/ (GitHub Pages, served from `main`).

## How it's built

| Part | What it is |
|---|---|
| `index.html` | The whole app: one self-contained page (HTML, CSS and JavaScript, about 2,000 lines). No framework and no build step. Edit it and push. |
| `supabase.js` | The Supabase JavaScript client (`@supabase/supabase-js` 2.117.3, UMD build). It's committed so the app doesn't depend on a CDN. |
| `setup.sql` | The database: tables, access rules (row-level security), triggers and one server function. Run it in Supabase › SQL Editor. It's safe to re-run, and that's how schema changes are deployed. |
| `manifest.webmanifest`, `icon-*.png` | Home-screen app support (icon, full-screen launch). |
| `tests/` | Access-rule tests and an end-to-end test that run against a local Postgres (see Testing). |

The backend is a Supabase project (Postgres, email sign-in and live updates). The page talks to it directly with the project's **publishable** key, which is public by design. **Security comes from the access rules in `setup.sql`, not from the page.** Anything the page hides, the database must also refuse.

## The page, top to bottom

`index.html` has four `<script>` blocks after the markup:

1. **Config:** `window.CREW_CFG = {url, key}`, the Supabase project URL and publishable key.
2. **Helpers and store** (starts around line 596):
   - helpers: `uid`, `clone`, `esc`, `toast`
   - `normRota` / `normAccom`, which clean up data
   - the Supabase layer: `rowsOf`, `syncNow`, `persist`, `loadAll`, `scheduleReload`, `sbRespond`
3. **The rota UI** (one large function, around line 720): every tab and its rendering, the cover planner, offers, training rules, accommodation, ideas, history and backup.
4. **Roles and sign-in** (around line 1828):
   - `applyRole`, which sets the body class `role-…` and shows or hides tabs
   - the Access grid in Settings
   - the sign-in screens (`gate…`), `start()` and `initStore()`
   - the Accounts, "Waiting to be let in" and Invite panels

### How data flows

The page keeps one copy of everything in two objects:

- `R`, the rota: `{people:[…], offers, vols, ideas, log, targets, access, feat}`
- `A`, accommodation: `{assign:{rotationId:{loc, mv:[…]}}, hotel, hotels}`

Code changes them like this: `const rd = clone(R); …edit rd…; R = rd; saveR();` (or `saveA()`).

`saveR` / `saveA` do two things:

- **Record history:** `logChanges()` compares the copy with how it was before and writes plain-English lines to the change history.
- **Save:** `persist()` waits 400 ms and then runs `syncNow()`. `syncNow()` turns the copy into table rows (`rowsOf`), compares them with the last saved rows, and does the inserts, updates and deletes in a safe order (people first, deleting children first).

If the database refuses something, for example an engineer trying to change a rotation, the page says so and reloads the real data.

Live updates: the page subscribes to Postgres changes and reloads (`scheduleReload`) when anyone changes something.

### Dates

Days are whole numbers counted from **1 Oct 2026 = day 0**. In code that's `START`, and `TODAY` is today's number. A rotation is:

```js
{id, s, e, d, loc, note}
```

| Field | Meaning |
|---|---|
| `s`, `e` | First and last day numbers, inclusive. |
| `d` | One character per day from `s` to `e`: `W` = travel, `#` = on site, `-` = off. |
| `loc` | Blank for the home workshop; a country such as "Germany" for work abroad. |
| `note` | Free text. |

Accommodation is keyed by rotation id. A stay runs from the travel-out night to the travel-home morning. `mv` holds "different place for some nights" moves as `{a, l, loc}`, where `l` is the morning they move back.

### Levels

| Level | Can |
|---|---|
| Owner | Everything, and can't be demoted or removed. The first person ever to sign in. |
| Admin | Everything except change the owner. |
| Manager | See all rotations, training and accommodation. Add engineers, change rotations and accommodation, make offers, decide ideas, and let new engineers in. Can't open Settings, change levels or see the history. |
| Engineer | See their own Home, training and accommodation, plus everyone's rotations for about 3 months (timeline). Edit their own training, volunteer, add dates they can't work, answer offers, suggest and vote on ideas. |
| Viewer | The 3-month timeline only. |
| Pending | Signed in but not let in yet. Sees nothing. |

Which tabs each level sees is set in Settings › Access. That only affects what's shown; the database rules decide what can be read and written.

### Database (setup.sql)

| Tables | What they hold |
|---|---|
| `members` | One row per sign-in: `user_id`, `email`, `person_id`, `role`. |
| `people` | The engineers. |
| `people_private` | Sign-in email and the level they'll get on first sign-in, kept separate so engineers can't read each other's. |
| `rotations`, `training`, `away`, `accom` | The rota itself. |
| `settings` | Key/value: `hotel`, `hotels`, `targets`, `access`, `feat`, `ideaWin`. |
| `offers`, `vols` | Offers of extra work, and engineers' "I can do extra". |
| `ideas`, `idea_votes` | Improvement ideas and votes. |
| `log` | Change history. |

Things worth knowing:

- **First sign-in:** a trigger on `auth.users` makes the very first sign-in the owner. After that, it links a sign-in to an engineer when the email matches `people_private`; anyone else is pending.
- **History names:** `log.who` is filled in by the server from who is actually signed in. The page's value isn't trusted.
- **H2S flag:** `people.h2s` follows the training record (trigger).
- **Answering offers:** engineers can't write rotations, so they answer through `respond_offer(oid, accept)`. When a manager makes an offer, the page works out the exact rota change (`data.result`) and the rows it expects to find (`data.expect`). The function applies the change only if those rows are still unchanged.

## Setting up from scratch

1. **Create a Supabase project** (London region) and run `setup.sql` in the SQL Editor.
2. **Connect your own email sender.** Use custom SMTP (Brevo works on its free plan) under Authentication › Emails › SMTP Settings. The built-in sender only allows a few emails an hour, and on newer free projects the templates can't be edited without your own SMTP.
   - **Brevo's IP blocking:** Brevo blocks unknown IP addresses by default; authorise Supabase's or turn the blocking off.
3. **Change the sign-in email templates.** In both **Magic Link** and **Confirm signup**, show the code (`{{ .Token }}`) and no link. Brevo rewrites links for click tracking, and Outlook pre-opens them, which breaks one-time links. The app asks for the code.
4. **Point Supabase at the site.** Under Authentication › URL Configuration, set the Site URL to the site, and add `<site>/**` to Redirect URLs.
5. **Connect the page.** Put the project URL and **publishable** key in `window.CREW_CFG` in `index.html`. Push to `main` and turn on GitHub Pages (Deploy from a branch › `main` › root).
6. **Sign in first** (you become the owner), then use Settings › Backup › Restore to load a backup file.

**Never put the `service_role` / secret key in the page or the repo.**

## Making changes

- **Use a separate Supabase project for development.** The free plan allows two. Point `CREW_CFG` at it locally and **don't commit that change**.
- **Don't test against the live project with real engineers' data.**
- **Keep changes small and in the existing style.**
  - Short functions, template strings for markup, and `esc()` on anything from the data.
  - CSS colours come from the variables in `:root` (light and dark mode).
  - Anything an engineer can trigger must also be allowed by `setup.sql`.
- **If you change the database,** edit `setup.sql` so it still runs cleanly on both a new and an existing project (`create … if not exists`, `alter … add column if not exists`, `create or replace`). The owner then re-runs it in the SQL Editor.
- **Commit messages** should say what changed for the people using the app.

## Testing

The tests run against a **local Postgres 16**. `tests/shim.sql` stands in for the parts of Supabase the setup script needs (`auth.users`, `auth.uid()`, roles).

```bash
pip install psycopg2-binary           # once
python3 tests/rls_test.py             # rebuilds a local "crew" database and checks every access rule (expects PASS 76 FAIL 0)
```

The end-to-end test runs the real page in Playwright against `tests/mockrest.py`, a small stand-in for Supabase's REST and sign-in endpoints backed by the same local database:

```bash
python3 tests/rls_test.py >/dev/null
psql -d crew -c 'truncate auth.users, people, settings, ideas, log, members cascade;'
python3 tests/mockrest.py 8787 &
node tests/e2e.js path/to/backup.json      # a backup downloaded from the app (Settings › Backup)
```

The e2e test checks the sign-in screens, restoring a backup and reloading it, invites, and that an engineer is linked and sees only their own data. It also covers training saves, refused writes, a manager getting in, making an offer and the engineer accepting it, ideas and votes, letting someone in, the owner linking their record, pre-set levels, and that a manager can't promote themself (expects PASS 50 FAIL 0).

Backups contain engineers' personal data: keep them out of the repo (`*.json` backups are not to be committed).

Connection settings can be changed with `CREW_TEST_DSN` (for Python) and `CREW_TEST_PSQL` (the psql command; default `psql -h /var/run/postgresql -U postgres`).

## Known limits

- **Email limits:** sign-in emails depend on the SMTP provider's limits.
- **Pausing:** Supabase pauses free projects after a week with no activity.
- **Data window:** the rota's day numbers start at 1 Oct 2026, and the timeline shows to February 2028. Extending it means changing `START` and the range constants in the rota UI script, and `day_idx()` in `setup.sql`.

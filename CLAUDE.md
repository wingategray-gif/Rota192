# Crew rota: notes for AI coding assistants

Read README.md first: it explains the structure, the data model and the levels.

## Rules

- **Security lives in `setup.sql`.** The page can hide things, but every read and write an engineer, viewer or manager can make must also be allowed by the row-level security there.
  - If you add something an engineer can save, add or extend the matching policy.
  - Add a check to `tests/rls_test.py` for anything a lower level must *not* be able to do.
- **Never add the Supabase `service_role` / secret key** to any file. Use the publishable key only. Anything needing elevated rights goes in a `security definer` function in `setup.sql`, following `respond_offer`.
- **`setup.sql` must stay re-runnable** on a project that already has data:
  - `if not exists` / `add column if not exists`
  - `create or replace`
  - `drop trigger if exists` before `create trigger`
  - policies are dropped and recreated at the top of section 3
- **No personal data in the repo:** no backups, no real emails, no names in tests beyond what's already there.
- **Keep `index.html` a single self-contained file:**
  - no frameworks and no build step
  - escape every value from the data with `esc()` before it goes into markup
  - colours come from the CSS variables in `:root`
- **Change data the existing way:** `const rd = clone(R); …; R = rd; saveR();` (or `saveA()` for accommodation). This keeps the change history and the database sync working. Don't write to Supabase directly from UI code. The exceptions already in place: `sbRespond`, accounts and invites in the roles script.
- **Day numbers are counted from 1 Oct 2026.** Rotation `d` strings use `W` (travel), `#` (on site) and `-` (off), one character per day from `s` to `e` inclusive.
- **UI text is British English, plain and short.** The people using it are engineers on their phones.

## Before you push

```bash
python3 tests/rls_test.py                     # PASS 76 FAIL 0 (or more, with your new checks)
node tests/e2e.js path/to/backup.json         # see README › Testing; needs tests/mockrest.py running
```

Check new screens at phone width (390px) and desktop: no sideways scrolling, nothing blank, no "undefined".

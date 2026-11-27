# Crew rota

The workshop crew rota: rotations, cover planning, training, accommodation and ideas.

- `index.html` is the app. It is served by GitHub Pages.
- `supabase.js` is the Supabase client library (v2.117.3), kept here so the app doesn't depend on a CDN.
- `setup.sql` creates the Supabase tables and access rules. Run it once in Supabase › SQL Editor.

Everyone signs in with their email. What each person can see and change is enforced by the database's access rules, not by the page.

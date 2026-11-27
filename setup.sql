-- Crew rota: Supabase setup
-- Paste all of this into Supabase > SQL Editor > New query, then press Run.
-- Safe to run once on a new project. It creates the tables, the access rules
-- (who can see and change what) and links people to their engineer record when they sign in.

-------------------------------------------------------------------------------
-- 1. Sign-in accounts and their level
-------------------------------------------------------------------------------
create table if not exists public.members (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  email      text not null,
  person_id  text,
  role       text not null default 'pending'
             check (role in ('owner','admin','manager','engineer','viewer','pending')),
  created_at timestamptz not null default now()
);

-- helper checks used by the access rules (security definer so they can read members)
create or replace function public.my_role() returns text
  language sql stable security definer set search_path = public
  as $$ select role from public.members where user_id = auth.uid() $$;
create or replace function public.my_person() returns text
  language sql stable security definer set search_path = public
  as $$ select person_id from public.members where user_id = auth.uid() $$;
create or replace function public.is_member() returns boolean
  language sql stable security definer set search_path = public
  as $$ select coalesce(public.my_role() in ('owner','admin','manager','engineer','viewer'), false) $$;
create or replace function public.is_staff() returns boolean
  language sql stable security definer set search_path = public
  as $$ select coalesce(public.my_role() in ('owner','admin','manager'), false) $$;
create or replace function public.is_admin() returns boolean
  language sql stable security definer set search_path = public
  as $$ select coalesce(public.my_role() in ('owner','admin'), false) $$;
-- day number used by the rota (0 = 1 Oct 2026)
create or replace function public.day_idx() returns integer
  language sql stable as $$ select (current_date - date '2026-10-01') $$;

-------------------------------------------------------------------------------
-- 2. The rota
-------------------------------------------------------------------------------
create table if not exists public.people (
  id      text primary key,
  no      integer not null default 0,
  name    text not null,
  h2s     boolean not null default false,
  na      boolean not null default false,
  cas     boolean not null default false     -- h2s is kept in step with training by a trigger below
);
-- sign-in email for each engineer, kept apart so other engineers can't read it
create table if not exists public.people_private (
  person_id text primary key references public.people(id) on delete cascade,
  email     text
);
create table if not exists public.rotations (
  id        text primary key,
  person_id text not null references public.people(id) on delete cascade,
  s int not null, e int not null,
  d text not null default '', loc text not null default '', note text not null default ''
);
create index if not exists rotations_person on public.rotations(person_id);
create table if not exists public.training (
  person_id text primary key references public.people(id) on delete cascade,
  tr        jsonb not null default '{}'::jsonb,
  self_at   text                         -- when the engineer last updated it themselves
);
create table if not exists public.away (
  id        text primary key,
  person_id text not null references public.people(id) on delete cascade,
  s int not null, e int not null,
  note text not null default ''
);
create table if not exists public.accom (
  key       text primary key,              -- the rotation id the stay belongs to
  person_id text references public.people(id) on delete cascade,
  data      jsonb not null default '{}'::jsonb
);
create table if not exists public.settings (
  key   text primary key,                  -- hotel, hotels, targets, access, feat, ideaWin
  value jsonb
);
create table if not exists public.offers (
  id        text primary key,
  person_id text not null references public.people(id) on delete cascade,
  data      jsonb not null,                -- the offer, plus the rota change it makes (result/expect)
  status    text not null default 'pending' check (status in ('pending','accepted','declined')),
  resp      text,
  resp_at   timestamptz
);
create table if not exists public.vols (
  id        text primary key,
  person_id text not null references public.people(id) on delete cascade,
  data      jsonb not null
);
create table if not exists public.ideas (
  id       text primary key,
  by_user  uuid default auth.uid(),
  by_name  text,
  title    text not null,
  detail   text,
  created  text,
  at       timestamptz not null default now(),
  st       text not null default 'open' check (st in ('open','planned','no','done')),
  reply    text,
  upd      text
);
create table if not exists public.idea_votes (
  idea_id text references public.ideas(id) on delete cascade,
  user_id uuid default auth.uid(),
  primary key (idea_id, user_id)
);
create table if not exists public.log (
  id   text primary key,
  at   timestamptz not null default now(),
  who  text,
  what text not null
);

-------------------------------------------------------------------------------
-- 3. Access rules
-------------------------------------------------------------------------------
alter table public.members        enable row level security;
alter table public.people         enable row level security;
alter table public.people_private enable row level security;
alter table public.rotations      enable row level security;
alter table public.training       enable row level security;
alter table public.away           enable row level security;
alter table public.accom          enable row level security;
alter table public.settings       enable row level security;
alter table public.offers         enable row level security;
alter table public.vols           enable row level security;
alter table public.ideas          enable row level security;
alter table public.idea_votes     enable row level security;
alter table public.log            enable row level security;

-- clear any earlier copies of the rules so this script can be run again safely
do $$ declare p record; begin
  for p in select policyname, tablename from pg_policies where schemaname = 'public'
    and tablename in ('members','people','people_private','rotations','training','away','accom',
                      'settings','offers','vols','ideas','idea_votes','log') loop
    execute format('drop policy %I on public.%I', p.policyname, p.tablename);
  end loop;
end $$;

-- members: you see yourself; you and managers see everyone; level changes are checked by a trigger below
create policy members_read  on public.members for select using (user_id = auth.uid() or public.is_staff());
create policy members_edit  on public.members for update using (public.is_staff()) with check (public.is_staff());
create policy members_del   on public.members for delete using (public.is_admin() and role <> 'owner');

-- people: every signed-in member sees names (for the timeline); you and managers add and change
create policy people_read  on public.people for select using (public.is_member());
create policy people_add   on public.people for insert with check (public.is_staff());
create policy people_edit  on public.people for update using (public.is_staff()) with check (public.is_staff());
create policy people_del   on public.people for delete using (public.is_admin());

create policy pp_read  on public.people_private for select using (public.is_staff() or person_id = public.my_person());
create policy pp_write on public.people_private for all using (public.is_staff()) with check (public.is_staff());

-- rotations: staff see all; engineers and viewers see their own, plus everyone's for the 3-month timeline
create policy rot_read on public.rotations for select using (
  public.is_staff() or person_id = public.my_person()
  or (public.is_member() and e >= public.day_idx() - 7 and s <= public.day_idx() + 100));
create policy rot_write on public.rotations for all using (public.is_staff()) with check (public.is_staff());

-- training: staff see all; engineers see and edit only their own
create policy tr_read  on public.training for select using (public.is_staff() or person_id = public.my_person());
create policy tr_write on public.training for all
  using (public.is_staff() or person_id = public.my_person())
  with check (public.is_staff() or person_id = public.my_person());

-- dates engineers can't work: same as training
create policy away_read  on public.away for select using (public.is_staff() or person_id = public.my_person());
create policy away_write on public.away for all
  using (public.is_staff() or person_id = public.my_person())
  with check (public.is_staff() or person_id = public.my_person());

-- accommodation: staff see and change all; engineers see only their own stays
create policy acc_read  on public.accom for select using (public.is_staff() or person_id = public.my_person());
create policy acc_write on public.accom for all using (public.is_staff()) with check (public.is_staff());

-- settings: everyone reads (hotel names, which tabs show); you change them; managers can switch 48-hour voting
create policy set_read  on public.settings for select using (public.is_member());
create policy set_write on public.settings for all
  using (public.is_admin() or (public.is_staff() and key = 'ideaWin'))
  with check (public.is_admin() or (public.is_staff() and key = 'ideaWin'));

-- offers: staff make them; an engineer sees their own and answers through respond_offer() below
create policy off_read  on public.offers for select using (public.is_staff() or person_id = public.my_person());
create policy off_write on public.offers for all using (public.is_staff()) with check (public.is_staff());

-- "I can do extra": engineers add and remove their own
create policy vol_read  on public.vols for select using (public.is_staff() or person_id = public.my_person());
create policy vol_write on public.vols for all
  using (public.is_staff() or person_id = public.my_person())
  with check (public.is_staff() or person_id = public.my_person());

-- ideas
create or replace function public.ideas_window_on() returns boolean
  language sql stable security definer set search_path = public
  as $$ select coalesce((select value::text = 'true' from public.settings where key = 'ideaWin'), false) $$;
create or replace function public.my_open_ideas() returns integer
  language sql stable security definer set search_path = public
  as $$ select count(*)::int from public.ideas where by_user = auth.uid() and st = 'open' $$;
create or replace function public.idea_voting(i public.ideas) returns boolean
  language sql stable as $$ select i.st = 'open' and (not public.ideas_window_on() or i.at > now() - interval '48 hours') $$;
create policy idea_read on public.ideas for select using (
  public.is_member() and (public.is_staff() or by_user = auth.uid() or st <> 'open'
    or not public.ideas_window_on() or at > now() - interval '48 hours'));
create policy idea_add on public.ideas for insert with check (
  public.is_member() and public.my_role() <> 'viewer' and by_user = auth.uid()
  and (public.is_staff() or (st = 'open' and public.my_open_ideas() < 3)));
create policy idea_edit on public.ideas for update using (public.is_staff()) with check (public.is_staff());
create policy idea_del  on public.ideas for delete using (public.is_admin() or (by_user = auth.uid() and st = 'open'));

create or replace function public.can_vote(iid text) returns boolean
  language sql stable security definer set search_path = public
  as $$ select exists(select 1 from public.ideas i where i.id = iid and i.by_user is distinct from auth.uid() and public.idea_voting(i)) $$;
create policy vote_read on public.idea_votes for select using (public.is_member());
create policy vote_add  on public.idea_votes for insert with check (
  public.is_member() and public.my_role() <> 'viewer' and user_id = auth.uid() and public.can_vote(idea_id));
create policy vote_del  on public.idea_votes for delete using (user_id = auth.uid() and public.can_vote(idea_id));

-- change history: everyone's changes are recorded; only you read it
create policy log_read on public.log for select using (public.is_admin());
create policy log_add  on public.log for insert with check (public.is_member());

-------------------------------------------------------------------------------
-- 4. Triggers: who is who
-------------------------------------------------------------------------------
-- a new sign-in: the very first becomes the owner; an email you've put on an engineer links to them;
-- anyone else waits as "pending" until you or a manager let them in
create or replace function public.on_new_user() returns trigger
  language plpgsql security definer set search_path = public as $$
declare pid text;
begin
  if not exists (select 1 from public.members) then
    insert into public.members(user_id, email, role) values (new.id, coalesce(new.email,''), 'owner');
    return new;
  end if;
  select person_id into pid from public.people_private
    where lower(email) = lower(new.email) and email <> '' limit 1;
  insert into public.members(user_id, email, person_id, role)
    values (new.id, coalesce(new.email,''), pid, case when pid is null then 'pending' else 'engineer' end)
    on conflict (user_id) do nothing;
  return new;
end $$;
drop trigger if exists crew_on_new_user on auth.users;
create trigger crew_on_new_user after insert on auth.users for each row execute function public.on_new_user();

-- an email added to an engineer later links anyone already waiting with that email
create or replace function public.on_person_email() returns trigger
  language plpgsql security definer set search_path = public as $$
begin
  if new.email is not null and new.email <> '' then
    update public.members set person_id = new.person_id, role = 'engineer'
      where role = 'pending' and lower(email) = lower(new.email);
  end if;
  return new;
end $$;
drop trigger if exists crew_on_person_email on public.people_private;
create trigger crew_on_person_email after insert or update on public.people_private
  for each row execute function public.on_person_email();

-- level changes: nobody can make or unmake the owner; managers can only let pending people in as engineers
create or replace function public.guard_members() returns trigger
  language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then return new; end if;          -- run from the SQL editor
  if old.role = 'owner' and (new.role <> 'owner' or new.user_id <> old.user_id) then
    raise exception 'The owner''s level can''t be changed';
  end if;
  if new.role = 'owner' and old.role <> 'owner' then
    raise exception 'There can only be one owner';
  end if;
  if public.my_role() = 'manager' and not (old.role in ('pending','engineer') and new.role in ('pending','engineer')) then
    raise exception 'Managers can only let new engineers in';
  end if;
  new.email := old.email;
  return new;
end $$;
drop trigger if exists crew_guard_members on public.members;
create trigger crew_guard_members before update on public.members for each row execute function public.guard_members();

-- history entries carry the real name of whoever made the change
create or replace function public.stamp_log() returns trigger
  language plpgsql security definer set search_path = public as $$
declare nm text; rl text;
begin
  select coalesce(p.name, m.email), m.role into nm, rl
    from public.members m left join public.people p on p.id = m.person_id where m.user_id = auth.uid();
  if rl in ('owner','admin') and new.who is not null and new.who <> '' and new.who not like 'Admin%' then
    return new;                                            -- a restore keeps its original names
  end if;
  new.who := coalesce(nm, 'Someone') || case when rl in ('owner','admin') then ' (admin)'
                                             when rl = 'manager' then ' (manager)' else '' end;
  return new;
end $$;
drop trigger if exists crew_stamp_log on public.log;
create trigger crew_stamp_log before insert on public.log for each row execute function public.stamp_log();

-- the H2S dot on the timeline follows the training record
create or replace function public.sync_h2s() returns trigger
  language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'DELETE' then update public.people set h2s = false where id = old.person_id; return old; end if;
  update public.people set h2s = (new.tr ? 'h2s') where id = new.person_id; return new;
end $$;
drop trigger if exists crew_sync_h2s on public.training;
create trigger crew_sync_h2s after insert or update or delete on public.training for each row execute function public.sync_h2s();

-- ideas carry the suggester's name
create or replace function public.stamp_idea() returns trigger
  language plpgsql security definer set search_path = public as $$
begin
  select coalesce(p.name, case when m.role in ('owner','admin') then 'Admin' when m.role = 'manager' then 'Manager' else m.email end)
    into new.by_name
    from public.members m left join public.people p on p.id = m.person_id where m.user_id = auth.uid();
  return new;
end $$;
drop trigger if exists crew_stamp_idea on public.ideas;
create trigger crew_stamp_idea before insert on public.ideas for each row execute function public.stamp_idea();

-------------------------------------------------------------------------------
-- 5. An engineer answering an offer
-- The rota change was worked out when the offer was made (data.result), and is only
-- applied if the rotations it touches haven't changed since (data.expect).
-------------------------------------------------------------------------------
create or replace function public.respond_offer(oid text, accept boolean) returns text
  language plpgsql security definer set search_path = public as $$
declare o public.offers; k text; v jsonb; cur jsonb; r jsonb;
begin
  select * into o from public.offers where id = oid for update;
  if o.id is null then return 'missing'; end if;
  if o.person_id is distinct from public.my_person() then raise exception 'Not your offer'; end if;
  if o.status <> 'pending' then return 'answered'; end if;
  if not accept then
    update public.offers set status = 'declined', resp = to_char(current_date,'YYYY-MM-DD'), resp_at = now() where id = oid;
    insert into public.log(id, what) values (gen_random_uuid()::text, 'Declined the offer: ' || coalesce(o.data->>'text',''));
    return 'declined';
  end if;
  if o.data->'result' is null then return 'changed'; end if;
  -- the rotations it changes must still be as they were when it was offered
  for k, v in select * from jsonb_each(coalesce(o.data->'expect','{}'::jsonb)) loop
    select jsonb_build_object('s', s, 'e', e, 'd', d) into cur from public.rotations where id = k;
    if cur is null or cur <> v then return 'changed'; end if;
  end loop;
  for r in select * from jsonb_array_elements(coalesce(o.data->'result'->'del','[]'::jsonb)) loop
    delete from public.rotations where id = r #>> '{}';
  end loop;
  for r in select * from jsonb_array_elements(coalesce(o.data->'result'->'put','[]'::jsonb)) loop
    insert into public.rotations(id, person_id, s, e, d, loc, note)
      values (r->>'id', r->>'person_id', (r->>'s')::int, (r->>'e')::int, coalesce(r->>'d',''), coalesce(r->>'loc',''), coalesce(r->>'note',''))
      on conflict (id) do update set person_id = excluded.person_id, s = excluded.s, e = excluded.e,
        d = excluded.d, loc = excluded.loc, note = excluded.note;
  end loop;
  update public.offers set status = 'accepted', resp = to_char(current_date,'YYYY-MM-DD'), resp_at = now() where id = oid;
  insert into public.log(id, what) values (gen_random_uuid()::text, 'Accepted the offer: ' || coalesce(o.data->>'text',''));
  return 'accepted';
end $$;

-------------------------------------------------------------------------------
-- 6. Let the app reach the tables, and send live updates
-------------------------------------------------------------------------------
grant usage on schema public to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
grant execute on all functions in schema public to authenticated;
revoke all on all tables in schema public from anon;

do $$ begin
  alter publication supabase_realtime add table
    public.people, public.rotations, public.training, public.away, public.accom, public.settings,
    public.offers, public.vols, public.ideas, public.idea_votes, public.members, public.people_private;
exception when others then null; end $$;

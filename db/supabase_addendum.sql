-- ============================================================================
-- PreflopRange — Supabase-specific addendum (run AFTER db/schema.sql)
-- Track D, D.1-supabase. Keeps the portable core (schema.sql) unchanged and
-- layers on the two things that only make sense inside Supabase:
--   1. tie profiles to the Supabase auth user (auth.users)
--   2. Row Level Security (RLS) — secure-by-default on public tables
--
-- HOW TO APPLY (Supabase dashboard):
--   SQL Editor -> paste db/schema.sql, Run  ->  then paste THIS file, Run.
--
-- Comments in English to match codebase convention; rationale (RU) in
-- docs/db_schema.md.
-- ============================================================================

-- 1. Link profiles.id to the Supabase auth user.
--    A profile row's PK *is* the auth user's id. on delete cascade => deleting
--    an auth user removes their app data too.
alter table public.profiles
    add constraint profiles_id_fkey
    foreign key (id) references auth.users (id) on delete cascade;

-- 2. Row Level Security.
--    We enable RLS on every app table. Our FastAPI backend connects with the
--    DIRECT Postgres connection (the `postgres` role from Settings -> Database),
--    which BYPASSES RLS — so nothing the server does breaks. RLS only matters if
--    something ever reaches these tables with the anon/auth key (client-side).
--    Enabling it now means the tables are NOT world-readable if that anon key
--    leaks. Per-user policies (each user sees only their own rows) are added in
--    D.2 when auth is wired and we know whether any access goes client-side.
alter table public.profiles enable row level security;
alter table public.answers  enable row level security;
alter table public.cards    enable row level security;
alter table public.goals    enable row level security;

-- No policies yet => with RLS on and no policy, the anon/auth roles can read
-- nothing (deny-by-default). The backend's direct connection is unaffected.
-- D.2 will add policies like:
--   create policy "own rows" on public.answers
--     for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ----------------------------------------------------------------------------
-- 3. (D.2 auth — leave commented until signup is wired.)
--    Auto-create a profile row when a new auth user signs up, with our app
--    defaults. Uncomment and run when building auth so every new user gets a
--    profiles row (timezone/session_min_hands) without an extra app call.
-- ----------------------------------------------------------------------------
-- create or replace function public.handle_new_user()
-- returns trigger
-- language plpgsql
-- security definer set search_path = public
-- as $$
-- begin
--     insert into public.profiles (id, email)
--     values (new.id, new.email);
--     return new;
-- end;
-- $$;
--
-- create trigger on_auth_user_created
--     after insert on auth.users
--     for each row execute function public.handle_new_user();

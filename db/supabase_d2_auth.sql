-- ============================================================================
-- PreflopRange -- Supabase D.2 (auth) migration. Run AFTER db/schema.sql and
-- db/supabase_addendum.sql.
--
-- This activates the two pieces the addendum deliberately left commented until
-- auth was wired:
--   1. handle_new_user() trigger -- auto-creates a profiles row on signup, so
--      every new user has the timezone/session_min_hands the dashboard views
--      JOIN against (without an extra app call).
--   2. per-user RLS policies (auth.uid() = user_id) -- a BACKSTOP. The FastAPI
--      backend connects as the postgres role (bypasses RLS) and enforces
--      isolation itself by filtering on the JWT's user_id; these policies only
--      matter if the anon key ever reaches the tables client-side (then the
--      tables are NOT world-readable).
--
-- Idempotent: safe to run more than once (drop-if-exists before each create,
-- create-or-replace for the function). ASCII-only so it pastes cleanly.
--
-- HOW TO APPLY (Supabase dashboard): SQL Editor -> paste -> Run.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Auto-create a profile row when a new auth user signs up.
--    security definer: runs as the function owner so the insert is allowed
--    regardless of RLS. search_path pinned for safety.
-- ----------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.profiles (id, email)
    values (new.id, new.email);
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- ----------------------------------------------------------------------------
-- 2. Per-user Row Level Security policies (backstop -- see header).
--    answers/cards/goals are keyed by user_id; profiles by its primary key id.
--    "for all" covers select/insert/update/delete; the with-check guards writes.
-- ----------------------------------------------------------------------------
drop policy if exists "own rows" on public.answers;
create policy "own rows" on public.answers
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own rows" on public.cards;
create policy "own rows" on public.cards
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own rows" on public.goals;
create policy "own rows" on public.goals
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own profile" on public.profiles;
create policy "own profile" on public.profiles
    for all using (auth.uid() = id) with check (auth.uid() = id);

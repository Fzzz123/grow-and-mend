-- Run once in Supabase: SQL Editor -> New query -> paste -> Run
insert into storage.buckets (id, name, public) values ('designs', 'designs', true)
on conflict (id) do nothing;

create table if not exists public.submissions (
  id bigint generated always as identity primary key,
  file text not null,
  mode text not null,
  name text,
  note text,
  time double precision not null
);
alter table public.submissions enable row level security;

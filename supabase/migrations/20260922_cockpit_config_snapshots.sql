-- Cockpit config snapshot table (mirrors 9router's router_config_snapshots).
-- Stores encrypted config snapshots per instance for restore after redeploy.

create table if not exists public.cockpit_config_snapshots (
  instance_id    text primary key,
  format_version integer not null,
  revision       bigint  not null,
  ciphertext     text    not null,
  checksum       text    not null,
  updated_at     timestamptz not null default now()
);

-- Restrict access: only service_role can read/write (RLS enabled, no anon policies).
alter table public.cockpit_config_snapshots enable row level security;

-- No policies for anon/authenticated — service_role bypasses RLS by default.

-- Index for lookups by instance (primary key already covers, but explicit for clarity).
create index if not exists cockpit_config_snapshots_updated_at_idx
  on public.cockpit_config_snapshots (updated_at desc);

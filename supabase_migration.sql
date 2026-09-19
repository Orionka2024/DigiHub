-- Users table (replaces ALLOWED_USERS env var)
create table digihub_users (
  id          uuid primary key default gen_random_uuid(),
  username    text unique not null,
  pwd_hash    text not null,           -- existing pbkdf2 format: salt:hash
  role        text not null default 'preparer', -- 'preparer' | 'reviewer' | 'admin'
  created_at  timestamptz default now()
);

-- Filings table (replaces WorkspaceStore._snapshots)
create table filings (
  filing_id         text primary key,
  kvk_number        text not null,
  entity_name       text,
  period_start      date not null,
  period_end        date not null,
  taxonomy_id       text not null,
  entry_point_key   text,
  document_sha256   text,
  state             text not null default 'draft',
  frozen_at         timestamptz,
  validation_digest text,
  frozen_digest     text,
  is_final          boolean default false,
  signatory_name    text,
  approval_date     date,
  report_sections   jsonb default '[]',
  reviewed_req_ids  jsonb default '[]',
  snapshot          jsonb not null,        -- the entire serialized FilingSnapshot
  created_by        text,                  -- username
  updated_at        timestamptz default now()
);

-- Documents table (replaces WorkspaceStore._documents)
create table documents (
  sha256     text primary key,
  nodes      jsonb not null,
  headers    jsonb default '[]',
  footers    jsonb default '[]',
  warnings   jsonb default '[]',
  created_at timestamptz default now()
);

-- Row-level security (optional, for future multi-tenant isolation)
-- alter table filings enable row level security;
-- alter table documents enable row level security;

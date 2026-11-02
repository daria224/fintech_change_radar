-- Additive, repeatable migration. Legacy findings and subscribers are preserved.
CREATE TABLE IF NOT EXISTS radar_meta (key text PRIMARY KEY, value text NOT NULL);
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;
ALTER TABLE materials ADD COLUMN IF NOT EXISTS radar_version text;
ALTER TABLE materials ADD COLUMN IF NOT EXISTS historical boolean NOT NULL DEFAULT true;
ALTER TABLE materials ADD COLUMN IF NOT EXISTS content_mode text NOT NULL DEFAULT 'описание';
ALTER TABLE materials ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
ALTER TABLE materials ADD COLUMN IF NOT EXISTS retry_at timestamptz;
CREATE TABLE IF NOT EXISTS radar_source_checks (
 id bigserial PRIMARY KEY, source_id integer REFERENCES sources(id), run_id integer REFERENCES runs(id),
 checked_at timestamptz NOT NULL DEFAULT now(), ok boolean NOT NULL,
 items integer NOT NULL DEFAULT 0, oldest timestamptz, newest timestamptz, note text NOT NULL
);
CREATE TABLE IF NOT EXISTS radar_events (
 id bigserial PRIMARY KEY, event_key text UNIQUE NOT NULL, company text NOT NULL,
 event_date date, change_type text NOT NULL, mechanism text NOT NULL,
 card jsonb NOT NULL, model text NOT NULL, rules_version text NOT NULL,
 historical boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS radar_evidence (
 event_id bigint REFERENCES radar_events(id), material_id integer UNIQUE REFERENCES materials(id),
 quote text NOT NULL, PRIMARY KEY(event_id,material_id)
);
CREATE TABLE IF NOT EXISTS radar_spend (
 id bigserial PRIMARY KEY, budget_day date NOT NULL, model text NOT NULL,
 reserved numeric NOT NULL CHECK(reserved >= 0), actual numeric,
 state text NOT NULL DEFAULT 'reserved', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS radar_spend_day ON radar_spend(budget_day);
CREATE TABLE IF NOT EXISTS radar_digests (
 day date PRIMARY KEY, text text NOT NULL, event_ids bigint[] NOT NULL,
 signal jsonb, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS radar_deliveries (
 day date REFERENCES radar_digests(day), chat_id bigint NOT NULL,
 state text NOT NULL DEFAULT 'pending', message_id bigint, note text,
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(day,chat_id)
);
CREATE TABLE IF NOT EXISTS radar_jobs (
 job text NOT NULL, slot text NOT NULL, state text NOT NULL DEFAULT 'started',
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(job,slot)
);

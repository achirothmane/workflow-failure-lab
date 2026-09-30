CREATE TABLE IF NOT EXISTS rg_releases (
 id text PRIMARY KEY, config jsonb NOT NULL, config_hash text NOT NULL,
 status text NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING','PAUSED','ROLLED_BACK','COMPLETED')),
 stage integer NOT NULL DEFAULT 0, epoch integer NOT NULL DEFAULT 1,
 revision integer NOT NULL DEFAULT 1, stage_since timestamptz NOT NULL DEFAULT clock_timestamp(),
 lease_until timestamptz NOT NULL DEFAULT clock_timestamp(),
 healthy_windows integer NOT NULL DEFAULT 0, last_candidate_n integer NOT NULL DEFAULT 0,
 last_stable_n integer NOT NULL DEFAULT 0, last_reason text, audit_seq integer NOT NULL DEFAULT 0,
 audit_head text NOT NULL DEFAULT '', created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS rg_requests (
 release_id text NOT NULL REFERENCES rg_releases(id), id text NOT NULL,
 fingerprint text NOT NULL, status text NOT NULL DEFAULT 'PENDING',
 owner text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 finished_at timestamptz, http_status integer, sealed_response text,
 PRIMARY KEY(release_id,id)
);
CREATE TABLE IF NOT EXISTS rg_attempts (
 id uuid PRIMARY KEY, release_id text NOT NULL REFERENCES rg_releases(id),
 request_id text NOT NULL, epoch integer NOT NULL, revision integer NOT NULL,
 arm text NOT NULL CHECK (arm IN ('stable','candidate')),
 source text NOT NULL CHECK (source IN ('route','probe','fallback')),
 dispatched boolean NOT NULL DEFAULT false, settled boolean NOT NULL DEFAULT false,
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), finished_at timestamptz,
 ok boolean, valid boolean, latency_ms double precision, reason text,
 FOREIGN KEY (release_id,request_id) REFERENCES rg_requests(release_id,id)
);
CREATE INDEX IF NOT EXISTS rg_attempt_window ON rg_attempts(release_id,epoch,started_at,arm);
CREATE INDEX IF NOT EXISTS rg_pending_requests ON rg_requests(status,created_at);
CREATE TABLE IF NOT EXISTS rg_evidence (
 release_id text NOT NULL REFERENCES rg_releases(id), seq integer NOT NULL,
 record jsonb NOT NULL, previous_hash text NOT NULL, hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(release_id,seq)
);
CREATE TABLE IF NOT EXISTS rg_outbox (
 release_id text NOT NULL, seq integer NOT NULL, body jsonb NOT NULL,
 attempts integer NOT NULL DEFAULT 0, delivered_at timestamptz,
 next_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(release_id,seq), FOREIGN KEY(release_id,seq) REFERENCES rg_evidence(release_id,seq)
);

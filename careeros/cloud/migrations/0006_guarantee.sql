-- Money-back guarantees: the Interview Guarantee (Pro and Ultra) and the Job Guarantee (with Concierge).
-- One row per account and kind. Portable SQL for SQLite and PostgreSQL.
CREATE TABLE guarantees (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                 -- interview | job
  status TEXT NOT NULL,               -- active | met | claimable | claimed | approved | refunded | rejected | ended | void
  plan TEXT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'INR',
  terms_version TEXT NOT NULL,
  agreed_at TEXT NOT NULL,
  agreed_ip TEXT NOT NULL DEFAULT '',
  starts_at TEXT NOT NULL,
  ends_at TEXT NOT NULL,
  eligibility TEXT NOT NULL DEFAULT '{}',   -- what was checked at enrolment, kept as the record
  progress TEXT NOT NULL DEFAULT '{}',      -- last computed progress
  reason TEXT,                              -- why it ended, was voided or was decided
  met_at TEXT,
  claimed_at TEXT,
  claim_note TEXT,
  decided_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  decided_at TEXT,
  refund_amount INTEGER,                    -- minor units (paise or cents), set when approved
  refunds INTEGER NOT NULL DEFAULT 0,       -- how many times this account was refunded for this kind
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, kind)
);
CREATE INDEX guarantees_status ON guarantees(status);

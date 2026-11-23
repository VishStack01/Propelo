-- Where a sign-up came from: a short label carried on the link they followed (?src=reddit-ukjobs), so each
-- channel's sign-ups and payers can be counted. Never an address, a referrer URL or anything about the person.
ALTER TABLE users ADD COLUMN signup_source TEXT NOT NULL DEFAULT '';

-- Passes: Pro or Ultra bought once for a fixed number of days, with nothing that renews (see passes.py).
CREATE TABLE passes (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  plan TEXT NOT NULL,
  days INTEGER NOT NULL,
  price INTEGER NOT NULL,
  currency TEXT NOT NULL,
  provider TEXT NOT NULL,
  pay_ref TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  paid_at TEXT,
  ends_at TEXT
);
CREATE INDEX passes_user ON passes(user_id, status);
CREATE INDEX passes_ref ON passes(pay_ref);

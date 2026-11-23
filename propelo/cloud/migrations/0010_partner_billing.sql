-- Business accounts can be requested (free pilot) or bought online (30 days, prepaid, nothing renews by itself).
ALTER TABLE partners ADD COLUMN plan TEXT NOT NULL DEFAULT '';
ALTER TABLE partners ADD COLUMN currency TEXT NOT NULL DEFAULT 'INR';
ALTER TABLE partners ADD COLUMN request TEXT NOT NULL DEFAULT '{}';
ALTER TABLE partners ADD COLUMN reminded TEXT NOT NULL DEFAULT '';

CREATE TABLE partner_payments (
  id TEXT PRIMARY KEY,
  partner_id TEXT NOT NULL REFERENCES partners(id) ON DELETE CASCADE,
  plan TEXT NOT NULL,
  provider TEXT NOT NULL,              -- razorpay | dodo
  ref TEXT NOT NULL DEFAULT '',        -- payment link id or checkout session id
  amount INTEGER NOT NULL,             -- minor units
  currency TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', -- open | paid | expired
  url TEXT NOT NULL DEFAULT '',
  created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  paid_at TEXT
);
CREATE INDEX partner_payments_ref ON partner_payments(ref);
CREATE INDEX partner_payments_partner ON partner_payments(partner_id, status);

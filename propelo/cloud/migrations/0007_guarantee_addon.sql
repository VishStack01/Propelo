-- The guarantees are paid add-ons: a one-time payment starts each one.
ALTER TABLE guarantees ADD COLUMN price INTEGER NOT NULL DEFAULT 0;      -- what was paid, in paise or cents
ALTER TABLE guarantees ADD COLUMN pay_provider TEXT;                    -- razorpay | dodo | grant
ALTER TABLE guarantees ADD COLUMN pay_ref TEXT;                         -- payment link or checkout session id
ALTER TABLE guarantees ADD COLUMN pay_url TEXT;
ALTER TABLE guarantees ADD COLUMN paid_at TEXT;
CREATE INDEX guarantees_pay_ref ON guarantees(pay_ref);

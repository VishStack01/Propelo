-- Guarantees are applied for and reviewed by the team before anything is paid.
ALTER TABLE guarantees ADD COLUMN application TEXT NOT NULL DEFAULT '{}';
ALTER TABLE guarantees ADD COLUMN reviewed_by TEXT;
ALTER TABLE guarantees ADD COLUMN reviewed_at TEXT;

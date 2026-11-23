-- Matching reads only what changed since a person's last match, with a full pass when their filters change,
-- when the last run had more fits than it could add, or once a week.
ALTER TABLE match_state ADD COLUMN full_at TEXT;
ALTER TABLE match_state ADD COLUMN more INTEGER NOT NULL DEFAULT 0;
CREATE INDEX jobs_changed ON jobs(last_seen_at);

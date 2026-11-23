-- Business accounts: study-abroad consultancies (branded student portal with seats) and recruiting
-- agencies (a filtered daily feed of open roles). Portable SQL for SQLite and PostgreSQL.
CREATE TABLE partners (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,                      -- consultancy | agency
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pilot',    -- pilot | active | paused | ended
  seats INTEGER NOT NULL DEFAULT 0,        -- consultancy: students who get the paid plan
  student_plan TEXT NOT NULL DEFAULT 'pro',
  invite_code TEXT NOT NULL UNIQUE,
  brand TEXT NOT NULL DEFAULT '{}',        -- {"color", "tagline", "website"}
  logo TEXT,                               -- data URL of a small PNG/JPEG/WebP, served from this site
  filters TEXT NOT NULL DEFAULT '{}',      -- agency feed filters
  feed_key_hash TEXT,                      -- sha256 of the agency's feed key; the key is shown once
  billing TEXT NOT NULL DEFAULT '{}',      -- {"amount", "currency", "note"}: what was agreed, for the record
  ends_at TEXT,                            -- the paid or pilot period ends; NULL: open-ended
  created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX partners_kind ON partners(kind, status);

CREATE TABLE partner_members (
  partner_id TEXT NOT NULL REFERENCES partners(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL,                      -- admin | student
  status TEXT NOT NULL DEFAULT 'active',   -- active | removed | left
  consent TEXT NOT NULL DEFAULT '',        -- what the student agreed the partner may see, and when
  joined_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (partner_id, user_id)
);
CREATE INDEX partner_members_user ON partner_members(user_id, status);

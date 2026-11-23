-- Uploaded files kept in the database (STORAGE=db), for a server with no disk of its own.
CREATE TABLE blobs (
  key TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  data BYTEA NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX blobs_user ON blobs(user_id);

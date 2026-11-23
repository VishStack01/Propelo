-- A short hash of each role's record and text, so a feed that repeats a role unchanged writes nothing.
ALTER TABLE jobs ADD COLUMN rev TEXT NOT NULL DEFAULT '';

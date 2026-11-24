-- Sign in with a mobile number: a member adds and confirms a number in Settings (a code by text message),
-- then can sign in with it. One account per number.
ALTER TABLE users ADD COLUMN phone TEXT;
ALTER TABLE users ADD COLUMN phone_verified_at TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS users_phone ON users(phone) WHERE phone IS NOT NULL;

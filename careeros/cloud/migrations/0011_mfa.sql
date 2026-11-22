-- Two-step sign-in with an authenticator app (TOTP, RFC 6238). The secret is encrypted with SECRETS_KEY;
-- recovery codes are stored as hashes and each works once.
ALTER TABLE users ADD COLUMN mfa_secret TEXT;
ALTER TABLE users ADD COLUMN mfa_enabled_at TEXT;
ALTER TABLE users ADD COLUMN mfa_recovery TEXT NOT NULL DEFAULT '[]';
ALTER TABLE users ADD COLUMN mfa_last_step INTEGER NOT NULL DEFAULT 0;

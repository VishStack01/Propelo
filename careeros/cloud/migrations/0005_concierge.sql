-- Propelo Concierge: an optional, human-run job search. The candidate pays a share of the fixed
-- CTC only after joining a company Propelo put them forward to, with their approval.

-- People on the Propelo team who run Concierge cases (talent partners). Admins can always act as staff.
ALTER TABLE users ADD COLUMN is_staff INTEGER NOT NULL DEFAULT 0;

CREATE TABLE concierge_cases (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL,              -- requested, active, paused, offer, placed, closed
  country TEXT NOT NULL,
  currency TEXT NOT NULL,
  intake TEXT NOT NULL,              -- JSON: target roles, locations, current and expected pay, notice period, phone, notes
  partner_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  terms_version TEXT NOT NULL,
  agreed_at TEXT NOT NULL,
  agreed_ip TEXT NOT NULL,
  closed_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX concierge_cases_status ON concierge_cases(status, updated_at);
CREATE INDEX concierge_cases_partner ON concierge_cases(partner_id);

-- Every company and role Propelo proposes. Only roles the candidate approved can lead to a fee.
CREATE TABLE concierge_submissions (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES concierge_cases(id) ON DELETE CASCADE,
  company TEXT NOT NULL,
  company_key TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  why TEXT,
  status TEXT NOT NULL,              -- proposed, approved, declined, submitted, interviewing, offer, rejected, withdrawn
  proposed_by TEXT,
  proposed_at TEXT NOT NULL,
  approved_at TEXT,
  submitted_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX concierge_submissions_case ON concierge_submissions(case_id, proposed_at);

-- Messages between the candidate and their partner, and the partner's private notes.
CREATE TABLE concierge_notes (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES concierge_cases(id) ON DELETE CASCADE,
  author_id TEXT,
  shared INTEGER NOT NULL DEFAULT 1,
  body TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX concierge_notes_case ON concierge_notes(case_id, at);

-- An accepted offer and the fee it creates.
CREATE TABLE concierge_placements (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES concierge_cases(id) ON DELETE CASCADE,
  submission_id TEXT REFERENCES concierge_submissions(id) ON DELETE SET NULL,
  company TEXT NOT NULL,
  fixed_ctc INTEGER NOT NULL,        -- yearly fixed pay, in the currency's main unit (rupees)
  currency TEXT NOT NULL,
  joining_date TEXT NOT NULL,
  fee INTEGER NOT NULL,              -- before tax
  tax_rate REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL,              -- reported, verified, invoicing, paid, waived, disputed
  offer_doc TEXT,                    -- upload id of the offer letter, if shared
  verified_by TEXT,
  verified_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX concierge_placements_case ON concierge_placements(case_id);

CREATE TABLE concierge_instalments (
  id TEXT PRIMARY KEY,
  placement_id TEXT NOT NULL REFERENCES concierge_placements(id) ON DELETE CASCADE,
  n INTEGER NOT NULL,
  amount INTEGER NOT NULL,           -- including tax, in paise or cents
  currency TEXT NOT NULL,
  due_on TEXT NOT NULL,
  status TEXT NOT NULL,              -- due, link_sent, paid, waived
  provider_link_id TEXT,
  link_url TEXT,
  paid_at TEXT,
  UNIQUE (placement_id, n)
);
CREATE INDEX concierge_instalments_link ON concierge_instalments(provider_link_id);

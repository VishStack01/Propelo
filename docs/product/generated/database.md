# Database tables (generated)

Generated from `careeros/cloud/migrations/*.sql`. Do not edit by hand.

32 tables.

## users

`id`, `email`, `name`, `password_hash`, `email_verified_at`, `is_admin`, `disabled_at`, `created_at`, `updated_at`, `last_login_at`, `password_changed_at`, `is_staff (0005_concierge)`, `mfa_secret (0011_mfa)`, `mfa_enabled_at (0011_mfa)`, `mfa_recovery (0011_mfa)`, `mfa_last_step (0011_mfa)`, `signup_source (0013_growth)`

## sessions

`id`, `user_id`, `token_hash`, `created_at`, `expires_at`, `last_seen_at`, `ip`, `user_agent`, `revoked_at`

## api_tokens

`id`, `user_id`, `name`, `token_hash`, `prefix`, `scopes`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`

## one_time_tokens

`token_hash`, `user_id`, `purpose`, `created_at`, `expires_at`, `used_at`

## rate_limits

`key`, `window_start`, `count`

## docs

`user_id`, `collection`, `id`, `data`, `version`, `size_bytes`, `created_at`, `updated_at`

## assets

`id`, `user_id`, `name`, `content_type`, `size_bytes`, `sha256`, `storage_key`, `text`, `created_at`

## applications

`user_id`, `key`, `job_id`, `company_key`, `state`, `attempts`, `receipt`, `created_at`, `updated_at`

## jobs

`id`, `company`, `title`, `url`, `source`, `posted_at`, `record`, `text`, `active`, `first_seen_at`, `last_seen_at`, `closed_at`, `rev (0012_job_rev)`

## feed_state

`key`, `value`, `updated_at`

## match_state

`user_id`, `settings_hash`, `last_match_at`, `last_feed_at`

## tasks

`id`, `kind`, `user_id`, `payload`, `dedupe_key`, `status`, `attempts`, `max_attempts`, `run_after`, `locked_by`, `locked_until`, `last_error`, `created_at`, `updated_at`, `finished_at`

## audit_events

`id`, `user_id`, `at`, `kind`, `ip`, `detail`

## subscriptions

`user_id`, `plan`, `status`, `provider`, `provider_sub_id`, `current_end`, `cancel_at_period_end`, `last_event_at`, `granted_by`, `created_at`, `updated_at`, `currency (0003_ultra)`, `provider_customer_id (0003_ultra)`, `pending_plan (0003_ultra)`, `pending_provider (0003_ultra)`, `pending_sub_id (0003_ultra)`

## billing_events

`id`, `provider`, `kind`, `provider_sub_id`, `received_at`, `payload`

## ai_usage

`user_id`, `period`, `hosted`, `own`

## ai_keys

`user_id`, `provider`, `model`, `base_url`, `secret`, `hint`, `created_at`, `updated_at`

## feature_usage

`user_id`, `period`, `feature`, `count`

## mailboxes

`user_id`, `provider`, `address`, `secret`, `connected_at`, `last_error`, `updated_at`

## outreach_sends

`id`, `user_id`, `job_id`, `kind`, `to_addr`, `to_source`, `subject`, `body`, `status`, `thread_id`, `message_id`, `error`, `created_at`, `sent_at`

## email_optouts

`address_hash`, `at`

## concierge_cases

`id`, `user_id`, `status`, `country`, `currency`, `intake`, `partner_id`, `terms_version`, `agreed_at`, `agreed_ip`, `closed_reason`, `created_at`, `updated_at`

## concierge_submissions

`id`, `case_id`, `company`, `company_key`, `title`, `url`, `why`, `status`, `proposed_by`, `proposed_at`, `approved_at`, `submitted_at`, `updated_at`

## concierge_notes

`id`, `case_id`, `author_id`, `shared`, `body`, `at`

## concierge_placements

`id`, `case_id`, `submission_id`, `company`, `fixed_ctc`, `currency`, `joining_date`, `fee`, `tax_rate`, `status`, `offer_doc`, `verified_by`, `verified_at`, `created_at`, `updated_at`

## concierge_instalments

`id`, `placement_id`, `n`, `amount`, `currency`, `due_on`, `status`, `provider_link_id`, `link_url`, `paid_at`

## guarantees

`id`, `user_id`, `kind`, `status`, `plan`, `currency`, `terms_version`, `agreed_at`, `agreed_ip`, `starts_at`, `ends_at`, `eligibility`, `progress`, `reason`, `met_at`, `claimed_at`, `claim_note`, `decided_by`, `decided_at`, `refund_amount`, `refunds`, `created_at`, `updated_at`, `price (0007_guarantee_addon)`, `pay_provider (0007_guarantee_addon)`, `pay_ref (0007_guarantee_addon)`, `pay_url (0007_guarantee_addon)`, `paid_at (0007_guarantee_addon)`, `application (0008_guarantee_review)`, `reviewed_by (0008_guarantee_review)`, `reviewed_at (0008_guarantee_review)`

## partners

`id`, `kind`, `name`, `slug`, `status`, `seats`, `student_plan`, `invite_code`, `brand`, `logo`, `filters`, `feed_key_hash`, `billing`, `ends_at`, `created_by`, `created_at`, `updated_at`, `plan (0010_partner_billing)`, `currency (0010_partner_billing)`, `request (0010_partner_billing)`, `reminded (0010_partner_billing)`

## partner_members

`partner_id`, `user_id`, `role`, `status`, `consent`, `joined_at`, `updated_at`

## partner_payments

`id`, `partner_id`, `plan`, `provider`, `ref`, `amount`, `currency`, `status`, `url`, `created_by`, `created_at`, `paid_at`

## passes

`id`, `user_id`, `plan`, `days`, `price`, `currency`, `provider`, `pay_ref`, `status`, `created_at`, `paid_at`, `ends_at`

## blobs

`key`, `user_id`, `data`, `created_at`, `key`, `user_id`, `data`, `created_at`

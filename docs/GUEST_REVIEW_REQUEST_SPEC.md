# Paradise Automator - Guest Review Request Feature Spec

> Status: Planned longer-term target. The repository currently includes a simpler manual CLI where the operator supplies guest name and phone number directly.

## Objective

Add a guest review request workflow to Paradise Automator so it can:

1. identify recently departed guests who should receive a review request
2. reuse the existing approved SMS review template
3. keep persistent send history so the same booking is not texted twice by accident
4. expose a simple operator/OpenClaw-friendly interface for reviewing pending sends and marking results

This should extend the current Paradise Automator model rather than introduce a separate system. Paradise Automator already knows how to authenticate to REI and already has a generic SMS transport path through the Comms API.

## Existing Building Blocks

Current repo capabilities that this feature should reuse:

- `booking_data_extractor.py`
  - logs into REI
  - searches bookings
  - extracts booking-grid rows keyed by `No.` and `Status`
- `api_email_sender.py`
  - already sends SMS through `POST /api/integrations/v1/send`
  - can point either at the existing remote Comms endpoint or the local Nerve Centre compatibility endpoint
- `rei_cloud_automation.py`
  - already persists lightweight automation state

Important current limitation:

- `booking_data_extractor.py` currently hard-codes `Date Mode = Arrival`
- review requests should be driven by checkout/departure timing, so the extractor must be extended to support `date_mode`
- current booking extraction does not yet capture guest mobile numbers, so the feature must add booking-detail extraction or another reliable phone lookup step

## Scope

In scope:

- find eligible departed stays
- fetch guest mobile number for each eligible stay
- normalize phone numbers
- prepare the review message using the existing template
- persist candidate, skip, failure, and sent state
- allow OpenClaw or an operator to export pending sends
- allow OpenClaw or an operator to mark sends as successful or failed
- prevent accidental duplicate sends by default

Out of scope for the first version:

- writing a brand new review template
- AI-generated review copy
- multi-step review campaigns
- reply handling or inbox management
- review-link analytics
- automatic opt-out detection from inbound SMS

## Recommended Workflow

1. Paradise Automator queries REI for bookings with status `Departed`.
2. Query window defaults to recent checkout dates, not arrival dates.
3. For each candidate booking, the feature extracts or resolves:
   - booking reference
   - guest name
   - property / room
   - check-in date
   - check-out date
   - guest mobile number
4. The feature applies eligibility rules and dedupe rules.
5. Eligible unsent bookings are stored as `pending_send`.
6. OpenClaw or an operator exports the pending queue.
7. OpenClaw sends the SMS using the rendered message body.
8. After each successful send, OpenClaw marks the request as `sent`.
9. Failed sends are marked `failed` with an error reason and remain visible for retry/review.

## Eligibility Rules

Recommended defaults:

- booking status must be `Departed`
- send delay defaults to `1` day after checkout
- catch-up lookback defaults to `3` days so a missed run can recover safely
- booking must have a valid guest mobile number after normalization
- booking must not already have a `sent` review request for the same template

Recommended skip reasons:

- `missing_phone`
- `invalid_phone`
- `not_departed`
- `outside_window`
- `already_sent`
- `manually_suppressed`

Implementation note:

- the default target set should be guests who checked out yesterday, plus a short catch-up window
- duplicate prevention matters more than aggressive retries

## Template Handling

The feature must use the existing approved SMS review template. It should not introduce a second competing copy in code.

Recommended contract:

- store a stable template identifier such as `guest_review_request_v1`
- load template content from configuration or a single dedicated template file
- render a final `message_body` for each pending request

Requirements:

- if the existing template is a static message, the renderer can return it unchanged
- if the existing template uses merge fields, only the already-approved fields should be supported
- the service should record the `template_key` used for every request so future template changes do not break dedupe history

## Data Extraction Requirements

The feature should add a dedicated extraction path for review requests instead of trying to infer everything from cleaning CSVs.

Required extractor changes:

1. `booking_data_extractor.py` must accept a `date_mode` argument.
   - default can remain `Arrival` for existing behavior
   - review request flow should use `Departure` or the REI equivalent checkout filter
2. the extractor must support a narrow date range for recent departures
3. the feature must fetch guest mobile number from booking details when the search grid does not expose it
4. extracted phones must be normalized to E.164 before dedupe or send

Minimum booking fields needed by the review workflow:

- `booking_ref`
- `guest_name`
- `guest_phone_raw`
- `guest_phone_e164`
- `property_name`
- `check_in_date`
- `check_out_date`
- `status`

## State And Duplicate Prevention

Use SQLite, not a flat JSON file, for this feature.

Reason:

- duplicate prevention needs durable uniqueness rules
- operators need audit history
- OpenClaw may run repeated export/mark cycles
- SQLite is available in Python stdlib and does not add deployment complexity

Recommended state database:

- `state/guest_review_requests.sqlite3`

Recommended tables:

### `review_requests`

- `id` text primary key
- `booking_ref` text not null
- `template_key` text not null
- `guest_name` text
- `guest_phone_e164` text
- `property_name` text
- `check_in_date` text
- `check_out_date` text
- `status` text not null
- `message_body` text not null
- `provider` text
- `provider_message_id` text
- `sent_at` text
- `last_error` text
- `created_at` text not null
- `updated_at` text not null

Required uniqueness rule:

- unique on `booking_ref, template_key`

This is the primary duplicate guard.

If REI booking references are ever unavailable, fall back to a derived dedupe key from:

- normalized phone
- check-out date
- property name
- template key

### `review_request_events`

- `id` text primary key
- `review_request_id` text not null
- `event_type` text not null
- `actor` text not null
- `details_json` text
- `created_at` text not null

Suggested event types:

- `candidate_found`
- `skipped_missing_phone`
- `skipped_already_sent`
- `queued`
- `exported`
- `sent`
- `failed`
- `force_resend_requested`
- `force_resend_sent`

### Optional `review_request_suppressions`

Use this only if manual suppression becomes necessary.

- `id` text primary key
- `booking_ref` text
- `guest_phone_e164` text
- `reason` text not null
- `created_at` text not null

## Status Model

Recommended `review_requests.status` values:

- `pending_send`
- `sent`
- `failed`
- `skipped`
- `suppressed`

Rules:

- once `sent`, a request must never return to `pending_send` automatically
- resend must require an explicit `--force` or equivalent override
- every override must create an event row explaining who did it and why

## Proposed CLI Interface

The simplest interface for OpenClaw is a Python CLI.

Recommended entry point:

- `python3 guest_review_requests.py <command> ...`

Required commands:

### `prepare`

Purpose:

- scrape recent departed bookings
- apply eligibility rules
- upsert pending or skipped rows into SQLite

Example:

```bash
python3 guest_review_requests.py prepare \
  --from 2026-03-16 \
  --to 2026-03-16 \
  --days-after-checkout 1
```

Behavior:

- idempotent for the same date range
- creates no duplicates if rerun
- prints counts for `queued`, `skipped`, and `already_sent`

### `export`

Purpose:

- return pending unsent requests for OpenClaw to process

Example:

```bash
python3 guest_review_requests.py export --status pending_send --format json
```

Expected JSON shape:

```json
{
  "requests": [
    {
      "id": "grr_01H...",
      "booking_ref": "REI-12345",
      "guest_name": "Jane Guest",
      "guest_phone_e164": "+61412345678",
      "property_name": "Unit 8",
      "check_out_date": "2026-03-16",
      "template_key": "guest_review_request_v1",
      "message_body": "Rendered review SMS here",
      "status": "pending_send"
    }
  ]
}
```

### `mark-sent`

Purpose:

- persist successful delivery after OpenClaw sends the text

Example:

```bash
python3 guest_review_requests.py mark-sent \
  --request-id grr_01H... \
  --provider openclaw \
  --provider-message-id msg_123
```

Behavior:

- sets `status = sent`
- stores `sent_at`
- stores provider metadata if supplied
- creates a `sent` event row

### `mark-failed`

Purpose:

- record a failed attempt without losing the request

Example:

```bash
python3 guest_review_requests.py mark-failed \
  --request-id grr_01H... \
  --reason "SMS provider rejected number"
```

Behavior:

- sets `status = failed`
- stores `last_error`
- creates a `failed` event row

### `list`

Purpose:

- inspect queue and history locally

Example:

```bash
python3 guest_review_requests.py list --status sent --from 2026-03-01 --to 2026-03-17
```

### Optional `send`

This can be added later if Paradise Automator should send directly through the existing Comms API without OpenClaw in the middle.

If implemented, it should reuse the existing SMS transport path in `api_email_sender.py`.

## Delivery Modes

The feature should support two operating modes.

### Mode 1: OpenClaw-managed send

Recommended first implementation.

- Paradise Automator prepares and exports pending requests
- OpenClaw sends the actual text
- OpenClaw immediately calls `mark-sent` or `mark-failed`

Why:

- matches the requested operating model
- keeps message approval and send orchestration flexible
- still gives Paradise Automator the dedupe ledger

### Mode 2: Direct Comms API send

Optional later mode.

- Paradise Automator calls the existing SMS transport directly
- useful for full automation

If `COMMS_API_URL` points to the local Nerve Centre compatibility endpoint, the send will also be logged centrally in `workflow_runs` and `communications_log`.

## Logging And Audit

Minimum audit requirements:

- every prepare run logs summary counts
- every exported request logs an `exported` event
- every send result creates an event row
- duplicate suppressions are visible in state, not silently ignored

Recommended log file:

- `logs/guest_review_requests.log`

Recommended human-readable summary output:

- queued count
- sent count
- failed count
- skipped count by reason

## Failure Handling

Expected failure cases:

- REI login failure
- REI page layout change
- phone extraction failure
- phone normalization failure
- missing template configuration
- OpenClaw send succeeds but `mark-sent` is not called

Required behavior:

- never mark a request as sent before actual send confirmation
- leave unsafely ambiguous requests in `pending_send` or `failed`
- provide enough metadata for an operator to reconcile manually

Recommended reconciliation rule:

- if OpenClaw reports that a text was sent but the request is still pending, operator should run `mark-sent` manually rather than resend

## Acceptance Criteria

The feature is ready when all of the following are true:

1. Running `prepare` twice for the same date range does not create duplicate pending rows.
2. A request marked `sent` is never exported again by default.
3. Missing-phone bookings are tracked as skipped with a reason.
4. OpenClaw can export a JSON queue and mark outcomes without editing the database directly.
5. A manual resend requires an explicit override and is visibly logged.
6. The workflow can recover from a missed day by using the lookback window without duplicate sends.

## Recommended Rollout

1. Extend booking extraction to support departure-based queries and phone extraction.
2. Implement the SQLite ledger and CLI commands.
3. Test on a small historical date range in dry-run mode.
4. Run `prepare` and `export` only, with no actual sends, to validate candidate quality.
5. Have OpenClaw send a controlled batch and use `mark-sent`.
6. Once stable, optionally add direct send mode through the existing Comms transport.

# Guest Review Request Implementation Notes

This note describes the implementation currently added in this repository and how it lines up with the live VPS setup observed on March 17, 2026.

## What Works Now

Current implementation:

- `guest_review_requests.py` provides:
  - `prepare`
  - `export`
  - `mark-sent`
  - `mark-failed`
  - `list`
  - `send`
  - `send-one`
  - `send-raw`
- queue state is stored in local SQLite at `state/guest_review_requests.sqlite3` by default
- duplicate protection is local-first and durable
- guest mobile numbers are supplied manually for now
- Australian mobile normalization supports `04...` input and converts it to `+614...`
- direct send mode uses the existing integrations contract from `guest_review_requests.py`

Manual prepare can be either:

- a one-off CLI call with `--guest-name` and `--guest-phone`
- a CSV/JSON import file for a small batch
- a single immediate-send call with `send-one <guest_name> <guest_phone>`
- a single raw-text immediate-send call with `send-raw "Min 0425287828"` or even `python3 guest_review_requests.py Min 0425287828`

For the current approved review SMS:

- only `guest_name` is used in the message body
- `booking_ref` is optional metadata only

`booking_ref` is not used for dedupe in the current implementation. It is just optional metadata if an operator wants to record it.

This deliberately keeps the first cut simple and avoids REI booking-detail phone extraction.

## Current Transport Reality

The live Paradise Automator systemd unit on this VPS points at:

- unit: `/etc/systemd/system/paradise-automator.service`
- env file: `/etc/paradise-automator/.env`

On this machine, that env file currently provides:

- a real `COMMS_API_KEY`
- a real `COMMS_API_URL`

The configured URL is the local compatibility endpoint on `http://127.0.0.1:4180/api/integrations/v1/send`, not the hosted Cloudflare URL.

That means the current live send path is:

1. `guest_review_requests.py send`
2. direct `POST /api/integrations/v1/send`
3. local integrations-compatible API on port `4180`

This is already compatible with the broader Paradise comms migration work because the payload shape is still the same integrations contract.

## Compatibility With Nerve Centre And VPS Comms

The local ledger was kept intentionally close to the current `nerve-centre` and `vps-comms` contracts:

- `rule_key` is stored, with default `REVIEW_REQUEST`
- `channel` is stored, currently `sms`
- optional context ids are stored when available:
  - `stay_id`
  - `booking_id`
  - `guest_id`
  - `property_id`
  - `unit_id`

This lines up with:

- `vps-comms` compatibility payload fields
- `nerve-centre` comms contract views:
  - `comms_contract_stay_context_v1`
  - `comms_contract_booking_context_v1`
  - `comms_contract_guest_context_v1`
  - `comms_contract_contact_context_v1`
- `nerve-centre` writeback event handling for:
  - `message_sent_summary`
  - `delivery_failed_permanently`
  - `inbound_guest_reply_received`

Important practical point:

- the SQLite ledger is still the local duplicate guard and queue
- it is not trying to replace `vps-comms` thread/message history
- it is not trying to replace `nerve-centre` writeback audit
- local dedupe is now based on normalized phone number only

That separation is intentional and keeps the current feature from becoming tightly coupled to unfinished migration work.

## What Needs To Change At VPS Comms Cutover

Code changes should be minimal because the CLI already records the identity fields that `vps-comms` expects later.

Main cutover changes:

1. Point `COMMS_API_URL` at the `vps-comms` compatibility endpoint.
2. Set the integration key expected by `vps-comms`.
3. Start supplying real `stay_id` / `booking_id` / `guest_id` / `property_id` / `unit_id` when that context is available.
4. If template management moves into `vps-comms`, map the local review send onto the `REVIEW_REQUEST` rule/template there.

Expected non-changes:

- no queue rewrite should be required
- no transport payload rewrite should be required
- no phone-normalization rewrite should be required

## Current Simplification

Compared with the longer planned spec, the current implementation intentionally does not do:

- REI guest-phone extraction
- REI booking-detail scraping
- automatic departure-based candidate generation

For now, the operator supplies the guest name and phone number manually, and the service handles:

- normalization
- dedupe
- queue export
- send result tracking

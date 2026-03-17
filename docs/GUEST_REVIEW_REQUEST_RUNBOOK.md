# Paradise Automator - Guest Review Request Runbook

> Status: Current manual operating guide for the guest review request CLI.

## Purpose

This runbook explains the current guest review request workflow now deployed in this repository.

Current operating model:

- the operator or OpenClaw supplies only `guest_name` and `guest_phone`
- the CLI normalizes Australian mobile numbers such as `04...` to `+614...`
- the CLI renders the approved Jim review SMS
- the SQLite ledger prevents duplicate sends by normalized phone number

This runbook does not assume REI departure extraction or guest-phone scraping. Those remain future work.

## Prerequisites

Before using the feature:

- `guest_review_requests.py` exists in this repo
- `COMMS_API_URL` and `COMMS_API_KEY` are configured
- the approved SMS review template is configured
- the SQLite state DB is available

On the current VPS, the active env file is `/etc/paradise-automator/.env`.

## Fastest Send Path

The simplest way to send a review SMS is one raw string:

```bash
python3 guest_review_requests.py "Min 0425287828"
```

Accepted input rules:

- order can be `name number` or `number name`
- spaces, multiple spaces, and newlines are accepted
- `04...` mobiles are normalized to `+614...`

Equivalent explicit form:

```bash
python3 guest_review_requests.py send-one "Min" 0425287828
```

Expected outcome:

- if that phone has never been sent this review SMS, the message is sent and recorded as `sent`
- if that phone was already sent, the CLI returns a skip result instead of sending again

## Queue-Based Flow

If you want a prepare/export/mark workflow instead of immediate send:

### 1. Prepare a request

```bash
python3 guest_review_requests.py prepare \
  --guest-name "Min" \
  --guest-phone 0425287828
```

### 2. Export pending requests

```bash
python3 guest_review_requests.py export --status pending_send --format json
```

### 3. Send texts

Use the exported `message_body` exactly as returned.

### 4. Mark the result

Successful send:

```bash
python3 guest_review_requests.py mark-sent \
  --request-id grr_01H... \
  --provider openclaw \
  --provider-message-id msg_123
```

Failed send:

```bash
python3 guest_review_requests.py mark-failed \
  --request-id grr_01H... \
  --reason "Provider rejected number"
```

## Duplicate Prevention

Current dedupe rule:

- unique by normalized phone number only

Important effects:

- `0425287828` and `+61425287828` are treated as the same recipient
- `booking_ref` is metadata only and does not affect dedupe
- `property_name` is not used

## Safe Retry Rules

Default policy:

- `sent` means do not send again
- resend requires `--force` and a reason

Allowed retry cases:

- phone number was corrected
- first send definitely did not go out
- there is an explicit operator instruction to resend

Example:

```bash
python3 guest_review_requests.py send --request-id grr_01H... --force --reason "Corrected mobile"
```

## Suggested OpenClaw Instruction

```text
When asked to send a Paradise Stayz guest review SMS, run:
python3 guest_review_requests.py "<name and mobile in either order>"

Examples:
- python3 guest_review_requests.py "Min 0425287828"
- python3 guest_review_requests.py "0425287828 Min"

Rules:
1. Use only one guest name and one Australian mobile number.
2. Do not rewrite the approved message body.
3. Do not resend to a phone that the CLI reports as already sent.
4. Only use force resend if the instruction explicitly says to do that and includes a reason.
```

## Verification

After a run, verify the state with:

```bash
python3 guest_review_requests.py list --status sent --format table
python3 guest_review_requests.py list --status failed --format table
python3 guest_review_requests.py list --status pending_send --format table
```

What to check:

- the intended phone appears once in `sent`
- no successful send remains in `pending_send`
- failures contain a readable error reason

## Troubleshooting

### Could not parse the input

Check:

- the input contains exactly one Australian mobile number
- the remaining text is the guest name

### Duplicate-send concern

Check:

- the normalized phone was not already sent previously
- a resend was not forced by mistake
- the operator did not bypass the CLI and text manually

### Send failed

Check:

- `COMMS_API_URL` is correct
- `COMMS_API_KEY` is configured
- the number normalized to a valid `+614...` mobile

## Future Work

The current implementation is intentionally simple. Future work can still add:

- departure-based REI extraction
- automatic candidate generation
- richer `stay_id` / `booking_id` context for `vps-comms`

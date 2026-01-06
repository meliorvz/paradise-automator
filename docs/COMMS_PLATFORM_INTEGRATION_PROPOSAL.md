# Comms Platform Integration Proposal

**Prepared for:** Comms Platform Team  
**From:** Paradise Stayz (Victor)  
**Date:** 5 January 2026

---

## Executive Summary

Paradise Stayz operates short-term rental properties and currently uses a VPS-based automation system to scrape data from REI Master (our property management system). We're proposing to integrate with the Comms Platform to enable **automated guest communications** — starting with **deposit requests via Stripe**.

The core idea:
- **Comms Platform** becomes the **source of truth** for bookings and communications.
- **VPS** acts as a **data scraper**, pushing booking data to Comms.
- **Comms Platform** handles Stripe integration, messaging, and staff UI.

---

## Current State: Paradise Stayz Operations

### The Problem
Our property management system (REI Master) and booking channels (Airbnb, Booking.com) do not offer API access for our tier. This means we cannot programmatically access booking data, guest contact info, or financial details.

### Current Solution: VPS Automation
We run a Python + Playwright automation on a VPS that:
1. Logs into REI Master via browser automation.
2. Scrapes daily arrival/departure reports (CSV/PDF).
3. Sends these reports to cleaners via email (using Comms API).
4. Sends failure alerts via SMS/Telegram.

**Tech Stack:**
- Python 3.11 + Playwright (headless Chrome)
- Runs on a VPS (always-on, can maintain browser sessions)
- Uses Comms API (`/api/integrations/v1/send`) for email delivery

### What We Can Extract from REI Master
| Field | Available? | Notes |
|-------|------------|-------|
| Booking Reference | ✅ | Unique ID per booking |
| Guest Name | ✅ | |
| Room/Property | ✅ | |
| Check-in Date | ✅ | |
| Check-out Date | ✅ | |
| Number of Guests | ✅ | Adults, children, infants |
| Guest Phone | ⚠️ | Likely available in detailed booking view |
| Guest Email | ⚠️ | Likely available in detailed booking view |
| Total Amount | ⚠️ | Likely available in financial reports |
| Amount Paid | ⚠️ | Likely available in financial reports |

*Note: We've only scraped the cleaning reports so far. Deeper scraping for guest contact info and financials is feasible but not yet implemented.*

---

## Proposed Integration: Automated Deposit Requests

### Use Case
When a guest books a stay, we want to:
1. Automatically send a **50% deposit request** via SMS/Email.
2. The message should include:
   - Deposit amount
   - Stay dates
   - Payment deadline (28 days before check-in)
   - A Stripe Payment Link
3. Track whether the deposit was: **Sent → Opened → Paid → Overdue**

### Why Stripe?
- Stripe supports **Payment Links** (no-code, shareable URLs).
- Stripe supports **Afterpay** and **Zip** (BNPL) in Australia.
- Stripe provides **webhooks** for real-time payment status updates.
- Stripe Dashboard shows **view counts** on Payment Links (limited but useful).

### Fee Handling (Important!)
Stripe and BNPL providers charge different fees:
| Method | Approx. Fee |
|--------|-------------|
| Stripe (Domestic Card) | 1.75% + $0.30 |
| Afterpay | 4–6% + $0.30 |
| Zip | ~5% (varies) |

**Stripe does NOT automatically "gross up" fees.** If we want to pass fees to the guest, we must calculate the adjusted amount ourselves before creating the Payment Link. Australian law (ACCC) allows surcharging only the *actual cost* of acceptance.

**Open Question:** Should we absorb fees, pass them on (with different amounts per method), or charge a flat "admin fee"?

---

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   VPS (Python + Playwright)                  │
│                     "The Scraper / Worker"                   │
├─────────────────────────────────────────────────────────────┤
│  - Logs into REI Master via Playwright                       │
│  - Scrapes booking data (guest info, amounts, dates)         │
│  - Pushes new/updated bookings to Comms Platform via API     │
│  - Runs on a schedule (e.g., every hour or daily)            │
└─────────────────────────────────────────────────────────────┘
                              │
                         PUSH (HTTP POST)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Comms Platform (CF Workers + Neon)           │
│                   "Source of Truth + Messaging"              │
├─────────────────────────────────────────────────────────────┤
│  DATA LAYER (Neon):                                          │
│    - properties                                              │
│    - bookings                                                │
│    - deposits (linked to bookings)                           │
│    - communications (audit log of all messages sent)         │
│                                                              │
│  API LAYER:                                                  │
│    POST /api/bookings/upsert   ← VPS pushes booking data     │
│    POST /api/deposits/create   ← Create Stripe link          │
│    POST /api/deposits/:id/send ← Send deposit request        │
│    POST /webhooks/stripe       ← Receive payment events      │
│                                                              │
│  BUSINESS LOGIC:                                             │
│    - On new booking → schedule deposit request               │
│    - On deposit due → send SMS/email                         │
│    - On Stripe webhook → update deposit status               │
│                                                              │
│  STAFF UI:                                                   │
│    - View bookings by property                               │
│    - View deposit status (pending, sent, paid, overdue)      │
│    - Manually resend messages                                │
│    - FAQ / guest communication features                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                         ┌─────────┐
                         │  Stripe │
                         │   API   │
                         └─────────┘
```

### Why Push (VPS → Comms) Instead of Pull?
- VPS knows exactly when it has new data after a scrape.
- Comms Platform (CF Workers) cannot initiate connections to the VPS.
- Push is lower latency and avoids wasteful polling.

---

## Suggested Data Model (Comms Platform)

### `properties`
| Column | Type | Notes |
|--------|------|-------|
| id | TEXT (PK) | e.g., "paradise-stayz" |
| name | TEXT | "Paradise Stayz" |
| timezone | TEXT | "Australia/Sydney" |

### `bookings`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID (PK) | Auto-generated |
| external_id | TEXT (UNIQUE) | REI booking ref |
| property_id | TEXT (FK) | Links to properties |
| guest_name | TEXT | |
| guest_phone | TEXT | E.164 format |
| guest_email | TEXT | |
| check_in | DATE | |
| check_out | DATE | |
| total_amount_cents | INTEGER | In cents |
| source | TEXT | "reimaster", "airbnb", "bookingcom" |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### `deposits`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID (PK) | |
| booking_id | UUID (FK) | Links to bookings |
| amount_cents | INTEGER | 50% of total |
| due_date | DATE | 28 days before check-in |
| stripe_payment_link_id | TEXT | Stripe's plink_xxx ID |
| stripe_payment_link_url | TEXT | Shareable URL |
| sent_at | TIMESTAMP | When SMS/email was sent |
| paid_at | TIMESTAMP | When Stripe confirmed payment |
| status | TEXT | pending, sent, paid, overdue |

### `communications`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID (PK) | |
| booking_id | UUID (FK) | |
| channel | TEXT | sms, email, whatsapp |
| template | TEXT | deposit_request, reminder, etc. |
| sent_at | TIMESTAMP | |
| status | TEXT | sent, delivered, failed |
| payload | JSONB | Raw message for audit |

---

## Example API Contract

### `POST /api/bookings/upsert`
VPS calls this after scraping REI Master.

**Request:**
```json
{
  "external_id": "REI-12345",
  "property_id": "paradise-stayz",
  "guest_name": "John Doe",
  "guest_phone": "+61412345678",
  "guest_email": "john@example.com",
  "check_in": "2026-02-15",
  "check_out": "2026-02-18",
  "total_amount_cents": 150000,
  "source": "reimaster"
}
```

**Response:**
```json
{
  "success": true,
  "booking_id": "uuid-xxx",
  "created": false,
  "updated": true
}
```

### `POST /webhooks/stripe`
Stripe calls this when a payment is completed.

**Event:** `checkout.session.completed`

Comms Platform should:
1. Look up the deposit by `stripe_payment_link_id` or `client_reference_id`.
2. Set `paid_at = now()`, `status = 'paid'`.
3. Optionally send a "Thank you, payment received" confirmation.

---

## Open Questions for Discussion

### 1. Does Comms Platform already have a bookings table?
If so, we should extend it rather than create a parallel structure.

### 2. Where should Stripe Payment Link creation live?
- **Option A:** Comms Platform creates the link (CF Workers can call Stripe API).
- **Option B:** VPS creates the link and pushes the URL to Comms.

*Recommendation: Option A keeps Stripe credentials centralized in Comms.*

### 3. How should deposits be triggered?
- Automatically when a booking is pushed (if check-in > 28 days away)?
- Manually by staff in the UI?
- By a scheduled job (e.g., nightly cron)?

### 4. Should Comms Platform hold Stripe API keys?
This would require storing `STRIPE_SECRET_KEY` as a secret in Cloudflare Workers.

### 5. What about "link viewed" tracking?
Stripe tracks Payment Link views in the Dashboard but doesn't fire a webhook for it. If we want this data, we'd need to periodically poll the Stripe API.

### 6. SMS/Telegram permissions
Our current Comms API integration key has SMS/Telegram restricted. Do we need to enable these channels for deposit notifications?

---

## Next Steps

1. **Comms Team:** Review this proposal and provide feedback on feasibility.
2. **Confirm existing schema:** Does Comms already have properties/bookings tables?
3. **Agree on API contract:** Finalize the `/api/bookings/upsert` shape.
4. **Stripe setup:** Decide who holds API keys and webhook secrets.
5. **Prototype:** VPS pushes a test booking → Comms creates deposit → Staff sees it in UI.

---

## Contact

For questions about the VPS automation or REI Master scraping, contact Victor.

# Comms Platform Integration — Paradise Stayz Response

**To:** Comms Platform Team  
**From:** Paradise Stayz (Victor)  
**Date:** 5 January 2026  
**Re:** Response to Integration Proposal

---

## Summary

Thank you for the thorough response. We're aligned on the approach and excited to proceed. Below are a few clarifications and one additional API request.

---

## Responses & Confirmations

### 1. Property Mapping — API Request

Rather than manually copying UUIDs from the Admin UI, we'd prefer to fetch properties programmatically. Could you expose an endpoint like:

```
GET /api/integrations/v1/properties
```

**Response:**
```json
{
  "properties": [
    { "id": "uuid-xxx", "name": "Unit 1 - Paradise Beach", "timezone": "Australia/Sydney" },
    { "id": "uuid-yyy", "name": "Unit 2 - Sunset Villa", "timezone": "Australia/Sydney" }
  ]
}
```

This allows the VPS to:
- Fetch property UUIDs on startup
- Match REI Master property names to Comms Platform UUIDs dynamically
- Handle new properties without manual config updates

If property names don't match exactly between systems, we can maintain a simple alias mapping on our end.

---

### 2. Deposit Settings — Confirmed

Per-company settings for deposit percentage (50%) and deadline (28 days) are sufficient for our needs. No per-property configuration required at this stage.

---

### 3. Stripe Credentials — Acknowledged

We'll have both test and live Stripe API keys ready for the Admin UI onboarding.

---

### 4. `external_id` Uniqueness — Confirmed

REI Master booking references are unique across our account. We'll use these directly as `external_id` values.

---

### 5. Timezone Handling — Acknowledged

We'll ensure all `check_in` and `check_out` values include timezone offset in ISO 8601 format (e.g., `2026-02-15T15:00:00+11:00`).

---

## Important: Payment Link Analytics

> [!IMPORTANT]
> **We'd like to emphasise the importance of Payment Link view tracking for Phase 2.**

Understanding guest engagement with deposit requests is critical for our operations:

| Metric | Business Value |
|--------|----------------|
| **Link opened but not paid** | Indicates intent — guest saw it but hesitated. Triggers softer follow-up. |
| **Link never opened** | May indicate wrong contact info, spam filters, or disengagement. Triggers different intervention (phone call?). |
| **Time from send to open** | Helps optimise send timing (morning vs evening, weekday vs weekend). |
| **Open-to-pay conversion rate** | Measures effectiveness of payment page and messaging. |

**Our preferred implementation:**

1. **Stripe provides view counts** on Payment Links via the API (`payment_link.retrieve()`).
2. A **nightly polling job** on Comms Platform could update `deposits.view_count` or `deposits.first_viewed_at`.
3. Staff UI shows: `Sent → Viewed (3x) → Paid` for complete visibility.

This data directly impacts our follow-up strategy. A guest who opened 5 times but didn't pay needs a different nudge than one who never opened at all.

**Request:** Please consider including this in the Phase 2 roadmap with priority, even if it ships after the initial integration.

---

## Summary of Action Items

| Item | Owner | Status |
|------|-------|--------|
| Expose `/api/integrations/v1/properties` endpoint | Comms Team | **Requested** |
| Schema changes + `/stays/upsert` endpoint | Comms Team | Proceeding |
| Payment Link view tracking (Phase 2) | Comms Team | **Priority requested** |
| Stripe credentials ready | Paradise Stayz | Ready when needed |
| VPS scraper extension (phone, email, amount) | Paradise Stayz | Will begin after Step 3 |

---

## Next Steps

We're ready to proceed with the outlined timeline. Please confirm:

1. Feasibility of the `/properties` listing endpoint
2. Phase 2 priority for Payment Link analytics

Looking forward to the technical sync.

— **Victor, Paradise Stayz**

import tempfile
import unittest
from pathlib import Path

from guest_review_requests import (
    ReviewRequestStore,
    build_prepare_candidate,
    normalize_phone,
    parse_name_and_phone,
    render_message,
)


class GuestReviewRequestTests(unittest.TestCase):
    def test_normalize_phone_converts_mobile_to_e164(self) -> None:
        normalized, error = normalize_phone("0425 287 828")
        self.assertEqual(normalized, "+61425287828")
        self.assertIsNone(error)

    def test_parse_name_and_phone_supports_reversible_order_and_newlines(self) -> None:
        self.assertEqual(
            parse_name_and_phone("Min 0425287828"),
            ("Min", "0425287828"),
        )
        self.assertEqual(
            parse_name_and_phone("0425287828 Min"),
            ("Min", "0425287828"),
        )
        self.assertEqual(
            parse_name_and_phone("Min\n\n0425 287 828"),
            ("Min", "0425 287 828"),
        )

    def test_render_message_supports_single_and_double_brace_tokens(self) -> None:
        payload = {"guest_name": "Min"}
        self.assertEqual(
            render_message("Hi {guest_name}", payload),
            "Hi Min",
        )
        self.assertEqual(
            render_message("Hi {{guest_name}}", payload),
            "Hi Min",
        )

    def test_prepare_export_and_mark_sent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "guest_review_requests.sqlite3"
            store = ReviewRequestStore(db_path)
            try:
                candidate = build_prepare_candidate(
                    raw_row={
                        "booking_ref": "REI-999",
                        "guest_name": "Min",
                        "guest_phone": "0425287828",
                        "message_body": "Hi {guest_name}.",
                    },
                    rule_key="REVIEW_REQUEST",
                    template_key="guest_review_request_v1",
                    template_text=None,
                )
                outcome = store.prepare_request(candidate, actor="test")
                self.assertEqual(outcome, "queued")

                rows = store.export_requests(status="pending_send", actor="test")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["guest_phone_e164"], "+61425287828")
                self.assertEqual(
                    rows[0]["message_body"],
                    "Hi Min.",
                )

                sent_row = store.mark_sent(
                    request_id=rows[0]["id"],
                    actor="test",
                    provider="integration_api",
                    provider_message_id="msg_123",
                )
                self.assertEqual(sent_row["status"], "sent")

                duplicate_outcome = store.prepare_request(candidate, actor="test")
                self.assertEqual(duplicate_outcome, "already_sent")
            finally:
                store.close()

    def test_dedupe_is_phone_only(self) -> None:
        candidate_a = build_prepare_candidate(
            raw_row={
                "guest_name": "Min",
                "guest_phone": "0425287828",
                "message_body": "Hi {guest_name}",
            },
            rule_key="REVIEW_REQUEST",
            template_key="guest_review_request_v1",
            template_text=None,
        )
        candidate_b = build_prepare_candidate(
            raw_row={
                "guest_name": "Min",
                "guest_phone": "0425287828",
                "message_body": "Completely different body",
            },
            rule_key="REVIEW_REQUEST",
            template_key="guest_review_request_v1",
            template_text=None,
        )
        self.assertEqual(candidate_a["dedupe_key"], candidate_b["dedupe_key"])


if __name__ == "__main__":
    unittest.main()

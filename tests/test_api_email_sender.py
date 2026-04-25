import unittest
from unittest.mock import patch

import api_email_sender


class ApiEmailSenderProviderTests(unittest.TestCase):
    def test_email_provider_default_ignores_stale_module_snapshot(self) -> None:
        with patch.dict(api_email_sender.os.environ, {}, clear=True):
            with patch.object(api_email_sender, "EMAIL_PROVIDER", "comms"):
                with patch.object(api_email_sender, "send_email_via_resend", return_value=False) as resend:
                    with patch.object(api_email_sender, "send_email_via_comms_centre", return_value=True) as comms:
                        result = api_email_sender.send_email_message(
                            "Subject",
                            "Text body",
                            "<p>HTML body</p>",
                            [],
                        )

        self.assertTrue(result)
        resend.assert_called_once()
        comms.assert_called_once()

    def test_explicit_comms_provider_skips_resend(self) -> None:
        with patch.dict(api_email_sender.os.environ, {"EMAIL_PROVIDER": "comms"}, clear=True):
            with patch.object(api_email_sender, "send_email_via_resend") as resend:
                with patch.object(api_email_sender, "send_email_via_comms_centre", return_value=True) as comms:
                    result = api_email_sender.send_email_message(
                        "Subject",
                        "Text body",
                        "<p>HTML body</p>",
                        [],
                    )

        self.assertTrue(result)
        resend.assert_not_called()
        comms.assert_called_once()

    def test_default_alert_providers_include_brrr_and_comms(self) -> None:
        with patch.dict(api_email_sender.os.environ, {}, clear=True):
            self.assertEqual(api_email_sender.selected_alert_providers(), ["brrr", "comms"])

    def test_send_ops_notification_via_ntfy_uses_info_severity(self) -> None:
        mock_client = unittest.mock.Mock()
        mock_client.send_alert.return_value = unittest.mock.Mock(
            success=True,
            error=None,
            status_code=200,
            response_text="",
        )

        with patch.object(api_email_sender, "build_ntfy_alert_client", return_value=mock_client):
            result = api_email_sender.send_ops_notification_via_ntfy("Automation is Live", "System initialized and ready.")

        self.assertTrue(result)
        mock_client.send_alert.assert_called_once_with(
            title="Automation is Live",
            body="System initialized and ready.",
            severity="info",
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()

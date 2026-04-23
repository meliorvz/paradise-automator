import unittest
from unittest.mock import patch

from comms_client import BrrrAlertClient, BrrrAlertConfig, ResendEmailClient, ResendEmailConfig


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="OK"):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = {"content-type": "application/json"}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.posts = []
        self.gets = []
        self.closed = False

    def mount(self, *args, **kwargs):
        return None

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({
            "url": url,
            "json": json,
            "headers": headers,
            "timeout": timeout,
        })
        return self.response

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append({
            "url": url,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        })
        return self.response

    def close(self):
        self.closed = True


class CommsClientTests(unittest.TestCase):
    def test_resend_email_client_maps_payload(self) -> None:
        fake_session = FakeSession(FakeResponse(status_code=200, payload={"id": "email_123"}))
        client = ResendEmailClient(
            ResendEmailConfig(
                api_url="https://api.resend.com/emails",
                api_key="re_test",
                from_email="Paradise Stayz Updates <reports@updates.paradisestayz.com.au>",
                reply_to="vip@paradisestayz.com.au",
            )
        )

        with patch("comms_client.requests.Session", return_value=fake_session):
            result = client.send_email(
                subject="Daily Cleaning",
                text="Plain body",
                html="<p>HTML body</p>",
                to=["cleaner@example.com"],
                cc=["manager@example.com"],
                attachments=[{"filename": "arrivals.pdf", "content": "abc123"}],
            )

        self.assertTrue(result.success)
        self.assertEqual(fake_session.posts[0]["url"], "https://api.resend.com/emails")
        self.assertEqual(fake_session.posts[0]["headers"]["Authorization"], "Bearer re_test")
        payload = fake_session.posts[0]["json"]
        self.assertEqual(payload["from"], "Paradise Stayz Updates <reports@updates.paradisestayz.com.au>")
        self.assertEqual(payload["to"], ["cleaner@example.com"])
        self.assertEqual(payload["cc"], ["manager@example.com"])
        self.assertEqual(payload["reply_to"], "vip@paradisestayz.com.au")
        self.assertEqual(payload["attachments"], [{"filename": "arrivals.pdf", "content": "abc123"}])
        self.assertTrue(fake_session.closed)

    def test_resend_email_client_requires_api_key(self) -> None:
        client = ResendEmailClient(
            ResendEmailConfig(
                api_url="https://api.resend.com/emails",
                api_key="",
                from_email="reports@updates.paradisestayz.com.au",
            )
        )

        result = client.send_email(
            subject="Daily Cleaning",
            text="Plain body",
            html="<p>HTML body</p>",
            to=["cleaner@example.com"],
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "RESEND_API_KEY is not configured")

    def test_brrr_alert_client_posts_webhook_payload(self) -> None:
        fake_session = FakeSession(FakeResponse(status_code=204, payload=None, text=""))
        client = BrrrAlertClient(
            BrrrAlertConfig(
                webhook_url="https://brrr.example/webhook",
                webhook_secret="",
                method="POST",
                title_prefix="[Paradise] ",
                thread_id="paradise-automator",
                interruption_level="time-sensitive",
                sound="",
                open_url="",
            )
        )

        with patch("comms_client.requests.Session", return_value=fake_session):
            result = client.send_alert(
                title="REI Automation Failed",
                body="Daily run missed deadline",
                severity="error",
            )

        self.assertTrue(result.success)
        self.assertEqual(fake_session.posts[0]["url"], "https://brrr.example/webhook")
        self.assertEqual(fake_session.posts[0]["headers"]["Content-Type"], "application/json")
        payload = fake_session.posts[0]["json"]
        self.assertEqual(payload["title"], "[Paradise] REI Automation Failed")
        self.assertEqual(payload["message"], "Daily run missed deadline")
        self.assertEqual(payload["severity"], "error")
        self.assertEqual(payload["thread_id"], "paradise-automator")
        self.assertEqual(payload["interruption_level"], "time-sensitive")
        self.assertTrue(fake_session.closed)


if __name__ == "__main__":
    unittest.main()

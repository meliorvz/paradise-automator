import importlib.util
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "rei_cloud_automation.py"


class FakeLocator:
    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    def count(self):
        return 1 if self._page.is_selector_visible(self._selector) else 0

    @property
    def first(self):
        return self

    def is_visible(self):
        return self._page.is_selector_visible(self._selector)

    def text_content(self):
        return self._page.selector_text.get(self._selector, "")

    def click(self, force=False):
        self._page.click_calls.append((self._selector, force))


class FakePage:
    def __init__(self, state="login"):
        self.state = state
        self.authenticated = state in {"dashboard", "report_list"}
        self.url = (
            "https://app.reimasterapps.com.au/Customers/Dashboard?reicid=758"
            if state == "dashboard"
            else "https://app.reimasterapps.com.au/report/reportlist?reicid=758"
            if state == "report_list"
            else "https://login.example.com/"
        )
        self.goto_calls = []
        self.wait_calls = []
        self.click_calls = []
        self.selector_text = {
            "text=Dashboard": "Dashboard",
            "text=Arrival Report": "Arrival Report",
            "text=Departure Report": "Departure Report",
            "input#email": "",
            "input#password": "",
            "button#next": "Sign in",
        }

    def is_selector_visible(self, selector):
        if self.state == "login":
            return selector in {"input#email", "input#password", "button#next"}
        if self.state == "dashboard":
            return selector == "text=Dashboard"
        if self.state == "report_list":
            return selector in {"text=Arrival Report", "text=Departure Report"}
        return False

    def goto(self, url, timeout=None):
        self.goto_calls.append((url, timeout))
        self.url = url
        if url.endswith("/Customers/Dashboard?reicid=758"):
            self.state = "dashboard" if self.authenticated else "login"
        elif "report/reportlist" in url:
            self.state = "report_list" if self.authenticated else "login"

    def wait_for_timeout(self, ms):
        self.wait_calls.append(ms)

    def wait_for_selector(self, selector, state=None, timeout=None):
        if not self.is_selector_visible(selector):
            raise RuntimeError(f"selector not visible: {selector}")

    def locator(self, selector):
        return FakeLocator(self, selector)

    def content(self):
        if self.state == "login":
            return "<html><body>Member Login Email Address Password</body></html>"
        if self.state == "dashboard":
            return "<html><body>Dashboard</body></html>"
        if self.state == "report_list":
            return "<html><body>Arrival Report Departure Report</body></html>"
        return "<html><body></body></html>"

    def click(self, selector, timeout=None, force=False):
        self.click_calls.append((selector, force))

    def evaluate(self, script):
        return None

    def expect_download(self):
        raise AssertionError("unexpected download in unit test")

    def expect_page(self):
        raise AssertionError("unexpected page popup in unit test")

    def screenshot(self, path):
        return None


def install_stub_modules(include_future_window=True):
    schedule = types.ModuleType("schedule")
    schedule.every = lambda *args, **kwargs: types.SimpleNamespace(
        minutes=types.SimpleNamespace(do=lambda *a, **k: None),
        day=types.SimpleNamespace(at=lambda *a, **k: types.SimpleNamespace(do=lambda *a2, **k2: None)),
        saturday=types.SimpleNamespace(at=lambda *a, **k: types.SimpleNamespace(do=lambda *a2, **k2: None)),
    )
    schedule.run_pending = lambda: None
    sys.modules["schedule"] = schedule

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv

    playwright = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: types.SimpleNamespace(start=lambda: types.SimpleNamespace(
        chromium=types.SimpleNamespace(launch_persistent_context=lambda **kwargs: types.SimpleNamespace(
            pages=[],
            new_page=lambda: None,
        ))
    ))
    sys.modules["playwright"] = playwright
    sys.modules["playwright.sync_api"] = sync_api

    booking = types.ModuleType("booking_data_extractor")
    booking.run_daily_maintenance = lambda *args, **kwargs: None
    if include_future_window:
        booking.run_future_window = lambda *args, **kwargs: None
    booking.run_historical = lambda *args, **kwargs: None
    sys.modules["booking_data_extractor"] = booking

    pytz = types.ModuleType("pytz")

    class FakeTZ:
        def __init__(self, name, hours):
            self.name = name
            self.hours = hours

        def utcoffset(self, dt):
            from datetime import timedelta

            return timedelta(hours=self.hours)

        def dst(self, dt):
            from datetime import timedelta

            return timedelta(0)

        def tzname(self, dt):
            return self.name

        def localize(self, dt):
            return dt.replace(tzinfo=self)

    pytz.UTC = FakeTZ("UTC", 0)
    pytz.timezone = lambda name: FakeTZ(name, 10)
    sys.modules["pytz"] = pytz


def load_module(include_future_window=True):
    install_stub_modules(include_future_window=include_future_window)
    sys.modules.pop("rei_cloud_automation_under_test", None)
    logging.shutdown()
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    temp_dir = tempfile.TemporaryDirectory()
    cwd = os.getcwd()
    os.chdir(temp_dir.name)

    spec = importlib.util.spec_from_file_location("rei_cloud_automation_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rei_cloud_automation_under_test"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)

    module._test_temp_dir = temp_dir
    return module


class ReiCloudAutomationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.addCleanup(lambda: self.module._test_temp_dir.cleanup())
        self.addCleanup(logging.shutdown)

    def test_page_predicates_distinguish_login_dashboard_and_report_list(self):
        login_page = FakePage("login")
        dashboard_page = FakePage("dashboard")
        report_page = FakePage("report_list")

        self.assertTrue(self.module.page_is_login_page(login_page))
        self.assertFalse(self.module.page_is_dashboard_ready(login_page))
        self.assertFalse(self.module.page_is_report_list_ready(login_page))

        self.assertTrue(self.module.page_is_dashboard_ready(dashboard_page))
        self.assertTrue(self.module.page_is_authenticated_session(dashboard_page))

        self.assertTrue(self.module.page_is_report_list_ready(report_page))
        self.assertTrue(self.module.page_is_authenticated_session(report_page))

    def test_missing_future_window_does_not_disable_existing_extractors(self):
        module = load_module(include_future_window=False)
        self.addCleanup(lambda: module._test_temp_dir.cleanup())

        self.assertNotEqual(module.run_booking_maintenance.__name__, "_missing")
        self.assertNotEqual(module.run_booking_historical.__name__, "_missing")
        self.assertEqual(module.run_booking_future_window.__name__, "_missing")

    def test_recover_session_with_fresh_context_targets_report_list(self):
        self.module.REI_USERNAME = "victor@example.com"
        self.module.REI_PASSWORD = "secret"

        close_calls = []

        def close_stub():
            close_calls.append(True)

        def launch_stub():
            self.module.page = FakePage("login")
            self.module.context = object()
            self.module.browser = object()
            self.module.playwright_instance = object()

        def auto_login_stub():
            self.module.page.authenticated = True
            self.module.page.state = "dashboard"
            self.module.page.url = self.module.REI_CLOUD_URL
            return True

        self.module.close_browser_context = close_stub
        self.module.launch_browser_context = launch_stub
        self.module.auto_login = auto_login_stub

        result = self.module.recover_session_with_fresh_context(
            "unit test",
            target="report_list",
            report_label="Arrival Report",
        )

        self.assertTrue(result)
        self.assertEqual(close_calls, [True])
        self.assertEqual(self.module.page.state, "report_list")
        self.assertEqual(self.module.page.goto_calls[-1][0], self.module.REPORT_LIST_URL)

    def test_ensure_report_list_ready_retries_through_fresh_context(self):
        self.module.page = FakePage("dashboard")

        recovery_calls = []

        def ensure_dashboard_stub(*args, **kwargs):
            return True

        def report_ready_stub(target_page, report_label="Arrival Report"):
            return len(recovery_calls) > 0

        def recover_stub(reason, target="dashboard", report_label="Arrival Report"):
            recovery_calls.append((reason, target, report_label))
            self.module.page = FakePage("report_list")
            return True

        self.module.ensure_dashboard_ready = ensure_dashboard_stub
        self.module.page_is_report_list_ready = report_ready_stub
        self.module.recover_session_with_fresh_context = recover_stub

        self.assertTrue(self.module.ensure_report_list_ready(recovery_reason="unit test"))
        self.assertEqual(len(recovery_calls), 1)
        self.assertEqual(recovery_calls[0][1], "report_list")


if __name__ == "__main__":
    unittest.main()

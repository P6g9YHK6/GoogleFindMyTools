import logging
import threading

from webui import notify


class FakeApprise:
    def __init__(self):
        self.added = []
        self.notifications = []
        self.reject = set()

    def add(self, url):
        if url in self.reject:
            return False
        self.added.append(url)
        return True

    def notify(self, title, body):
        self.notifications.append((title, body))


def _remove(handler):
    if handler is not None:
        logging.getLogger().removeHandler(handler)


def test_configure_is_a_noop_without_apprise_urls():
    assert notify.configure_apprise_logging(env={}) is None
    assert notify.configure_apprise_logging(env={"APPRISE_URLS": "   "}) is None


def test_configure_installs_a_handler_on_the_root_logger(monkeypatch):
    fake = FakeApprise()
    monkeypatch.setattr(notify.apprise, "Apprise", lambda: fake)

    handler = notify.configure_apprise_logging(env={"APPRISE_URLS": "json://example.com/hook"})
    try:
        assert handler is not None
        assert fake.added == ["json://example.com/hook"]
        assert handler.level == logging.WARNING  # the default
        assert handler in logging.getLogger().handlers
    finally:
        _remove(handler)


def test_configure_catches_a_logger_outside_the_webui_tree(monkeypatch):
    """The whole point of attaching to root: a logger under a completely
    different tree (e.g. Auth.fcm_receiver) must still reach Apprise."""
    fake = FakeApprise()
    monkeypatch.setattr(notify.apprise, "Apprise", lambda: fake)

    handler = notify.configure_apprise_logging(env={"APPRISE_URLS": "json://example.com/hook"})
    try:
        threads_before = set(threading.enumerate())
        logging.getLogger("Auth.fcm_receiver").warning("push client crashed")
        for t in set(threading.enumerate()) - threads_before:
            t.join(timeout=2)
        assert any("push client crashed" in body for _, body in fake.notifications)
    finally:
        _remove(handler)


def test_configure_parses_multiple_urls_and_a_custom_level(monkeypatch):
    fake = FakeApprise()
    monkeypatch.setattr(notify.apprise, "Apprise", lambda: fake)

    handler = notify.configure_apprise_logging(env={
        "APPRISE_URLS": "json://a.example.com/hook,json://b.example.com/hook",
        "APPRISE_NOTIFY_LEVEL": "error",
    })
    try:
        assert fake.added == ["json://a.example.com/hook", "json://b.example.com/hook"]
        assert handler.level == logging.ERROR
    finally:
        _remove(handler)


def test_configure_falls_back_to_warning_for_an_unknown_level(monkeypatch):
    fake = FakeApprise()
    monkeypatch.setattr(notify.apprise, "Apprise", lambda: fake)

    handler = notify.configure_apprise_logging(env={
        "APPRISE_URLS": "json://example.com/hook",
        "APPRISE_NOTIFY_LEVEL": "not-a-real-level",
    })
    try:
        assert handler.level == logging.WARNING
    finally:
        _remove(handler)


def test_emit_sends_the_formatted_record_through_apprise_in_the_background():
    fake = FakeApprise()
    handler = notify._AppriseLogHandler(fake, logging.WARNING)
    handler.setFormatter(logging.Formatter("%(message)s"))

    record = logging.LogRecord(
        name="webui.scheduler", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="Locate failed for %s: %s", args=("My Tracker", "boom"), exc_info=None,
    )

    threads_before = set(threading.enumerate())
    handler.emit(record)
    for t in set(threading.enumerate()) - threads_before:
        t.join(timeout=2)

    assert fake.notifications == [("GoogleFindMyToolsWebUi: WARNING", "Locate failed for My Tracker: boom")]

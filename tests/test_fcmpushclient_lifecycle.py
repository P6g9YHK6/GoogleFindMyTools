import Auth.firebase_messaging.fcmpushclient as fcmpushclient_module
from Auth.firebase_messaging.fcmpushclient import FcmPushClient, FcmRegisterConfig


def _make_client() -> FcmPushClient:
    config = FcmRegisterConfig(
        project_id="proj", app_id="app", api_key="key", messaging_sender_id="sender",
    )
    return FcmPushClient(callback=lambda *a: None, fcm_config=config, credentials=None)


async def test_stop_before_start_does_not_raise():
    """FcmReceiver._register_for_fcm calls pc.stop() from its except-handler
    when the very first checkin/registration attempt fails - i.e. before
    pc.start() has ever run. stop() used to do `async with self.stopping_lock`
    while that lock was still None (only created in start()), raising
    "'NoneType' object does not support the asynchronous context manager
    protocol" - which surfaced up through webui.scheduler as a baffling
    "Locate failed for <device>: 'NoneType' object does not support the
    asynchronous context manager protocol" warning."""
    client = _make_client()

    # Never called client.start() - reset_lock/stopping_lock must already be
    # usable locks, not None.
    await client.stop()


async def test_checkin_or_register_closes_session_even_on_failure(monkeypatch):
    """If FcmRegister.checkin_or_register() raises (e.g. gcm checkin
    exhausts its retries), the FcmRegister's own aiohttp session used to
    never get closed - checkin_or_register() awaited self.register.close()
    on the line right after the call that raised, so it was skipped
    entirely. That leaked ClientSession/TCPConnector, logged later by
    aiohttp as "Unclosed client session" / "Unclosed connector
    connections" once garbage collected."""
    client = _make_client()

    closed = []

    async def boom(self):
        raise RuntimeError("checkin failed")

    async def fake_close(self):
        closed.append(True)

    monkeypatch.setattr(
        fcmpushclient_module.FcmRegister, "checkin_or_register", boom
    )
    monkeypatch.setattr(fcmpushclient_module.FcmRegister, "close", fake_close)

    try:
        await client.checkin_or_register()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the simulated checkin failure to propagate")

    assert closed == [True], "FcmRegister.close() must run even when checkin_or_register() raises"

from Auth.firebase_messaging.fcmpushclient import FcmPushClient, FcmRegisterConfig
from Auth.firebase_messaging.proto.mcs_pb2 import AppData, DataMessageStanza


def _make_client(app_id: str) -> FcmPushClient:
    config = FcmRegisterConfig(
        project_id="proj", app_id="app", api_key="key", messaging_sender_id="sender",
    )
    credentials = {"gcm": {"app_id": app_id}}
    return FcmPushClient(callback=lambda *a: None, fcm_config=config, credentials=credentials)


def _stanza(subtype: str) -> DataMessageStanza:
    msg = DataMessageStanza()
    msg.app_data.append(AppData(key="subtype", value=subtype))
    msg.app_data.append(AppData(key="crypto-key", value="dh=not-real"))
    msg.app_data.append(AppData(key="encryption", value="salt=not-real"))
    return msg


def test_a_foreign_subtype_is_skipped_without_attempting_decryption(monkeypatch):
    client = _make_client(app_id="our-real-app-id")

    def boom(*args, **kwargs):
        raise AssertionError("must not attempt to decrypt a message meant for a different app")

    monkeypatch.setattr(FcmPushClient, "_decrypt_raw_data", staticmethod(boom))

    # Must not raise - this used to fall through to _decrypt_raw_data (and
    # crash the whole listener) even after warning that the message wasn't
    # ours.
    client._handle_data_message(_stanza(subtype="someone-elses-app-id"))


def test_a_matching_subtype_still_gets_decrypted(monkeypatch):
    client = _make_client(app_id="our-real-app-id")

    calls = []
    monkeypatch.setattr(
        FcmPushClient, "_decrypt_raw_data",
        staticmethod(lambda *a, **kw: calls.append(1) or b"{}"),
    )

    client._handle_data_message(_stanza(subtype="our-real-app-id"))
    assert calls == [1]

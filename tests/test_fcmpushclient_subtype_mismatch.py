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


def test_multi_param_headers_are_trimmed_to_just_the_value_we_want(monkeypatch):
    """Crypto-Key/Encryption can carry more than one ;-separated parameter
    (e.g. "dh=<point>;p256ecdsa=<other key>") - keeping the rest used to
    decode into one garbage-length blob (base64 silently drops the stray
    ";"/"=" from the second parameter instead of raising), which then failed
    EC point validation with a confusing "Invalid EC key" deep inside
    http_ece, instead of ever reaching real decryption."""
    client = _make_client(app_id="our-real-app-id")

    captured = {}

    def fake_decrypt(credentials, crypto_key, salt, raw_data):
        captured["crypto_key"] = crypto_key
        captured["salt"] = salt
        return b"{}"

    monkeypatch.setattr(FcmPushClient, "_decrypt_raw_data", staticmethod(fake_decrypt))

    msg = DataMessageStanza()
    msg.app_data.append(AppData(key="subtype", value="our-real-app-id"))
    msg.app_data.append(AppData(key="crypto-key", value="dh=REALDHVALUE;p256ecdsa=OTHERKEYVALUE"))
    msg.app_data.append(AppData(key="encryption", value="salt=REALSALTVALUE;anotherparam=x"))

    client._handle_data_message(msg)

    assert captured["crypto_key"] == "REALDHVALUE"
    assert captured["salt"] == "REALSALTVALUE"

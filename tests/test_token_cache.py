import json

import pytest

from Auth import token_cache


@pytest.fixture
def secrets_dir(tmp_path, monkeypatch):
    # _auth_store_path() reads the env fresh on every call, so no reload needed.
    monkeypatch.setenv("GFMT_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("GFMT_DATA_DIR", raising=False)
    return tmp_path


def test_set_and_get_round_trip(secrets_dir):
    assert token_cache.get_cached_value("username") is None
    token_cache.set_cached_value("username", "alice")
    assert token_cache.get_cached_value("username") == "alice"
    assert (secrets_dir / "auth.yaml").exists()


def test_get_cached_value_or_set_only_calls_the_generator_once(secrets_dir):
    calls = []

    def generator():
        calls.append(1)
        return "generated"

    assert token_cache.get_cached_value_or_set("aas_token", generator) == "generated"
    assert token_cache.get_cached_value_or_set("aas_token", generator) == "generated"
    assert len(calls) == 1


def test_get_cached_values_with_prefix(secrets_dir):
    token_cache.set_cached_value("shared_key_v1", "a")
    token_cache.set_cached_value("shared_key_v2", "b")
    token_cache.set_cached_value("owner_key", "c")

    assert token_cache.get_cached_values_with_prefix("shared_key_") == {
        "shared_key_v1": "a", "shared_key_v2": "b",
    }


def test_clear_all_cached_values(secrets_dir):
    token_cache.set_cached_value("username", "alice")
    token_cache.clear_all_cached_values()
    assert token_cache.get_cached_value("username") is None


def test_migrates_from_legacy_secrets_json(secrets_dir):
    (secrets_dir / "secrets.json").write_text(json.dumps({"username": "bob", "aas_token": "tok"}))

    assert token_cache.get_cached_value("username") == "bob"
    assert (secrets_dir / "auth.yaml").exists()
    assert (secrets_dir / "secrets.json").exists()  # left alone, not deleted

    # From here on, auth.yaml is authoritative - a stale/wiped legacy file
    # must not affect anything anymore.
    (secrets_dir / "secrets.json").write_text(json.dumps({}))
    assert token_cache.get_cached_value("aas_token") == "tok"


def test_falls_back_to_gfmt_data_dir_when_secrets_dir_is_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("GFMT_SECRETS_DIR", raising=False)
    monkeypatch.setenv("GFMT_DATA_DIR", str(tmp_path))

    token_cache.set_cached_value("username", "carol")
    assert (tmp_path / "auth.yaml").exists()


def test_set_cached_value_refuses_to_clobber_an_unparseable_file(secrets_dir):
    (secrets_dir / "auth.yaml").write_text("not: valid: yaml: [")
    with pytest.raises(Exception, match="Could not read secrets file"):
        token_cache.set_cached_value("username", "alice")


def test_values_are_plain_text_without_an_encryption_key(secrets_dir, monkeypatch):
    monkeypatch.delenv("SECRETS_ENCRYPTION_KEY", raising=False)
    token_cache.set_cached_value("username", "alice")
    assert "alice" in (secrets_dir / "auth.yaml").read_text()


def test_encryption_key_encrypts_values_at_rest_and_round_trips(secrets_dir, monkeypatch):
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "correct horse battery staple")

    token_cache.set_cached_value("username", "alice")
    raw = (secrets_dir / "auth.yaml").read_text()
    assert "alice" not in raw
    assert "gfmtenc1:" in raw

    assert token_cache.get_cached_value("username") == "alice"


def test_encryption_round_trips_nested_values(secrets_dir, monkeypatch):
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "a-key")

    fcm_credentials = {"gcm": {"android_id": 123, "security_token": "tok"}, "keys": {"private": "p"}}
    token_cache.set_cached_value("fcm_credentials", fcm_credentials)
    assert token_cache.get_cached_value("fcm_credentials") == fcm_credentials


def test_wrong_encryption_key_fails_closed_instead_of_crashing(secrets_dir, monkeypatch):
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "key-one")
    token_cache.set_cached_value("username", "alice")

    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "key-two")
    assert token_cache.get_cached_value("username") is None


def test_get_cached_values_with_prefix_decrypts_each_entry(secrets_dir, monkeypatch):
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "a-key")
    token_cache.set_cached_value("shared_key_v1", "a")
    token_cache.set_cached_value("shared_key_v2", "b")

    assert token_cache.get_cached_values_with_prefix("shared_key_") == {
        "shared_key_v1": "a", "shared_key_v2": "b",
    }


def test_migration_from_legacy_json_encrypts_when_a_key_is_set(secrets_dir, monkeypatch):
    (secrets_dir / "secrets.json").write_text(json.dumps({"username": "bob"}))
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "a-key")

    assert token_cache.get_cached_value("username") == "bob"
    assert "bob" not in (secrets_dir / "auth.yaml").read_text()


def test_warns_once_when_no_encryption_key_is_configured(secrets_dir, monkeypatch, caplog):
    monkeypatch.delenv("SECRETS_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(token_cache, "_warned_unencrypted", False)

    with caplog.at_level("WARNING", logger="Auth.token_cache"):
        token_cache.set_cached_value("username", "alice")
        token_cache.get_cached_value("username")

    warnings = [r for r in caplog.records if "plain text" in r.message]
    assert len(warnings) == 1  # only the first call logs it, not every call

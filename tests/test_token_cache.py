import json

import pytest

from Auth import token_cache


@pytest.fixture
def secrets_dir(tmp_path, monkeypatch):
    # _get_secrets_file() reads the env fresh on every call, so no reload needed.
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

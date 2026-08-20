"""Tests for webui/esp_idf_provisioning.py - cloning/installing ESP-IDF on
demand, independent of the build state machine built on top of it (see
tests/test_firmware.py). Follows tests/test_browser_stack.py's _FakeProc
style, extended with communicate()."""

import asyncio

import webui.esp_idf_provisioning as esp_idf_provisioning
from webui import config


class _FakeProc:
    """Stands in for an asyncio.subprocess.Process for _run_checked/get_env's
    communicate()-based calls."""

    def __init__(self, returncode=0, output=b""):
        self.returncode = returncode
        self._output = output

    async def communicate(self):
        return self._output, None

    async def wait(self):
        return self.returncode

    def kill(self):
        pass


def _patch_dirs(monkeypatch, tmp_path):
    idf_dir = tmp_path / "esp-idf"
    tools_dir = tmp_path / "esp-idf-tools"
    monkeypatch.setattr(config, "GFMT_ESP_IDF_DIR", idf_dir)
    monkeypatch.setattr(config, "GFMT_ESP_IDF_TOOLS_DIR", tools_dir)
    return idf_dir, tools_dir


def test_is_provisioned_false_when_marker_missing(monkeypatch, tmp_path):
    idf_dir, tools_dir = _patch_dirs(monkeypatch, tmp_path)
    (idf_dir / "tools").mkdir(parents=True)
    (idf_dir / "tools" / "idf.py").write_text("")
    tools_dir.mkdir()

    assert esp_idf_provisioning.is_provisioned() is False


def test_is_provisioned_true_when_marker_and_idf_py_present(monkeypatch, tmp_path):
    idf_dir, tools_dir = _patch_dirs(monkeypatch, tmp_path)
    (idf_dir / "tools").mkdir(parents=True)
    (idf_dir / "tools" / "idf.py").write_text("")
    tools_dir.mkdir()
    (tools_dir / ".gfmt-provisioned").write_text("")

    assert esp_idf_provisioning.is_provisioned() is True


async def test_provision_skips_clone_when_already_provisioned(monkeypatch, tmp_path):
    _patch_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(esp_idf_provisioning, "is_provisioned", lambda: True)

    async def fake_exec(*args, **kwargs):
        raise AssertionError("should never spawn a subprocess when already provisioned")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    events = []

    async def on_progress(phase, message, percent):
        events.append(phase)

    await esp_idf_provisioning.provision(on_progress=on_progress)

    assert events == ["provisioning"]


async def test_provision_clones_and_installs_when_missing(monkeypatch, tmp_path):
    idf_dir, tools_dir = _patch_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(esp_idf_provisioning, "is_provisioned", lambda: False)

    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return _FakeProc(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    events = []

    async def on_progress(phase, message, percent):
        events.append(phase)

    await esp_idf_provisioning.provision(on_progress=on_progress)

    assert events == ["cloning", "installing_toolchain", "provisioning"]
    assert calls[0][0] == "git"
    assert "clone" in calls[0]
    assert esp_idf_provisioning.IDF_BRANCH in calls[0]
    assert str(idf_dir) in calls[0]
    assert calls[1][0] == str(idf_dir / "install.sh")
    assert esp_idf_provisioning.IDF_TARGETS in calls[1]
    assert (tools_dir / ".gfmt-provisioned").exists()


async def test_provision_raises_and_leaves_no_marker_on_install_failure(monkeypatch, tmp_path):
    idf_dir, tools_dir = _patch_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(esp_idf_provisioning, "is_provisioned", lambda: False)

    async def fake_exec(*args, **kwargs):
        if args[0] == "git":
            return _FakeProc(0)
        return _FakeProc(1, output=b"install.sh: missing dependency")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    try:
        await esp_idf_provisioning.provision()
        raised = False
    except RuntimeError as e:
        raised = True
        assert "missing dependency" in str(e)

    assert raised
    assert not (tools_dir / ".gfmt-provisioned").exists()


async def test_get_env_parses_key_value_output(monkeypatch, tmp_path):
    _patch_dirs(monkeypatch, tmp_path)

    output = b'PATH="/fake/idf/tools:$PATH"\nIDF_PATH="/fake/idf"\n'

    async def fake_exec(*args, **kwargs):
        return _FakeProc(0, output=output)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    env = await esp_idf_provisioning.get_env()

    assert env["IDF_PATH"] == "/fake/idf"
    assert env["PATH"] == "/fake/idf/tools:$PATH"

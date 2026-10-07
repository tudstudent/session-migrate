"""Windows-specific filesystem branches; native Windows remains a separate gate."""

import os
import subprocess
from pathlib import Path

import pytest

from session_migrate import conversion, jsonl
from session_migrate.errors import JsonlError


def test_windows_directory_fsync_skips_both_helpers(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Windows directory open attempted")

    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "nt")
        patch.setattr(os, "open", unexpected)
        jsonl._fsync_directory(tmp_path)
        conversion._fsync_directory(tmp_path)


def test_failed_atomic_setup_closes_owned_descriptor(tmp_path, monkeypatch):
    seen = []

    def fail(descriptor, mode):
        seen.append(descriptor)
        raise OSError("failed setup")

    monkeypatch.setattr(os, "fchmod", fail, raising=False)
    with pytest.raises(JsonlError, match="failed setup"):
        jsonl.write_private_atomic(tmp_path / "file.json", b"{}\n")
    assert seen
    with pytest.raises(OSError):
        os.fstat(seen[0])
    assert not list(tmp_path.glob(".*.tmp"))


def test_native_manifest_and_export_descriptors_request_binary_mode(tmp_path, monkeypatch):
    original_open = os.open
    fake_binary = 1 << 29
    seen = []

    def recording_open(path, flags, *args, **kwargs):
        seen.append(flags)
        return original_open(path, flags & ~fake_binary, *args, **kwargs)

    monkeypatch.setattr(os, "O_BINARY", fake_binary, raising=False)
    monkeypatch.setattr(os, "open", recording_open)
    path = tmp_path / "manifest.json"
    path.write_bytes(b"{}\n")
    metadata = path.stat()
    fd = conversion._open_identity_guard(path, (metadata.st_dev, metadata.st_ino), writable=True)
    os.close(fd)
    monkeypatch.setattr(conversion, "_opencode_version", lambda *args: "2.0.23")

    def exported(command, **kwargs):
        os.write(kwargs["stdout"], b'{"info":{}}\n')
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", exported)
    conversion._invoke_opencode_export(
        Path("opencode.exe"), "ses_test", tmp_path / "export.json", {}
    )
    assert len(seen) == 2 and all(flags & fake_binary for flags in seen)

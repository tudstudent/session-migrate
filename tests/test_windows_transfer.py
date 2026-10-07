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


@pytest.mark.parametrize("failure", ["timeout", "oserror"])
def test_native_export_closes_descriptor_before_exception_cleanup(tmp_path, monkeypatch, failure):
    from session_migrate.errors import SessionMigrateError

    monkeypatch.setattr(conversion, "_opencode_version", lambda *args: "2.0.23")
    descriptor = None

    def failed_export(command, **kwargs):
        nonlocal descriptor
        descriptor = kwargs["stdout"]
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        raise OSError("export failed")

    monkeypatch.setattr(subprocess, "run", failed_export)
    original_unlink = os.unlink

    def windows_style_unlink(path, *args, **kwargs):
        assert descriptor is not None
        with pytest.raises(OSError):
            os.fstat(descriptor)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", windows_style_unlink)
    target = tmp_path / "failed-export.json"
    with pytest.raises(SessionMigrateError, match="CLI export failed"):
        conversion._invoke_opencode_export(Path("opencode.exe"), "ses_test", target, {})
    assert not target.exists()


@pytest.mark.parametrize("target", ["opencode", "kilo", "shared"])
@pytest.mark.parametrize("outcome", ["success", "import_failure", "finalization_failure"])
def test_manifest_guard_allows_windows_finalization_and_rollback(
    tmp_path, monkeypatch, target, outcome
):
    from session_migrate.conversion import ConversionOptions, convert_session, load_session
    from session_migrate.errors import SessionMigrateError
    from session_migrate.formats import kilo, opencode
    from session_migrate.model import AgentFormat, TargetFormat

    source = load_session(
        Path(__file__).parent / "fixtures/codex-0.144.4/basic.jsonl", AgentFormat.CODEX
    )
    format_ = {
        "opencode": TargetFormat.OPENCODE,
        "kilo": TargetFormat.KILO,
        "shared": TargetFormat.MUSE,
    }[target]
    artifact = convert_session(source, ConversionOptions(target_format=format_, cwd=tmp_path))
    manifest = tmp_path / "manifest.json"
    guard = None
    real_guard = conversion._open_identity_guard
    real_unlink = Path.unlink
    real_replace = os.replace
    operations = []

    def guarded(path, identity, **kwargs):
        nonlocal guard
        guard = real_guard(path, identity, **kwargs)
        return guard

    def deny_open_mutation(path):
        if Path(path) != manifest or guard is None:
            return
        try:
            os.fstat(guard)
        except OSError:
            return
        raise PermissionError(32, "Windows sharing violation", str(path))

    def unlink(path, *args, **kwargs):
        deny_open_mutation(path)
        if path == manifest:
            operations.append("unlink")
        return real_unlink(path, *args, **kwargs)

    def replace(src, dst, *args, **kwargs):
        deny_open_mutation(dst)
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(conversion, "_open_identity_guard", guarded)
    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(os, "replace", replace)

    def imported(*args, **kwargs):
        if outcome == "import_failure":
            raise SessionMigrateError("original import failure")
        return tmp_path / "database.db"

    if outcome == "finalization_failure":

        def failed_finalization(*args):
            raise JsonlError("original manifest write failure")

        monkeypatch.setattr(conversion, "_write_reserved_file", failed_finalization)

    cli = tmp_path / "native.exe"
    if target == "opencode":
        monkeypatch.setattr(conversion, "_resolve_opencode_cli", lambda *args: cli)
        monkeypatch.setattr(
            conversion, "_opencode_version", lambda *args: opencode.PINNED_OPENCODE_VERSION
        )
        states = iter([set(), set(), {artifact.session_id}])
        monkeypatch.setattr(conversion, "_opencode_session_ids", lambda *args: next(states))
        monkeypatch.setattr(conversion, "_invoke_opencode_import", imported)

        def install():
            return conversion.install_opencode_artifact(
                artifact, manifest_path=manifest, environ={}
            )
    elif target == "kilo":
        monkeypatch.setattr(conversion, "_resolve_kilo_cli", lambda *args: cli)
        monkeypatch.setattr(conversion, "_kilo_version", lambda *args: kilo.PINNED_KILO_VERSION)
        states = iter([False, False, True])
        monkeypatch.setattr(conversion, "_kilo_session_exists", lambda *args: next(states))
        monkeypatch.setattr(conversion, "_invoke_kilo_import", imported)

        def install():
            return conversion.install_kilo_artifact(artifact, manifest_path=manifest, environ={})
    else:
        monkeypatch.setattr(
            conversion, "shared_database_manifest_path", lambda *args, **kwargs: manifest
        )

        def install():
            return conversion._install_shared_database_artifact(
                artifact, target_home=tmp_path, installer=imported, dry_run=False
            )

    if outcome == "success":
        install()
        assert manifest.read_bytes()
        assert operations == []
    else:
        expected = (
            "original import failure"
            if outcome == "import_failure"
            else "manifest finalization failed"
        )
        with pytest.raises(SessionMigrateError, match=expected) as error:
            install()
        if outcome == "finalization_failure":
            assert isinstance(error.value.__cause__, JsonlError)
            assert "original manifest write failure" in str(error.value.__cause__)
        assert operations == ["unlink"]
        assert not manifest.exists()
    assert guard is not None
    with pytest.raises(OSError):
        os.fstat(guard)

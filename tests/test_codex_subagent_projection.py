"""Self-contained child rollouts preserve child data without replaying parent context."""

import copy
import json
from pathlib import Path

import pytest

from session_migrate.conversion import ConversionOptions, convert_session
from session_migrate.errors import SessionMigrateError
from session_migrate.formats import codex, opencode
from session_migrate.model import AgentFormat, EventKind, Role, TargetFormat

FIXTURE = Path(__file__).parent / "fixtures/codex-0.153.4/paginated.jsonl"
CHILD_ID = "60000000-0000-4000-8000-000000000001"
CHILD_PATH = "/root/child"


def records():
    original = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    primary = copy.deepcopy(original[0])
    primary["payload"].update(id=CHILD_ID, session_id=CHILD_ID, agent_path=CHILD_PATH, cwd="/child")
    inherited = copy.deepcopy(original[:8])
    inherited[0]["payload"]["history_mode"] = "legacy"
    inherited[7]["payload"]["call_id"] = "parent_call"
    inherited[7]["payload"]["arguments"] = '{"secret":"PARENT PRIVATE INPUT"}'
    primary["payload"]["subagent_history_start_ordinal"] = 1 + len(inherited)
    seed = {
        "type": "response_item",
        "timestamp": "2026-08-17T13:00:00Z",
        "payload": {
            "type": "agent_message",
            "id": "task_seed",
            "author": "/root",
            "recipient": CHILD_PATH,
            "content": [
                {"type": "input_text", "text": "Child task — λ\nkeep exact"},
                {"type": "encrypted_content", "encrypted_content": "PRIVATE CIPHERTEXT"},
            ],
        },
    }
    result = [primary, *inherited, seed, *copy.deepcopy(original[1:])]
    for ordinal, item in enumerate(result):
        item["ordinal"] = ordinal
    return result


def write(tmp_path, value):
    path = tmp_path / "child.jsonl"
    path.write_text("".join(json.dumps(item) + "\n" for item in value))
    return path


def test_child_metadata_plaintext_and_tool_image_linkage_roundtrip(tmp_path):
    value = records()
    session = codex.parse(write(tmp_path, value))
    start = value[0]["payload"]["subagent_history_start_ordinal"]
    assert session.session_id == CHILD_ID
    assert session.cwd == Path("/child")
    messages = [e for e in session.events if e.kind == EventKind.MESSAGE]
    assert messages[0].role == Role.USER
    assert messages[0].text == "Child task — λ\nkeep exact"
    assert messages[0].provenance.record_index == start
    calls = [e for e in session.events if e.kind == EventKind.TOOL_CALL]
    results = [e for e in session.events if e.kind == EventKind.TOOL_RESULT]
    assert [e.tool_call_id for e in calls] == ["call_fixture_1"]
    assert [e.tool_call_id for e in results] == ["call_fixture_1"]
    target = convert_session(
        session,
        ConversionOptions(
            target_format=TargetFormat.OPENCODE,
            target_cli_version="1.17.20",
            cwd=tmp_path,
            model_provider="fixture",
            model="test",
        ),
    )
    assert b"PARENT PRIVATE INPUT" not in target.native_bytes
    assert b"PRIVATE CIPHERTEXT" not in target.native_bytes
    assert target.dropped["opaque:subagent_inherited_prefix"] == start - 1
    assert target.dropped["opaque:subagent_encrypted_message_part"] == 1
    assert target.dropped["opaque:subagent_message_envelope"] == 1
    path = tmp_path / "legacy.json"
    path.write_bytes(target.native_bytes)
    reopened = opencode.parse_import(path)
    assert any(e.text == messages[0].text and e.role == Role.USER for e in reopened.events)
    assert [e.tool_call_id for e in reopened.events if e.kind == EventKind.TOOL_CALL] == [
        "call_fixture_1"
    ]
    assert any(e.payload.get("image_url") for e in reopened.events if e.kind == EventKind.CONTEXT)
    assert any(
        e.payload.get("content_blocks") for e in reopened.events if e.kind == EventKind.TOOL_RESULT
    )


@pytest.mark.parametrize(
    "recipient,author", [("/foreign", "/root"), (CHILD_PATH, None), ("/root", CHILD_PATH)]
)
def test_foreign_outbound_or_ambiguous_correspondence_is_opaque(tmp_path, recipient, author):
    value = records()
    seed = value[value[0]["payload"]["subagent_history_start_ordinal"]]["payload"]
    seed.update(recipient=recipient, author=author)
    session = codex.parse(write(tmp_path, value))
    assert not any(e.text == "Child task — λ\nkeep exact" for e in session.events)
    assert any(
        e.payload.get("reason") == "subagent_foreign_or_ambiguous_message" for e in session.events
    )


@pytest.mark.parametrize(
    "block",
    [None, {"type": "input_text", "text": 3}, {"type": "encrypted_content"}, {"type": "future"}],
)
def test_malformed_targeted_envelope_fails_closed(tmp_path, block):
    value = records()
    value[value[0]["payload"]["subagent_history_start_ordinal"]]["payload"]["content"] = [block]
    with pytest.raises(SessionMigrateError, match="agent-message"):
        codex.parse(write(tmp_path, value))


@pytest.mark.parametrize("boundary", [True, -1, "9", 100000])
def test_invalid_or_truncated_prefix_fails_closed(tmp_path, boundary):
    value = records()
    value[0]["payload"]["subagent_history_start_ordinal"] = boundary
    with pytest.raises(SessionMigrateError, match="boundary|incomplete"):
        codex.parse(write(tmp_path, value))


def test_complete_prefix_with_empty_child_suffix_is_valid_but_not_resumable(tmp_path):
    value = records()
    value = value[: value[0]["payload"]["subagent_history_start_ordinal"]]
    session = codex.parse(write(tmp_path, value))
    assert not any(e.kind != EventKind.OPAQUE for e in session.events)
    with pytest.raises(SessionMigrateError):
        convert_session(
            session,
            ConversionOptions(
                target_format=TargetFormat.OPENCODE, target_cli_version="1.17.20", cwd=tmp_path
            ),
        )


def test_empty_encrypted_seed_does_not_block_child_history(tmp_path):
    value = records()
    seed = value[value[0]["payload"]["subagent_history_start_ordinal"]]["payload"]
    seed["content"] = [{"type": "encrypted_content", "encrypted_content": "PRIVATE CIPHERTEXT"}]
    session = codex.parse(write(tmp_path, value))
    assert any(
        e.payload.get("reason") == "subagent_message_without_readable_text" for e in session.events
    )
    assert any(e.kind == EventKind.TOOL_CALL for e in session.events)


def test_envelope_duplicate_requires_matching_id_and_exact_content(tmp_path):
    value = records()
    seed = value[value[0]["payload"]["subagent_history_start_ordinal"]]["payload"]
    canonical = next(
        r["payload"]["item"]
        for r in value
        if r.get("type") == "event_msg"
        and r["payload"].get("item", {}).get("type") == "UserMessage"
    )
    seed["id"] = canonical["id"]
    seed["content"] = [{"type": "input_text", "text": canonical["content"][0]["text"]}]
    session = codex.parse(write(tmp_path, value))
    assert any(
        e.payload.get("reason") == "subagent_canonical_message_duplicate" for e in session.events
    )
    seed["content"][0]["text"] = "Conflicting message"
    with pytest.raises(SessionMigrateError, match="canonical message ID disagree"):
        codex.parse(write(tmp_path, value))


def test_parent_tool_result_in_child_is_not_replayed(tmp_path):
    value = records()
    item = {
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": "parent_call",
            "output": "PARENT SECRET OUTPUT",
        },
        "ordinal": len(value),
    }
    value.append(item)
    session = codex.parse(write(tmp_path, value))
    assert not any(e.text == "PARENT SECRET OUTPUT" for e in session.events)
    assert any(e.payload.get("reason") == "subagent_inherited_tool_result" for e in session.events)


@pytest.mark.parametrize(
    "change", ["id", "boundary", "boolean_boundary", "mode", "history_base", "ordinal"]
)
def test_child_metadata_updates_and_external_lineage_fail_closed(tmp_path, change):
    value = records()
    extra = copy.deepcopy(value[0])
    extra["ordinal"] = len(value)
    value.append(extra)
    if change == "id":
        extra["payload"]["id"] = "other_child"
    elif change == "boundary":
        extra["payload"]["subagent_history_start_ordinal"] += 1
    elif change == "boolean_boundary":
        extra["payload"]["subagent_history_start_ordinal"] = True
    elif change == "mode":
        extra["payload"]["history_mode"] = "legacy"
    elif change == "history_base":
        value[0]["payload"]["history_base"] = {"end_ordinal_exclusive": 100}
    else:
        value[4]["ordinal"] = "4"
    with pytest.raises(
        SessionMigrateError, match="identity|boundary|paginated|history_base|ordinal"
    ):
        codex.parse(write(tmp_path, value))


def test_same_shaped_nonauthoritative_payload_cannot_suppress_child_task(tmp_path):
    value = records()
    seed = value[value[0]["payload"]["subagent_history_start_ordinal"]]["payload"]
    value.append(
        {
            "ordinal": len(value),
            "type": "world_state",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "UserMessage",
                    "id": seed["id"],
                    "content": [{"type": "text", "text": "conflicting unrelated payload"}],
                },
            },
        }
    )
    session = codex.parse(write(tmp_path, value))
    assert any(
        e.kind == EventKind.MESSAGE and e.text == "Child task — λ\nkeep exact"
        for e in session.events
    )


def test_same_id_opposite_canonical_role_cannot_suppress_incoming_task(tmp_path):
    value = records()
    seed = value[value[0]["payload"]["subagent_history_start_ordinal"]]["payload"]
    value.append(
        {
            "ordinal": len(value),
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "AgentMessage",
                    "id": seed["id"],
                    "content": [{"type": "Text", "text": "Child task — λ\nkeep exact"}],
                },
            },
        }
    )
    with pytest.raises(SessionMigrateError, match="canonical message ID disagree"):
        codex.parse(write(tmp_path, value))


def test_boundary_only_in_later_metadata_is_rejected(tmp_path):
    value = records()
    value[0]["payload"].pop("subagent_history_start_ordinal")
    value[1]["payload"]["subagent_history_start_ordinal"] = 9
    with pytest.raises(SessionMigrateError, match="primary metadata"):
        codex.parse(write(tmp_path, value))


@pytest.mark.parametrize("kind", ["valid", "external", "invalid", "empty"])
def test_catalog_classification_matches_bounded_child_parser(tmp_path, kind):
    from session_migrate.catalog import _scan_file

    value = records()
    if kind == "external":
        value[0]["payload"]["history_base"] = {"end_ordinal_exclusive": 10}
    elif kind == "invalid":
        value[0]["payload"]["subagent_history_start_ordinal"] = True
    elif kind == "empty":
        value = value[: value[0]["payload"]["subagent_history_start_ordinal"]]
    path = write(tmp_path, value)
    scan = _scan_file(path, AgentFormat.CODEX, tmp_path)
    expected = {
        "valid": ("candidate", None),
        "external": ("unsupported", "codex_history_base"),
        "invalid": ("corrupt", "codex_subagent_projection"),
        "empty": ("corrupt", "no_conversation_records"),
    }
    assert (scan.status, scan.reason) == expected[kind]


def test_pinned_legacy_client_accepts_child_projection_without_parent_context(tmp_path):
    import os

    from session_migrate.conversion import install_opencode_artifact, load_opencode_session

    binary = os.environ.get("SESSION_MIGRATE_OPENCODE_BIN")
    if not binary:
        pytest.skip("set SESSION_MIGRATE_OPENCODE_BIN to the pinned 1.17.20 executable")
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_CONFIG_CONTENT": '{"disabled_providers":["opencode"]}',
    }
    for key in [
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
        "TMPDIR",
    ]:
        folder = tmp_path / key.lower()
        folder.mkdir()
        env[key] = str(folder)
    source = codex.parse(write(tmp_path, records()))
    artifact = convert_session(
        source,
        ConversionOptions(
            target_format=TargetFormat.OPENCODE,
            target_cli_version="1.17.20",
            cwd=tmp_path,
            model_provider="fixture",
            model="test",
        ),
    )
    install_opencode_artifact(
        artifact, manifest_path=tmp_path / "manifest.json", target_cli=Path(binary), environ=env
    )
    reopened = load_opencode_session(artifact.session_id, source_cli=Path(binary), environ=env)
    assert any(
        e.kind == EventKind.MESSAGE and e.text == "Child task — λ\nkeep exact"
        for e in reopened.events
    )
    assert any(
        e.kind == EventKind.TOOL_CALL and e.tool_call_id == "call_fixture_1"
        for e in reopened.events
    )
    assert any(
        e.kind == EventKind.TOOL_RESULT and e.tool_call_id == "call_fixture_1"
        for e in reopened.events
    )
    assert not any(
        "PARENT PRIVATE INPUT" in str(e.payload) or "PRIVATE CIPHERTEXT" in str(e.payload)
        for e in reopened.events
    )

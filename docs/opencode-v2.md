# OpenCode 2.0 transfers

`session-migrate import SOURCE --to opencode --target-cli /path/to/opencode`
now detects the installed CLI and selects its public transfer format. Legacy
1.17.20 continues using `opencode import/export --pure`; 2.0.x uses
`opencode session import/export --standalone`. Convert-only output remains
legacy by default; pass `--target-cli-version 2.0.23` to write a v2 bundle.
Other schema series are rejected for automatic import. Custom release suffixes
and the v2 `opencode v…` version prefix are accepted.

The v2 bundle uses session `location`/`model` and flat typed messages, including
native tool content and completed compaction summaries. Conversion reuses the
existing portable-event normalization and loss manifest. Text, linked tool
input/results, inline image attachments, and portable compaction summaries are
retained. Incomplete tool calls are archived as explicit imported errors,
because native v2 transfer drops unsettled assistant records. Their input is
retained and this change is recorded in the loss manifest. Encrypted checkpoints
and provider-private state are not portable and remain explicitly accounted for.
Reasoning variants in source Model.Ref are counted as omissions because the
portable session model has no variant field; choose the desired target variant
in OpenCode. Private-only or whitespace-only compaction records never become
portable checkpoints that could retire the earlier readable history.
No private SQLite writes or source transcript changes are performed.
Free-form tool inputs are wrapped as `{\"input\": ORIGINAL_VALUE}` to satisfy
OpenCode's object input schema. The `tool_call:non_object_input` manifest counter
records this shape transformation, not an omitted call. String inputs remain
unchanged inside the wrapper, along with their call IDs and linked results.

Dry run performs native preflight without importing a session or writing a
migration manifest. The target CLI itself may initialize its ordinary local
store during preflight. Native import enforces global identity conflicts; the
adapter also checks existing IDs and requires the explicit native success
confirmation (v2 returns exit status zero even on conflict). Verification exports
the imported ID through the public CLI rather than relying on a project-filtered
session list.

For isolated validation, use a clean HOME and XDG_CONFIG_HOME/XDG_DATA_HOME/
XDG_CACHE_HOME/XDG_STATE_HOME, a credential-free configuration, and the actual
binary instead of a user wrapper that injects production credentials. Migration
manifests contain source hashes, the target release, conversion warnings, and
omission counts. Native database imports remain owned by OpenCode.

Validation currently targets the installed Linux gateway build of OpenCode
2.0.23, using synthetic transcripts and no paid model requests. Windows native
validation is recorded separately below; Linux tests alone do not establish Windows runtime behavior.

## Validation record

The implementation at `eeb2623` was validated on Linux with Python 3.12 and
the installed OpenCode 2.0.23 gateway binary:

- Full Python suite: **1,557 passed, 55 skipped**, with 1,343 existing
  Devin/SQLite deprecation warnings. The run completed in 2,167.20 seconds.
- Repository-wide Ruff checks and formatting checks for all ten changed Python
  files passed. The wheel built and installed into a separate clean virtual
  environment; its public CLI converted a synthetic Codex fixture into a valid
  v2 bundle, retaining its portable compaction.
- Opt-in native v2 tests exercised public import/export, dry run, identity
  collisions, linked tool content, inline user/tool images, and completed
  compaction in isolated, credential-free HOME/XDG directories.
- An independent actual-native continuation test sent the imported compaction
  summary and a new prompt to one loopback fake-provider request. The reply
  persisted under the same session ID (six imported messages became ten), and
  a cold native TUI reopen displayed that persisted reply.
- A separate independent continuation test confirmed the original tool call
  and its linked `/work` result appeared in the fake-provider request. Its
  continued reply also persisted under the same ID (five messages became nine).

The full-suite skips cover unavailable exact-pinned historical clients, opt-in
live-client gates, and the opt-in real-store catalog smoke test. In particular,
native legacy OpenCode 1.17.20 was not installed; its unit and wire-format
regressions ran, but its original native CLI tests did not. This is not a claim
that all 18 supported clients were tested live. The 2.0.x version selector is
tested independently; native behavior was verified only on the installed 2.0.23
build. The Linux gates made no real supplier requests and imported no real user sessions.
Subsequent user-run Windows evidence is recorded separately below.

The full suite uses a consistent datastore `TMPDIR` and pytest `--basetemp`.
An earlier run with those roots mismatched failed an existing OMP temporary-path
expectation; the corrected environment passed without modifying or suppressing
that test. Provider-private traces and source reasoning variants remain the
explicit omissions described above; native continuation does not establish
their portability or recover malformed source records.

## Windows preparation

The separate Windows changes reuse [upstream PR #8](https://github.com/xhluca/session-migrate/pull/8)
(commit `8ee41da7433374803373ba7f66d6740a89757b0f`, Enrico), retaining its
attribution. Further fixes cover the native import manifest's separate directory
fsync helper, binary descriptors, and temporary descriptor cleanup on errors. Failed exports close their descriptor
before attempting to unlink the partial file, including timeouts.
Native imports also close their manifest identity guard before deleting a failed
reservation. Previously, Windows could report WinError 32 during this cleanup
and hide the original import or finalization failure. Successful finalization
continues writing the guarded file in place, preserving the identity check;
it does not replace the open file. Linux regressions simulate Windows denial of
unlink/replace for open manifests across successful imports, importer failures,
and finalization failures for OpenCode, Kilo, and shared-database imports.
Use an actual `opencode.exe` with `--target-cli`; native import/export remains the
same public v2 route. Windows inherits directory ACLs; POSIX mode 0600/0700 does
not establish equivalent Windows privacy. Store source exports, temporary files,
and migration manifests under directories accessible only to your Windows user.
File contents are flushed, but skipped directory fsync means crash durability
has not been established by these tests. Linux mock tests exercise the Windows
branches; user-run Windows import/export/reopen evidence follows below.


## User-run Windows validation (2026-10-07)

Python 3.13.7 and a custom OpenCode `2.0.23-gateway.3648f00e` build were
validated through a user-run Windows test package, using the converter at
`8e9b9a0`. This is runtime evidence for that particular build, not a Windows
full-suite run or validation of every 2.0.x release.

- A synthetic source converted successfully, then imported/exported through
  the public native CLI in a fresh isolated profile. Text, an image, linked
  tool input/result and a readable compaction summary were retained. The
  user confirmed the same history displayed on reopening the native TUI.
- A 73.37 MB real source was audited before import: 559 readable message
  events, 1,589 tool calls and 1,589 tool-result texts matched. All 59
  malformed-text counters represented empty strings. Its native import
  subsequently passed export verification.
- A batch considered 42 source files and verified 28 native sessions.
  Repeated runs recognised previously imported IDs instead of duplicating
  them. Five existing sessions were moved to current project directories
  through OpenCode's public move API while retaining IDs and content.
- Fourteen files were not imported: seven intentionally excluded obsolete
  projects, one log without readable conversation, and six unsupported
  paginated subagent-history projections. These are explicit exclusions;
  they must not be described as a complete migration of all source files.

The batch orchestration and path mappings live outside this library. Its first
message audit produced false mismatches when multiple user text blocks from
one source record became the exact newline-joined v2 `user.text`. The corrected
audit compares exact ordered messages after that narrow normalization, retaining
separate source records, assistant text blocks and tool/compaction boundaries.
Changed, removed and reordered messages remain rejected. All 14 affected
previews then passed and imported. This was an audit correction, not a relaxation
of the converter's safety checks.

Source files, manifests and database backups were retained. No inference/model
requests were made during these Windows checks. Real-session model continuation,
crash durability, encrypted-state reuse and native paginated-subagent conversion
were not tested. Encrypted/private state omissions remain as documented above.

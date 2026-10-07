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
validation is separate; Linux tests do not establish Windows runtime behavior.

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
build. Real Windows native import/export/reopen remains untested. These gates
made no real supplier requests and imported no real user sessions.

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
Use an actual `opencode.exe` with `--target-cli`; native import/export remains the
same public v2 route. Windows inherits directory ACLs; POSIX mode 0600/0700 does
not establish equivalent Windows privacy. Store source exports, temporary files,
and migration manifests under directories accessible only to your Windows user.
File contents are flushed, but skipped directory fsync means crash durability
has not been established by these tests. Linux mock tests exercise the Windows
branches; real Windows import/export/reopen validation is still required.

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

# Windows native transfer cleanup

This follow-up retains Enrico's atomic-write fix from upstream PR #8
(`8ee41da7433374803373ba7f66d6740a89757b0f`) and its author attribution.
It adds the separate native-manifest directory-fsync path, binary descriptors,
failed-export descriptor ownership, and close-before-rollback for reserved
native-import manifests. OpenCode, Kilo and shared database imports write the
successful guarded manifest in place and check its identity; error cleanup
releases that guard before identity-checked unlink so Windows WinError 32 does
not mask the original import/finalization failure. Cursor and Antigravity use
the same reservation cleanup order.

The regressions simulate Windows denial of deleting/replacing an open manifest
for success, importer failure and finalization failure. They use synthetic
sessions and fake native commands. This branch changes no provider or session
schema and does not depend on the OpenCode v2 or Codex child-history changes.
Linux mock coverage does not establish native Windows behavior. Windows inherits
directory ACLs; POSIX modes do not establish equivalent Windows privacy. Skipped
directory fsync also means crash durability is not established on Windows.

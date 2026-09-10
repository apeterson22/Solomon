# Self-maintenance implementation checkpoint

This checkpoint supersedes home-rc1 source but is NOT the requested fully validated
v1 installer. Do not interpret this document or package as production acceptance.

## New workflow

The chat tool catalog now includes development proposal, validation, exact approval
request/application, snapshot build, build status, and promotion approval request.
Read/search remain restricted to configured repositories. Chat cannot approve its
own patch or deployment.

A build freezes tracked and nonignored source into a local archive. Protected paths,
symlinks, runtime databases and detected credential patterns are rejected. The
archive's exact bytes and file hashes are bound to an isolated job. Allowlisted test
commands execute under the existing low-privilege, resource-limited systemd job
broker, with network disabled and a root-owned dependency environment. Successful
status requires test exit success, the matching harness marker, unchanged tested
source bytes and the original archive hash. Generated package paths stay local.

The old DevelopmentLab.test implementation ran repository code under the service
user; it now fails closed. The API's test action starts a maintenance build instead.
The UI's Jobs list shows the bounded job; chat/build-status API reports its package.

For completed builds:
- GET /v1/development/builds/BUILD-ID provides evidence.
- GET /v1/development/builds/BUILD-ID/archive downloads the archive with Admin auth.
- Chat may request maintenance.promote approval, bound to build ID and archive hash.
- An operator executes the returned sudo command after reviewing and approving it.

The operator promotion helper validates/extracts regular files into a root-only
staging directory, consumes the matching approval once, and invokes the packaged
controller upgrader. The existing upgrader owns checkpoint and rollback behavior.
Automatic service-initiated privileged promotion and worker fleet rollout are NOT
implemented here. A package without deploy.sh is source-only and cannot be promoted.

## Installer changes

The controller upgrade installs a separate root-owned build environment from tested
Linux dependency constraints. It migrates the known previous pytest command to this
environment while preserving other operator commands. Existing development branches
remain preserved; they are not automatically overwritten with the new live source.
Operators must reconcile an older development baseline before building its successor.
Android builds still require a separately provisioned Android SDK/dependency cache.

## Security corrections

- Job result output uses a root-owned temporary file and atomic replacement, so a
  job-controlled result.json symlink cannot redirect the privileged write.
- Patch validation rejects protected metadata, secret paths and symlink/submodule modes.
- Validation fingerprints source contents, not merely Git status labels.
- Development apply consumes the exact approval once with an expiry check.
- Explicit state_dir settings relocate all default state database paths, allowing
  isolated tests without opening live databases.

## Validation scope

The Python suite includes a deliberately broken addition fixture that fails its
check, proceeds through chat proposal/validation/approval/application, and passes
from the packaged snapshot. The fixture harness runs directly ONLY for its fixed
test source. This does not prove systemd isolation or a production deployment.
Archive traversal/symlink rejection, result symlink handling, changed-source
invalidation, secret-path rejection and build-evidence checks have regression tests.

The environment cannot switch to a separate OS user (setgroups denied) or run the
home systemd services. Therefore privileged broker isolation, installation, rollback,
Windows/WSL GPU behavior and actual device behavior are not verified here. The Android
SDK and home-host connections are also unavailable.

The remaining broader v1 gates from HOME_TEST_RELEASE.md still apply, particularly
per-node credentials, general permission-scoped host mutation, durable job recovery,
validated device adapters, and host acceptance. Do not call this v1 complete.

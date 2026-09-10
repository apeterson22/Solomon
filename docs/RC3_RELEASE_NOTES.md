# SolomonPrime v1.0.0-home-rc3

RC3 is a drop-in home-test release over `v1.0.0-home-rc2`. It preserves the
application semantic version `1.0.0` so existing v1 configuration and state
remain compatible, while the `/health` release marker reports `home-rc3`.

## RC2 blocker fixed

A long-running controller could remain `active (running)` while HTTP requests
stopped returning. Live `py-spy` evidence showed the FastAPI heartbeat waiting
inside `audit.emit()` while edge discovery held the audit lock in
`AuditLog._last_hash()`.

RC2's `_last_hash()` walked the audit file backward one byte at a time with an
unreachable newline break condition, then loaded the entire file again. As the
audit grew, each emit became progressively more expensive.

RC3:

- recovers the newest valid audit hash once at process startup in bounded blocks;
- caches and advances the chain head only after a successful append;
- preserves the existing JSONL/hash-chain record format and existing audit data;
- tolerates an incomplete final audit line after an unclean shutdown;
- moves mesh heartbeat audit I/O off the asyncio event-loop thread;
- audits edge-device candidate state only when the exact pending fingerprint set
  changes instead of every scan cycle;
- adds regression coverage for chain continuity, restart recovery, partial-tail
  recovery, no steady-state history rescan, and concurrent emit serialization;
- makes upgrade health probes bounded so a wedged RC2 cannot stall the RC3
  updater indefinitely.

## Upgrade existing RC2 controller

```bash
tar -xzf solomonprime_v1.0.0-home-rc3.tar.gz
cd solomonprime_v1.0.0-home-rc3
chmod +x deploy.sh install-*.sh upgrade-*.sh scripts/*.sh
sudo ./deploy.sh controller upgrade
```

For a worker node:

```bash
sudo ./deploy.sh node upgrade
```

Fresh installation remains:

```bash
sudo ./deploy.sh controller install
# or
sudo ./deploy.sh node install
```

The upgrade creates a rollback checkpoint before replacing the runtime and keeps
site-specific configuration, keys, databases, audit history, and approved state.

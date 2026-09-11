# SolomonPrime PKI and secret scanning

## Temporary CA placement

For v1.1 home development, Jarvis2 is the temporary SolomonPrime private CA and keystore host. Private material lives under `/etc/solomonprime/pki`, outside Git. The CA is an operational dependency, not application source.

- CA private key: `/etc/solomonprime/pki/ca/ca.key` (root-only)
- CA certificate: `/etc/solomonprime/pki/ca/ca.crt`
- public trust copy: `/etc/solomonprime/pki/trust/solomonprime-ca.crt`
- node identities: `/etc/solomonprime/pki/nodes/<node>/tls.{key,crt}`
- leaf certificates default to 90 days and support both `serverAuth` and `clientAuth` during the transition to mTLS.

The bootstrap refuses to overwrite an existing CA or node identity. CA migration to a dedicated server must be explicit and operator approved. The CA private key must never be copied into the repository, development worktrees, chat context, scanner reports, or ordinary fleet nodes.

## Bootstrap

```bash
sudo bash scripts/setup-local-pki.sh init-ca
sudo bash scripts/setup-local-pki.sh issue jarvis2 DNS:jarvis2.askme.myhome
sudo bash scripts/setup-local-pki.sh issue pwrgmr DNS:pwrgmr DNS:pwrgmr.askme.myhome
sudo bash scripts/setup-local-pki.sh verify jarvis2
```

Add known LAN/Tailscale IP SANs only when they are stable and intentionally part of the identity. DNS SANs are preferred where local name resolution is controlled.

Before distributing a node identity, copy only that node's `tls.key`, `tls.crt`, and `ca.crt` over an authenticated channel and install the private key root-only. Never distribute `ca.key`.

## Gitleaks on Jarvis2

Install using the repository installer:

```bash
bash scripts/install-gitleaks.sh
gitleaks version
```

Scan the current working tree:

```bash
gitleaks dir . --redact --config .gitleaks.toml
```

Scan Git history:

```bash
gitleaks git . --redact --config .gitleaks.toml
```

The salvage workflow should use Gitleaks as an independent second scanner alongside TruffleHog. Raw scanner reports are private because a finding may contain credential material; only counts/verification metadata belong in repository documentation.

## Commit-time gate

The repository includes a pre-commit configuration that blocks private keys and invokes Gitleaks against staged changes. Install `pre-commit` (or a compatible runner) locally and enable it before agent-driven development. CI remains an independent gate; local hooks are defense in depth, not the sole protection.

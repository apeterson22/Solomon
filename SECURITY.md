# SolomonPrime security and local-data boundary

Do not commit API keys, OAuth client secrets or tokens, cluster keys, device
credentials, voiceprints, signing keys, databases, machine capability reports,
network inventories, model files, chat histories, or Open WebUI state.

The supported locations are:

- Configuration: `/etc/solomonprime` and `/var/lib/solomonprime/*.yaml`
- Secrets: `/etc/solomonprime/secrets` and `/etc/solomonprime/*.key`
- State and audit ledgers: `/var/lib/solomonprime`
- Model weights: `/var/lib/solomonprime/models` or the locally configured model store
- Android signing material: an operator-owned local keystore outside this tree

The Development Lab can read, search, validate, and test only explicitly
allowlisted development copies. It blocks common secret-file paths. Applying an
exact patch to a non-live development copy requires a digest-bound Admin
approval. Production promotion, Git push, dependency installation, service
restart, radio transmission, firmware flashing, and physical movement remain
separate operator actions.

Report a suspected credential exposure by rotating the credential at its
provider first, revoking affected mobile/device tokens, and then privately
contacting the repository owner. Do not open a public issue containing secrets.

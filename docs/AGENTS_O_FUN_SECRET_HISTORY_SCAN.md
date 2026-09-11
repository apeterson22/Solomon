# agents-o-fun historical secret review

Status: in progress; this document records only metadata and conclusions. Secret values must never be copied into SolomonPrime.

## Confirmed `.env` history

GitHub history for `agents-o-fun/.env` shows exactly two commits that modified the file:

- `c6cff505369988c4330c8721bc30a717b2684663` — initial `.env` creation
- `6fd6f6b29e0a88eae4b7bad6573c5471c1fdcf82` — later update

Both revisions contain placeholder credential strings for the following variable names:

- `FIDELITY_API_KEY`
- `COINBASE_KEY`
- `CRYPTOCOM_KEY`
- `CRYPTOCOM_BETTING_KEY`
- `AI_API_KEY`
- `AI_ENDPOINT`

No live credential value was observed in either `.env` revision. The only material change between the two revisions is the local AI endpoint binding.

## Rotation decision from `.env` history

Based on the two `.env` revisions alone:

- Fidelity credential: no rotation required by evidence seen so far.
- Coinbase credential: no rotation required by evidence seen so far.
- Crypto.com credential: no rotation required by evidence seen so far.
- Generic AI credential: no rotation required by evidence seen so far.
- Gambling/betting integration: do not salvage into SolomonPrime core.

This is not yet a whole-repository historical-secret clearance. Removed files, renamed files, source-code literals, configuration files, notebooks, logs, binary artifacts, and prior Git objects still require a full-history scanner.

## Required full-history gate before salvage

Run a full clone/mirror scan with at least two independent scanners where available, for example:

1. Gitleaks against all refs and reachable commits.
2. TruffleHog against the repository's Git history.
3. Supplemental regex/name scan for credential-like assignments and private-key markers.
4. File inventory for `.env`, key stores, databases, logs, checkpoints, pickle files, and archives.

The sanitized report may record variable/provider name, affected commit count, path count, severity, and whether rotation is required. It must not contain the discovered secret value.

Any verified historical credential causes the source repository to be treated as compromised for that credential even if the current branch contains only placeholders. Rotate/revoke it before any salvage promotion.

## Salvage policy

`agents-o-fun` is a reference/research source. Do not import its Git history into SolomonPrime. Port useful ideas or reviewed source into fresh files with provenance notes. Do not import `.env`, gambling/betting functionality, generated databases, logs, checkpoints, or credential-bearing configuration.

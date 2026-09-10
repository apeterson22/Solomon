# Cloud Routing and Local Improvement

SolomonPrime remains local-first. Cloud models are optional bounded advisors, not required dependencies.

## Routing order

1. Local model performs ordinary work.
2. A deterministic complexity scorer decides whether a cloud advisory may add value.
3. CloudRouter checks privacy policy, provider eligibility, and local quota ledger.
4. Quota is reserved before a call. Unknown quota means deny.
5. Cloud advisory is returned to the local model as evidence/advice.
6. The local model synthesizes the final response and remains responsible for local tool use.
7. If no cloud provider is eligible, the request proceeds locally with no failure.

## Zero-overage rule

A provider is callable only when all are true:

- enabled explicitly;
- `allow_overage: false`;
- `billing_mode` is `free` or `subscription-included`;
- conservative request/input/output limits are configured;
- usage plus the reservation remains under the configured quota margin;
- required credentials/session are available;
- sensitive-input policy permits the call.

SolomonPrime uses a conservative local ledger and does not refund reservations after failed calls. Under-using a quota is preferable to crossing it.

For GitHub Copilot CLI, account-level Additional usage must be disabled. Per-session AI-credit limits are treated as a second guard, not the primary hard stop.

## Privacy

Only the current user request is sent to a cloud advisor by default. SolomonPrime memory, tool results, files, Home/Farm records, and system prompts are not forwarded. Secret-like inputs are blocked from cloud routing by default.

## Teacher/student improvement

Useful cloud advisories are written locally as *candidate* teacher examples. They are never automatically promoted into production training data.

Improvement order:

1. Retrieval quality
2. Tools
3. Prompts
4. Workflow decomposition
5. Routing
6. Memory/context construction
7. Quant/runtime configuration
8. Fine-tuning/LoRA when hardware/model support makes it justified
9. Distillation only after evaluation

Every candidate local model or tuning change must run in the model lab, compare against a baseline, and require approval before production promotion.

With the current controller host + worker-node hardware, the practical automated improvements are prompt/routing/memory optimization, dataset curation, benchmark generation, quant/runtime experiments, and training of smaller compatible models. Full 27B weight training is not treated as an automatic background job.

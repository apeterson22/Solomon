# Runtime topology discovery

SolomonPrime does not embed a deployment's hostnames, addresses, hardware, or
storage paths in source control. Each installation creates a local capability
report and registers only with its configured controller.

## Controller

The controller hosts the API, Admin workspace, governance ledgers, scheduler,
and optional Open WebUI integration. Existing inference services are detected
and preserved. A clean deployment can add the pinned Ollama runtime or a
locally configured llama.cpp service after installation.

## Nodes

Nodes discover CPU, memory, GPU, storage, USB, Bluetooth, and receive-only RF
capabilities locally. Registration requires the local cluster credential.
Mutating device and radio operations remain disabled until an operator grants
an action-specific, time-bounded approval for verified hardware.

## Private state

The generated capability report, peer addresses, model inventory, credentials,
provider configuration, and operational databases stay on the deployment and
are excluded from the repository.

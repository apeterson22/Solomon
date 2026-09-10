# Correlation with the attached prior build conversation

The attached conversation documents the progression from the original boot/storage-controller issue through BIOS tuning, persistent remote access, voice, a web interface, multi-GPU plans, and a separate 4 GB simulation worker.

SolomonPrime v0.2 retains the parts that still align with the current machines:

- server-style persistent services rather than transient terminal sessions;
- LAN and remote access to the AI interface;
- Tailscale for remote/fallback connectivity;
- both local/backend and browser/device voice paths;
- a separate simulation/tool role for worker-node;
- non-root application services and strict shell/install error handling;
- explicit firewall awareness and preservation of SSH access.

It intentionally supersedes obsolete assumptions from that earlier build stage:

- controller host no longer contains the RTX 5070; it now uses RX 6700 XT + GTX 1070 natively.
- The production inference engine is llama.cpp, not two Ollama instances.
- Open WebUI is the supported browser UI instead of the older Pi web layer.
- Local/direct networking is now preferred over Tailscale for on-site machines; Tailscale remains remote/fallback.
- The installer does not automatically enable UFW, because doing so previously caused loss of remote reachability.
- worker-node's GTX 970 is on a separate physical computer, so it is represented as a worker node rather than a local GPU index.

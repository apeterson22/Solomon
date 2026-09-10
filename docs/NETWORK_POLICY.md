# Local-first network and workload policy

Path ranking is deterministic:

`loopback > direct Ethernet > wired LAN > Wi-Fi > Tailscale`

Each node advertises every usable IPv4 endpoint and path metadata. The controller tests reachability and latency, considers link type/speed, and combines path quality with CPU/RAM/GPU headroom. Stateful services receive an extra penalty on Wi-Fi/Tailscale unless no better path exists.

mDNS provides same-LAN discovery. Tailscale peer discovery provides remote/fallback discovery. Unknown/unsigned devices are `pending`; a cluster-signed heartbeat is required for trust.

LLM scheduling advice is allowed only as a bounded tie-break among candidates that deterministic policy already considers valid.

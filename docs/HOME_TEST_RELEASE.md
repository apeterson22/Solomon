# SolomonPrime v1 home-test candidate 2

This candidate is for supervised local acceptance testing. It is not a verified
production release and does not complete every item in the requested v1 scope.
The API reports version 1.0.0 and release home-rc4 for upgrade compatibility.

## Changes in this candidate

- Fixed GPU-required placement admitting nodes with no GPU or no free VRAM.
- Fixed job IDs escaping the job workspace before reaching the privileged broker.
- Upgrade rollback cannot run before a valid checkpoint exists. Checkpoint scans
  exclude backup directories and retain database owner/group/mode for restoration.
- Clean installation refuses an existing configuration; deployment from inside
  the live application directory is rejected.
- Chat can inspect local/remote enrolled hosts with fixed read-only skills, propose
  sandboxed Python/Blender/OpenSCAD jobs, and execute exact single-use Admin approvals.
  Job approval includes source, resources and target constraints. It cannot grant root.
- Admin shows exact approval payloads and device parameters/results for review.
- Serial ports are discovered without opening them; USB records without serial
  numbers include port identity to avoid merging two identical attached devices.
- Approved serial bench sessions support 1200..115200 baud (listed choices), at
  most 256 transmitted bytes, 10 seconds and 16384 received bytes. Listening also
  needs approval because opening a port can reset attached hardware.
- Capture analysis reports length, hash, printable fraction, entropy and tentative
  NMEA framing. These are evidence, not protocol validation or decryption.
- Optional WSL worker admission follows Windows activity/manual mode. Expired
  admission stops new jobs, and bounded runners interrupt active jobs. Dedicated
  Ollama can be stopped for gaming by the monitor. No automatic job migration or
  checkpoint/resume is claimed.
- Worker inference substitutes its own configured model name instead of receiving
  the controller's unrelated model name.

## Linux installation or upgrade

Use a supported Ubuntu/Debian host with systemd and Python 3.11+. Keep the previous
release and backups. Do not run this installer on an unrelated workstation role.

Extract outside /apps/solomonprime/app:

```bash
cd ~
tar -xzf solomonprime_v1.0.0-home-rc4.tar.gz
cd solomonprime_v1.0.0-home-rc4
chmod +x deploy.sh install-*.sh upgrade-*.sh scripts/*.sh
bash scripts/home-preflight.sh
```

For existing installations, preflight expects curl, jq, rsync and system PyYAML.
If these are missing, install those specific packages through the host's supported
package manager before attempting upgrade. New installers install dependencies.

Existing controller (Jarvis2):

```bash
sudo ./deploy.sh controller upgrade
```

Existing worker (pwrgmr):

```bash
sudo ./deploy.sh node upgrade
```

New worker only (replace CONTROLLER-IP locally):

```bash
sudo SOLOMON_CONTROLLER_URLS='http://CONTROLLER-IP:8765' ./deploy.sh node install
```

The worker prompts for the controller cluster key with hidden input. Retrieve and
transfer that key locally; never upload it or share it in chat. The current mesh
uses a shared HMAC key. This authenticates requests but is NOT transport encryption
or per-node cryptographic isolation; use an isolated trusted LAN for this candidate.
Full per-node key rotation/revocation remains a release gap.

After installation:

```bash
curl -fsS http://127.0.0.1:8765/health
sudo systemctl status solomonprime --no-pager
sudo journalctl -u solomonprime -n 60 --no-pager
```

Existing inference is preserved. If an existing Ollama executable is not serving:

```bash
sudo ./scripts/repair-ollama.sh
curl -fsS http://127.0.0.1:11434/api/tags
```

On a worker with local Ollama models and no configured inference, run:

```bash
sudo /apps/solomonprime/.venv/bin/python ./scripts/configure-node-inference.py
sudo systemctl restart solomonprime
```

This publishes the worker's inference capability through its regular heartbeat.
The controller is not manually redirected to the worker.

## Chat acceptance

Use the existing Open WebUI SolomonPrime chat and Admin console.

1. Ask: "List my live nodes and their available GPU resources."
2. Ask: "Inspect disk space on node NODE-ID using the host skill."
3. Ask: "Propose a Python job on NODE-ID that computes sum(i*i for i in range(10000)) and prints the result."
4. In Admin → Approvals inspect the complete payload and approve the exact request.
5. Ask chat to execute that approval ID. Record the returned job ID.
6. Ask for that job's status; check node placement, stdout/result, and completion.
7. Attempt the same approval again: it must fail as consumed.

Jobs run in isolated workspaces, not with arbitrary read/write access to host files.
Host inspection is a fixed read-only command catalog. Broader approved file/service
mutation and per-skill standing permissions are NOT implemented by this candidate.

## USB and serial acceptance on the controller

1. Attach a known, owned bench device with actuators disconnected.
2. Open Admin → Edge Devices or ask chat to list devices.
3. Verify USB/serial mapping and identity against the physical device. Discovery
   infers interfaces; it does not certify vendor identity or full functionality.
4. Approve the candidate for analysis.
5. The SolomonPrime service user needs OS permission to open this exact port.
   For a temporary bench session, after verifying the port and installing `acl`
   if needed, grant only that device node:

```bash
service_user=$(systemctl show solomonprime -p User --value)
# Replace ttyUSB0 with the physically verified port.
sudo setfacl -m "u:${service_user}:rw" /dev/ttyUSB0
```

6. Request `serial_exchange` with parameters such as:

```json
{"baud":9600,"payload_hex":"","duration_seconds":2,"max_bytes":4096}
```

7. Review and approve the action; execute it from Admin or chat. Inspect response
   bytes and analysis. An empty response is not proof of a broken device.
8. Transmit only a documented harmless command for this exact device in the next
   separately approved action. Do not send generic guessed commands or baud sweeps.
9. Unplug the device: records should show it absent and execution should fail.
10. Revoke temporary access when done:

```bash
sudo setfacl -x "u:${service_user}" /dev/ttyUSB0
```

## Alternatives for unsupported devices

Test alternatives in this order, keeping captures/results local:

| Obstacle | Home-lab alternative | Required evidence |
| --- | --- | --- |
| Proprietary protocol | Official/local vendor bridge; maintained open driver; capture an owned device's vendor-software exchange | Repeatable request/response and bounded adapter tests |
| Encrypted protocol | Official pairing/exported authorized keys; documented local API; vendor bridge | Working authorized session; do not claim entropy proves encryption or decryption |
| Undocumented serial behavior | Approved listening, known harmless commands, pseudoterminal protocol simulator | Capture hashes, response fixtures, failure and disconnect tests |
| Unsupported hardware capability | External sensor/actuator, protocol converter, or replacement controller | Electrical compatibility, isolation, and end-to-end bench result |
| Locked or unsuitable firmware | Supported alternative firmware only with backup/recovery procedure | Exact board compatibility, recovery test, separate flashing approval |

Only bounded serial transport and offline capture heuristics are newly executable
here. USB endpoint adapters, vendor-specific decoders, firmware flashing and physical
control are NOT universally implemented. Device-specific development and hardware
validation are still required. This package does not attempt key brute-force,
unapproved authentication, blind fuzzing or protection bypass on attached devices.

## Optional Windows 11 full worker through WSL

This is an experimental full Linux worker on Windows, not a native Windows agent.
It uses the same enrollment, signed dispatch, host inspection and job executor as
the Linux worker. Windows file/app automation is not included.

Use a dedicated WSL distribution so stopping workloads does not affect unrelated
WSL projects. In Administrator PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
wsl --update
```

Reboot if requested and finish Ubuntu first-run user setup. WSL requires systemd;
verify `ps -p 1 -o comm=` inside Ubuntu. Review Microsoft's systemd/network guidance:
https://learn.microsoft.com/en-us/windows/wsl/wsl-config
https://learn.microsoft.com/en-us/windows/wsl/networking

For controller-to-worker LAN access, configure mirrored networking on supported
Windows 11/WSL and permit port 8765 only from the controller through the relevant
Windows/Hyper-V firewall. Do not replace your existing .wslconfig blindly. LAN
reachability must be tested before enrollment can be counted as successful.

Inside the dedicated distribution, extract this archive and create the fail-closed
admission gate BEFORE installation:

```bash
sudo mkdir -p /etc/solomonprime
sudo ./scripts/worker-mode.sh disabled
sudo SOLOMON_CONTROLLER_URLS='http://CONTROLLER-IP:8765' ./deploy.sh node install
/usr/lib/wsl/lib/nvidia-smi
```

Use the Windows NVIDIA driver with WSL GPU support. Do not install a Linux NVIDIA
kernel driver inside WSL. Install local inference separately if desired and run
configure-node-inference.py after a local model is present. For a dedicated Ollama
service to be stopped/restarted by the gaming gate:

```bash
sudo touch /etc/solomonprime/opportunistic-ollama
```

Extract the archive on Windows too, then run the activity monitor in a normal,
interactive PowerShell session (use the distribution name from `wsl -l -v`):

```powershell
.\windows\Watch-Worker.ps1 -Distribution Ubuntu-24.04 -IdleSeconds 300 -GameProcesses 'YourGameProcess'
```

The game process names omit .exe. Configure actual games: keyboard/mouse idle alone
cannot detect controller-only gaming. For deterministic manual gaming mode run with
`-Mode Gaming`; manual availability uses `-Mode Available`. Stop the first monitor
before starting another. Ctrl+C requests Disabled; a crash expires admission after
30 seconds. The script is not installed as an automatic startup task.

This path has not been executed on Windows here. PowerShell, WSL network/firewall,
GPU acceleration, gaming preemption and reliable VRAM release require host testing.
A monitor crash does not guarantee that a previously loaded Ollama model is unloaded.
The bounded job runner does enforce the expiring gate independently.

## Remaining release gates

- Real Linux install/upgrade/rollback tests under systemd on representative hosts.
- Actual model-driven tool-call and distributed-job acceptance on the home network.
- Per-node cryptographic credentials and rotation; current shared-key mesh is insufficient for hostile nodes.
- Durable job recovery/reassignment and general standing host/skill permissions.
- Device-specific adapters and physical-device control beyond approved serial bench exchanges.
- Native Windows worker or validated WSL deployment and graphics/gaming acceptance.
- Android SDK build and physical phone acceptance.
- Sanitized GitHub publication and repository CI validation.

No host tests are implied by a passing Python suite. Do not label these gates passed
until the corresponding machine evidence exists.

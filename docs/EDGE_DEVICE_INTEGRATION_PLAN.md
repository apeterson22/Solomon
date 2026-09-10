# SolomonPrime Edge Device Integration Plan

This plan records photo-derived hypotheses, not completed connections. Exact revisions and capabilities remain unverified until controller host captures local evidence.

## Inventory and best-fit roles

| Device | Connection hypothesis | Best first use | Important boundary |
|---|---|---|---|
| Makey Makey | USB HID keyboard/mouse | contact inputs, large task buttons, leak/gate alerts | input-only; not safety-critical |
| CodeGamer KosmoDuino | USB serial and BLE, to verify | portable interactive sensor/checklist station | preserve firmware; approve pairing/write |
| ELEGOO robot car | USB serial, Bluetooth UART, IR | supervised inspection and sensor mule | wheels-up test, e-stop, speed/exclusion limits |
| 2 JAKKS Mini Antigravity racers | proprietary 2.4 GHz, FCC OTA02497RX | receive-only research or supervised chassis study | no transmit without approval |
| 4 Raykit tags | Android Find Hub over BLE/cloud | keys, tool cases and movable equipment | private owner location; not primary livestock tracking |

## Staged onboarding

1. Photograph labels and board revisions; assign stable IDs and intended owners/assets.
2. Run read-only USB, serial and already-paired Bluetooth inventory on controller host.
3. Compare detected identifiers with official manuals; update confidence and evidence notes.
4. Propose one reversible connection experiment per device class.
5. Obtain approval before pairing, firmware writes, radio transmission, physical motion, or location sharing.
6. Bench-test locally, record evidence and rollback, then promote from verified to trusted.

## Dynamic attachment discovery

controller host checks USB sysfs every five seconds and samples Bluetooth advertisements
once per minute. A newly observed fingerprint enters `pending` quarantine. USB
class codes and Bluetooth advertisement/RSSI evidence are used only to infer a
starting capability class; they never prove ownership or trust. RSSI is affected
by walls, antennas, orientation, interference, and transmit power, so “nearby”
is an estimate rather than a guaranteed 20-foot boundary.

Admin can approve a fingerprint for deeper **local analysis** or deny it. That
approval does not authorize pairing, authentication attempts, kernel-driver
detachment, endpoint writes, firmware changes, radio commands, location access,
or physical motion. Each of those remains a separate governed action.

## Action authorization and execution

Admin exposes action-specific authorization for pairing, authentication
attempts, USB endpoint writes, driver detachment, firmware flashing, radio
commands, location access, and physical movement. Requests bind the discovered
fingerprint, exact bounded parameters, requester, purpose, risk, and expiration.
They can be approved or denied and can execute only once before expiry.

BlueZ pairing and connection have fixed, argument-array executors when
`bluetoothctl` is installed. No shell is invoked and the Bluetooth address is
copied from the quarantined fingerprint rather than accepted from browser input.
All other operations require a signed fingerprint-scoped adapter before their
Execute control becomes available. Firmware requests bind an image ID and
SHA-256; movement is initially limited to two seconds and 25 percent speed;
location access is one-time/nearby-only and limited to five minutes; endpoint
and radio payloads have strict hexadecimal length limits; driver detachment
requires an automatic rebind interval.

Authorization availability does not misrepresent executor availability. Admin
shows both independently and records every request, decision, attempted
execution, result, failure, and unavailable-adapter reason.

Free cloud advisors may help interpret public manuals or compare protocols only after local models cannot resolve the question. They receive no credentials, precise locations, live household telemetry, or physical-control authority. All device commands remain local and deterministic.

## Initial local evidence commands

```bash
lsusb
find /dev/serial/by-id -maxdepth 1 -type l -ls 2>/dev/null
bluetoothctl list
bluetoothctl devices Paired
```

These commands do not pair or flash anything. Save their output as experiment evidence before proceeding.

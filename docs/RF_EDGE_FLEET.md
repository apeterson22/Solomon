# RF and Edge Fleet Operations

SolomonPrime r9 extends dynamic USB/Bluetooth discovery and receive-only RF
monitoring to controller and node roles. Each node performs local discovery and
reports bounded capability summaries through cluster-signed heartbeats.

## Enabled discovery

- USB device and interface-class fingerprinting every five seconds.
- Bluetooth advertisement sampling every minute with approximate RSSI status.
- RTL-SDR/rtl_433 receive windows every five minutes when the tool and compatible
  hardware are available.
- Detection of HackRF, SoapySDR, USRP, Wi-Fi and Bluetooth tool candidates.
- Central fleet summaries and recent redacted RF observations in Admin.

Installing a tool is not proof that its hardware is attached. The dashboard
therefore distinguishes candidate, available, active, failed and unavailable.

## RF control boundary

Unknown signals remain untrusted and local. Automatic monitoring is receive
only. RF transmission requires all of the following:

1. An operator-owned, fingerprinted device.
2. A verified device/protocol adapter.
3. A configured regional frequency and duty-cycle policy.
4. An exact bounded command request.
5. A non-expired approval.
6. A single atomic execution claim and recorded result.

No generic spectrum transmitter or arbitrary shell interface is exposed.

## Install and verify a node

```bash
sudo ./upgrade-node-v0.4.0.sh
KEY=$(sudo cat /etc/solomonprime/api.key)
curl -sS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/rf/status | jq
curl -sS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/edge-devices | jq '.counts'
```

The controller receives the new summary on the next signed heartbeat, normally
within 15 seconds.

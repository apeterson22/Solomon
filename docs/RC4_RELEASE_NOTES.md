# SolomonPrime v1.0.0-home-rc4

RC4 is the finalization build on top of the validated RC3 stability baseline.
It intentionally avoids architectural churn.

## Changes from RC3

1. **Dynamic local Ollama endpoint discovery**
   - preserves a healthy configured endpoint;
   - detects `OLLAMA_HOST` from the existing systemd unit;
   - recognizes custom local ports such as `11436`;
   - probes the standard ports and the active Ollama service listen sockets;
   - never rewrites a healthy custom Ollama unit merely to force port `11434`;
   - records the discovered endpoint back into SolomonPrime config during upgrade.

2. **Existing Open WebUI adoption**
   - if `/etc/solomonprime/open-webui.env` is absent but `open-webui` exists,
     RC4 captures the container's effective environment into a root-only env file;
   - SolomonPrime modifies only integration-owned values;
   - recreation remains guarded: an unrelated/custom container that does not use
     the expected persistent `open-webui` volume is not replaced;
   - rollback behavior remains intact if the integrated replacement fails health
     or SolomonPrime self-tests.

3. **RC3 audit fix retained unchanged**
   - constant-time audit chain head during steady-state writes;
   - async heartbeat logging moved off the Uvicorn event loop;
   - edge-discovery candidate auditing is state-change based.

## Upgrade

```bash
tar -xzf solomonprime_v1.0.0-home-rc4.tar.gz
cd solomonprime_v1.0.0-home-rc4
chmod +x deploy.sh install-*.sh upgrade-*.sh scripts/*.sh
sudo ./deploy.sh controller upgrade   # Jarvis2
sudo ./deploy.sh node upgrade         # pwrgmr / existing workers
```

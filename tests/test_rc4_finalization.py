from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_release_marker_rc4():
    api=(ROOT/'solomonprime/api.py').read_text()
    assert '"release":"home-rc4"' in api

def test_ollama_detector_preserves_systemd_custom_endpoint_logic():
    s=(ROOT/'scripts/detect-ollama-endpoint.sh').read_text()
    assert 'systemctl show ollama.service -p Environment' in s
    assert 'OLLAMA_HOST=' in s
    assert '11436' in s
    assert '/api/tags' in s

def test_upgrade_persists_detected_ollama_endpoint():
    s=(ROOT/'scripts/upgrade-v1.0.0-common.sh').read_text()
    assert 'DETECTED_OLLAMA_ENDPOINT' in s
    assert "d['ollama_endpoint']=os.environ.get('DETECTED_OLLAMA_ENDPOINT')" in s

def test_openwebui_missing_env_is_adopted_not_skipped():
    s=(ROOT/'scripts/link-openwebui-admin.sh').read_text()
    assert 'Adopted existing Open WebUI environment' in s
    assert 'docker inspect' in s
    assert 'expected persistent volume' in s
    assert 'Missing $ENV_FILE; skipping Admin link.' not in s

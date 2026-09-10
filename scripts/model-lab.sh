#!/usr/bin/env bash
set -Eeuo pipefail
MODEL_DIR="${SOLOMON_MODEL_DIR:-/var/lib/solomonprime/models}"
export OLLAMA_HOST="${SOLOMON_OLLAMA_URL:-${OLLAMA_HOST:-http://127.0.0.1:11434}}"
LLAMA_BENCH="/opt/llama.cpp/build/bin/llama-bench"
HF="$HOME/hf-tools/bin/hf"
ACTION="${1:-bench}"
CANDIDATE="${2:-}"
mkdir -p "$MODEL_DIR" /var/lib/solomonprime/model-lab 2>/dev/null || true
ollama_bin(){
  local candidate
  for candidate in "${SOLOMON_OLLAMA_BIN:-}" "$(command -v ollama 2>/dev/null || true)" /usr/local/bin/ollama /usr/bin/ollama /snap/bin/ollama; do
    [[ -n "$candidate" && -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}
ollama_http_ready(){ curl -fsS --max-time 3 "${OLLAMA_HOST%/}/api/tags" >/dev/null 2>&1; }
case "$ACTION" in
  inventory)
    echo '=== Active llama.cpp model ==='
    readlink -f "$MODEL_DIR/primary.gguf" 2>/dev/null || echo 'No primary.gguf symlink'
    echo '=== Downloaded GGUF models ==='
    find "$MODEL_DIR" -type f -iname '*.gguf' -printf '%s %p\n' 2>/dev/null | sort -nr
    echo '=== Ollama local and cloud models ==='
    if ollama_http_ready; then
      curl -fsS "${OLLAMA_HOST%/}/api/tags" | jq -r '.models[]? | [.name,((.size//0)|tostring),(.digest//"")] | @tsv'
    else
      echo "Ollama daemon is unavailable at $OLLAMA_HOST"
      "$0" diagnose-ollama || true
    fi
    ;;
  list-candidates)
    printf '%s\n' \
      'qwen35-27b-q4      Qwen3.5 27B Q4 quality candidate' \
      'gemma3-12b-q4      Gemma 3 12B IT QAT Q4_0' \
      'ministral3-14b-q4  Ministral 3 14B Instruct Q4_K_M' \
      'ollama-gpt-oss-20b Ollama gpt-oss:20b local reasoning model (Apache-2.0)' \
      'ollama-qwen3-14b    Ollama qwen3:14b local tool/general model (Apache-2.0)' \
      'ollama-gpt-oss-120b-cloud Ollama cloud complex-task model; free allowance gate'
    ;;
  download-candidate)
    CANDIDATE=qwen35-27b-q4
    ;&
  download)
    case "$CANDIDATE" in
      qwen35-27b-q4)
        [[ -x "$HF" ]] || { echo "Missing $HF. Create the existing hf-tools venv first."; exit 2; }
        "$HF" download unsloth/Qwen3.5-27B-GGUF Qwen3.5-27B-UD-Q4_K_XL.gguf --local-dir "$MODEL_DIR";;
      gemma3-12b-q4)
        [[ -x "$HF" ]] || { echo "Missing $HF. Create the existing hf-tools venv first."; exit 2; }
        "$HF" download google/gemma-3-12b-it-qat-q4_0-gguf gemma-3-12b-it-q4_0.gguf --local-dir "$MODEL_DIR";;
      ministral3-14b-q4)
        [[ -x "$HF" ]] || { echo "Missing $HF. Create the existing hf-tools venv first."; exit 2; }
        "$HF" download mistralai/Ministral-3-14B-Instruct-2512-GGUF Ministral-3-14B-Instruct-2512-Q4_K_M.gguf --local-dir "$MODEL_DIR";;
      ollama-gpt-oss-20b)
        "$0" license-check "$CANDIDATE"
        OLLAMA_BIN="$(ollama_bin)" || { echo 'Ollama executable is unavailable; run repair-ollama.sh'; exit 2; }
        "$OLLAMA_BIN" pull gpt-oss:20b;;
      ollama-qwen3-14b)
        "$0" license-check "$CANDIDATE"
        OLLAMA_BIN="$(ollama_bin)" || { echo 'Ollama executable is unavailable; run repair-ollama.sh'; exit 2; }
        "$OLLAMA_BIN" pull qwen3:14b;;
      ollama-gpt-oss-120b-cloud)
        "$0" license-check "$CANDIDATE"
        OLLAMA_BIN="$(ollama_bin)" || { echo 'Ollama executable is unavailable; run repair-ollama.sh'; exit 2; }
        echo 'Ollama sign-in and a free/included quota confirmation are required.'
        "$OLLAMA_BIN" pull gpt-oss:120b-cloud;;
      *) echo "Unknown candidate: $CANDIDATE" >&2; "$0" list-candidates; exit 2;;
    esac
    echo "Candidate downloaded. It is not promoted automatically."
    ;;
  diagnose-ollama)
    echo "Endpoint: $OLLAMA_HOST"
    if ollama_http_ready; then
      curl -fsS "${OLLAMA_HOST%/}/api/tags" | jq '{state:"ready",models:[.models[]?|{name:(.name//.model),size,digest}]}'
      exit 0
    fi
    echo 'HTTP state: unreachable'
    if OLLAMA_BIN="$(ollama_bin)"; then echo "Executable: $OLLAMA_BIN"; else echo 'Executable: not found'; fi
    if command -v systemctl >/dev/null; then
      echo "System unit load state: $(systemctl show ollama.service -p LoadState --value 2>/dev/null || echo unknown)"
      echo "System unit active state: $(systemctl is-active ollama.service 2>/dev/null || true)"
      systemctl show ollama.service -p Environment --value 2>/dev/null | sed -E 's/(TOKEN|KEY|PASSWORD)=[^ ]+/\1=<redacted>/g' || true
    fi
    command -v ss >/dev/null && ss -ltn 2>/dev/null | awk '$4 ~ /:11434$/ {print "Listener:",$4}' || true
    echo 'Recovery: sudo /apps/solomonprime/app/scripts/repair-ollama.sh'
    exit 2
    ;;
  license-check)
    exec python3 "$(dirname "$0")/license-gate.py" "$CANDIDATE"
    ;;
  bench)
    [[ -x "$LLAMA_BENCH" ]] || { echo "Missing llama-bench"; exit 2; }
    LLAMA_SERVICE="${SOLOMON_LLAMA_SERVICE:-$(systemctl list-units --type=service --state=running --no-legend 2>/dev/null | awk '$1 ~ /llama/ {print $1; exit}')}"
    [[ -n "$LLAMA_SERVICE" ]] || { echo 'No running llama.cpp systemd service found.' >&2; exit 2; }
    sudo systemctl stop "$LLAMA_SERVICE"
    trap 'sudo systemctl start "$LLAMA_SERVICE" >/dev/null 2>&1 || true' EXIT
    ts="$(date -u +%Y%m%dT%H%M%SZ)"; out="/var/lib/solomonprime/model-lab/bench-$ts.txt"
    for model in "$MODEL_DIR"/Qwen3.5-27B-Q4_K_M.gguf "$MODEL_DIR"/Qwen3.5-27B-UD-Q4_K_XL.gguf; do
      [[ -r "$model" ]] || continue
      for split in 3,2 5,3 2,1; do
        echo "===== $(basename "$model") split=$split =====" | tee -a "$out"
        "$LLAMA_BENCH" -m "$model" -dev Vulkan0,Vulkan1 -sm layer -ts "$split" -ngl all -p 256 -n 64 -r 1 2>&1 | tee -a "$out" || true
      done
    done
    echo "Results: $out"
    ;;
  *) echo "Usage: $0 [inventory|diagnose-ollama|bench|list-candidates|license-check <candidate-id>|download <candidate-id>]"; exit 2;;
esac

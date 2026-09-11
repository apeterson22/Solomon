#!/usr/bin/env bash
set -euo pipefail

# SolomonPrime development/home PKI bootstrap.
# Private material is generated only under /etc/solomonprime/pki and is never
# written into the source tree. Jarvis2 is the temporary CA host until an
# operator-approved CA migration is performed.

PKI_ROOT="${SOLOMON_PKI_ROOT:-/etc/solomonprime/pki}"
CA_DIR="$PKI_ROOT/ca"
NODES_DIR="$PKI_ROOT/nodes"
TRUST_DIR="$PKI_ROOT/trust"
CA_CN="${SOLOMON_CA_CN:-SolomonPrime Home CA}"
CA_DAYS="${SOLOMON_CA_DAYS:-3650}"
LEAF_DAYS="${SOLOMON_LEAF_DAYS:-90}"

usage() {
  cat <<'EOF'
Usage:
  sudo scripts/setup-local-pki.sh init-ca
  sudo scripts/setup-local-pki.sh issue <node-name> [san ...]
  sudo scripts/setup-local-pki.sh verify <node-name>

SAN examples: DNS:jarvis2 DNS:jarvis2.askme.myhome IP:10.0.0.101

Private CA and node keys remain under /etc/solomonprime/pki with restrictive
permissions. Only ca.crt and explicitly exported public certificates should be
copied to other hosts.
EOF
}

require_root() { [[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo/root" >&2; exit 1; }; }
secure_dirs() {
  install -d -o root -g root -m 0700 "$PKI_ROOT" "$CA_DIR" "$NODES_DIR"
  install -d -o root -g root -m 0755 "$TRUST_DIR"
}

init_ca() {
  secure_dirs
  if [[ -e "$CA_DIR/ca.key" || -e "$CA_DIR/ca.crt" ]]; then
    echo "CA already exists; refusing to overwrite: $CA_DIR" >&2
    exit 2
  fi
  umask 077
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$CA_DIR/ca.key"
  openssl req -x509 -new -sha256 -key "$CA_DIR/ca.key" -days "$CA_DAYS" \
    -subj "/CN=$CA_CN" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" \
    -out "$CA_DIR/ca.crt"
  chmod 0600 "$CA_DIR/ca.key"
  chmod 0644 "$CA_DIR/ca.crt"
  cp "$CA_DIR/ca.crt" "$TRUST_DIR/solomonprime-ca.crt"
  chmod 0644 "$TRUST_DIR/solomonprime-ca.crt"
  openssl x509 -in "$CA_DIR/ca.crt" -noout -subject -fingerprint -sha256
  echo "CA initialized. Back up $CA_DIR offline; never copy ca.key to a node."
}

issue_node() {
  local node="${1:?node name required}"; shift || true
  [[ "$node" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid node name" >&2; exit 3; }
  [[ -f "$CA_DIR/ca.key" && -f "$CA_DIR/ca.crt" ]] || { echo "Initialize CA first" >&2; exit 4; }
  local dir="$NODES_DIR/$node"
  if [[ -e "$dir/tls.key" || -e "$dir/tls.crt" ]]; then
    echo "Identity already exists; refusing to overwrite: $dir" >&2
    exit 5
  fi
  install -d -o root -g root -m 0700 "$dir"
  local san="DNS:$node"
  local item
  for item in "$@"; do san+=",$item"; done
  umask 077
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$dir/tls.key"
  openssl req -new -sha256 -key "$dir/tls.key" -subj "/CN=$node" \
    -addext "subjectAltName=$san" -out "$dir/tls.csr"
  cat > "$dir/ext.cnf" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyAgreement
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=$san
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
  openssl x509 -req -sha256 -in "$dir/tls.csr" -CA "$CA_DIR/ca.crt" -CAkey "$CA_DIR/ca.key" \
    -CAcreateserial -days "$LEAF_DAYS" -extfile "$dir/ext.cnf" -out "$dir/tls.crt"
  cp "$CA_DIR/ca.crt" "$dir/ca.crt"
  chmod 0600 "$dir/tls.key"
  chmod 0644 "$dir/tls.crt" "$dir/ca.crt"
  rm -f "$dir/tls.csr" "$dir/ext.cnf"
  openssl verify -CAfile "$CA_DIR/ca.crt" "$dir/tls.crt"
  openssl x509 -in "$dir/tls.crt" -noout -subject -issuer -dates -ext subjectAltName
  echo "Issued dual-use TLS/mTLS identity: $dir"
}

verify_node() {
  local node="${1:?node name required}"
  openssl verify -CAfile "$CA_DIR/ca.crt" "$NODES_DIR/$node/tls.crt"
  openssl x509 -in "$NODES_DIR/$node/tls.crt" -noout -subject -issuer -dates -fingerprint -sha256
}

require_root
case "${1:-}" in
  init-ca) init_ca ;;
  issue) shift; issue_node "$@" ;;
  verify) shift; verify_node "$@" ;;
  *) usage; exit 64 ;;
esac

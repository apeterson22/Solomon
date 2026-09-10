#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }

APP_USER="${1:?usage: install-job-broker.sh <service-user>}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
id "$APP_USER" >/dev/null 2>&1 || { echo "User $APP_USER not found" >&2; exit 2; }

getent group solomonprime >/dev/null || groupadd --system solomonprime
usermod -aG solomonprime "$APP_USER"
if ! id solomonjob >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --gid solomonprime solomonjob
else
  usermod -g solomonprime solomonjob
fi
for group_name in video render; do
  getent group "$group_name" >/dev/null && usermod -aG "$group_name" solomonjob || true
done

install -d -o "$APP_USER" -g solomonprime -m 0770 /apps/solomonprime-jobs
install -d -o root -g root -m 0755 /usr/local/libexec
install -d -o root -g root -m 0755 /etc/solomonprime
install -d -o root -g root -m 0755 /etc/tmpfiles.d
install -o root -g root -m 0755 "$SRC/scripts/solomon-job-runner.py" /usr/local/libexec/solomon-job-runner
install -o root -g root -m 0755 "$SRC/scripts/solomon-job-broker.py" /usr/local/libexec/solomon-job-broker
install -o root -g root -m 0755 "$SRC/scripts/solomon-job-broker-client.py" /usr/local/libexec/solomon-job-broker-client

APP_UID="$(id -u "$APP_USER")"
JOB_GID="$(getent group solomonprime | cut -d: -f3)"
printf 'SOLOMON_JOB_CLIENT_UID=%s\nSOLOMON_JOB_GROUP_GID=%s\n' "$APP_UID" "$JOB_GID" >/etc/solomonprime/job-broker.env
chown root:root /etc/solomonprime/job-broker.env
chmod 0600 /etc/solomonprime/job-broker.env

install -o root -g root -m 0644 "$SRC/systemd/solomon-job-broker.socket" /etc/systemd/system/solomon-job-broker.socket
install -o root -g root -m 0644 "$SRC/systemd/solomon-job-broker@.service" /etc/systemd/system/solomon-job-broker@.service
install -o root -g root -m 0644 "$SRC/systemd/solomon-job-broker.tmpfiles" /etc/tmpfiles.d/solomon-job-broker.conf
systemd-tmpfiles --create /etc/tmpfiles.d/solomon-job-broker.conf

mkdir -p /etc/systemd/system/solomonprime.service.d
DROPIN_TMP="$(mktemp /tmp/solomonprime-v032-conf.XXXXXX)"
trap 'rm -f "$DROPIN_TMP"' EXIT
command tee "$DROPIN_TMP" >/dev/null <<'EOF'
[Unit]
RequiresMountsFor=/apps/solomonprime-jobs
After=solomon-job-broker.socket
Wants=solomon-job-broker.socket

[Service]
SupplementaryGroups=solomonprime
Environment=SOLOMON_JOB_BROKER_SOCKET=/run/solomonprime/job-broker.sock
ReadWritePaths=
ReadWritePaths=/apps/solomonprime /apps/solomonprime-jobs /var/lib/solomonprime /var/log/solomonprime
ReadWritePaths=-/apps/solomonprime-development
EOF
install -o root -g root -m 0644 "$DROPIN_TMP" /etc/systemd/system/solomonprime.service.d/v032.conf
rm -f "$DROPIN_TMP"
trap - EXIT

systemctl daemon-reload
systemctl enable --now solomon-job-broker.socket
for _ in $(seq 1 20); do
  [[ -S /run/solomonprime/job-broker.sock ]] && exit 0
  sleep 0.25
done
echo 'Job broker socket did not become ready' >&2
exit 3

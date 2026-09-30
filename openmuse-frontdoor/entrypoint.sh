#!/bin/sh
# OpenMuse frontdoor entrypoint. Runs as root, then drops privileges.
#  - Grants the openmuse user access to the host Docker socket so the
#    optional agent computer can be managed (COMPUTER_ENABLED=true).
#  - Builds the computer image on the host on first run if it is missing.
#  - Execs the server as the unprivileged openmuse user.
set -eu

if [ "${COMPUTER_ENABLED:-}" = "true" ] && [ -S /var/run/docker.sock ]; then
  DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
  GROUP_NAME="$(getent group "$DOCKER_GID" | cut -d: -f1 || true)"
  if [ -z "$GROUP_NAME" ]; then
    GROUP_NAME="docker-host"
    groupadd -o -g "$DOCKER_GID" "$GROUP_NAME"
  fi
  usermod -aG "$GROUP_NAME" openmuse
  IMAGE="${COMPUTER_IMAGE:-openmuse-computer:local}"
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Building agent computer image $IMAGE on the host..."
    docker build -t "$IMAGE" /app/computer-src
  fi
fi

if command -v runuser >/dev/null 2>&1; then
  exec runuser -u openmuse -- "$@"
else
  exec setpriv --reuid openmuse --regid openmuse --clear-groups "$@"
fi

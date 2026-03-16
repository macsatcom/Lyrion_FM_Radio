#!/bin/bash
set -e

# Apply defaults for any env vars not set via docker-compose / .env
: "${ICECAST_MODE:=internal}"   # 'internal' = run Icecast in this container
                                # 'external' = use an existing Icecast on the network
: "${ICECAST_SOURCE:=hackme}"
: "${ICECAST_ADMIN_PASS:=hackme_admin}"
: "${ICECAST_MOUNT:=/fm}"
: "${ICECAST_PORT:=8000}"
: "${STARTUP_FREQ:=90800000}"
: "${DAEMON_PORT:=8080}"
: "${RTL_DEVICE:=0}"

export ICECAST_SOURCE ICECAST_ADMIN_PASS ICECAST_MOUNT ICECAST_PORT
export STARTUP_FREQ DAEMON_PORT RTL_DEVICE

if [ "$ICECAST_MODE" = "internal" ]; then
    # Always reach Icecast on localhost when running inside the container
    export ICECAST_HOST=localhost

    # Generate icecast.xml from template (substitutes $ICECAST_SOURCE and $ICECAST_ADMIN_PASS)
    envsubst '${ICECAST_SOURCE} ${ICECAST_ADMIN_PASS}' \
        < /etc/icecast.xml.template \
        > /etc/icecast2/icecast.xml

    # Start Icecast in the background
    echo "[entrypoint] Starting Icecast on port ${ICECAST_PORT}..."
    icecast2 -c /etc/icecast2/icecast.xml &

    # Give Icecast a moment to bind its socket before ffmpeg connects
    sleep 2

elif [ "$ICECAST_MODE" = "external" ]; then
    if [ -z "${ICECAST_HOST:-}" ]; then
        echo "[entrypoint] ERROR: ICECAST_MODE=external but ICECAST_HOST is not set." >&2
        exit 1
    fi
    export ICECAST_HOST
    echo "[entrypoint] Using external Icecast at ${ICECAST_HOST}:${ICECAST_PORT}${ICECAST_MOUNT}"

else
    echo "[entrypoint] ERROR: Unknown ICECAST_MODE='${ICECAST_MODE}'. Use 'internal' or 'external'." >&2
    exit 1
fi

echo "[entrypoint] Starting FM daemon (device=${RTL_DEVICE}, freq=${STARTUP_FREQ} Hz)..."
exec python3 /usr/local/bin/fm-daemon.py --device "$RTL_DEVICE"

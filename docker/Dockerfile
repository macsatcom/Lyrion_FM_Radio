# FM Radio Daemon — Docker image
# Includes: redsea (built from source), ffmpeg, Icecast2, Python3
# Uses rtl_fm (from rtl-sdr package) for FM demodulation.
#
# Build context must be the repository root:
#   docker build -f docker/Dockerfile -t fm-radio .
#
# Normally you use docker-compose instead — see docker-compose.yml.

FROM debian:bookworm-slim

# ── Runtime dependencies ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        ffmpeg \
        icecast2 \
        rtl-sdr \
        libusb-1.0-0 \
        libsndfile1 \
        libliquid1 \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

# ── Build redsea from source ──────────────────────────────────────────────────
# windytan/redsea — FM RDS decoder; reads rtl_fm output and emits JSON lines.
# Requires --recurse-submodules for the nlohmann/json submodule.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates meson ninja-build build-essential pkg-config \
        libsndfile1-dev libliquid-dev \
    && git clone --depth 1 --recurse-submodules https://github.com/windytan/redsea.git /tmp/redsea \
    && cd /tmp/redsea \
    && meson setup --buildtype=release build \
    && ninja -C build \
    && (install -m 755 build/src/redsea /usr/local/bin/redsea 2>/dev/null || install -m 755 build/redsea /usr/local/bin/redsea) \
    && rm -rf /tmp/redsea \
    && apt-get purge -y git meson ninja-build build-essential pkg-config libsndfile1-dev libliquid-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# ── Application files ─────────────────────────────────────────────────────────
COPY daemon/fm-daemon.py         /usr/local/bin/fm-daemon.py
COPY docker/icecast.xml.template /etc/icecast.xml.template
COPY docker/entrypoint.sh        /entrypoint.sh

RUN chmod +x /usr/local/bin/fm-daemon.py /entrypoint.sh

# 8080 = FM Daemon HTTP API, 8000 = Icecast stream
EXPOSE 8080 8000

ENTRYPOINT ["/entrypoint.sh"]

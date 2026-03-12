# FM Radio Daemon — Docker image
# Includes: SoftFM (built from source), ffmpeg, Icecast2, Python3
#
# Build context must be the repository root:
#   docker build -f docker/Dockerfile -t fm-radio .
#
# Normally you use docker-compose instead — see docker-compose.yml.

FROM debian:bookworm-slim

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        ffmpeg \
        icecast2 \
        rtl-sdr \
        librtlsdr-dev \
        libusb-1.0-0 \
        cmake \
        build-essential \
        git \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

# ── Build SoftFM from source ──────────────────────────────────────────────────
# Using jorisvr/SoftFM — produces the 'softfm' binary used by the daemon.
RUN git clone --depth 1 https://github.com/jorisvr/SoftFM.git /tmp/softfm \
    && cmake -S /tmp/softfm -B /tmp/softfm/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/softfm/build -j$(nproc) \
    && install -m 755 /tmp/softfm/build/softfm /usr/local/bin/softfm \
    && rm -rf /tmp/softfm

# ── Application files ─────────────────────────────────────────────────────────
COPY daemon/fm-daemon.py        /usr/local/bin/fm-daemon.py
COPY docker/icecast.xml.template /etc/icecast.xml.template
COPY docker/entrypoint.sh        /entrypoint.sh

RUN chmod +x /usr/local/bin/fm-daemon.py /entrypoint.sh

# 8080 = FM Daemon HTTP API, 8000 = Icecast stream
EXPOSE 8080 8000

ENTRYPOINT ["/entrypoint.sh"]

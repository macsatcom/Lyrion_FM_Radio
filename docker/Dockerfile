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
        ca-certificates \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

# ── Build NGSoftFM from source ────────────────────────────────────────────────
# Using f4exb/ngsoftfm — produces the 'ngsoftfm' binary; installed as 'softfm'.
RUN git clone --depth 1 https://github.com/f4exb/ngsoftfm.git /tmp/ngsoftfm \
    && cmake -S /tmp/ngsoftfm -B /tmp/ngsoftfm/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/ngsoftfm/build -j$(nproc) \
    && install -m 755 /tmp/ngsoftfm/build/ngsoftfm /usr/local/bin/softfm \
    && rm -rf /tmp/ngsoftfm

# ── Application files ─────────────────────────────────────────────────────────
COPY daemon/fm-daemon.py        /usr/local/bin/fm-daemon.py
COPY docker/icecast.xml.template /etc/icecast.xml.template
COPY docker/entrypoint.sh        /entrypoint.sh

RUN chmod +x /usr/local/bin/fm-daemon.py /entrypoint.sh

# 8080 = FM Daemon HTTP API, 8000 = Icecast stream
EXPOSE 8080 8000

ENTRYPOINT ["/entrypoint.sh"]

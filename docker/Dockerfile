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
        pkg-config \
        libasound2-dev \
        libboost-program-options-dev \
        libhackrf-dev \
        libairspy-dev \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

# ── Copy build-time helper before compiling NGSoftFM ─────────────────────────
COPY docker/patch-cmake.py /tmp/patch-cmake.py

# ── Build NGSoftFM from source ────────────────────────────────────────────────
# Using f4exb/ngsoftfm — produces the 'softfm' binary used by the daemon.
# BladeRFSource.cpp uses a deprecated API incompatible with Debian bookworm's
# libbladerf; we only need RTL-SDR, so it is patched out before building.
RUN git clone --depth 1 https://github.com/f4exb/ngsoftfm.git /tmp/ngsoftfm \
    && python3 /tmp/patch-cmake.py /tmp/ngsoftfm \
    && cmake -S /tmp/ngsoftfm -B /tmp/ngsoftfm/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/ngsoftfm/build --target softfm -j$(nproc) \
    && install -m 755 /tmp/ngsoftfm/build/softfm /usr/local/bin/softfm \
    && rm -rf /tmp/ngsoftfm /tmp/patch-cmake.py

# ── Application files ─────────────────────────────────────────────────────────
COPY daemon/fm-daemon.py         /usr/local/bin/fm-daemon.py
COPY docker/icecast.xml.template /etc/icecast.xml.template
COPY docker/entrypoint.sh        /entrypoint.sh

RUN chmod +x /usr/local/bin/fm-daemon.py /entrypoint.sh

# 8080 = FM Daemon HTTP API, 8000 = Icecast stream
EXPOSE 8080 8000

ENTRYPOINT ["/entrypoint.sh"]

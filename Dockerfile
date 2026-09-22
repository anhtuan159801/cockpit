# Multi-stage build for cockpit on Koyeb with optional Supabase bridge overlay.
# Stage 1 (web):        build dist/ from source with Node 22.
# Stage 2 (pydeps):     install python3-cryptography for Supabase sync (final image is FROM scratch).
# Stage 3 (bridge):     optional — copy custom bridge + vendor sources when BUILD_BRIDGE=1.
# Final:                FROM quay.io/cockpit/ws + dist/ + custom/ overlay.

# ---------------------------------------------------------------------------
# Stage 1 — web build
# ---------------------------------------------------------------------------
FROM node:22 AS web
WORKDIR /src

# Copy package manifests first so dependency layer is cached.
COPY package.json ./

# Install deps and generate package-lock.json (no .git present → tools/node-modules
# takes the no-git branch; package-lock is created/updated by npm install).
RUN npm install

# Copy full source (reset mtime so make_package_lock_json sees package-lock newer).
COPY . .

# Re-run install to sync lock with any changes introduced by full COPY, then
# force package-lock.json mtime newer than package.json for the no-git branch.
RUN npm install && touch package-lock.json

# Build dist/ (po plugin reads po/*.po directly — no .pot / POTFILES.in needed).
RUN node build.js

# ---------------------------------------------------------------------------
# Stage 2 — python deps for Supabase sync (cryptography)
# Install via pip --target so native .so wheels land in one tree (dnf paths
# differ across lib/lib64 and the old cp || true failed silently).
# ---------------------------------------------------------------------------
FROM fedora:43 AS pydeps
RUN dnf install -y python3-pip python3-setuptools && dnf clean all
RUN mkdir -p /custom/pylibs && \
    pip3 install --no-cache-dir --target /custom/pylibs cryptography && \
    test -d /custom/pylibs/cryptography && \
    python3 -c "import sys; sys.path.insert(0, '/custom/pylibs'); from cryptography.hazmat.primitives.ciphers.aead import AESGCM; print('ok')"

# ---------------------------------------------------------------------------
# Stage 3 — optional bridge overlay (BUILD_BRIDGE=1)
# Skipped by default: fork == upstream, stock bridge in quay.io/cockpit/ws is identical.
# Enable when fork diverges and a patched bridge is needed.
# ---------------------------------------------------------------------------
FROM alpine AS bridge
ARG BUILD_BRIDGE=0
WORKDIR /tmp

# When enabled, clone vendor sources at pinned SHAs (works even if build context
# lacks submodule content or .git). SHAs verified against git submodule status.
# beipack        4217d8ade60885a18156e86e566b808edad000ee
# ferny          73dd163349bf048d3d0a36f43228a9d052104e30
# systemd_ctypes a627fb8b2b58e6dead4ab85aa14abb41d1a48397
RUN if [ "$BUILD_BRIDGE" = "1" ]; then \
      apk add --no-cache git && \
      mkdir -p /custom/vendor && \
      git clone --depth 1 https://github.com/jgiardino/beipack.git /tmp/beipack && \
      git -C /tmp/beipack fetch --depth 1 origin 4217d8ade60885a18156e86e566b808edad000ee && \
      git -C /tmp/beipack checkout 4217d8ade60885a18156e86e566b808edad000ee && \
      cp -a /tmp/beipack /custom/vendor/beipack && \
      git clone --depth 1 https://github.com/jmatth/ferny.git /tmp/ferny && \
      git -C /tmp/ferny fetch --depth 1 origin 73dd163349bf048d3d0a36f43228a9d052104e30 && \
      git -C /tmp/ferny checkout 73dd163349bf048d3d0a36f43228a9d052104e30 && \
      cp -a /tmp/ferny /custom/vendor/ferny && \
      git clone --depth 1 https://github.com/cockpit-project/systemd_ctypes.git /tmp/systemd_ctypes && \
      git -C /tmp/systemd_ctypes fetch --depth 1 origin a627fb8b2b58e6dead4ab85aa14abb41d1a48397 && \
      git -C /tmp/systemd_ctypes checkout a627fb8b2b58e6dead4ab85aa14abb41d1a48397 && \
      cp -a /tmp/systemd_ctypes /custom/vendor/systemd_ctypes && \
      rm -rf /tmp/beipack /tmp/ferny /tmp/systemd_ctypes; \
    else \
      mkdir -p /custom/vendor; \
    fi

# ---------------------------------------------------------------------------
# Final image
# ---------------------------------------------------------------------------
FROM quay.io/cockpit/ws:latest

ARG BUILD_BRIDGE=0

# Python path: cryptography (Supabase sync) + optional bridge sources.
ENV PYTHONPATH=/custom/pylibs:/custom/bridge

# Web assets → standard cockpit location.
COPY --from=web /src/dist/ /usr/share/cockpit/

# Python crypto deps for Supabase sync.
COPY --from=pydeps /custom/pylibs/ /custom/pylibs/

# Custom runtime: entrypoint + Supabase sync + optional bridge/vendor.
COPY custom/ /container/custom/
RUN chmod +x /container/custom/entrypoint.py

# Optional bridge overlay (empty unless BUILD_BRIDGE=1).
COPY --from=bridge /custom/vendor/ /custom/vendor/
COPY src/cockpit/ /custom/bridge/cockpit/

# Rewrite _vendor symlinks to resolve under /custom layout when bridge is active.
# Stock symlinks point to ../../../vendor/*/src/* which resolves correctly from
# /custom/bridge/cockpit/_vendor/ → /custom/vendor/*/src/*.
RUN if [ "$BUILD_BRIDGE" = "1" ]; then \
      for d in bei ferny systemd_ctypes; do \
        src_file="/custom/vendor/${d}/src"; \
        [ -e "$src_file" ] && ln -sfn "$src_file" "/custom/bridge/cockpit/_vendor/${d}" || true; \
      done; \
    fi

# No Docker HEALTHCHECK: scratch-based ws image has no wget/curl.
# Koyeb probes the service port / login path from the deployment config.

ENTRYPOINT ["/container/custom/entrypoint.py"]

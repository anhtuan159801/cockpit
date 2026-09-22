# Multi-stage build for cockpit on Koyeb with optional Supabase bridge overlay.
# Stage 1 (web):        build dist/ from source with Node 22.
# Stage 2 (pydeps):     install python3-cryptography for Supabase sync.
# Stage 3 (bridge):     optional — vendor/bridge sources when BUILD_BRIDGE=1.
# Final:                fedora:43 + cockpit packages + dist/ + custom/ overlay.

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
# Stage 3 — bridge overlay placeholder.
# Koyeb's deploy archive omits vendor/ by default (--archive-ignore-dir), so
# this stage only stages empty dirs. To build with BUILD_BRIDGE=1, deploy with
# --archive-ignore-dir .git --archive-ignore-dir node_modules (include vendor/)
# and restore COPY vendor/ + COPY src/cockpit/ here.
# ---------------------------------------------------------------------------
FROM alpine AS bridge
RUN mkdir -p /out/bridge /out/vendor

# ---------------------------------------------------------------------------
# Final image — Fedora base so cockpit-session (PAM local auth) is present.
# quay.io/cockpit/ws strips cockpit-session and shadow-utils; a full Fedora
# install keeps local password login working without SSH loopback/sshd.
# ---------------------------------------------------------------------------
FROM fedora:43

ARG BUILD_BRIDGE=0

# Cockpit + local login tools + python for entrypoint/sync + dbus (system bus).
RUN dnf install -y \
      --setopt=install_weak_deps=False \
      cockpit-ws cockpit-bridge openssh-clients shadow-utils passwd python3 \
      dbus-daemon dbus-common \
    && dnf clean all \
    && rm -rf /var/cache/dnf \
    && mkdir -p /var/log /run/dbus /var/lib/dbus \
    && touch /var/log/btmp /var/log/wtmp /var/log/lastlog \
    && chmod 664 /var/log/btmp /var/log/wtmp \
    && chmod 664 /var/log/lastlog \
    && if [ ! -f /var/lib/dbus/machine-id ] && [ ! -f /etc/machine-id ]; then \
         python3 -c "import uuid; open('/var/lib/dbus/machine-id','w').write(uuid.uuid4().hex)"; \
       fi \
    && test -x /usr/bin/dbus-daemon

# Python path: cryptography always; bridge sources only when BUILD_BRIDGE=1.
ENV PYTHONPATH=/custom/pylibs

# Web assets → standard cockpit location (overrides dnf's dist/ with fork build).
COPY --from=web /src/dist/ /usr/share/cockpit/

# Python crypto deps for Supabase sync.
COPY --from=pydeps /custom/pylibs/ /custom/pylibs/

# Custom runtime: entrypoint + Supabase sync.
COPY custom/ /container/custom/
RUN chmod +x /container/custom/entrypoint.py

# Optional bridge overlay (empty unless BUILD_BRIDGE=1).
COPY --from=bridge /out/vendor/ /custom/vendor/
COPY --from=bridge /out/bridge/ /custom/bridge/
RUN if [ "$BUILD_BRIDGE" = "1" ]; then \
      ENV_PYTHONPATH="$(printf '/custom/bridge%s' ":${PYTHONPATH}")"; \
      echo "PYTHONPATH=${ENV_PYTHONPATH}" >> /etc/environment; \
      # Bake into a file the entrypoint reads; ENV can't be conditional at runtime.
      echo "/custom/bridge" > /custom/bridge.path; \
    fi

# Local PAM stack for cockpit-session (dnf may already install this; ensure present).
COPY tools/cockpit.pam /etc/pam.d/cockpit

# No Docker HEALTHCHECK: Koyeb probes the service port /login path.

ENTRYPOINT ["/container/custom/entrypoint.py"]

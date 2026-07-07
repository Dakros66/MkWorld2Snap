#!/bin/sh
# Prepare writable runtime mounts before starting the local API process.
set -eu

UID_TARGET="${APP_UID:-1000}"
GID_TARGET="${APP_GID:-1000}"

for runtime_dir in \
    /app/tmp \
    /app/tmp_failed \
    /app/user_profiles \
    /app/rules \
    /app/target_profiles
do
    if [ -d "$runtime_dir" ]; then
        chown -R "${UID_TARGET}:${GID_TARGET}" "$runtime_dir" 2>/dev/null || true
    fi
done

exec /usr/bin/tini -- gosu "${UID_TARGET}:${GID_TARGET}" "$@"

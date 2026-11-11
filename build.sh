#!/usr/bin/bash
# MilizOS - orquestrador de build (podman rootless, sem sudo)
#   ./build.sh [rpms|rootfs|configure|image|all|shell]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=milizos-builder
podman image exists $IMG || podman build -t $IMG -f builder/Containerfile builder
run() { podman run --rm --privileged -e EROFS_OPTS -e ZLEVEL --network host -v "$PWD":/work -w /work $IMG "$@"; }
case "${1:-all}" in
    rpms)      run build/stage-rpms.sh ;;
    rootfs)    run build/stage-rootfs.sh ;;
    configure) run build/stage-configure.sh "${@:2}" ;;
    image)     run build/stage-image.sh ;;
    all)       run build/stage-rpms.sh; run build/stage-rootfs.sh; run build/stage-configure.sh; run build/stage-image.sh ;;
    shell)     podman run --rm -it --privileged --network host -v "$PWD":/work -w /work $IMG bash ;;
    *) echo "uso: $0 [rpms|rootfs|configure|image|all|shell]"; exit 64 ;;
esac

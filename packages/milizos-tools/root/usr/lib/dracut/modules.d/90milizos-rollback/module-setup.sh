#!/usr/bin/bash
# MilizOS: rollback para um checkpoint ainda no initramfs (milizos.rollback=ID)
check() { require_binaries btrfs || return 1; return 0; }
depends() { echo btrfs; }
install() {
    inst_multiple btrfs mv mkdir mount umount
    inst_hook pre-mount 20 "$moddir/milizos-rollback.sh"
}

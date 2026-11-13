#!/usr/bin/bash
# Heloisa: volta a um ponto (heloisa.rollback=ID) ou troca de ramo (heloisa.branch=NOME) ainda no initramfs
check() { require_binaries btrfs || return 1; return 0; }
depends() { echo btrfs; }
install() {
    inst_multiple btrfs mv mkdir mount umount
    inst_hook pre-mount 20 "$moddir/heloisa-rollback.sh"
}

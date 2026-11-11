#!/bin/sh
# Troca o subvolume "root" pelo checkpoint pedido antes de a raiz ser montada.
# O estado que estava em uso e preservado em snapshots/pre-rollback-N.
type getarg > /dev/null 2>&1 || . /lib/dracut-lib.sh
nos_id=$(getarg milizos.rollback=)
if [ -n "$nos_id" ]; then
    nos_r=$(getarg root=)
    case "$nos_r" in
        UUID=*) nos_dev=/dev/disk/by-uuid/${nos_r#UUID=} ;;
        LABEL=*) nos_dev=/dev/disk/by-label/${nos_r#LABEL=} ;;
        *) nos_dev=$nos_r ;;
    esac
    nos_t=/run/milizos-top
    mkdir -p $nos_t
    if mount -t btrfs -o subvolid=5 "$nos_dev" $nos_t; then
        if [ -d "$nos_t/snapshots/$nos_id/root" ]; then
            nos_n=1
            while [ -e "$nos_t/snapshots/pre-rollback-$nos_n" ]; do nos_n=$((nos_n + 1)); done
            mkdir -p "$nos_t/snapshots/pre-rollback-$nos_n"
            if [ ! -d "$nos_t/root" ] || mv "$nos_t/root" "$nos_t/snapshots/pre-rollback-$nos_n/root"; then
                if btrfs subvolume snapshot "$nos_t/snapshots/$nos_id/root" "$nos_t/root" > /dev/null; then
                    info "MilizOS: sistema revertido para o checkpoint #$nos_id"
                else
                    warn "MilizOS: falha ao restaurar o checkpoint #$nos_id; mantendo o sistema atual"
                    [ -d "$nos_t/snapshots/pre-rollback-$nos_n/root" ] && mv "$nos_t/snapshots/pre-rollback-$nos_n/root" "$nos_t/root"
                fi
            fi
        else
            warn "MilizOS: checkpoint #$nos_id nao encontrado"
        fi
        umount $nos_t
    else
        warn "MilizOS: rollback: nao foi possivel montar $nos_dev"
    fi
fi

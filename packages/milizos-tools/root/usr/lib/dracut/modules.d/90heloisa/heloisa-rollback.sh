#!/bin/sh
# Troca o subvolume "root" pelo ponto pedido antes de a raiz ser montada.
# O estado que estava em uso e preservado em snapshots/pre-rollback-N.
type getarg > /dev/null 2>&1 || . /lib/dracut-lib.sh
nos_id=$(getarg heloisa.rollback=)
if [ -n "$nos_id" ]; then
    nos_r=$(getarg root=)
    case "$nos_r" in
        UUID=*) nos_dev=/dev/disk/by-uuid/${nos_r#UUID=} ;;
        LABEL=*) nos_dev=/dev/disk/by-label/${nos_r#LABEL=} ;;
        *) nos_dev=$nos_r ;;
    esac
    nos_t=/run/heloisa-top
    mkdir -p $nos_t
    if mount -t btrfs -o subvolid=5 "$nos_dev" $nos_t; then
        if [ -d "$nos_t/snapshots/$nos_id/root" ]; then
            nos_n=1
            while [ -e "$nos_t/snapshots/pre-rollback-$nos_n" ]; do nos_n=$((nos_n + 1)); done
            mkdir -p "$nos_t/snapshots/pre-rollback-$nos_n"
            if [ ! -d "$nos_t/root" ] || mv "$nos_t/root" "$nos_t/snapshots/pre-rollback-$nos_n/root"; then
                if btrfs subvolume snapshot "$nos_t/snapshots/$nos_id/root" "$nos_t/root" > /dev/null; then
                    info "Heloisa: sistema de volta ao ponto #$nos_id"
                else
                    warn "Heloisa: falha ao restaurar o ponto #$nos_id; mantendo o sistema atual"
                    [ -d "$nos_t/snapshots/pre-rollback-$nos_n/root" ] && mv "$nos_t/snapshots/pre-rollback-$nos_n/root" "$nos_t/root"
                fi
            fi
        else
            warn "Heloisa: ponto #$nos_id nao encontrado"
        fi
        umount $nos_t
    else
        warn "Heloisa: rollback: nao foi possivel montar $nos_dev"
    fi
fi

# Ramos: heloisa.branch=NOME inicia outro ramo da maquina. O ramo que estava em uso e guardado
# em branches/<atual>/root e o escolhido assume o lugar de "root".
nos_b=$(getarg heloisa.branch=)
if [ -n "$nos_b" ]; then
    nos_r=$(getarg root=)
    case "$nos_r" in
        UUID=*) nos_dev=/dev/disk/by-uuid/${nos_r#UUID=} ;;
        LABEL=*) nos_dev=/dev/disk/by-label/${nos_r#LABEL=} ;;
        *) nos_dev=$nos_r ;;
    esac
    nos_t=/run/heloisa-top
    mkdir -p $nos_t
    if mount -t btrfs -o subvolid=5 "$nos_dev" $nos_t; then
        nos_c=principal
        [ -s "$nos_t/snapshots/.state/branch" ] && read -r nos_c < "$nos_t/snapshots/.state/branch"
        if [ "$nos_c" = "$nos_b" ]; then
            info "Heloisa: o ramo $nos_b ja e o que esta em uso"
        elif [ -d "$nos_t/branches/$nos_b/root" ] && [ -d "$nos_t/root" ] && [ ! -e "$nos_t/branches/$nos_c/root" ]; then
            mkdir -p "$nos_t/branches/$nos_c" "$nos_t/snapshots/.state"
            if mv "$nos_t/root" "$nos_t/branches/$nos_c/root"; then
                if mv "$nos_t/branches/$nos_b/root" "$nos_t/root"; then
                    echo "$nos_b" > "$nos_t/snapshots/.state/branch"
                    info "Heloisa: iniciando o ramo $nos_b (o ramo $nos_c ficou guardado)"
                else
                    mv "$nos_t/branches/$nos_c/root" "$nos_t/root"
                    warn "Heloisa: nao foi possivel trocar para o ramo $nos_b; mantendo $nos_c"
                fi
            fi
        else
            warn "Heloisa: ramo $nos_b nao encontrado; mantendo o ramo $nos_c"
        fi
        umount $nos_t
    else
        warn "Heloisa: ramos: nao foi possivel montar $nos_dev"
    fi
fi

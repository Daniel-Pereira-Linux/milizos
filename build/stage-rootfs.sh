#!/usr/bin/bash
# Monta o sistema em cache/rootfs (roda no container).
#  1) o dnf resolve as dependencias e baixa tudo para cache/dnf (--downloadonly)
#  2) o rpm instala numa transacao unica. O dnf5 executa os scriptlets %sysusers ja dentro
#     do chroot, onde o systemd-sysusers ainda nao existe; o rpm os executa de fora (--root).
set -euo pipefail
cd /work
# esconde o SELinux do host: o plugin do rpm tentaria trocar de contexto e o exec seria negado
mountpoint -q /sys/fs/selinux && mount -t tmpfs tmpfs /sys/fs/selinux || true
ROOT=/work/cache/rootfs; PK=/work/cache/dnf
PKGS=$(grep -hv '^#' build/packages.list build/packages-extra.list | tr '\n' ' ')
[ -e $ROOT/usr ] && { echo "rootfs ja existe; remova com: podman unshare rm -rf cache/rootfs"; exit 1; }
mkdir -p $PK /tmp/resolve
dnf -y --installroot=/tmp/resolve --use-host-config --releasever=44 \
    --setopt=install_weak_deps=False --setopt=keepcache=True \
    --setopt=cachedir=$PK --setopt=system_cachedir=$PK \
    --setopt=max_parallel_downloads=16 --setopt=retries=20 --setopt=timeout=60 \
    --repofrompath=milizos,file:///work/out/repo --setopt=milizos.gpgcheck=0 \
    --setopt=milizos.metadata_expire=0 \
    --exclude='fedora-release*' --exclude='generic-release*' --exclude='fedora-logos*' \
    install --downloadonly --skip-unavailable --skip-broken $PKGS > /tmp/resolve.log 2>&1 || { tail -30 /tmp/resolve.log; exit 1; }
grep -a 'No match for argument' /tmp/resolve.log || true
# lista exata da transacao: NEVRA -> arquivo
awk '$2 ~ /^(x86_64|noarch)$/ && $3 ~ /^[0-9]+:/ {split($3,v,":"); print $1"-"v[2]"."$2".rpm"}' /tmp/resolve.log | sort -u > /tmp/want.txt
: > /tmp/files.txt
while read -r f; do
    p=$(find $PK /work/out/repo -name "$f" -print -quit)
    [ -n "$p" ] || { echo "faltando no cache: $f"; exit 1; }
    echo "$p" >> /tmp/files.txt
done < /tmp/want.txt
echo "transacao: $(wc -l < /tmp/files.txt) pacotes"
mkdir -p $ROOT
rpm --root $ROOT --import /etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-44-x86_64 2>/dev/null || true
rpm --root $ROOT -i --define '_pkgverify_level digest' $(cat /tmp/files.txt) 2>&1 | grep -v '^warning: .*NOKEY' | tail -40
n=$(rpm --root $ROOT -qa | wc -l)
[ "$n" -ge "$(wc -l < /tmp/files.txt)" ] || { echo "instalados $n de $(wc -l < /tmp/files.txt)"; exit 1; }
echo "ROOTFS-OK $(du -sh $ROOT 2>/dev/null | cut -f1) $n pacotes"

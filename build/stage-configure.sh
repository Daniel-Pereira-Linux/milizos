#!/usr/bin/bash
# Configura o rootfs e gera o initramfs live (roda no container)
set -euo pipefail
cd /work
# esconde o SELinux do host: o plugin do rpm tentaria trocar de contexto e o exec seria negado
mountpoint -q /sys/fs/selinux && mount -t tmpfs tmpfs /sys/fs/selinux || true
ROOT=/work/cache/rootfs; ISO=/work/cache/iso
[ -d $ROOT/usr ] || { echo "rootfs ausente"; exit 1; }

# reinstala os pacotes do MilizOS se foram reconstruidos
if [ "${1:-}" = "--refresh" ]; then
    rpm --root $ROOT -U --replacepkgs --define '_pkgverify_level digest' /work/out/repo/*.rpm
fi

for m in proc sys dev; do mountpoint -q $ROOT/$m || mount --rbind /$m $ROOT/$m; done
trap 'for m in dev sys proc; do umount -Rl $ROOT/$m 2>/dev/null || true; done' EXIT
C() { chroot $ROOT "$@"; }

# --- refaz o que os scriptlets nao conseguiram sem /proc e /dev
C ldconfig
C systemd-hwdb update || true
C journalctl --update-catalog || true
C fc-cache -f >/dev/null 2>&1 || true
C update-mime-database /usr/share/mime >/dev/null 2>&1 || true
C gio-querymodules-64 /usr/lib64/gio/modules 2>/dev/null || true
C gdk-pixbuf-query-loaders-64 --update-cache 2>/dev/null || true
C update-ca-trust 2>/dev/null || true
C systemd-sysusers 2>/dev/null || true
C systemd-tmpfiles --create --boot 2>/dev/null || true

# --- servicos
systemctl --root=$ROOT preset-all >/dev/null 2>&1 || true
systemctl --root=$ROOT --global preset-all >/dev/null 2>&1 || true
ln -sfn /usr/lib/systemd/system/graphical.target $ROOT/etc/systemd/system/default.target

# --- identidade e padroes
echo milizos > $ROOT/etc/hostname
echo 'LANG=pt_BR.UTF-8' > $ROOT/etc/locale.conf
printf 'KEYMAP="br-abnt2"\nFONT="eurlatgr"\nXKBLAYOUT="br"\n' > $ROOT/etc/vconsole.conf
mkdir -p $ROOT/etc/X11/xorg.conf.d
printf 'Section "InputClass"\n        Identifier "system-keyboard"\n        MatchIsKeyboard "on"\n        Option "XkbLayout" "br"\nEndSection\n' > $ROOT/etc/X11/xorg.conf.d/00-keyboard.conf
ln -sfn ../usr/share/zoneinfo/America/Sao_Paulo $ROOT/etc/localtime
: > $ROOT/etc/machine-id
: > $ROOT/etc/fstab
ln -sfn ../run/systemd/resolve/stub-resolv.conf $ROOT/etc/resolv.conf
sed -i 's|^SHELL=.*|SHELL=/usr/bin/zsh|' $ROOT/etc/default/useradd
C passwd -l root >/dev/null
# dnf: mantem o sistema coerente com a base
mkdir -p $ROOT/etc/dnf/dnf.conf.d 2>/dev/null || true
grep -q '^excludepkgs' $ROOT/etc/dnf/dnf.conf 2>/dev/null || \
    printf '[main]\nexcludepkgs=fedora-release*,generic-release*,fedora-logos*\ninstall_weak_deps=False\n' >> $ROOT/etc/dnf/dnf.conf

# --- dconf / plymouth
if ! grep -qs 'system-db:distro' $ROOT/etc/dconf/profile/user; then
    mkdir -p $ROOT/etc/dconf/profile
    printf 'user-db:user\nsystem-db:local\nsystem-db:site\nsystem-db:distro\n' > $ROOT/etc/dconf/profile/user
fi
C dconf update
C /usr/libexec/milizos/setup-plymouth
C glib-compile-schemas /usr/share/glib-2.0/schemas 2>/dev/null || true
C gtk4-update-icon-cache -q -f /usr/share/icons/hicolor 2>/dev/null || true
C update-desktop-database -q 2>/dev/null || true

# --- initramfs live
KVER=$(ls $ROOT/lib/modules | sort -V | tail -1)
mkdir -p $ISO/boot $ISO/LiveOS
C dracut --force --no-hostonly --no-hostonly-cmdline --compress "zstd -19 -T0" \
    --add "dmsquash-live plymouth" --omit "nfs iscsi nbd multipath" \
    /boot/initramfs-live.img $KVER
mv $ROOT/boot/initramfs-live.img $ISO/boot/initrd.img
cp $ROOT/lib/modules/$KVER/vmlinuz $ISO/boot/vmlinuz
chmod 644 $ISO/boot/initrd.img $ISO/boot/vmlinuz

# --- catalogo estendido de ferramentas (so o que esta instalado)
mkdir -p $ROOT/usr/share/milizos/catalog.d
python3 /work/build/gen-catalog.py $ROOT $ROOT/usr/share/milizos/catalog.d/extra.json

# --- dieta: o que nao serve a um SOC e so pesa na imagem
rm -rf $ROOT/usr/share/doc/* $ROOT/usr/share/help/*
# perfis SCAP de outras distribuicoes (ficam Fedora, RHEL, CentOS Stream, Debian, Ubuntu e Firefox)
find $ROOT/usr/share/xml/scap/ssg/content -name 'ssg-*-ds.xml' \
    ! -name 'ssg-fedora-*' ! -name 'ssg-rhel*' ! -name 'ssg-cs*' ! -name 'ssg-debian1[23]-*' \
    ! -name 'ssg-ubuntu2[46]04-*' ! -name 'ssg-firefox-*' -delete 2>/dev/null || true
find $ROOT/usr/share/locale -mindepth 1 -maxdepth 1 -type d ! -name 'pt*' ! -name 'en*' -exec rm -rf {} + 2>/dev/null || true

# --- limpeza
rm -rf $ROOT/boot/initramfs-* $ROOT/boot/*rescue* $ROOT/boot/loader/entries/* 2>/dev/null || true
rm -rf $ROOT/var/cache/libdnf5/* $ROOT/var/cache/dnf/* $ROOT/var/log/*.log $ROOT/var/log/dnf5.log* $ROOT/tmp/* $ROOT/var/tmp/* $ROOT/root/.bash_history
echo "CONFIGURE-OK kernel=$KVER initrd=$(du -h $ISO/boot/initrd.img | cut -f1)"

#!/usr/bin/bash
# Empacota o rootfs (EROFS com rotulos SELinux) e monta a ISO hibrida BIOS+UEFI (roda no container)
set -euo pipefail
cd /work
ROOT=/work/cache/rootfs; ISO=/work/cache/iso; LABEL=MILIZOS-1-0
VERSION=1.0; OUT=/work/out/MilizOS-$VERSION-x86_64.iso
for m in dev sys proc; do umount -Rl $ROOT/$m 2>/dev/null || true; done
mkdir -p $ISO/{LiveOS,boot/grub2,EFI/BOOT,milizos}

# --- sistema: EROFS rotulado a partir do file_contexts do proprio sistema
FC=/tmp/file_contexts; D=$ROOT/etc/selinux/targeted/contexts/files
cat $D/file_contexts $D/file_contexts.homedirs $D/file_contexts.local 2>/dev/null > $FC
rm -f $ISO/LiveOS/squashfs.img
mkfs.erofs --quiet ${EROFS_OPTS:--zzstd,level=12 -C131072 -Eztailpacking} \
    --file-contexts=$FC -T0 -L MilizOS $ISO/LiveOS/squashfs.img $ROOT
echo "sistema: $(du -h $ISO/LiveOS/squashfs.img | cut -f1)"

# --- GRUB
T=$ROOT/usr/share/grub/themes/milizos
mkdir -p $ISO/boot/grub2/themes/milizos $ISO/boot/grub2/fonts
cp -r $T/. $ISO/boot/grub2/themes/milizos/
cp $ROOT/usr/share/grub/unicode.pf2 $ISO/boot/grub2/fonts/ 2>/dev/null || true
cp -r $ROOT/usr/lib/grub/i386-pc $ISO/boot/grub2/
K="root=live:CDLABEL=$LABEL rd.live.image enforcing=0"
cat > $ISO/boot/grub2/grub.cfg <<CFG
set default=0
set timeout=10
search --no-floppy --set=root -l '$LABEL'
if [ "\$grub_platform" = "pc" ]; then
  insmod all_video
  insmod gfxterm
  insmod gfxmenu
  insmod png
fi
set gfxmode=1280x800,1024x768,auto
set gfxpayload=keep
if loadfont /boot/grub2/fonts/unicode.pf2; then
  loadfont /boot/grub2/themes/milizos/sans-20.pf2
  loadfont /boot/grub2/themes/milizos/sans-13.pf2
  loadfont /boot/grub2/themes/milizos/mono-14.pf2
  terminal_output gfxterm
  set theme=/boot/grub2/themes/milizos/theme.txt
  export theme
fi
menuentry 'MilizOS $VERSION - iniciar (live / instalar)' {
  linux /boot/vmlinuz $K quiet rhgb
  initrd /boot/initrd.img
}
menuentry 'MilizOS $VERSION - modo gráfico seguro' {
  linux /boot/vmlinuz $K nomodeset
  initrd /boot/initrd.img
}
menuentry 'MilizOS $VERSION - modo texto (console)' {
  linux /boot/vmlinuz $K systemd.unit=multi-user.target
  initrd /boot/initrd.img
}
menuentry 'MilizOS $VERSION - instalação desassistida' {
  linux /boot/vmlinuz $K systemd.unit=multi-user.target milizos.autoinstall=reboot
  initrd /boot/initrd.img
}
if [ "\$grub_platform" = "efi" ]; then
  menuentry 'Configurações do firmware UEFI' { fwsetup }
fi
menuentry 'Iniciar pelo disco local' { exit }
CFG
cat > $ISO/milizos/LEIAME.txt <<TXT
MilizOS $VERSION (Sentinel) - SOC, Blue Team e Engenharia de Redes
Criado por Daniel Pereira da Silva - https://www.linkedin.com/in/danielpereira-linux/

Instalacao desassistida: grave aqui um arquivo autoinstall.json e escolha a entrada
correspondente no menu de boot. Exemplo:

{"disk": "/dev/sda", "filesystem": "btrfs", "encrypt": false, "passphrase": "",
 "hostname": "sensor01", "locale": "pt_BR.UTF-8", "keymap": "br",
 "timezone": "America/Sao_Paulo", "profile": "sensor",
 "user": {"name": "soc", "fullname": "SOC", "password": "troque-esta-senha", "admin": true}}
TXT

# BIOS: imagem El Torito do GRUB
grub2-mkimage -O i386-pc-eltorito -d $ROOT/usr/lib/grub/i386-pc -p /boot/grub2 -o $ISO/boot/grub2/eltorito.img \
    iso9660 biosdisk part_gpt part_msdos search search_label normal configfile linux test echo all_video gfxterm gfxmenu png

# UEFI: shim + GRUB assinados da distribuicao base, numa ESP FAT embutida
E=$ROOT/boot/efi/EFI
cp $E/BOOT/BOOTX64.EFI $ISO/EFI/BOOT/BOOTX64.EFI
cp $E/fedora/grubx64.efi $ISO/EFI/BOOT/grubx64.efi
cp $E/fedora/mmx64.efi $ISO/EFI/BOOT/mmx64.efi
cat > $ISO/EFI/BOOT/grub.cfg <<CFG
search --no-floppy --set=root -l '$LABEL'
set prefix=(\$root)/boot/grub2
configfile /boot/grub2/grub.cfg
CFG
IMG=/tmp/efiboot.img; rm -f $IMG
truncate -s 12M $IMG
mkfs.vfat -n EFIBOOT $IMG >/dev/null
mmd -i $IMG ::/EFI ::/EFI/BOOT
mcopy -i $IMG $ISO/EFI/BOOT/* ::/EFI/BOOT/

rm -f $OUT
xorriso -as mkisofs -quiet -iso-level 3 -R -J -joliet-long -V "$LABEL" -volset "MilizOS $VERSION" \
    -publisher "Daniel Pereira da Silva - linkedin.com/in/danielpereira-linux" -p "MilizOS build system" -A "MilizOS $VERSION Sentinel" \
    --grub2-mbr $ROOT/usr/lib/grub/i386-pc/boot_hybrid.img \
    -partition_offset 16 -appended_part_as_gpt \
    -append_partition 2 C12A7328-F81F-11D2-BA4B-00A0C93EC93B $IMG \
    -iso_mbr_part_type EBD0A0A2-B9E5-4433-87C0-68B6B72699C7 \
    -c boot.cat --boot-catalog-hide \
    -b boot/grub2/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
    -eltorito-alt-boot -e '--interval:appended_partition_2:all::' -no-emul-boot \
    -o $OUT $ISO
(cd /work/out && sha256sum $(basename $OUT) > $(basename $OUT).sha256)
echo "ISO-OK $(du -h $OUT | cut -f1) $OUT"

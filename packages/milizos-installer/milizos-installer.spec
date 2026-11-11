Name:           milizos-installer
Version:        2.0
Release:        1
Summary:        Instalador do MilizOS
License:        GPL-3.0-or-later
Obsoletes:      networkos-installer < 2
BuildArch:      noarch
Requires:       python3 python3-gobject gtk4 libadwaita
Requires:       rsync gdisk parted util-linux cryptsetup
Requires:       btrfs-progs xfsprogs e2fsprogs dosfstools
Requires:       grub2-tools grub2-pc grub2-pc-modules grub2-efi-x64 shim-x64 efibootmgr grubby
Requires:       dracut policycoreutils sudo dconf
%{?systemd_requires}

%description
Instalador grafico proprio do MilizOS (GTK4/libadwaita) e seu motor de
instalacao: particionamento GPT, LUKS2, btrfs/xfs/ext4, GRUB para BIOS e UEFI,
perfis de uso (SOC, Engenharia de Redes, Sensor) e instalacao desassistida.

%install
cp -a %{_sourcedir}/root/. %{buildroot}/
(cd %{buildroot} && find . \( -type f -o -type l \) | sed 's|^\.||;s|.*|"&"|') > files.list

%post
systemctl preset milizos-live.service milizos-autoinstall.service >/dev/null 2>&1 || :

%files -f files.list

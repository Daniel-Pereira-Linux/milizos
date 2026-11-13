Name:           milizos-tools
Version:        2.1.0
Release:        1
Summary:        Heloisa (maquina do tempo), Pandora (caixas Linux) e menu de ferramentas do MilizOS
License:        GPL-3.0-or-later
Obsoletes:      networkos-tools < 2
BuildArch:      noarch
Requires:       python3 milizos-installer dconf zsh
Requires:       btrfs-progs libdnf5-plugin-actions diffutils rsync polkit
Requires:       python3-gobject gtk4 libadwaita podman distrobox nftables util-linux
Requires:       systemd-container openssl openssh-clients libnotify procps-ng psmisc

%description
Heloisa: linha do tempo da maquina inteira em snapshots btrfs, com volta de
qualquer arquivo, pasta ou do sistema. Pandora: caixas Linux descartaveis com
atalhos no GNOME. Mais os lancadores por categoria e o shell padrao.

%install
cp -a %{_sourcedir}/root/. %{buildroot}/
(cd %{buildroot} && find . \( -type f -o -type l \) | sed 's|^\.||;s|.*|"&"|') > files.list

%posttrans
dconf update >/dev/null 2>&1 || :
install -m644 /usr/share/milizos/zshrc /etc/skel/.zshrc 2>/dev/null || :
systemctl preset heloisa-boot.service heloisa-timeline.timer >/dev/null 2>&1 || :

%files -f files.list

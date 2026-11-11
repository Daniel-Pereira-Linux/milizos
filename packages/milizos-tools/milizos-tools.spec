Name:           milizos-tools
Version:        1.0
Release:        5
Summary:        Central de comando e menu de ferramentas do MilizOS
License:        GPL-3.0-or-later
Obsoletes:      networkos-tools < 2
BuildArch:      noarch
Requires:       python3 milizos-installer dconf zsh
Requires:       iproute tcpdump audit btrfs-progs libdnf5-plugin-actions diffutils

%description
O comando nos (postura de seguranca, catalogo de ferramentas, captura em anel,
triagem de host e perfis de servico), os lancadores por categoria e o shell
padrao do MilizOS.

%install
cp -a %{_sourcedir}/root/. %{buildroot}/
(cd %{buildroot} && find . \( -type f -o -type l \) | sed 's|^\.||;s|.*|"&"|') > files.list

%posttrans
dconf update >/dev/null 2>&1 || :
install -m644 /usr/share/milizos/zshrc /etc/skel/.zshrc 2>/dev/null || :
systemctl preset milizos-checkpoint-finalize.service >/dev/null 2>&1 || :

%files -f files.list

Name:           milizos-branding
Version:        1.0
Release:        6
Summary:        Identidade visual do MilizOS
License:        CC-BY-SA-4.0
Obsoletes:      networkos-branding < 2
BuildArch:      noarch
Requires:       dconf
Requires:       plymouth-plugin-script
Requires:       plymouth-plugin-label
Requires:       jetbrains-mono-fonts-all
Requires:       rsms-inter-fonts

%description
Logotipo, papeis de parede, tema do GRUB, tela de boot (Plymouth) e padroes
de area de trabalho do MilizOS.

%install
cp -a %{_sourcedir}/root/. %{buildroot}/
(cd %{buildroot} && find . \( -type f -o -type l \) | sed 's|^\.||;s|.*|"&"|') > files.list

%posttrans
/usr/libexec/milizos/setup-plymouth >/dev/null 2>&1 || :
dconf update >/dev/null 2>&1 || :

%files -f files.list

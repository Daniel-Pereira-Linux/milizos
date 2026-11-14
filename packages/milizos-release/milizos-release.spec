Name:           milizos-release
Version:        2.1.0
Release:        2
Summary:        Arquivos de release do MilizOS
License:        MIT
Obsoletes:      networkos-release < 2
BuildArch:      noarch
Provides:       system-release = 44
Provides:       system-release(44)
Provides:       system-release(releasever) = 44
Provides:       base-module(platform:f44)
Requires:       fedora-repos(44)
Conflicts:      fedora-release
Conflicts:      fedora-release-identity
Conflicts:      generic-release

%description
Identidade do sistema (os-release), presets de servicos do systemd e macros
de distribuicao do MilizOS, o Linux em que tudo e commit: distribuicao baseada
no Fedora em que a maquina inteira tem historico.

%install
cp -a %{_sourcedir}/root/. %{buildroot}/
cp -a %{_sourcedir}/presets/. %{buildroot}/
(cd %{buildroot} && find . \( -type f -o -type l \) | sed 's|^\.||;s|.*|"&"|') > files.list

%files -f files.list

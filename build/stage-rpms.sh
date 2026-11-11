#!/usr/bin/bash
# Constroi os RPMs do MilizOS e o repositorio local (roda no container)
set -euo pipefail
cd /work
REPO=/work/out/repo; TOP=/tmp/rpmbuild; PRE=/work/cache/presets
rm -rf $REPO $TOP; mkdir -p $REPO
if [ ! -d $PRE/usr/lib/systemd ]; then
    mkdir -p $PRE /tmp/fr
    dnf -y -q download fedora-release-common --destdir /tmp/fr
    (cd $PRE && rpm2cpio /tmp/fr/fedora-release-common-*.rpm | cpio -idm --quiet './usr/lib/systemd/*')
fi
for pkg in milizos-release milizos-branding milizos-installer milizos-tools; do
    S=$TOP/$pkg/SOURCES; mkdir -p $S/root
    cp -a packages/$pkg/root/. $S/root/
    find $S/root -name __pycache__ -prune -exec rm -rf {} +
    case $pkg in
        milizos-release)  mkdir -p $S/presets; cp -a $PRE/. $S/presets/ ;;
        milizos-branding) build/gen-branding.sh $S/root ;;
        milizos-tools)    python3 build/gen-menu.py $S/root/usr/share/milizos/catalog.json $S/root ;;
    esac
    rpmbuild -bb --quiet --define "_topdir $TOP/$pkg" --define "_sourcedir $S" \
        --define "_rpmdir $REPO" --define "_build_name_fmt %%{NAME}-%%{VERSION}-%%{RELEASE}.%%{ARCH}.rpm" \
        packages/$pkg/$pkg.spec
done
createrepo_c -q $REPO
ls -la $REPO

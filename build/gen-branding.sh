#!/usr/bin/bash
# Gera os artefatos binarios da identidade visual em $1 (arvore root/ do pacote)
set -euo pipefail
B=$1; S=/work/branding/src; T=$(mktemp -d)
mkdir -p $B/usr/share/{milizos,backgrounds/milizos,pixmaps,icons/hicolor/scalable/apps,icons/hicolor/256x256/apps,grub/themes/milizos,plymouth/themes/milizos}
python3 $S/gen_wallpaper.py $T
rsvg-convert -w 3840 -h 2160 $T/wallpaper-default.svg -o $T/default.png
rsvg-convert -w 3840 -h 2160 $T/wallpaper-mesh.svg -o $T/mesh.png
rsvg-convert -w 1920 -h 1080 $T/wallpaper-dim.svg -o $T/dim.png
magick $T/default.png -quality 93 $B/usr/share/backgrounds/milizos/default.jpg
magick $T/mesh.png -quality 93 $B/usr/share/backgrounds/milizos/mesh.jpg
# logos e icones
install -m644 $S/logo.svg $S/logo-mono.svg $S/wordmark.svg $B/usr/share/milizos/
for n in milizos-logo milizos-installer milizos; do
  install -m644 $S/logo.svg $B/usr/share/icons/hicolor/scalable/apps/$n.svg
  rsvg-convert -w 256 -h 256 $S/logo.svg -o $B/usr/share/icons/hicolor/256x256/apps/$n.png
done
rsvg-convert -w 256 -h 256 $S/logo.svg -o $B/usr/share/pixmaps/milizos-logo.png
rsvg-convert -h 96 $S/wordmark.svg -o $B/usr/share/milizos/wordmark.png
# plymouth: globo 3D animado + marca + elementos da caixa de senha
PT=$B/usr/share/plymouth/themes/milizos
python3 /work/build/gen-bootanim.py $S/logo.svg $PT 80 380
rsvg-convert -w 300 $S/wordmark.svg -o $PT/wordmark.png
magick -size 8x3 xc:'#1B2744' PNG32:$PT/bar-track.png
magick -size 8x3 xc:'#00F0C8' PNG32:$PT/bar-fill.png
echo '<svg xmlns="http://www.w3.org/2000/svg" width="340" height="42"><rect x="1" y="1" width="338" height="40" rx="10" fill="#0D1428" stroke="#2D7FF9" stroke-width="1.5"/></svg>' | rsvg-convert -o $PT/entry.png
echo '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><circle cx="5" cy="5" r="4.5" fill="#00F0C8"/></svg>' | rsvg-convert -o $PT/bullet.png
# grub
G=$B/usr/share/grub/themes/milizos
magick $T/dim.png -strip PNG24:$G/background.png
rsvg-convert -w 450 -h 120 $S/wordmark.svg -o $G/wordmark.png
magick -size 8x8 xc:'rgba(0,240,200,0.13)' PNG32:$G/select_c.png
pfname() { python3 - "$1" <<'PY'
import struct,sys
d=open(sys.argv[1],'rb').read(); i=0
while i < len(d)-8:
    tag=d[i:i+4]; n=struct.unpack('>I',d[i+4:i+8])[0]
    if tag==b'NAME': print(d[i+8:i+8+n].rstrip(b'\0').decode()); break
    if tag==b'DATA': break
    i+=8+n
PY
}
sans=$(fc-match -f '%{file}' 'Inter:style=Regular'); mono=$(fc-match -f '%{file}' 'JetBrains Mono:style=Regular')
grub2-mkfont -s 20 -o $G/sans-20.pf2 "$sans"
grub2-mkfont -s 13 -o $G/sans-13.pf2 "$sans"
grub2-mkfont -s 14 -o $G/mono-14.pf2 "$mono"
sed -e "s|@SANS@|$(pfname $G/sans-20.pf2)|" -e "s|@SMALL@|$(pfname $G/sans-13.pf2)|" \
    -e "s|@MONO@|$(pfname $G/mono-14.pf2)|" /work/packages/milizos-branding/root/usr/share/grub/themes/milizos/theme.txt.in > $G/theme.txt
rm -f $G/theme.txt.in
rm -rf $T

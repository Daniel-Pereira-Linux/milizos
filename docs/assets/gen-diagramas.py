#!/usr/bin/python3
"""Gera os diagramas da documentacao (SVG). Uso: python3 gen-diagramas.py  (na pasta docs/assets)"""
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
HEAD = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="Inter, 'Segoe UI', Arial, sans-serif">
<defs>
<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#7C8AA8"/></marker>
<marker id="at" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#00F0C8"/></marker>
<marker id="ab" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#2D7FF9"/></marker>
<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#F0616D"/></marker>
</defs>
<rect width="{w}" height="{h}" rx="18" fill="#070B16"/>
<text x="32" y="44" fill="#E8EEFA" font-size="21" font-weight="700">{title}</text>
<text x="32" y="68" fill="#7C8AA8" font-size="13.5">{sub}</text>
'''
KIND = [("#0D1428", "#1F2C4D"), ("#0B2A33", "#00F0C8"), ("#101C3D", "#2D7FF9"), ("#2A1218", "#F0616D")]


def box(x, y, w, h, t, s=None, kind=0, fs=15):
    fill, stroke = KIND[kind]
    cy = y + h / 2 + (5 if not s else -3)
    o = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
         f'<text x="{x + w / 2}" y="{cy}" fill="#E8EEFA" font-size="{fs}" font-weight="600" text-anchor="middle">{t}</text>')
    if s:
        o += f'<text x="{x + w / 2}" y="{cy + 18}" fill="#7C8AA8" font-size="11.5" text-anchor="middle">{s}</text>'
    return o + "\n"


def arrow(x1, y1, x2, y2, m="a", c="#7C8AA8", dash=False):
    d = ' stroke-dasharray="5 4"' if dash else ""
    return f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{c}" stroke-width="1.6" fill="none" marker-end="url(#{m})"{d}/>\n'


def text(x, y, t, c="#7C8AA8", fs=12, w=400):
    return f'<text x="{x}" y="{y}" fill="{c}" font-size="{fs}" font-weight="{w}">{t}</text>\n'


def group(x, y, w, h, label):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="none" stroke="#1F2C4D" stroke-dasharray="6 5"/>'
            f'<text x="{x + 14}" y="{y + 22}" fill="#7C8AA8" font-size="11.5" font-weight="700" letter-spacing="1.2">{label}</text>\n')


def save(name, w, h, title, sub, body):
    with open(name, "w", encoding="utf-8") as f:
        f.write(HEAD.format(w=w, h=h, title=title, sub=sub) + body + "</svg>\n")


T, B = "#00F0C8", "#2D7FF9"

# 1. arquitetura em camadas
b = group(32, 92, 896, 112, "O QUE VOCÊ VÊ")
b += box(52, 124, 196, 62, "Heloisa", "máquina do tempo", 1) + box(264, 124, 196, 62, "Pandora", "caixas Linux", 1)
b += box(476, 124, 196, 62, "Instalador", "gráfico e desassistido", 2)
b += box(688, 124, 220, 62, "Ferramentas originais", "nmap · suricata · wireshark…", 0)
b += group(32, 222, 896, 112, "O QUE FAZ O TRABALHO")
b += box(52, 254, 196, 62, "heloisa-engine", "root via polkit · JSON", 0)
b += box(264, 254, 196, 62, "podman + distrobox", "sem root · nftables", 0)
b += box(476, 254, 196, 62, "engine.py", "GPT · LUKS2 · GRUB", 0)
b += box(688, 254, 220, 62, "dnf · systemd · SELinux", "Fedora 44, Enforcing", 0)
b += group(32, 352, 896, 112, "ONDE TUDO MORA")
b += box(52, 384, 408, 62, "btrfs: root · home · log · snapshots", "copy-on-write, compressão zstd", 2)
b += box(476, 384, 196, 62, "/boot (ext4) + ESP", "kernel de cada ponto", 0)
b += box(688, 384, 220, 62, "zram (zstd)", "swap em RAM · roda em 4 GB", 0)
for x in (150, 362, 574, 798):
    b += arrow(x, 186, x, 252) + arrow(x, 316, x, 382)
save("arquitetura.svg", 960, 490, "MilizOS por dentro",
     "Três camadas: aplicativos, motores e armazenamento. Nenhuma delas usa formato próprio.", b)

# 2. heloisa: volume e pontos
b = group(32, 92, 430, 330, "VOLUME BTRFS: UM DISCO, VÁRIOS SUBVOLUMES")
b += box(56, 128, 118, 54, "root", "/  /etc  /usr  /var", 2) + box(186, 128, 118, 54, "home", "/home", 2)
b += box(316, 128, 118, 54, "log", "/var/log", 2)
b += text(56, 214, "snapshots/   (visível em /.heloisa, somente leitura)", T, 12.5, 600)
for i, (n, d) in enumerate([("1", "instalação limpa"), ("6", "antes de: dnf install zeek"), ("7", "automático, 14:00")]):
    b += box(56, 228 + i * 60, 378, 48, f"#{n}   root · home · log", d, 1, 13.5)
b += group(492, 92, 436, 150, "CRIAR UM PONTO: MENOS DE 1 SEGUNDO")
b += box(512, 128, 120, 50, "gatilho", "hora · boot · dnf", 0, 13.5) + box(654, 128, 120, 50, "snapshot -r", "dos 3 subvolumes", 1, 13.5)
b += box(796, 128, 116, 50, "kernel", "hardlink em /boot", 0, 13.5)
b += arrow(632, 153, 652, 153) + arrow(774, 153, 794, 153)
b += text(512, 212, "O ponto nasce ocupando quase nada: só cresce com o que mudar depois.")
b += group(492, 260, 436, 162, "VOLTAR: NUNCA APAGA HISTÓRIA")
b += box(512, 296, 120, 50, "estado atual", "vira ponto novo", 3, 13.5) + box(654, 296, 120, 50, "troca", "root ← ponto #6", 1, 13.5)
b += box(796, 296, 116, 50, "reinicia", "já no passado", 0, 13.5)
b += arrow(632, 321, 652, 321) + arrow(774, 321, 794, 321)
b += text(512, 376, "Arquivo ou pasta: cópia direta do ponto, sem reiniciar.")
b += text(512, 396, "Arrependeu? Volte para o ponto criado no primeiro passo.")
save("heloisa-pontos.svg", 960, 446, "Heloisa: como um ponto funciona",
     "Snapshots btrfs comuns. A interface é só uma forma confortável de usá-los.", b)

# 3. pandora: topologia de rede
b = box(390, 96, 180, 50, "Internet", None, 2)
b += box(50, 196, 160, 56, "Rede local", "impressora, NAS, roteador", 0, 13.5)
b += group(250, 176, 460, 250, "SEU COMPUTADOR (MILIZOS)")
b += box(270, 208, 420, 44, "pilha de rede do host", None, 0, 13.5)
b += box(270, 300, 190, 100, "Caixa isolada", "rede própria + filtro", 1)
b += box(500, 300, 190, 100, "Caixa em ponte", "usa a rede do host", 2)
b += arrow(365, 298, 365, 254, "at", T) + text(374, 282, "só internet", T, 11.5)
b += arrow(595, 298, 595, 254, "ab", B) + text(604, 282, "igual ao host", B, 11.5)
b += arrow(480, 206, 480, 148) + arrow(268, 228, 212, 224)
b += '<path d="M290 300 C 230 292, 170 280, 140 256" stroke="#F0616D" stroke-width="1.6" fill="none" stroke-dasharray="5 4" marker-end="url(#ar)"/>\n'
b += text(150, 300, "recusado", "#F0616D", 11.5, 700)
b += box(750, 196, 170, 80, "Menu do GNOME", "atalhos criados sozinhos", 0, 13.5)
b += arrow(692, 340, 800, 280, "at", T, True) + text(742, 332, "app instalado vira atalho", T, 11.5)
b += text(742, 384, "Destruir a caixa apaga") + text(742, 402, "programas, atalhos e pasta.")
save("pandora-rede.svg", 960, 450, "Pandora: os dois modos de rede",
     "Conteiners sem root. O isolamento é um filtro nftables dentro da rede da própria caixa.", b)

# 4. boot
b = ""
xs = [40, 222, 404, 586, 768]
steps = [("Firmware", "BIOS ou UEFI + Secure Boot", 0), ("GRUB", "tema MilizOS", 2), ("initramfs", "animação 3D (Plymouth)", 0),
         ("btrfs root", "monta o subvolume", 2), ("GNOME", "desktop estático, leve", 0)]
for x, (t, s, k) in zip(xs, steps):
    b += box(x, 110, 152, 62, t, s, k, 14)
for x in xs[:-1]:
    b += arrow(x + 152, 141, x + 180, 141)
b += box(222, 236, 152, 62, "Submenu Heloisa", "15 pontos recentes", 1, 14)
b += box(404, 236, 152, 62, "gancho de volta", "heloisa.rollback=N", 1, 14)
b += box(586, 236, 152, 62, "root ← ponto N", "o quebrado é guardado", 1, 14)
b += arrow(298, 172, 298, 234, "at", T) + arrow(374, 267, 402, 267, "at", T) + arrow(556, 267, 584, 267, "at", T)
b += arrow(662, 234, 662, 174, "at", T)
b += text(40, 262, "Caminho de resgate:", T, 12.5, 700) + text(40, 282, "o sistema não sobe?") + text(40, 300, "Escolha um ponto no boot.")
b += text(768, 262, "Cada ponto leva o kernel") + text(768, 280, "e o initramfs do seu tempo.")
save("boot.svg", 960, 330, "Do botão de ligar ao desktop",
     "O caminho normal em cima; embaixo, a volta no tempo feita antes mesmo de o sistema montar.", b)
print("diagramas gerados")

#!/usr/bin/python3
"""Gera os quadros da animacao de boot: a logo dentro de um globo de rede 3D em rotacao.

Uso: gen-bootanim.py logo.svg DIR_SAIDA [quadros] [tamanho]
Geometria em Python puro (projecao em perspectiva) -> SVG -> PNG com rsvg-convert.
A mesma malha (esfera de Fibonacci, arestas i->i+5 e i->i+8) e usada no shader do desktop.
"""
import math, os, re, subprocess, sys

logo_path, out = sys.argv[1], sys.argv[2]
F = int(sys.argv[3]) if len(sys.argv) > 3 else 96
S = int(sys.argv[4]) if len(sys.argv) > 4 else 380
N, TILT, CAM, R = 22, math.radians(22), 3.2, 0.92
GOLD = math.pi * (3 - math.sqrt(5))
nodes = []
for i in range(N):
    y = 1 - 2 * (i + 0.5) / N
    r = math.sqrt(1 - y * y)
    nodes.append((r * math.cos(i * GOLD), y, r * math.sin(i * GOLD)))
edges = [(i, i + k) for k in (5, 8) for i in range(N - k)]
logo = re.sub(r"<\?xml[^>]*\?>|</?svg[^>]*>", "", open(logo_path).read())
logo = logo.replace('id="g"', 'id="lg"').replace("url(#g)", "url(#lg)").replace('id="bg"', 'id="lbg"').replace("url(#bg)", "url(#lbg)")


def proj(p, a):
    x, y, z = p
    x, z = x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)
    y, z = y * math.cos(TILT) - z * math.sin(TILT), y * math.sin(TILT) + z * math.cos(TILT)
    s = CAM / (CAM + z)                      # z > 0 = longe da camera
    return S / 2 + x * R * s * S * 0.40, S / 2 + y * R * s * S * 0.40, z, s


def layer(pts, f, front):
    o = []
    for n, (i, j) in enumerate(edges):
        a, b = pts[i], pts[j]
        zm = (a[2] + b[2]) / 2
        if (zm < 0) != front:
            continue
        op = 0.16 + 0.30 * (1 - (zm + 1) / 2)
        o.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#2D7FF9" stroke-width="{0.9 + 0.8 * (1 - (zm + 1) / 2):.2f}" opacity="{op:.2f}"/>')
        if n % 3 == 0:                       # pulso de dados percorrendo a aresta
            t = (f / F * 2 + n * 0.37) % 1.0
            px, py = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            o.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{2.2 + 1.2 * (1 - (zm + 1) / 2):.1f}" fill="#9FFFF0" opacity="{0.55 + 0.4 * (1 - (zm + 1) / 2):.2f}" filter="url(#glow)"/>')
    for x, y, z, s in pts:
        if (z < 0) != front:
            continue
        near = 1 - (z + 1) / 2
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{(2.6 + 3.4 * near) * 2.6:.1f}" fill="url(#halo)" opacity="{0.25 + 0.55 * near:.2f}"/>')
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{2.2 + 3.0 * near:.1f}" fill="#00F0C8" opacity="{0.45 + 0.55 * near:.2f}"/>')
    return "\n".join(o)


os.makedirs(out, exist_ok=True)
ls = S * 0.40                                # lado da logo
for f in range(F):
    a = 2 * math.pi * f / F
    pts = [proj(p, a) for p in nodes]
    breath = 1 + 0.025 * math.sin(2 * math.pi * f / F * 2)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{S}" height="{S}" viewBox="0 0 {S} {S}">
<defs>
<radialGradient id="halo"><stop offset="0" stop-color="#00F0C8" stop-opacity=".85"/><stop offset="1" stop-color="#00F0C8" stop-opacity="0"/></radialGradient>
<radialGradient id="core"><stop offset="0" stop-color="#2D7FF9" stop-opacity=".30"/><stop offset="1" stop-color="#2D7FF9" stop-opacity="0"/></radialGradient>
<filter id="glow" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="1.6"/></filter>
</defs>
<circle cx="{S / 2}" cy="{S / 2}" r="{S * 0.46}" fill="url(#core)"/>
{layer(pts, f, False)}
<g transform="translate({S / 2 - ls * breath / 2:.2f},{S / 2 - ls * breath / 2:.2f}) scale({ls * breath / 512:.5f})">{logo}</g>
{layer(pts, f, True)}
</svg>'''
    p = subprocess.run(["rsvg-convert", "-o", f"{out}/anim-{f}.png"], input=svg.encode())
    if p.returncode:
        sys.exit("rsvg-convert falhou")
print(f"{F} quadros de {S}px em {out}")

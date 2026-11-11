#!/usr/bin/env python3
"""Gera os wallpapers do MilizOS (malha de rede procedural) em SVG."""
import math, random, sys

def wallpaper(w, h, seed, logo=True, dim=1.0):
    r = random.Random(seed)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
           '<defs>',
           '<radialGradient id="bg" cx="72%" cy="38%" r="85%">'
           '<stop offset="0" stop-color="#12203F"/><stop offset=".45" stop-color="#0A1226"/>'
           '<stop offset="1" stop-color="#05080F"/></radialGradient>',
           '<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
           '<stop offset="0" stop-color="#00F0C8"/><stop offset="1" stop-color="#2D7FF9"/></linearGradient>',
           '<radialGradient id="glow" cx="50%" cy="50%" r="50%">'
           '<stop offset="0" stop-color="#00F0C8" stop-opacity=".22"/>'
           '<stop offset="1" stop-color="#00F0C8" stop-opacity="0"/></radialGradient>',
           '</defs>',
           f'<rect width="{w}" height="{h}" fill="url(#bg)"/>']
    # grade hexagonal sutil
    s = w / 48
    hh = s * math.sqrt(3)
    out.append('<g fill="none" stroke="#5B8CFF" stroke-opacity=".045" stroke-width="2">')
    row = 0
    y = -hh
    while y < h + hh:
        x = -s * 2 + (1.5 * s if row % 2 else 0)
        while x < w + s * 2:
            pts = " ".join(f"{x + s * math.cos(math.radians(60 * k)):.1f},{y + s * math.sin(math.radians(60 * k)):.1f}" for k in range(6))
            out.append(f'<polygon points="{pts}"/>')
            x += 3 * s
        y += hh / 2
        row += 1
    out.append('</g>')
    # malha de nos, mais densa a direita
    nodes = []
    tries = 0
    while len(nodes) < 95 and tries < 20000:
        tries += 1
        x, y = r.uniform(0, w), r.uniform(0, h)
        dens = 0.12 + 0.88 * (x / w) ** 1.6
        if r.random() > dens:
            continue
        if any((x - a) ** 2 + (y - b) ** 2 < (w / 22) ** 2 for a, b, _ in nodes):
            continue
        nodes.append((x, y, r.random()))
    out.append('<g stroke="url(#g)" stroke-linecap="round">')
    lim = (w / 7.5) ** 2
    for i, (x, y, _) in enumerate(nodes):
        near = sorted(((x - a) ** 2 + (y - b) ** 2, j) for j, (a, b, _) in enumerate(nodes) if j != i)[:3]
        for d, j in near:
            if j > i and d < lim:
                a, b, _ = nodes[j]
                op = 0.10 + 0.32 * (1 - d / lim) * (0.3 + 0.7 * x / w)
                out.append(f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{a:.0f}" y2="{b:.0f}" stroke-width="{w/1500:.1f}" stroke-opacity="{op * dim:.2f}"/>')
    out.append('</g>')
    for x, y, k in nodes:
        rad = w / 520 * (0.8 + 1.6 * k)
        op = (0.25 + 0.6 * (x / w)) * dim
        if k > 0.86:
            out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rad * 9:.0f}" fill="url(#glow)"/>')
            out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rad * 1.5:.1f}" fill="#00F0C8" fill-opacity="{min(1, op + .3):.2f}"/>')
        else:
            out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rad:.1f}" fill="#0A1226" stroke="#3FA9F5" stroke-opacity="{op:.2f}" stroke-width="{w/1300:.1f}"/>')
    if logo:
        sc = h / 512 * 0.30
        lx, ly = w * 0.5 - 256 * sc, h * 0.44 - 256 * sc
        out.append(f'<circle cx="{w*0.5:.0f}" cy="{h*0.44:.0f}" r="{h*0.36:.0f}" fill="url(#glow)" opacity=".7"/>')
        out.append(f'<g transform="translate({lx:.1f},{ly:.1f}) scale({sc:.4f})">'
                   '<path d="M256 30 L452 143 V369 L256 482 L60 369 V143 Z" fill="#070B16" fill-opacity=".85" stroke="url(#g)" stroke-width="22" stroke-linejoin="round"/>'
                   '<path d="M176 344 V168 L336 344 V168" fill="none" stroke="url(#g)" stroke-width="26" stroke-linecap="round" stroke-linejoin="round"/>'
                   '<circle cx="176" cy="344" r="27" fill="#070B16" stroke="url(#g)" stroke-width="14"/>'
                   '<circle cx="176" cy="168" r="27" fill="#070B16" stroke="url(#g)" stroke-width="14"/>'
                   '<circle cx="336" cy="344" r="27" fill="#070B16" stroke="url(#g)" stroke-width="14"/>'
                   '<circle cx="336" cy="168" r="44" fill="none" stroke="#00F0C8" stroke-width="5" opacity=".35"/>'
                   '<circle cx="336" cy="168" r="30" fill="#00F0C8"/></g>')
        fs = h * 0.062
        out.append(f'<text x="{w*0.5:.0f}" y="{h*0.44 + 256*sc + fs*1.25:.0f}" text-anchor="middle" font-family="Inter, sans-serif" font-weight="800" font-size="{fs:.0f}" letter-spacing="-2" fill="#F2F6FF">Miliz<tspan fill="url(#g)">OS</tspan></text>')
        out.append(f'<text x="{w*0.5:.0f}" y="{h*0.44 + 256*sc + fs*1.95:.0f}" text-anchor="middle" font-family="JetBrains Mono, monospace" font-weight="500" font-size="{fs*0.24:.0f}" letter-spacing="{fs*0.07:.0f}" fill="#7C8AA8">DEFEND · DETECT · RESPOND</text>')
    out.append('</svg>')
    return "\n".join(out)

if __name__ == "__main__":
    d = sys.argv[1]
    open(f"{d}/wallpaper-default.svg", "w").write(wallpaper(3840, 2160, 7))
    open(f"{d}/wallpaper-mesh.svg", "w").write(wallpaper(3840, 2160, 42, logo=False))
    open(f"{d}/wallpaper-dim.svg", "w").write(wallpaper(1920, 1080, 11, logo=False, dim=0.55))

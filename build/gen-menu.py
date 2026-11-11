#!/usr/bin/python3
"""Gera os lancadores .desktop e as pastas do menu do GNOME a partir do catalogo."""
import json, os, sys
cat = json.load(open(sys.argv[1], encoding="utf-8")); root = sys.argv[2]
apps = f"{root}/usr/share/applications"; dc = f"{root}/etc/dconf/db/distro.d"
os.makedirs(apps, exist_ok=True); os.makedirs(dc, exist_ok=True)
def desktop(fn, name, comment, cmd, cats):
    open(f"{apps}/{fn}", "w", encoding="utf-8").write(
        f"[Desktop Entry]\nType=Application\nName={name}\nComment={comment}\n"
        f"Exec=/usr/libexec/milizos/tool-shell {cmd}\nIcon=milizos\nTerminal=true\nCategories={cats}\n")
desktop("milizos-nos.desktop", "MilizOS Central", "Postura de segurança e catálogo de ferramentas", "nos", "System;")
out = ["[org/gnome/desktop/app-folders]", "folder-children=[%s]" % ", ".join(f"'nos-{k}'" for k in cat), ""]
for k, c in cat.items():
    ids = []
    for t in c["tools"]:
        if t.get("gui"):
            ids.append(t["gui"])
        elif t.get("menu"):
            fn = f"milizos-{t['cmd']}.desktop"
            desktop(fn, t["cmd"], t["desc"], t["cmd"], f"X-MilizOS-{k};")
            ids.append(fn)
    out += [f"[org/gnome/desktop/app-folders/folders/nos-{k}]", f"name='{c['label']}'",
            "apps=[%s]" % ", ".join(f"'{i}'" for i in ids), ""]
open(f"{dc}/10-milizos-menu", "w", encoding="utf-8").write("\n".join(out))

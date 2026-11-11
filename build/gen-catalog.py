#!/usr/bin/python3
# Gera o catalogo estendido (catalog.d/extra.json) a partir de build/tools-extra.list,
# so com o que esta de fato instalado no rootfs: comando = executaveis do pacote,
# descricao = resumo do RPM.   uso: gen-catalog.py ROOTFS SAIDA.json
import json
import subprocess
import sys

root, out = sys.argv[1], sys.argv[2]
LABELS = {"traffic": "Captura e análise de tráfego", "detect": "Detecção e monitoramento",
          "discovery": "Descoberta e varredura", "diag": "Diagnóstico de rede", "neteng": "Engenharia de redes",
          "dfir": "Forense e análise de malware", "passwords": "Senhas e criptografia", "web": "Aplicações web",
          "wireless": "Redes sem fio e rádio", "redteam": "Simulação de adversário", "audit": "Auditoria e hardening"}
base = json.load(open("/work/packages/milizos-tools/root/usr/share/milizos/catalog.json", encoding="utf-8"))
known = {t["cmd"] for v in base.values() for t in v["tools"]}
rpm = lambda *a: subprocess.run(["rpm", "--root", root] + list(a), capture_output=True, text=True).stdout
cat, total = {}, 0
for line in open("/work/build/tools-extra.list", encoding="utf-8"):
    if line.startswith("#") or ":" not in line:
        continue
    key, pkgs = line.split(":", 1)
    tools = []
    for p in pkgs.split():
        summ = rpm("-q", "--qf", "%{SUMMARY}", p)
        if not summ or "is not installed" in summ or "não está instalado" in summ:
            continue
        bins = sorted({f.rsplit("/", 1)[1] for f in rpm("-ql", p).splitlines()
                       if f.startswith(("/usr/bin/", "/usr/sbin/")) and "/" not in f[10:].lstrip("/")})
        if not bins:
            continue
        # o executavel principal: o que tem o nome do pacote, senao o mais parecido, senao o primeiro
        short = p.replace("python3-", "")
        main = next((b for b in bins if b == short), None) or next((b for b in bins if short in b or b in short), bins[0])
        if main in known:
            continue
        known.add(main)
        more = f" (+{len(bins) - 1} comandos)" if len(bins) > 1 else ""
        tools.append({"cmd": main, "desc": summ.strip().rstrip(".") + more, "pkg": p})
    if tools:
        cat[key.strip()] = {"label": LABELS.get(key.strip(), key.strip()), "tools": sorted(tools, key=lambda t: t["cmd"])}
        total += len(tools)
json.dump(cat, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(f"catalogo estendido: {total} ferramentas em {len(cat)} categorias")

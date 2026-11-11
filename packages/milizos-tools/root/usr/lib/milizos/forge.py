# MilizOS - Forja de imagens
# Gera, a partir da ISO oficial, uma ISO propria que instala sozinha com a SUA configuracao:
# ligue a maquina com o pendrive e ela vira um sensor/estacao pronta, sem teclado nem monitor.
#   nos forge --iso MilizOS.iso [--config arquivo.json] [-o saida.iso]
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from ui import ac, dim, ok, warn


def ask(q, default=""):
    r = input(f"  {q}" + (f" [{default}]" if default else "") + ": ").strip()
    return r or default


def hashpw(pw):
    return subprocess.run(["openssl", "passwd", "-6", "-stdin"], input=pw, capture_output=True, text=True, check=True).stdout.strip()


def wizard():
    print(dim("  Responda para montar a configuração (Enter aceita o padrão)."))
    cfg = {"disk": "auto", "locale": "pt_BR.UTF-8", "keymap": "br", "timezone": "America/Sao_Paulo"}
    cfg["hostname"] = ask("Nome da máquina", "sensor01")
    cfg["profile"] = ask("Perfil (soc, neteng, sensor)", "sensor")
    cfg["filesystem"] = ask("Sistema de arquivos (btrfs, xfs, ext4)", "btrfs")
    user = ask("Usuário administrador", "soc")
    while True:
        p1 = getpass.getpass("  Senha do usuário: ")
        if len(p1) >= 8 and p1 == getpass.getpass("  Repita a senha: "):
            break
        print(warn("  as senhas não conferem ou têm menos de 8 caracteres"))
    cfg["user"] = {"name": user, "fullname": user, "password_hash": hashpw(p1), "admin": True}
    cfg["encrypt"] = False
    return cfg


def main(args):
    opt = {"--iso": None, "--config": None, "-o": None}
    it = iter(args)
    for a in it:
        if a in opt:
            opt[a] = next(it, None)
        else:
            sys.exit("uso: nos forge --iso MilizOS.iso [--config autoinstall.json] [-o saida.iso]")
    iso = opt["--iso"]
    if not iso or not os.path.isfile(iso):
        sys.exit("informe a ISO oficial: nos forge --iso /caminho/MilizOS-x86_64.iso")
    if not shutil.which("xorriso"):
        sys.exit("xorriso não está instalado")
    print(ac("▍Forja de imagens"))
    if opt["--config"]:
        cfg = json.load(open(opt["--config"], encoding="utf-8"))
    else:
        cfg = wizard()
    u = cfg.get("user") or {}
    if u.get("password"):           # nunca grava senha em claro na midia
        u["password_hash"] = hashpw(u.pop("password"))
    if cfg.get("root_password"):
        cfg["root_password_hash"] = hashpw(cfg.pop("root_password"))
    if cfg.get("encrypt"):
        print(warn("  Atenção: com criptografia, a senha do disco fica em claro na mídia gerada (é necessária para instalar)."))
    out = opt["-o"] or f"MilizOS-{cfg.get('hostname', 'custom')}.iso"
    if os.path.exists(out):
        sys.exit(f"{out} já existe")
    work = tempfile.mkdtemp(prefix="nos-forge-")
    try:
        with open(f"{work}/autoinstall.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        subprocess.run(["xorriso", "-osirrox", "on", "-indev", iso, "-extract", "/boot/grub2/grub.cfg", f"{work}/grub.cfg"],
                       capture_output=True, check=True)
        os.chmod(f"{work}/grub.cfg", 0o644)
        g = open(f"{work}/grub.cfg", encoding="utf-8").read()
        idx = [m.group(1) for m in re.finditer(r"^menuentry '([^']*)'", g, re.M)]
        pos = next((i for i, t in enumerate(idx) if "desassistida" in t), None)
        if pos is None:
            sys.exit("esta ISO não tem a entrada de instalação desassistida")
        g = re.sub(r"^set default=.*$", f"set default={pos}", g, count=1, flags=re.M)
        g = re.sub(r"^set timeout=.*$", "set timeout=8", g, count=1, flags=re.M)
        g = g.replace("instalação desassistida'", f"INSTALAR AUTOMATICAMENTE ({cfg.get('hostname', '')}) - APAGA O DISCO'")
        open(f"{work}/grub.cfg", "w", encoding="utf-8").write(g)
        p = subprocess.run(["xorriso", "-indev", iso, "-outdev", out, "-boot_image", "any", "replay",
                            "-map", f"{work}/autoinstall.json", "/milizos/autoinstall.json",
                            "-map", f"{work}/grub.cfg", "/boot/grub2/grub.cfg", "-commit"],
                           capture_output=True, text=True)
        if p.returncode != 0 or not os.path.exists(out):
            sys.exit("falha ao gerar a ISO:\n" + p.stderr[-1500:])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    dg = subprocess.run(["sha256sum", out], capture_output=True, text=True).stdout.split()[0]
    open(out + ".sha256", "w").write(f"{dg}  {os.path.basename(out)}\n")
    print(f"  {ok('✔')} {out}  ({os.path.getsize(out) / 2**30:.1f} GB)\n  sha256: {dg}")
    print(warn("  Esta mídia APAGA o disco da máquina em que iniciar, sem perguntar. Identifique-a bem."))

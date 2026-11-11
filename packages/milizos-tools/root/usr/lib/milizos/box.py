# MilizOS - caixas de outras distribuicoes (Kali, Debian, Arch...) integradas ao sistema.
# Usa distrobox + podman sem root: a caixa compartilha a pasta pessoal, a rede e o display,
# entao as ferramentas dela rodam como se fossem do MilizOS, sem tocar na base.
import os
import shutil
import subprocess
import sys

from ui import ac, dim, ok, warn

IMAGES = {
    "kali": ("docker.io/kalilinux/kali-rolling:latest", "Kali Linux (rolling)",
             "sudo apt update && sudo apt install -y kali-linux-headless   # ~600 ferramentas do Kali"),
    "debian": ("docker.io/library/debian:stable", "Debian estável", "sudo apt update && sudo apt install -y PACOTE"),
    "ubuntu": ("docker.io/library/ubuntu:latest", "Ubuntu LTS", "sudo apt update && sudo apt install -y PACOTE"),
    "arch": ("docker.io/library/archlinux:latest", "Arch Linux (+ BlackArch opcional)",
             "sudo pacman -Syu PACOTE   # BlackArch: curl -O https://blackarch.org/strap.sh"),
    "parrot": ("docker.io/parrotsec/security:latest", "Parrot Security", "sudo apt update && sudo apt install -y PACOTE"),
    "alpine": ("docker.io/library/alpine:latest", "Alpine Linux", "sudo apk add PACOTE"),
    "fedora": ("registry.fedoraproject.org/fedora:latest", "Fedora (caixa descartável)", "sudo dnf install PACOTE"),
}


def existing():
    p = subprocess.run(["podman", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"], capture_output=True, text=True)
    return dict(l.split("\t", 1) for l in p.stdout.splitlines() if l.startswith("nos-") and "\t" in l)


def main(args):
    if os.geteuid() == 0:
        sys.exit("use o nos box com o seu usuário, sem sudo (as caixas rodam sem root)")
    if not shutil.which("distrobox") or not shutil.which("podman"):
        sys.exit("distrobox/podman não instalados")
    act = args[0] if args else "list"
    have = existing()
    if act == "list":
        print(ac("▍Caixas de outras distribuições") + dim("   nos box NOME [comando]  ·  nos box rm NOME"))
        for k, (img, label, _h) in IMAGES.items():
            st = have.get("nos-" + k)
            print(f"  {ok('●') if st else dim('○')} {k:<8} {label:<34} {dim(st or 'não criada')}")
        return
    if act == "rm":
        if len(args) < 2:
            sys.exit("uso: nos box rm NOME")
        sys.exit(subprocess.call(["distrobox", "rm", "--force", "nos-" + args[1]]))
    if act not in IMAGES:
        sys.exit(f"caixa desconhecida: {act} (opções: {', '.join(IMAGES)})")
    img, label, hint = IMAGES[act]
    name = "nos-" + act
    if name not in have:
        print(ac(f"▍Criando a caixa {label}") + dim(f"   {img}"))
        r = subprocess.call(["distrobox", "create", "--yes", "--name", name, "--image", img, "--hostname", f"{act}-{os.uname().nodename}"])
        if r != 0:
            sys.exit(warn("não foi possível criar a caixa (é preciso internet para baixar a imagem)"))
        print(f"  {ok('✔')} pronta. Dentro dela: {dim(hint)}")
    cmd = ["distrobox", "enter", name]
    if len(args) > 1:
        cmd += ["--"] + args[1:]
    os.execvp(cmd[0], cmd)

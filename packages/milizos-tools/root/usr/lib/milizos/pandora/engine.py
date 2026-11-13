#!/usr/bin/python3
# Pandora - caixas Linux descartaveis para o MilizOS.
#
# Cada caixa e um conteiner podman sem root criado com o distrobox; nada de formato proprio:
# `podman ps`, `distrobox list` e `distrobox enter` enxergam e operam as mesmas caixas.
# O que a Pandora acrescenta:
#   - aplicativos instalados dentro da caixa aparecem sozinhos no menu do GNOME;
#   - dois modos de rede: "isolada" (so sai para a internet) e "ponte" (a rede do host);
#   - destruir a caixa leva junto atalhos, icones e a pasta pessoal dela;
#   - pontos: a caixa inteira (programas e pasta) congelada, para voltar depois. Um ponto e uma
#     imagem podman comum (`podman images` mostra em localhost/pandora-pontos/<caixa>).
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
DATA = os.path.join(os.environ.get("XDG_DATA_HOME", HOME + "/.local/share"), "pandora")
APPS = os.path.join(os.environ.get("XDG_DATA_HOME", HOME + "/.local/share"), "applications")
ENTER = "/usr/libexec/milizos/pandora-enter"
PTS = DATA + "/points"
PT_IMG = "localhost/pandora-pontos"
PT_KEEP_AUTO = 5          # pontos "antes de voltar" guardados por caixa

IMAGES = [
    # id, nome, imagem, familia
    ("debian", "Debian 13", "quay.io/toolbx-images/debian-toolbox:13"),
    ("kali", "Kali Linux (rolling)", "docker.io/kalilinux/kali-rolling:latest"),
    ("alma", "AlmaLinux 9", "quay.io/toolbx-images/almalinux-toolbox:9"),
    ("ubuntu", "Ubuntu 24.04 LTS", "quay.io/toolbx/ubuntu-toolbox:24.04"),
    ("fedora", "Fedora 44", "registry.fedoraproject.org/fedora-toolbox:44"),
    ("arch", "Arch Linux", "quay.io/toolbx/arch-toolbox:latest"),
    ("rocky", "Rocky Linux 9", "quay.io/toolbx-images/rockylinux-toolbox:9"),
    ("opensuse", "openSUSE Tumbleweed", "registry.opensuse.org/opensuse/distrobox:latest"),
    ("alpine", "Alpine Linux", "quay.io/toolbx-images/alpine-toolbox:edge"),
    ("parrot", "Parrot Security", "docker.io/parrotsec/core:latest"),
]
MODES = {
    "isolada": ("Isolada", "Rede própria: só sai para a internet. Não alcança sua rede local nem o host, "
                           "e nada entra. Pasta pessoal separada."),
    "ponte": ("Ponte", "Usa a rede do host como se fosse um programa instalado nele: enxerga a rede local, "
                       "as interfaces e as portas. Compartilha a sua pasta pessoal."),
}
# instalar pacotes: (teste, comando)
PKG = [("apt-get", "sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y {p}"),
       ("dnf", "sudo dnf install -y {p}"), ("pacman", "sudo pacman -Sy --noconfirm {p}"),
       ("zypper", "sudo zypper -n install {p}"), ("apk", "sudo apk add {p}")]
NFT = """
table inet pandora
delete table inet pandora
table inet pandora {
  chain out {
    type filter hook output priority 0; policy accept;
    oifname "lo" accept
    meta l4proto { tcp, udp } th dport 53 accept
    meta l4proto ipv6-icmp accept
    ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10 } reject
    ip6 daddr { fc00::/7, fe80::/10 } reject
  }
}
"""


class Error(Exception):
    pass


def run(cmd, check=True, timeout=None, input=None):
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, input=input)
    if check and p.returncode != 0:
        raise Error((p.stderr or p.stdout).strip()[-500:] or f"falhou: {' '.join(cmd[:3])}")
    return p.stdout.strip()


def state_path(name):
    return f"{DATA}/{name}.json"


def state(name):
    try:
        return json.load(open(state_path(name)))
    except (OSError, ValueError):
        return {}


def save_state(name, st):
    os.makedirs(DATA, exist_ok=True)
    json.dump(st, open(state_path(name), "w"))


def boxes():
    try:
        raw = json.loads(run(["podman", "ps", "-a", "--filter", "label=pandora=1", "--format", "json"]) or "[]")
    except (Error, ValueError):
        raw = []
    out = []
    for c in raw:
        name = c["Names"][0]
        lab = c.get("Labels") or {}
        img = c.get("Image", "")
        img = state(name).get("image") or img          # depois de uma volta a imagem e a do ponto
        out.append({"name": name, "image": img, "mode": lab.get("pandora.mode", "ponte"),
                    "distro": next((n for _i, n, im in IMAGES if im == img),
                                   "caixa restaurada" if img.startswith(PT_IMG) else img.split("/")[-1]),
                    "running": c.get("State") == "running", "apps": exported(name), "points": points(name)})
    return sorted(out, key=lambda b: b["name"])


def box_home(name):
    return f"{DATA}/homes/{name}"


def create(name, image, mode, log=print):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", name):
        raise Error("nome: minúsculas, números e hífen, começando por letra")
    if mode not in MODES:
        raise Error("modo de rede desconhecido")
    if subprocess.call(["podman", "container", "exists", name]) == 0:
        raise Error(f"já existe uma caixa ou conteiner chamado {name}")
    _make(name, image, mode, log)
    save_state(name, {"image": image, "mode": mode, "baseline": sorted(inside_apps(name))})
    log("▍pronta")


def _make(name, image, mode, log):
    cmd = ["distrobox", "create", "--yes", "--no-entry", "--name", name, "--image", image,
           "--additional-flags", f"--label pandora=1 --label pandora.mode={mode}"]
    if mode == "isolada":
        os.makedirs(box_home(name), exist_ok=True)
        cmd += ["--unshare-netns", "--home", box_home(name)]
    if stream(cmd, log) != 0:
        raise Error("não foi possível criar a caixa (veja o registro)")
    log("▍preparando a caixa (a primeira vez instala o básico dentro dela)…")
    start(name)
    wait_ready(name, log)


def wait_ready(name, log):
    """Acompanha a preparacao inicial do distrobox (instala o basico dentro da caixa)."""
    p = subprocess.Popen(["podman", "logs", "-f", name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, text=True, errors="replace")
    ok = False
    for line in p.stdout:
        line = line.rstrip()
        if "container_setup_done" in line:
            ok = True
            break
        if line and not line.startswith("+ "):
            log(line[:200])
    p.kill()
    if not ok:
        raise Error("a caixa foi criada, mas a preparação falhou (veja o registro)")


def stream(cmd, log):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         text=True, errors="replace")
    for line in p.stdout:
        line = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", line.rstrip())
        if line:
            log(line)
    return p.wait()


def mode_of(name):
    return run(["podman", "inspect", "-f", '{{index .Config.Labels "pandora.mode"}}', name], check=False) or "ponte"


def isolate(name):
    """Modo isolado: dentro da rede da caixa, recusa tudo que nao seja internet (e DNS)."""
    pid = run(["podman", "inspect", "-f", "{{.State.Pid}}", name])
    p = subprocess.run(["podman", "unshare", "nsenter", "-t", pid, "-n", "nft", "-f", "-"], input=NFT,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise Error("não foi possível isolar a rede da caixa: " + p.stderr.strip()[-300:])


def start(name):
    """Liga a caixa (se preciso) e, no modo isolado, aplica o filtro antes de qualquer uso."""
    running = run(["podman", "inspect", "-f", "{{.State.Running}}", name], check=False) == "true"
    if not running:
        run(["podman", "start", name])
    if mode_of(name) == "isolada":
        try:
            isolate(name)
        except Error:
            if not running:
                run(["podman", "stop", "-t", "2", name], check=False)
            raise


def stop(name):
    run(["podman", "stop", "-t", "5", name], check=False)


def destroy(name):
    if run(["podman", "inspect", "-f", '{{index .Config.Labels "pandora"}}', name], check=False) != "1":
        raise Error(f"{name} não é uma caixa da Pandora")
    for f in exported_files(name):
        unexport_file(f)
    run(["podman", "rm", "-f", "-v", name], check=False)
    h = box_home(name)
    if os.path.isdir(h):
        # arquivos criados pelo root da caixa pertencem a sub-uids: remove de dentro do namespace
        run(["podman", "unshare", "rm", "-rf", h], check=False)
    if os.path.exists(state_path(name)):
        os.unlink(state_path(name))
    for p in points(name):
        _point_drop(name, p)
    shutil.rmtree(f"{PTS}/{name}", ignore_errors=True)
    run(["update-desktop-database", APPS], check=False)


# ---------------------------------------------------------------- pontos da caixa
def _is_box(name):
    return run(["podman", "inspect", "-f", '{{index .Config.Labels "pandora"}}', name], check=False) == "1"


def points(name):
    out = []
    for f in glob.glob(f"{PTS}/{name}/*.json"):
        try:
            out.append(json.load(open(f)))
        except (OSError, ValueError):
            pass
    return sorted(out, key=lambda p: p["id"])


def _point_drop(name, p):
    run(["podman", "rmi", "-f", p["image"]], check=False)
    d = f"{PTS}/{name}/{p['id']}"
    if os.path.isdir(d):
        run(["podman", "unshare", "rm", "-rf", d], check=False)
    try:
        os.unlink(f"{d}.json")
    except OSError:
        pass


def point_create(name, desc="ponto manual", kind="manual"):
    """Congela a caixa inteira: os programas instalados (imagem) e, no modo isolado, a pasta pessoal dela."""
    if not _is_box(name):
        raise Error(f"{name} não é uma caixa da Pandora")
    pts = points(name)
    n = pts[-1]["id"] + 1 if pts else 1
    tag = f"{PT_IMG}/{name}:{n}"
    os.makedirs(f"{PTS}/{name}", exist_ok=True)
    run(["podman", "commit", "-q", "--pause", name, tag], timeout=1800)
    home = False
    if mode_of(name) == "isolada" and os.path.isdir(box_home(name)):
        os.makedirs(f"{PTS}/{name}/{n}", exist_ok=True)
        run(["podman", "unshare", "cp", "-a", "--reflink=auto", box_home(name), f"{PTS}/{name}/{n}/home"])
        home = True
    p = {"id": n, "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "desc": desc or "ponto manual",
         "kind": kind, "image": tag, "home": home}
    json.dump(p, open(f"{PTS}/{name}/{n}.json", "w"), ensure_ascii=False)
    for old in [x for x in points(name) if x.get("kind") == "antes"][:-PT_KEEP_AUTO]:
        _point_drop(name, old)
    return p


def point_delete(name, n):
    p = next((x for x in points(name) if x["id"] == n), None)
    if not p:
        raise Error(f"a caixa {name} não tem o ponto #{n}")
    _point_drop(name, p)


def point_restore(name, n, log=print):
    """Volta a caixa a um ponto. O estado de agora vira um ponto antes: voltar nunca apaga."""
    p = next((x for x in points(name) if x["id"] == n), None)
    if not p:
        raise Error(f"a caixa {name} não tem o ponto #{n}")
    if subprocess.call(["podman", "image", "exists", p["image"]]) != 0:
        raise Error(f"a imagem do ponto #{n} não existe mais")
    mode = mode_of(name)
    st = state(name)
    if not st.get("image"):        # caixa sem registro: guarda de qual imagem ela nasceu
        st["image"] = run(["podman", "inspect", "-f", "{{.ImageName}}", name], check=False)
    log(f"▍guardando o estado de agora (ponto antes de voltar ao #{n})…")
    saved = point_create(name, f"antes de voltar ao ponto #{n}", "antes")
    for f in exported_files(name):
        unexport_file(f)
    run(["podman", "rm", "-f", "-v", name], check=False)
    if mode == "isolada" and p.get("home"):
        if os.path.isdir(box_home(name)):
            run(["podman", "unshare", "rm", "-rf", box_home(name)], check=False)
        os.makedirs(os.path.dirname(box_home(name)), exist_ok=True)
        run(["podman", "unshare", "cp", "-a", "--reflink=auto", f"{PTS}/{name}/{n}/home", box_home(name)])
    log(f"▍recriando a caixa a partir do ponto #{n}…")
    _make(name, p["image"], mode, log)
    st.setdefault("mode", mode)
    save_state(name, st)
    sync(name, log)
    log("▍pronta")
    return saved


# ---------------------------------------------------------------- aplicativos no menu
def inside_apps(name):
    """Lancadores visiveis dentro da caixa: {arquivo.desktop}."""
    sh = ("for f in /usr/share/applications/*.desktop /usr/local/share/applications/*.desktop "
          "/var/lib/flatpak/exports/share/applications/*.desktop; do [ -f \"$f\" ] || continue; "
          "grep -qiE '^(NoDisplay|Hidden)=true' \"$f\" && continue; grep -q '^Exec=' \"$f\" && echo \"$f\"; done")
    out = run(["podman", "exec", name, "sh", "-c", sh], check=False, timeout=30)
    return {l for l in out.splitlines() if l.endswith(".desktop")}


def exported_files(name):
    return sorted(glob.glob(f"{APPS}/{name}-*.desktop"))


def exported(name):
    out = []
    for f in exported_files(name):
        txt = open(f, errors="replace").read()
        m = re.search(r"^Name=(.*)$", txt, re.M)
        out.append({"file": f, "id": os.path.basename(f), "name": m.group(1) if m else os.path.basename(f)})
    return out


def unexport_file(f):
    try:
        os.unlink(f)
    except OSError:
        pass


def sync(name, log=lambda *_: None):
    """Deixa o menu do GNOME igual ao que esta instalado na caixa. Retorna (novos, removidos)."""
    st = state(name)
    base = set(st.get("baseline", []))
    want = {f for f in inside_apps(name) if f not in base}
    have = {os.path.basename(f)[len(name) + 1:]: f for f in exported_files(name)}
    added, removed = [], []
    for f in sorted(want):
        b = os.path.basename(f)
        if b in have:
            continue
        p = subprocess.run(["distrobox", "enter", name, "--", "distrobox-export", "--app", f],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        dst = f"{APPS}/{name}-{b}"
        if p.returncode == 0 and os.path.exists(dst):
            fix_launcher(name, dst)
            added.append(b)
            log(f"novo no menu: {b}")
    wantb = {os.path.basename(f) for f in want}
    for b, f in have.items():
        if b not in wantb:
            unexport_file(f)
            removed.append(b)
    if added or removed:
        run(["update-desktop-database", APPS], check=False)
    return added, removed


def fix_launcher(name, path):
    """O atalho passa pela Pandora: liga a caixa, aplica o modo de rede e so entao executa."""
    txt = open(path, errors="replace").read()
    txt = re.sub(r"^(Exec=)\S*distrobox(?:-enter)?\s+(?:enter\s+)?(?:-n|--name)\s+\S+\s+--\s+", rf"\1{ENTER} {name} -- ",
                 txt, flags=re.M)
    txt = re.sub(r"^(Name(?:\[[^\]]+\])?=.*?)\s*\(on [^)]*\)\s*$", rf"\1 ({name})", txt, flags=re.M)
    if "X-Pandora=" not in txt:
        txt = txt.replace("[Desktop Entry]", f"[Desktop Entry]\nX-Pandora={name}", 1)
    open(path, "w").write(txt)


def install_cmd(name):
    for test, cmd in PKG:
        if subprocess.call(["podman", "exec", name, "sh", "-c", f"command -v {test}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            return cmd
    raise Error("não reconheci o gerenciador de pacotes desta caixa")


def install(name, pkgs, log=print):
    if not re.fullmatch(r"[A-Za-z0-9+._:@ -]+", pkgs):
        raise Error("nome de pacote inválido")
    start(name)
    rc = stream(["distrobox", "enter", name, "--", "sh", "-c", install_cmd(name).format(p=pkgs)], log)
    added, _r = sync(name, log)
    if rc != 0:
        raise Error("a instalação falhou (veja o registro)")
    return added


def watch():
    """Enquanto houver caixa ligada, acompanha o que e instalado dentro delas e ajusta o menu."""
    seen = {}
    idle = 0
    while idle < 4:
        names = run(["podman", "ps", "--filter", "label=pandora=1", "--format", "{{.Names}}"], check=False).split()
        idle = 0 if names else idle + 1
        for n in names:
            try:
                sig = hashlib.sha1("\n".join(sorted(inside_apps(n))).encode()).hexdigest()
                if seen.get(n) != sig:
                    if state(n):
                        sync(n)
                    seen[n] = sig
            except (Error, subprocess.TimeoutExpired, OSError):
                pass
        time.sleep(8)


def enter(name, cmd):
    start(name)
    subprocess.Popen(["systemctl", "--user", "start", "pandora-watch.service"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.execvp("distrobox", ["distrobox", "enter", name] + (["--"] + cmd if cmd else []))


def main(argv):
    try:
        if len(argv) >= 3 and argv[1] == "enter":
            rest = argv[3:]
            if rest[:1] == ["--"]:
                rest = rest[1:]
            enter(argv[2], rest)
        elif argv[1:] == ["watch"]:
            watch()
        elif argv[1:] == ["list"]:
            print(json.dumps(boxes(), ensure_ascii=False, indent=1))
        elif len(argv) == 3 and argv[1] == "sync":
            print(sync(argv[2], print))
        elif len(argv) == 5 and argv[1] == "create":
            create(argv[2], argv[3], argv[4])
        elif len(argv) == 4 and argv[1] == "install":
            print(install(argv[2], argv[3]))
        elif len(argv) == 3 and argv[1] == "destroy":
            destroy(argv[2])
        elif len(argv) >= 3 and argv[1] == "point-create":
            print(json.dumps(point_create(argv[2], " ".join(argv[3:])), ensure_ascii=False))
        elif len(argv) == 3 and argv[1] == "points":
            print(json.dumps(points(argv[2]), ensure_ascii=False, indent=1))
        elif len(argv) == 4 and argv[1] == "point-restore":
            print(json.dumps(point_restore(argv[2], int(argv[3])), ensure_ascii=False))
        elif len(argv) == 4 and argv[1] == "point-delete":
            point_delete(argv[2], int(argv[3]))
        else:
            print("uso interno da Pandora (abra o aplicativo Pandora)", file=sys.stderr)
            return 64
    except Error as e:
        print(f"pandora: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

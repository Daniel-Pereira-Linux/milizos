# MilizOS - Modo Incidente
# Contem a maquina e preserva evidencias na ordem de volatilidade, com trilha de custodia.
#   nos incident start [--allow IP] [--no-isolate]   |   nos incident status   |   nos incident release
import datetime
import getpass
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile

from ui import ac, bad, dim, need_root, ok, sh, rc, warn

BASE = "/var/lib/milizos/incidents"
ACTIVE = BASE + "/ACTIVE"
UNIT = "nos-incident-capture"
TABLE = "nos_isolate"

VOLATILE = [
    ("01-data-hora", "date -Is; timedatectl 2>/dev/null; uptime"),
    ("02-processos", "ps -eo pid,ppid,user,lstart,stat,%cpu,%mem,cmd --forest"),
    ("03-conexoes", "ss -tulpanH; echo; ss -xpanH 2>/dev/null | head -n 400"),
    ("04-rede", "ip -d addr; echo; ip route show table all; echo; ip neigh; echo; conntrack -L 2>/dev/null | head -n 2000"),
    ("05-usuarios", "who -a; echo; w; echo; last -n 100 -F 2>/dev/null"),
    ("06-arquivos-abertos-rede", "lsof -nP -i 2>/dev/null | head -n 2000"),
    ("07-modulos", "lsmod; echo; cat /proc/sys/kernel/tainted"),
    ("08-exe-apagados", "ls -l /proc/[0-9]*/exe 2>/dev/null | grep '(deleted)'"),
    ("09-mapas-suspeitos", "grep -l 'rwxp' /proc/[0-9]*/maps 2>/dev/null | head -n 200"),
    ("10-montagens", "findmnt -A; echo; lsblk -f"),
    ("11-firewall", "nft list ruleset 2>&1"),
    ("12-timers-cron", "systemctl list-timers --all --no-pager; for f in /etc/crontab /etc/cron.*/* /var/spool/cron/*; do echo \"== $f\"; cat \"$f\" 2>/dev/null; done"),
    ("13-journal", "journalctl -b --no-pager | tail -n 5000"),
    ("14-auditoria", "ausearch -ts today 2>&1 | tail -n 3000"),
]


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class Case:
    def __init__(self, path):
        self.path = path
        self.id = os.path.basename(path)

    def log(self, msg):
        with open(f"{self.path}/timeline.log", "a", encoding="utf-8") as f:
            f.write(f"{now()}  {msg}\n")
        print(f"  {dim(now()[11:19])}  {msg}")

    def collect(self, name, cmd, timeout=180):
        out = sh(cmd, timeout=timeout)
        p = f"{self.path}/volatil/{name}.txt"
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"# {cmd}\n{out}\n")
        self.log(f"coletado {name}  sha256={sha256(p)[:16]}…")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def manifest(case):
    lines = []
    for root, _d, files in os.walk(case.path):
        for fn in sorted(files):
            if fn == "MANIFEST.sha256":
                continue
            p = os.path.join(root, fn)
            lines.append(f"{sha256(p)}  {os.path.relpath(p, case.path)}")
    with open(f"{case.path}/MANIFEST.sha256", "w") as f:
        f.write("\n".join(sorted(lines, key=lambda l: l.split('  ', 1)[1])) + "\n")
    return len(lines)


def isolate(allow):
    rules = [f"table inet {TABLE} {{",
             "  set allow4 { type ipv4_addr; flags interval; " + (f"elements = {{ {', '.join(allow)} }}; " if allow else "") + "}",
             "  chain input { type filter hook input priority -300; policy drop;",
             "    iif lo accept",
             "    ip saddr @allow4 accept",
             "  }",
             "  chain output { type filter hook output priority -300; policy drop;",
             "    oif lo accept",
             "    ip daddr @allow4 accept",
             "  }",
             "  chain forward { type filter hook forward priority -300; policy drop; }",
             "}"]
    subprocess.run(["nft", "delete", "table", "inet", TABLE], capture_output=True)
    p = subprocess.run(["nft", "-f", "-"], input="\n".join(rules), text=True, capture_output=True)
    return p.returncode == 0, p.stderr.strip()


def active():
    try:
        return Case(open(ACTIVE).read().strip())
    except OSError:
        return None


def start(args):
    need_root(["incident", "start"] + args)
    if active():
        sys.exit(f"já existe um incidente ativo: {active().id} (encerre com: nos incident release)")
    allow, do_isolate = [], True
    it = iter(args)
    for a in it:
        if a == "--allow":
            allow.append(next(it, ""))
        elif a == "--no-isolate":
            do_isolate = False
        else:
            sys.exit("uso: nos incident start [--allow IP/CIDR]... [--no-isolate]")
    ssh = os.environ.get("SSH_CONNECTION") or os.environ.get("SUDO_SSH_CONNECTION", "")
    if ssh and ssh.split()[0] not in allow and ":" not in ssh.split()[0]:
        allow.append(ssh.split()[0])       # nao derruba a propria sessao de quem esta respondendo
    cid = "INC-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = f"{BASE}/{cid}"
    os.makedirs(f"{path}/volatil", mode=0o700)
    os.makedirs(f"{path}/captura", mode=0o700)
    os.chmod(BASE, 0o700)
    case = Case(path)
    with open(ACTIVE, "w") as f:
        f.write(path + "\n")
    print(ac(f"▍MODO INCIDENTE  {cid}"))
    who = os.environ.get("SUDO_USER") or getpass.getuser()
    json.dump({"id": cid, "host": os.uname().nodename, "aberto_por": who, "inicio": now(),
               "isolamento": do_isolate, "permitidos": allow, "kernel": os.uname().release},
              open(f"{path}/caso.json", "w"), ensure_ascii=False, indent=1)
    case.log(f"incidente aberto por {who} em {os.uname().nodename}")

    # 1) captura de trafego primeiro: registra o que acontecer daqui em diante
    cap = ["systemd-run", "--quiet", "--unit", UNIT, "--collect", "tcpdump", "-i", "any", "-n", "-s", "0",
           "-C", "50", "-W", "20", "-w", f"{path}/captura/incidente.pcap"]
    if rc(cap) == 0:
        case.log("captura de tráfego iniciada (anel 20 × 50 MB, todas as interfaces)")
    else:
        case.log("AVISO: não foi possível iniciar a captura de tráfego")

    # 2) estado volatil, do mais efemero para o menos
    for name, cmd in VOLATILE:
        case.collect(name, cmd)
    if shutil.which("avml"):
        r = rc(["avml", "--compress", f"{path}/memoria.lime"], timeout=1800)
        case.log("memória RAM adquirida (avml)" if r == 0 else "AVISO: falha na aquisição de memória")
    else:
        case.log("memória RAM não adquirida: sem ferramenta de aquisição (kernel em lockdown bloqueia /proc/kcore)")

    # 3) contencao
    if do_isolate:
        good, err = isolate(allow)
        if good:
            case.log("HOST ISOLADO da rede" + (f" (permitidos: {', '.join(allow)})" if allow else " (nenhum endereço permitido)"))
        else:
            case.log(f"FALHA no isolamento: {err}")
    else:
        case.log("isolamento não aplicado (--no-isolate)")

    # 4) estado em disco: checkpoint + triagem
    try:
        sys.path.insert(0, "/usr/lib/milizos")
        import checkpoint as cp
        if cp.supported() and not cp.pending():
            n = cp.create(f"incidente {cid}", "manual")
            case.log(f"checkpoint #{n} do sistema criado (estado em disco preservado)")
        else:
            case.log("checkpoint não criado: sistema de arquivos sem suporte (requer btrfs)")
    except Exception as e:  # noqa
        case.log(f"checkpoint não criado: {e}")
    r = subprocess.run(["/usr/bin/nos", "triage", "-q", "-d", path], capture_output=True, text=True)
    case.log("triagem do host concluída" if r.returncode == 0 else "AVISO: triagem falhou")
    n = manifest(case)
    case.log(f"manifesto de integridade gravado ({n} arquivos)")
    print(f"\n  {ok('✔')} evidências em {path}")
    if do_isolate:
        print(f"  {warn('A máquina está isolada.')} Para encerrar e empacotar: {ac('sudo nos incident release')}")


def status(_args):
    c = active()
    if not c:
        print(dim("  Nenhum incidente ativo."))
        if os.path.isdir(BASE) and os.access(BASE, os.R_OK):
            done = sorted(f for f in os.listdir(BASE) if f.endswith(".tar.gz"))
            for d in done[-5:]:
                print(f"  {dim('·')} {d}")
        return
    need_root(["incident", "status"])
    info = json.load(open(f"{c.path}/caso.json"))
    iso = rc(["nft", "list", "table", "inet", TABLE]) == 0
    cap = sh(["systemctl", "is-active", UNIT])
    print(ac(f"▍Incidente ativo  {c.id}"))
    print(f"  aberto por {info['aberto_por']} em {info['inicio']}")
    print(f"  {bad('●') if iso else dim('○')} isolamento de rede   {'ATIVO' if iso else 'inativo'}")
    print(f"  {ok('●') if cap == 'active' else dim('○')} captura de tráfego   {cap}")
    print(f"  pasta: {c.path}  ({sh('du -sh ' + c.path).split()[0]})")


def release(args):
    need_root(["incident", "release"] + args)
    c = active()
    if not c:
        sys.exit("nenhum incidente ativo")
    print(ac(f"▍Encerrando {c.id}"))
    subprocess.run(["systemctl", "stop", UNIT], capture_output=True)
    c.log("captura de tráfego encerrada")
    if rc(["nft", "delete", "table", "inet", TABLE]) == 0:
        c.log("isolamento de rede removido")
    info = json.load(open(f"{c.path}/caso.json"))
    info["fim"] = now()
    info["encerrado_por"] = os.environ.get("SUDO_USER") or getpass.getuser()
    json.dump(info, open(f"{c.path}/caso.json", "w"), ensure_ascii=False, indent=1)
    c.log(f"incidente encerrado por {info['encerrado_por']}")
    n = manifest(c)
    tar = f"{BASE}/{c.id}.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(c.path, arcname=c.id)
    os.chmod(tar, 0o600)
    digest = sha256(tar)
    open(tar + ".sha256", "w").write(f"{digest}  {os.path.basename(tar)}\n")
    os.unlink(ACTIVE)
    if "--keep" not in args:
        shutil.rmtree(c.path)
    print(f"  {ok('✔')} pacote de evidências: {tar}  ({n} arquivos)")
    print(f"  sha256: {digest}")


def main(args):
    act = args[0] if args else "status"
    {"start": start, "status": status, "release": release}.get(
        act, lambda _a: sys.exit("ações: start [--allow IP]... [--no-isolate], status, release [--keep]"))(args[1:])

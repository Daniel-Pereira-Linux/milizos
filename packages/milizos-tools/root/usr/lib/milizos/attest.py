# MilizOS - Atestacao de integridade
# Responde: "este sistema ainda e o que foi instalado?"  Confere cada arquivo de pacote
# contra o banco RPM, procura executaveis sem dono, e compara com o selo gravado.
#   nos attest            verifica          nos attest seal   grava o selo (estado de referencia)
import datetime
import hashlib
import json
import os
import subprocess
import sys

from ui import ac, bad, dim, need_root, ok, sh, warn

SEAL = "/var/lib/milizos/attest/seal.json"
BINDIRS = ["/usr/bin", "/usr/sbin", "/usr/libexec", "/usr/lib/systemd/system", "/etc/systemd/system"]


def boot_state():
    def rd(p):
        try:
            return open(p).read().strip()
        except OSError:
            return ""
    sb = sh("mokutil --sb-state 2>/dev/null")
    lock = rd("/sys/kernel/security/lockdown")
    return {
        "secure_boot": "enabled" in sb.lower(),
        "lockdown": lock[lock.find("[") + 1:lock.find("]")] if "[" in lock else "none",
        "selinux": sh("getenforce 2>/dev/null") or "?",
        "tainted": rd("/proc/sys/kernel/tainted") or "0",
        "kernel": os.uname().release,
    }


def modified():
    """Arquivos de pacote cujo conteudo difere do que o pacote instalou (ignora configuracao)."""
    p = subprocess.run(["rpm", "-Va", "--nomtime", "--nouser", "--nogroup", "--nomode", "--nordev", "--nocaps",
                        "--nolinkto"], capture_output=True, text=True)
    out = []
    for l in p.stdout.splitlines():
        flags, rest = l[:9], l[9:].strip()
        if rest.startswith(("c ", "d ", "g ", "l ", "r ")):
            continue
        if "5" in flags or flags.startswith("missing"):
            path = rest.split()[-1]
            if path.startswith(("/usr/lib/.build-id", "/var/", "/usr/share/mime", "/usr/lib/sysimage", "/usr/share/doc/", "/usr/share/xml/scap/", "/usr/share/scap-security-guide/", "/boot/", "/etc/")) or path.endswith(".pyc"):
                continue
            out.append(("ausente" if flags.startswith("missing") else "alterado", path))
    return out


def unowned():
    files = []
    for d in BINDIRS:
        for root, _dirs, fs in os.walk(d):
            files += [os.path.join(root, f) for f in fs]
    res = []
    for i in range(0, len(files), 500):
        p = subprocess.run(["rpm", "-qf"] + files[i:i + 500], capture_output=True, text=True,
                           env=dict(os.environ, LC_ALL="C"))
        for l in p.stdout.splitlines():
            if "is not owned by any package" in l:
                f = l.split(" ", 1)[1].rsplit(" is not owned", 1)[0]
                if not os.path.islink(f) or not f.startswith("/etc/systemd/system"):
                    res.append(f)
    return sorted(res)


def digest(paths):
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.encode())
        try:
            with open(p, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            h.update(b"-")
    return h.hexdigest()


def state():
    pk = sorted(sh("rpm -qa --qf '%{NAME} %{EVR}.%{ARCH}\\n'", timeout=120).splitlines())
    un = unowned()
    return {"pacotes": pk, "sem_dono": un, "sem_dono_sha256": digest(un), "boot": boot_state()}


def main(args):
    act = args[0] if args else "verify"
    if act not in ("verify", "seal"):
        sys.exit("ações: verify (padrão) | seal")
    need_root(["attest"] + args)
    if act == "seal":
        s = state()
        s["quando"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        os.makedirs(os.path.dirname(SEAL), mode=0o700, exist_ok=True)
        json.dump(s, open(SEAL, "w"), ensure_ascii=False)
        os.chmod(SEAL, 0o600)
        print(f"  {ok('✔')} selo gravado: {len(s['pacotes'])} pacotes, {len(s['sem_dono'])} arquivos fora de pacote")
        print(dim("  guarde uma cópia fora da máquina para comparar com segurança: " + SEAL))
        return
    print(ac("▍Atestação de integridade") + dim("   conferindo todos os arquivos de pacotes (leva alguns minutos)…"), flush=True)
    problems = 0
    b = boot_state()
    rows = [("Secure Boot", b["secure_boot"], "ativo" if b["secure_boot"] else "inativo"),
            ("Kernel lockdown", b["lockdown"] != "none", b["lockdown"]),
            ("SELinux", b["selinux"] == "Enforcing", b["selinux"]),
            ("Kernel sem módulos externos", b["tainted"] == "0", "limpo" if b["tainted"] == "0" else f"tainted={b['tainted']}")]
    for name, good, val in rows:
        print(f"  {ok('●') if good else warn('●')} {name:<30} {val}")
    mod = modified()
    print(f"  {ok('●') if not mod else bad('●')} {'Arquivos de pacote íntegros':<30} "
          + ("todos conferem" if not mod else f"{len(mod)} divergência(s)"))
    for kind, path in mod[:40]:
        print(f"      {bad(kind):<10} {path}  {dim(sh(['rpm', '-qf', '--qf', '%{NAME}', path]))}")
    problems += len(mod)
    cur = state()
    if os.path.exists(SEAL):
        seal = json.load(open(SEAL))
        a, c = set(seal["pacotes"]), set(cur["pacotes"])
        newf = sorted(set(cur["sem_dono"]) - set(seal["sem_dono"]))
        chg = cur["sem_dono_sha256"] != seal["sem_dono_sha256"] and not newf
        print(f"  {ok('●') if a == c else warn('●')} {'Pacotes desde o selo':<30} +{len(c - a)} / -{len(a - c)}"
              + dim(f"   (selo de {seal.get('quando', '?')})"))
        for x in sorted(c - a)[:15]:
            print(f"      {ok('+')} {x}")
        for x in sorted(a - c)[:15]:
            print(f"      {bad('-')} {x}")
        print(f"  {ok('●') if not newf and not chg else bad('●')} {'Executáveis/units fora de pacote':<30} "
              + ("sem novidades" if not newf and not chg else f"{len(newf)} novo(s)" + (" · conteúdo alterado" if chg else "")))
        for f in newf[:40]:
            print(f"      {bad('novo')} {f}")
        problems += len(newf) + int(chg)
    else:
        print(f"  {dim('○')} {'Selo de referência':<30} ainda não gravado — use: sudo nos attest seal")
        for f in cur["sem_dono"][:20]:
            print(f"      {warn('fora de pacote')} {f}")
    print("\n  Veredito: " + (ok("ÍNTEGRO") if problems == 0 else bad(f"ALTERADO ({problems} achado(s))")))
    sys.exit(0 if problems == 0 else 3)

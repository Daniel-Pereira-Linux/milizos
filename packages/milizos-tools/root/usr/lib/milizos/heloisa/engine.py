#!/usr/bin/python3
# Heloisa - motor da linha do tempo do MilizOS.
#
# Um "ponto" e uma fotografia somente-leitura da maquina inteira, feita com snapshots btrfs:
#
#   volume btrfs:  root  home  log  snapshots/<id>/{root,home,log,info.json,packages.txt}
#
# O kernel e o initramfs de cada ponto ficam em /boot/checkpoints/<id>/ e o ponto ganha uma
# entrada no GRUB. Nada aqui e formato proprio: sao subvolumes btrfs comuns, visiveis em
# /.heloisa e manipulaveis com btrfs, cp, diff, rsync.
#
# Toda operacao destrutiva cria antes um ponto com o estado atual; voltar atras nunca
# apaga historia (como um "git revert").
import collections
import datetime
import gzip
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys

TOP = "/run/heloisa/top"
SNAP = TOP + "/snapshots"
BOOTCP = "/boot/checkpoints"
GRUBCFG = "/boot/grub2/heloisa.cfg"
SELF = "/usr/libexec/milizos/heloisa-engine"
PARTS = {"root": "/", "home": "/home", "log": "/var/log"}       # subvolume -> ponto de montagem
KINDS = {"install": "instalação", "manual": "manual", "dnf": "pacotes", "hora": "automático",
         "boot": "inicialização", "antes": "antes de voltar"}
KEEP = {"dnf": 12, "boot": 5, "antes": 12}      # quantos manter por tipo (manual e install: todos)
KEEP_HOURLY_H, KEEP_DAILY_D = 24, 14            # tipo "hora": todos por 24 h, um por dia por 14 dias
GRUB_MAX = 15
MIN_FREE = 0.15                                  # abaixo disso de espaco livre, pontos automaticos antigos saem
AUTO_KINDS = ("hora", "boot", "dnf", "antes")   # manual e install nunca sao apagados sozinhos
TEXT_MAX = 2 * 1024 * 1024
STATE = SNAP + "/.state"                         # estado que sobrevive a qualquer volta do sistema
BR = TOP + "/branches"                           # ramos inativos: branches/<nome>/root
BOOTBR = "/boot/branches"
MAIN = "principal"
MAX_BRANCHES = 6
ORPHAN = re.compile(r"^o\d+-\d+-\d+$")
NOISE_ROOT = re.compile(r"^(var/(cache|tmp|lib/(dnf|rpm|systemd|NetworkManager|chrony|heloisa|selinux|plymouth|fwupd|"
                        r"PackageKit|upower|bluetooth|AccountsService|gdm|geoclue|colord|logrotate)|spool|run|lock)|"
                        r"tmp|root/\.cache|etc/(resolv\.conf|adjtime|machine-id|\.updated|\.pwd\.lock))(/|$)")
RANSOM_MIN = 100                                 # arquivos pessoais reescritos entre dois pontos
RANSOM_ENTROPY = 7.6                             # bits por byte: dado cifrado fica perto de 8
COMPRESSED = (".zip .gz .xz .zst .bz2 .7z .rar .jpg .jpeg .png .gif .webp .heic .mp3 .mp4 .mkv .mov .avi .webm "
              ".ogg .opus .flac .m4a .pdf .docx .xlsx .pptx .odt .ods .odp .iso .img .qcow2 .rpm .deb .apk .jar "
              ".whl .gpg .age .kdbx .enc").split()
RISKY_DIRS = re.compile(r"^/var/lib/(mysql|mariadb|pgsql|postgresql|mongodb|mongo|redis|valkey|clickhouse|influxdb|"
                        r"elasticsearch|opensearch|cassandra|etcd|libvirt/images|containers|docker|machines)(/|$)")
RISKY_EXT = {".sqlite": "banco SQLite", ".sqlite3": "banco SQLite", ".db": "banco de dados", ".mdb": "banco de dados",
             ".ldb": "banco de dados", ".wal": "registro de transações de banco", ".ibd": "tabela do MySQL/MariaDB",
             ".frm": "tabela do MySQL/MariaDB", ".qcow2": "disco de máquina virtual", ".vmdk": "disco de máquina virtual",
             ".vdi": "disco de máquina virtual", ".raw": "imagem de disco", ".kdbx": "cofre de senhas"}


class Error(Exception):
    pass


def run(cmd, check=True, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)
    if check and p.returncode != 0:
        raise Error(f"{' '.join(cmd[:3])}: {(p.stderr or p.stdout).strip()[-400:]}")
    return p.stdout.strip()


def now():
    return datetime.datetime.now()


def rootdev():
    dev = os.environ.get("HELOISA_ROOTDEV") or run(["findmnt", "-no", "SOURCE", "/"], check=False)
    return re.sub(r"\[.*\]$", "", dev)


def live():
    return os.path.exists("/run/initramfs/live")


def supported():
    if os.environ.get("HELOISA_ROOTDEV"):
        return True
    if live():
        return False
    opts = run(["findmnt", "-no", "OPTIONS", "/"], check=False)
    return (run(["findmnt", "-no", "FSTYPE", "/"], check=False) == "btrfs"
            and re.search(r"subvol=/(root|snapshots/\.old-root-\d+|branches/[^/,]+/root)(,|$)", opts) is not None)


def pending():
    """Ha uma volta no tempo aplicada aguardando reinicializacao?"""
    for mp in ("/", "/home", "/var/log"):
        o = run(["findmnt", "-no", "OPTIONS", mp], check=False)
        if "snapshots/.old-" in o or "subvol=/branches/" in o:
            return True
    return False


def need(write=True):
    if os.geteuid() != 0:
        raise Error("é preciso ser administrador")
    if not supported():
        raise Error("a Heloisa precisa do MilizOS instalado em btrfs (padrão do instalador)")
    if write and pending():
        raise Error("há uma volta no tempo aguardando: reinicie o computador para concluí-la")


class Top:
    """Monta a raiz do volume btrfs (subvolid=5) enquanto durar o bloco."""
    depth = 0

    def __enter__(self):
        if Top.depth == 0:
            os.makedirs(TOP, exist_ok=True)
            if not os.path.ismount(TOP):
                run(["mount", "-t", "btrfs", "-o", "subvolid=5", rootdev(), TOP])
            if not os.path.isdir(SNAP):
                run(["btrfs", "subvolume", "create", SNAP])
            if not os.path.isdir(STATE):
                os.makedirs(STATE, mode=0o755, exist_ok=True)
            elif os.stat(STATE).st_mode & 0o777 != 0o755:
                os.chmod(STATE, 0o755)      # a interface le daqui, sem privilegio, se ha algo esperando resposta
        Top.depth += 1
        return self

    def __exit__(self, *_a):
        Top.depth -= 1
        if Top.depth == 0 and not SERVING:
            run(["umount", TOP], check=False)


SERVING = False


# ---------------------------------------------------------------- pontos
def items():
    out = []
    for n in os.listdir(SNAP):
        if not n.isdigit():
            continue
        try:
            with open(f"{SNAP}/{n}/info.json", encoding="utf-8") as f:
                i = json.load(f)
        except (OSError, ValueError):
            continue
        i["parts"] = [p for p in PARTS if os.path.isdir(f"{SNAP}/{n}/{p}")]
        i["bootable"] = bool(i.get("cmdline")) and all(
            os.path.exists(f"{BOOTCP}/{i['id']}/{f}") for f in ("vmlinuz", "initramfs.img"))
        i["label"] = KINDS.get(i.get("kind"), i.get("kind", ""))
        i.setdefault("branch", MAIN)
        i.setdefault("summary", "")
        i["protected"] = bool(i.get("protected"))
        i["sealed"] = os.path.exists(f"{SNAP}/{n}/seal.json")
        i["pushed"] = list(i.get("pushed") or [])
        out.append(i)
    return sorted(out, key=lambda i: i["id"])


def _kver():
    cand = [os.uname().release] + sorted(
        (f[8:] for f in os.listdir("/boot") if f.startswith("vmlinuz-") and "rescue" not in f), reverse=True)
    for k in cand:
        if os.path.exists(f"/boot/vmlinuz-{k}") and os.path.exists(f"/boot/initramfs-{k}.img"):
            return k
    return None


def _link(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def _pkgs(root="/"):
    return run(["rpm", "--root", root, "-qa", "--qf", "%{NAME} %{EVR}.%{ARCH}\n"], check=False)


def _write_info(d, info, root):
    with open(f"{d}/packages.txt", "w") as f:
        f.write("\n".join(sorted(_pkgs(root).splitlines())) + "\n")
    with open(f"{d}/info.json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False)


def _info_update(cid, **kw):
    f = f"{SNAP}/{cid}/info.json"
    with open(f, encoding="utf-8") as h:
        i = json.load(h)
    i.update(kw)
    with open(f + ".new", "w", encoding="utf-8") as h:
        json.dump(i, h, ensure_ascii=False)
    os.replace(f + ".new", f)
    return i


def _state(name, default=None):
    try:
        with open(f"{STATE}/{name}.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _set_state(name, value):
    os.makedirs(STATE, mode=0o755, exist_ok=True)
    f = f"{STATE}/{name}.json"
    if value is None:
        if os.path.exists(f):
            os.unlink(f)
        return
    with open(f + ".new", "w", encoding="utf-8") as h:
        json.dump(value, h, ensure_ascii=False)
    os.replace(f + ".new", f)


def _kept(i, its):
    """Pontos que nunca saem sozinhos: protegidos, selados e o ultimo enviado para fora (base do proximo envio)."""
    if i["protected"] or i["sealed"]:
        return True
    pushed = [x["id"] for x in its if x["pushed"]]
    return bool(pushed) and i["id"] == pushed[-1]


def _next_id():
    ids = [int(n) for n in os.listdir(SNAP) if n.isdigit()]
    return max(ids) + 1 if ids else 1


def create(desc, kind="manual"):
    """Fotografa a maquina inteira (sistema, /home e logs). Retorna o numero do ponto."""
    need()
    with Top():
        cid = _next_id()
        d = f"{SNAP}/{cid}"
        os.makedirs(d)
        try:
            for part, mp in PARTS.items():
                if os.path.isdir(f"{TOP}/{part}") and os.path.ismount(mp):
                    run(["btrfs", "subvolume", "snapshot", "-r", mp, f"{d}/{part}"])
            if not os.path.isdir(f"{d}/root"):
                raise Error("não foi possível fotografar o sistema")
        except Error:
            _delete(cid)
            raise
        info = {"id": cid, "time": now().strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "desc": desc,
                "kernel": None, "cmdline": "", "branch": branch_name()}
        k = _kver()
        if k:
            os.makedirs(f"{BOOTCP}/{cid}", exist_ok=True)
            _link(f"/boot/vmlinuz-{k}", f"{BOOTCP}/{cid}/vmlinuz")
            _link(f"/boot/initramfs-{k}.img", f"{BOOTCP}/{cid}/initramfs.img")
            info["kernel"] = k
        try:
            info["cmdline"] = open("/etc/kernel/cmdline").read().strip()
        except OSError:
            pass
        _write_info(d, info, "/")
        try:
            _describe(cid)
        except Exception:  # noqa: o resumo nunca impede um ponto de existir
            pass
        prune()
        space_guard()
        gen_grub()
    return cid


def prune():
    its = items()
    for kind, keep in KEEP.items():
        for i in [x for x in its if x["kind"] == kind][:-keep]:
            if not _kept(i, its):
                _delete(i["id"])
    days = set()
    for i in reversed([x for x in its if x["kind"] == "hora"]):
        if _kept(i, its):
            continue
        t = datetime.datetime.strptime(i["time"][:16], "%Y-%m-%d %H:%M")
        age = now() - t
        day = i["time"][:10]
        if age <= datetime.timedelta(hours=KEEP_HOURLY_H):
            days.add(day)
        elif age <= datetime.timedelta(days=KEEP_DAILY_D) and day not in days:
            days.add(day)
        else:
            _delete(i["id"])


def _free_ratio():
    u = run(["btrfs", "filesystem", "usage", "-b", TOP], check=False)
    m1, m2 = re.search(r"Device size:\s+(\d+)", u), re.search(r"Free \(estimated\):\s+(\d+)", u)
    return int(m2.group(1)) / int(m1.group(1)) if m1 and m2 and int(m1.group(1)) else 1.0


def space_guard():
    """Disco enchendo: apaga os pontos automaticos mais antigos ate voltar a ter folga.
    O ponto automatico mais recente sempre fica."""
    its = items()
    auto = [i for i in its if i["kind"] in AUTO_KINDS and not _kept(i, its)][:-1]
    removed = 0
    while auto and _free_ratio() < MIN_FREE:
        _delete(auto.pop(0)["id"])
        removed += 1
        run(["btrfs", "filesystem", "sync", TOP], check=False)
    return removed


def _delete(cid):
    d = f"{SNAP}/{cid}"
    for part in PARTS:
        if os.path.isdir(f"{d}/{part}"):
            run(["btrfs", "subvolume", "delete", f"{d}/{part}"], check=False)
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(f"{BOOTCP}/{cid}", ignore_errors=True)


def delete(cid):
    need()
    with Top():
        if not os.path.isdir(f"{SNAP}/{cid}"):
            raise Error(f"o ponto #{cid} não existe")
        b = _state("bisect")
        if b and b.get("active") and cid in (b.get("origin"), b.get("good"), b.get("testing")):
            raise Error("este ponto está em uso pela busca do que quebrou; conclua ou cancele a busca antes")
        _delete(cid)
        gen_grub()


def protect(cid, on=True):
    """Ponto protegido nunca e apagado sozinho (nem pela retencao, nem pela trava de espaco)."""
    need(write=False)
    with Top():
        if not os.path.isdir(f"{SNAP}/{cid}"):
            raise Error(f"o ponto #{cid} não existe")
        _info_update(cid, protected=bool(on))


def gen_grub():
    """Reescreve o submenu lido pelo grub.cfg (sem precisar do grub2-mkconfig)."""
    if not os.path.isdir("/boot/grub2"):
        return
    uuid = os.environ.get("HELOISA_BOOTUUID") or run(["findmnt", "-no", "UUID", "/boot"], check=False)
    ents = [i for i in items() if i["bootable"]][-GRUB_MAX:]
    lines = []
    if ents and uuid:
        lines.append("submenu 'Heloisa: voltar o sistema no tempo' {")
        for i in reversed(ents):
            title = f"#{i['id']}  {i['time'][:16]}  {i['label']}: {i['desc']}".replace("'", "").replace("\\", "")[:90]
            cl = re.sub(r"\s*\bheloisa\.rollback=\S+", "", i["cmdline"])
            lines += [f"  menuentry '{title}' {{",
                      f"    search --no-floppy --fs-uuid --set=root {uuid}",
                      f"    linux /checkpoints/{i['id']}/vmlinuz {cl} heloisa.rollback={i['id']}",
                      f"    initrd /checkpoints/{i['id']}/initramfs.img", "  }"]
        lines.append("}")
    brs = [b for b in branches() if not b["active"] and b["bootable"]] if uuid else []
    if brs:
        lines.append("submenu 'Heloisa: iniciar outro ramo da máquina' {")
        for b in brs:
            title = f"ramo {b['name']}  {b.get('desc', '')}".replace("'", "").replace("\\", "").strip()[:90]
            cl = re.sub(r"\s*\bheloisa\.(rollback|branch)=\S+", "", b.get("cmdline") or "")
            lines += [f"  menuentry '{title}' {{",
                      f"    search --no-floppy --fs-uuid --set=root {uuid}",
                      f"    linux /branches/{b['name']}/vmlinuz {cl} heloisa.branch={b['name']}",
                      f"    initrd /branches/{b['name']}/initramfs.img", "  }"]
        lines.append("}")
    tmp = GRUBCFG + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# gerado pela Heloisa - nao edite\n" + "\n".join(lines) + "\n")
    os.replace(tmp, GRUBCFG)


def sync_boot():
    """Alinha /boot ao sistema atual: um kernel em /boot para cada um em /lib/modules, e so eles."""
    mods = {k for k in os.listdir("/lib/modules") if os.path.exists(f"/lib/modules/{k}/vmlinuz")}
    ed = "/boot/loader/entries"
    have = {}
    for fn in os.listdir(ed) if os.path.isdir(ed) else []:
        m = re.search(r"^linux\s+\S*/vmlinuz-(\S+)", open(f"{ed}/{fn}").read(), re.M)
        if m and "rescue" not in m.group(1):
            have[m.group(1)] = fn
    for k in sorted(mods):
        if k not in have or not os.path.exists(f"/boot/vmlinuz-{k}") or not os.path.exists(f"/boot/initramfs-{k}.img"):
            run(["kernel-install", "add", k, f"/lib/modules/{k}/vmlinuz"], check=False)
            if not os.path.exists(f"/boot/initramfs-{k}.img"):
                run(["dracut", "--force", "--kver", k, f"/boot/initramfs-{k}.img"], check=False)
    for k, fn in have.items():
        if k not in mods:
            run(["kernel-install", "remove", k], check=False)
            for f in (f"{ed}/{fn}", f"/boot/vmlinuz-{k}", f"/boot/initramfs-{k}.img", f"/boot/System.map-{k}",
                      f"/boot/config-{k}", f"/boot/symvers-{k}.xz", f"/boot/.vmlinuz-{k}.hmac"):
                if os.path.exists(f):
                    os.unlink(f)


# ---------------------------------------------------------------- voltar a maquina
def rollback(cid, parts=("root",)):
    """Troca os subvolumes pedidos pelos do ponto; vale a partir da proxima inicializacao.
    O estado atual vira um ponto antes, entao a volta pode ser desfeita."""
    need()
    parts = [p for p in parts if p in PARTS]
    with Top():
        for p in parts:
            if not os.path.isdir(f"{SNAP}/{cid}/{p}"):
                raise Error(f"o ponto #{cid} não tem '{p}'")
        if _bisecting():
            raise Error("há uma busca do que quebrou em andamento; conclua ou cancele antes de voltar a máquina")
        what = " e ".join({"root": "sistema", "home": "arquivos pessoais", "log": "logs"}[p] for p in parts)
        saved = create(f"{what} antes de voltar ao ponto #{cid}", "antes")
        _swap(cid, parts)
    return saved


def _swap(cid, parts):
    """Troca os subvolumes em uso por copias gravaveis dos do ponto (sem criar ponto). Chame dentro de Top()."""
    stamp = now().strftime("%Y%m%d%H%M%S%f")
    done = []
    try:
        for p in parts:
            old = f"{SNAP}/.old-{p}-{stamp}"
            os.rename(f"{TOP}/{p}", old)
            done.append((p, old))
            run(["btrfs", "subvolume", "snapshot", f"{SNAP}/{cid}/{p}", f"{TOP}/{p}"])
    except (Error, OSError) as e:
        for p, old in reversed(done):
            if os.path.isdir(f"{TOP}/{p}"):
                run(["btrfs", "subvolume", "delete", f"{TOP}/{p}"], check=False)
            os.rename(old, f"{TOP}/{p}")
        raise Error(f"não foi possível voltar: {e}")
    if "root" in parts:
        _sync_boot_in(f"{TOP}/root")


def _chroot_binds(new):
    binds = [("/boot", True), ("/boot/efi", os.path.ismount("/boot/efi")), ("/proc", True),
             ("/sys", True), ("/dev", True), ("/run", True)]
    mounted = []
    for m, want in binds:
        if want:
            run(["mount", "--rbind", m, new + m])
            run(["mount", "--make-rslave", new + m])
            mounted.append(new + m)
    return mounted


def _sync_boot_in(new):
    """Alinha /boot aos kernels do sistema que vai assumir na proxima inicializacao."""
    mounted = []
    try:
        mounted = _chroot_binds(new)
        if os.path.exists(new + SELF):
            run(["chroot", new, SELF, "sync-boot"], check=False)
    finally:
        for m in reversed(mounted):
            run(["umount", "-R", m], check=False)


def finalize():
    """A cada inicializacao: conclui voltas no tempo e registra um ponto de inicializacao."""
    if not supported() or os.geteuid() != 0:
        return
    with Top():
        changed = False
        for n in sorted(os.listdir(SNAP)):
            p = f"{SNAP}/{n}"
            if n.startswith("pre-rollback-") and os.path.isdir(f"{p}/root"):
                # volta feita pelo menu de boot (initramfs): o estado anterior vira um ponto
                cid = _next_id()
                os.rename(p, f"{SNAP}/{cid}")
                run(["btrfs", "property", "set", "-ts", f"{SNAP}/{cid}/root", "ro", "true"], check=False)
                _write_info(f"{SNAP}/{cid}", {"id": cid, "time": now().strftime("%Y-%m-%d %H:%M:%S"),
                            "kind": "antes", "desc": "sistema antes da volta feita pelo menu de boot",
                            "kernel": None, "cmdline": ""}, f"{SNAP}/{cid}/root")
                changed = True
            elif n.startswith(".old-"):
                run(["btrfs", "subvolume", "delete", p], check=False)
                changed = True
            elif n.startswith(".try-"):
                _try_cleanup(p)
            elif n.startswith("pre-rollback-"):
                shutil.rmtree(p, ignore_errors=True)
        cl = open("/proc/cmdline").read()
        if "heloisa.branch=" in cl:
            for b in branches():
                if not b["active"] and not b["bootable"]:
                    _branch_boot(b["name"])
            changed = True
        shutil.rmtree(f"{BOOTBR}/{branch_name()}", ignore_errors=True)     # o ramo em uso inicia pelas entradas normais
        if changed or "heloisa.rollback=" in cl:
            sync_boot()
        if not pending() and not _bisecting():
            its = [i for i in items() if i["kind"] == "boot"]
            today = now().strftime("%Y-%m-%d")
            if not its or its[-1]["time"][:10] != today:
                create("primeira inicialização do dia", "boot")
        gen_grub()


# ---------------------------------------------------------------- qualquer arquivo ou pasta
def _locate(path):
    """Caminho absoluto -> (subvolume, caminho relativo dentro dele)."""
    path = os.path.abspath(path)
    best = ("root", path.lstrip("/"))
    for part, mp in PARTS.items():
        if mp != "/" and (path == mp or path.startswith(mp + "/")):
            best = (part, path[len(mp):].lstrip("/"))
    return best


def _snap_path(i, path):
    part, rel = _locate(path)
    if part not in i["parts"]:
        return None
    return f"{SNAP}/{i['id']}/{part}" + ("/" + rel if rel else "")


def _sig(p):
    """Assinatura barata de um caminho: tipo, tamanho, mtime (e inode/geracao via st)."""
    try:
        st = os.lstat(p)
    except OSError:
        return None
    if stat.S_ISDIR(st.st_mode):
        return {"type": "dir", "size": 0, "mtime": int(st.st_mtime), "mode": st.st_mode, "ino": st.st_ino}
    t = "link" if stat.S_ISLNK(st.st_mode) else "file"
    return {"type": t, "size": st.st_size, "mtime": int(st.st_mtime), "mode": st.st_mode, "ino": st.st_ino}


def _dir_differs(a, b):
    p = subprocess.run(["diff", "-rq", "--no-dereference", a, b], capture_output=True)
    return p.returncode != 0


def versions(path, deep=False):
    """Todas as versoes de um caminho ao longo dos pontos (da mais nova para a mais antiga).
    Versoes iguais a seguinte mais nova sao marcadas same=True."""
    need(write=False)
    path = os.path.abspath(path)
    with Top():
        cur = _sig(path)
        out = []
        prev, prevp = cur, path
        for i in reversed(items()):
            sp = _snap_path(i, path)
            s = _sig(sp) if sp else None
            v = {"id": i["id"], "time": i["time"], "kind": i["kind"], "label": i["label"], "desc": i["desc"],
                 "exists": s is not None}
            if s:
                v.update(type=s["type"], size=s["size"], mtime=s["mtime"])
                if prev is None or s["type"] != prev["type"]:
                    v["same"] = False
                elif s["type"] == "dir":
                    v["same"] = (not _dir_differs(sp, prevp)) if deep else None
                else:
                    v["same"] = (s["size"], s["mtime"]) == (prev["size"], prev["mtime"])
            else:
                v["same"] = prev is None
            out.append(v)
            prev, prevp = s, sp
        return {"path": path, "current": cur, "versions": out}


def listdir(cid, path):
    """Conteudo de uma pasta dentro de um ponto (cid=0: estado atual)."""
    need(write=False)
    path = os.path.abspath(path)
    with Top():
        if cid:
            i = next((x for x in items() if x["id"] == cid), None)
            if not i:
                raise Error(f"o ponto #{cid} não existe")
            base = _snap_path(i, path)
        else:
            base = path
        if not base or not os.path.isdir(base):
            raise Error(f"{path} não é uma pasta neste ponto")
        ents = []
        for n in sorted(os.listdir(base), key=str.lower)[:5000]:
            s = _sig(f"{base}/{n}")
            if s:
                ents.append({"name": n, "type": s["type"], "size": s["size"], "mtime": s["mtime"]})
        ents.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        return {"path": path, "entries": ents}


def _is_text(p):
    try:
        with open(p, "rb") as f:
            return b"\0" not in f.read(8192)
    except OSError:
        return False


def diff(path, cid, other=0):
    """Diferenca entre o caminho no ponto cid e no ponto 'other' (0 = estado atual)."""
    need(write=False)
    path = os.path.abspath(path)
    with Top():
        its = {i["id"]: i for i in items()}
        if cid not in its or (other and other not in its):
            raise Error("ponto inexistente")
        a = _snap_path(its[cid], path)
        b = _snap_path(its[other], path) if other else path
        la, lb = f"ponto #{cid}{path}", (f"ponto #{other}{path}" if other else f"atual{path}")
        ea, eb = a and os.path.lexists(a), b and os.path.lexists(b)
        if not ea and not eb:
            return {"text": "O caminho não existe em nenhum dos dois lados."}
        if not ea or not eb:
            return {"text": f"Só existe em: {lb if eb else la}"}
        if os.path.isdir(a) and not os.path.islink(a):
            p = subprocess.run(["diff", "-rq", "--no-dereference", a, b], capture_output=True, text=True,
                               errors="replace")
            lines = []
            for l in p.stdout.splitlines()[:3000]:
                l = l.replace(a, f"#{cid}:").replace(b, "atual:" if not other else f"#{other}:")
                l = re.sub(r"^Only in (\S+?):?: (.*)$", r"só em \1  \2", l)
                l = re.sub(r"^Files (.+) and (.+) differ$", r"mudou  \1", l)
                lines.append(l)
            return {"text": "\n".join(lines) or "Sem diferenças."}
        if os.path.getsize(a) > TEXT_MAX or os.path.getsize(b) > TEXT_MAX or not (_is_text(a) and _is_text(b)):
            same = subprocess.run(["cmp", "-s", a, b]).returncode == 0
            return {"text": "Arquivo binário ou grande: " + ("idêntico." if same else "o conteúdo é diferente.")}
        p = subprocess.run(["diff", "-u", "--label", la, "--label", lb, a, b], capture_output=True, text=True,
                           errors="replace")
        return {"text": p.stdout or "Sem diferenças."}


def _unit_of(pid):
    try:
        cg = open(f"/proc/{pid}/cgroup").read()
    except OSError:
        return None
    m = re.search(r"/system\.slice/(?:.*/)?([^/\n]+\.service)", cg)
    return m.group(1) if m else None


def writers(path):
    """Processos com o caminho (ou algo dentro dele) aberto para escrita agora."""
    path = os.path.realpath(path)
    pre = path.rstrip("/") + "/"
    found = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                t = os.readlink(f"/proc/{pid}/fd/{fd}")
                if t != path and not t.startswith(pre):
                    continue
                flags = int(re.search(r"^flags:\s*(\d+)", open(f"/proc/{pid}/fdinfo/{fd}").read(), re.M).group(1), 8)
            except (OSError, AttributeError, ValueError):
                continue
            if flags & 3:           # O_WRONLY ou O_RDWR
                try:
                    comm = open(f"/proc/{pid}/comm").read().strip()
                except OSError:
                    comm = "?"
                found[int(pid)] = {"pid": int(pid), "name": comm, "unit": _unit_of(pid), "file": t}
                break
    return sorted(found.values(), key=lambda w: w["pid"])


def _risky(path, probe=None):
    """Tipo de dado que nao gosta de voltar no tempo com o dono rodando (banco, disco de VM...)."""
    if RISKY_DIRS.search(path):
        return "dados de um banco de dados, de contêineres ou de máquinas virtuais"
    ext = os.path.splitext(path)[1].lower()
    if ext in RISKY_EXT:
        return RISKY_EXT[ext]
    for p in (probe, path):
        try:
            if p and os.path.isfile(p):
                with open(p, "rb") as f:
                    if f.read(16).startswith(b"SQLite format 3"):
                        return "banco SQLite"
        except OSError:
            pass
    return None


def precheck(path, cid):
    """O que a interface precisa saber antes de voltar um caminho no lugar."""
    need(write=False)
    path = os.path.abspath(path)
    with Top():
        i = next((x for x in items() if x["id"] == cid), None)
        src = _snap_path(i, path) if i else None
        ws = writers(path) if os.path.lexists(path) else []
        return {"path": path, "writers": ws, "units": sorted({w["unit"] for w in ws if w["unit"]}),
                "risky": _risky(path, src), "isdir": bool(src and os.path.isdir(src) and not os.path.islink(src))}


def restore(path, cid, inplace=True, stop=()):
    """Traz um arquivo ou pasta de volta de um ponto, na hora, sem reiniciar. Em 'inplace' o caminho
    fica identico ao do ponto (o estado atual vira um ponto antes); senao, uma copia e criada ao lado.
    'stop': servicos que estao escrevendo no caminho; sao parados antes e religados depois."""
    need()
    path = os.path.abspath(path)
    if path == "/":
        raise Error("para a máquina inteira use 'voltar o sistema'")
    with Top():
        i = next((x for x in items() if x["id"] == cid), None)
        if not i:
            raise Error(f"o ponto #{cid} não existe")
        src = _snap_path(i, path)
        if not src or not os.path.lexists(src):
            raise Error(f"{path} não existia no ponto #{cid}")
        isdir = os.path.isdir(src) and not os.path.islink(src)
        if not inplace:
            dst = f"{path.rstrip('/')}.ponto-{cid}"
            n = 1
            while os.path.lexists(dst):
                n += 1
                dst = f"{path.rstrip('/')}.ponto-{cid}-{n}"
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            run(["cp", "-a", "--reflink=auto", src, dst])
            return {"saved": None, "dest": dst, "stopped": []}
        # so para servico que de fato esta escrevendo ali
        allowed = {w["unit"] for w in writers(path) if w["unit"]} if os.path.lexists(path) else set()
        units = [u for u in stop if u in allowed]
        saved = create(f"antes de restaurar {path} do ponto #{cid}", "antes")
        stopped = []
        try:
            for u in units:
                if subprocess.call(["systemctl", "stop", u], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                    stopped.append(u)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if isdir:
                if os.path.lexists(path) and not os.path.isdir(path):
                    os.unlink(path)
                os.makedirs(path, exist_ok=True)
                # identico ao ponto, sem atravessar para outros sistemas de arquivos montados
                run(["rsync", "-aHAX", "--delete", "--one-file-system", "--numeric-ids", src + "/", path + "/"])
            else:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                run(["cp", "-a", "--reflink=auto", "--remove-destination", src, path])
        finally:
            failed = [u for u in stopped
                      if subprocess.call(["systemctl", "start", u], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0]
        return {"saved": saved, "dest": path, "stopped": stopped, "failed": failed}


def changes(cid, other=0):
    """O que mudou entre o ponto cid e 'other' (0 = agora): pacotes e arquivos de /etc."""
    need(write=False)
    with Top():
        d = f"{SNAP}/{cid}"
        if not os.path.isdir(f"{d}/root"):
            raise Error(f"o ponto #{cid} não existe")

        def parse(txt):
            return dict(l.split(" ", 1) for l in txt.splitlines() if " " in l)

        def pk(c):
            try:
                return parse(open(f"{SNAP}/{c}/packages.txt").read())
            except OSError:
                return {}
        old = pk(cid)
        new = pk(other) if other else parse(_pkgs())
        pkd = {"added": sorted(f"{n} {new[n]}" for n in new.keys() - old.keys()),
               "removed": sorted(f"{n} {old[n]}" for n in old.keys() - new.keys()),
               "changed": sorted(f"{n} {old[n]} → {new[n]}" for n in new.keys() & old.keys() if new[n] != old[n])}
        a = f"{d}/root/etc"
        b = f"{SNAP}/{other}/root/etc" if other else "/etc"
        p = subprocess.run(["diff", "-rq", "--no-dereference", a, b], capture_output=True, text=True,
                           errors="replace")
        et = {"added": [], "removed": [], "changed": []}
        for l in p.stdout.splitlines():
            m = re.match(r"Only in (.+?): (.+)$", l)
            if m:
                full = m.group(1).rstrip("/") + "/" + m.group(2)
                if full.startswith(a):
                    et["removed"].append("/etc" + full[len(a):])
                else:
                    et["added"].append("/etc" + full[len(b):])
                continue
            m = re.match(r"Files (.+?) and (.+?) differ$", l)
            if m:
                et["changed"].append("/etc" + m.group(1)[len(a):])
        return {"packages": pkd, "etc": et}


def status():
    st = {"live": live(), "supported": supported(), "pending": False, "points": [], "usage": None,
          "branches": [], "branch": MAIN, "bisect": None, "alert": None}
    if os.geteuid() != 0 or not st["supported"]:
        return st
    st["pending"] = pending()
    with Top():
        st["points"] = items()
        st["branches"] = branches()
        st["branch"] = branch_name()
        st["bisect"] = _bisect_view(_state("bisect"))
        st["alert"] = _state("alert")
        u = run(["btrfs", "filesystem", "usage", "-b", TOP], check=False)
        m1 = re.search(r"Device size:\s+(\d+)", u)
        m2 = re.search(r"Free \(estimated\):\s+(\d+)", u)
        if m1 and m2:
            st["usage"] = {"size": int(m1.group(1)), "free": int(m2.group(1))}
    return st


# ---------------------------------------------------------------- resgate pela midia live
def rescue_find():
    """Volumes btrfs com MilizOS instalado. Retorna [{dev, points, locked}]."""
    found = []
    for l in run(["lsblk", "-rno", "PATH,FSTYPE,TYPE"], check=False).splitlines():
        f = l.split(" ")
        dev, fs = f[0], f[1] if len(f) > 1 else ""
        if fs == "crypto_LUKS":
            kids = run(["lsblk", "-rno", "PATH", dev], check=False).splitlines()[1:]
            if not kids:
                found.append({"dev": dev, "points": [], "locked": True})
            continue
        if fs != "btrfs":
            continue
        os.makedirs(TOP, exist_ok=True)
        if subprocess.call(["mount", "-t", "btrfs", "-o", "subvolid=5", dev, TOP], stderr=subprocess.DEVNULL) != 0:
            continue
        try:
            if os.path.isdir(SNAP):
                its = items()
                for i in its:
                    i["bootable"] = True
                if its:
                    found.append({"dev": dev, "points": its, "locked": False})
        finally:
            run(["umount", TOP], check=False)
    return found


def rescue(dev, cid):
    """Restaura um ponto num sistema que nao inicia mais e reconstroi /boot e o GRUB."""
    if os.geteuid() != 0:
        raise Error("é preciso ser administrador")
    os.makedirs(TOP, exist_ok=True)
    run(["mount", "-t", "btrfs", "-o", "subvolid=5", dev, TOP])
    T = "/run/heloisa/rescue"
    done = []
    try:
        src = f"{SNAP}/{cid}/root"
        if not os.path.isdir(src):
            raise Error(f"o ponto #{cid} não existe")
        stamp = now().strftime("%Y%m%d%H%M%S")
        if os.path.isdir(f"{TOP}/root"):
            os.makedirs(f"{SNAP}/pre-rollback-{stamp}", exist_ok=True)
            os.rename(f"{TOP}/root", f"{SNAP}/pre-rollback-{stamp}/root")
        run(["btrfs", "subvolume", "snapshot", src, f"{TOP}/root"])
        os.makedirs(T, exist_ok=True)
        run(["mount", "-t", "btrfs", "-o", "subvol=root", dev, T]); done.append(T)
        boot = efi = None
        for l in open(f"{T}/etc/fstab"):
            f = l.split()
            if len(f) >= 2 and not l.startswith("#"):
                if f[1] == "/boot":
                    boot = f[0]
                elif f[1] == "/boot/efi":
                    efi = f[0]
        if not boot:
            raise Error("o fstab do ponto não tem /boot")
        run(["mount", boot, f"{T}/boot"]); done.append(f"{T}/boot")
        bootdev = run(["findmnt", "-no", "SOURCE", f"{T}/boot"])
        disk = "/dev/" + run(["lsblk", "-no", "PKNAME", bootdev]).splitlines()[0]
        if efi:
            os.makedirs(f"{T}/boot/efi", exist_ok=True)
            if subprocess.call(["mount", efi, f"{T}/boot/efi"]) == 0:
                done.append(f"{T}/boot/efi")
        for m in ("/proc", "/sys", "/dev", "/run"):
            run(["mount", "--rbind", m, T + m]); run(["mount", "--make-rslave", T + m]); done.append(T + m)
        ch = lambda *c: run(["chroot", T] + list(c), check=False)
        os.makedirs(f"{T}/boot/loader/entries", exist_ok=True)
        os.makedirs(f"{T}/boot/grub2", exist_ok=True)
        ch(SELF, "sync-boot")
        th = f"{T}/usr/share/grub/themes/milizos"
        if os.path.isdir(th):
            shutil.copytree(th, f"{T}/boot/grub2/themes/milizos", dirs_exist_ok=True)
        ch("grub2-install", "--target=i386-pc", "--recheck", disk)
        buuid = run(["blkid", "-s", "UUID", "-o", "value", bootdev])
        stub = (f"search --no-floppy --fs-uuid --set=dev {buuid}\n"
                "set prefix=($dev)/grub2\nexport $prefix\nconfigfile $prefix/grub.cfg\n")
        ed = f"{T}/boot/efi/EFI"
        if os.path.isdir(ed):
            for d in os.listdir(ed):
                if d.upper() == "BOOT" or os.path.exists(f"{ed}/{d}/grubx64.efi"):
                    open(f"{ed}/{d}/grub.cfg", "w").write(stub)
        ch("grub2-mkconfig", "-o", "/boot/grub2/grub.cfg")
        subprocess.run(["chroot", T, SELF, "gen-grub"], capture_output=True,
                       env=dict(os.environ, HELOISA_ROOTDEV=dev, HELOISA_BOOTUUID=buuid))
        if not os.listdir(f"{T}/boot/loader/entries"):
            raise Error("nenhuma entrada de boot foi recriada")
        return {"disk": disk}
    finally:
        for m in reversed(done):
            run(["umount", "-R", m], check=False)
        run(["umount", TOP], check=False)


# ---------------------------------------------------------------- o que mudou entre dois pontos (so metadados)
def _unesc(s):
    return re.sub(r"\\(.)", r"\1", s)


def _delta(a, b, timeout=40):
    """Compara dois snapshots somente-leitura do mesmo subvolume sem ler dados (btrfs send --no-data).
    Retorna {"created","modified","deleted": conjuntos; "renamed": [(de, para)]} ou None."""
    try:
        send = subprocess.Popen(["btrfs", "-q", "send", "--no-data", "-p", a, b], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        recv = subprocess.Popen(["btrfs", "receive", "--dump"], stdin=send.stdout, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        send.stdout.close()
        raw, _e = recv.communicate(timeout=timeout)
        send.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        for p in (send, recv):
            try:
                p.kill()
            except Exception:  # noqa
                pass
        return None
    if send.returncode != 0:
        return None
    tok = re.compile(r"((?:\\.|[^ \\])+)")
    new, created, modified, deleted, gone, renamed, links = set(), set(), set(), set(), set(), [], {}
    moves = {}                          # movido para dentro de uma pasta que ainda tem nome temporario

    def rel(p):
        p = _unesc(p)
        if not p.startswith("./"):          # o destino de um "link" ja vem relativo ao subvolume
            return p
        p = p[2:]
        return p.split("/", 1)[1] if "/" in p else ""

    def orphan(p):
        return bool(ORPHAN.match(p.split("/", 1)[0])) or bool(ORPHAN.match(os.path.basename(p)))

    for line in raw.decode("utf-8", "replace").splitlines():
        op, rest = line[:16].strip(), line[16:]
        m = tok.match(rest)
        if not m:
            continue
        path = rel(m.group(1))
        dm = re.search(r" dest=((?:\\.|[^ \\])+)", rest)
        dest = rel(dm.group(1)) if dm else None
        if op in ("mkfile", "mkdir", "mksock", "mkfifo", "mknod", "symlink"):
            new.add(path)
        elif op == "rename" and dest is not None:
            po, do = orphan(path), orphan(dest)
            if po and not do:
                created.add(dest)
                for src, sub in moves.pop(path, []):
                    renamed.append((src, f"{dest}/{sub}"))
            elif not po and do:
                if "/" in dest:
                    moves.setdefault(dest.split("/", 1)[0], []).append((path, dest.split("/", 1)[1]))
                else:
                    gone.add(path)
            elif not po and not do:
                renamed.append((path, dest))
        elif op in ("unlink", "rmdir"):
            if path and not orphan(path):
                deleted.add(path)
        elif op in ("write", "update_extent", "truncate", "clone"):
            if path and not orphan(path):
                modified.add(path)
        elif op == "link" and path and not orphan(path):
            created.add(path)
            if dest:
                links[path] = dest
    gone |= deleted
    for newp, oldp in links.items():        # renomear na mesma pasta chega como link + unlink
        if oldp in gone and newp in created:
            gone.discard(oldp)
            created.discard(newp)
            renamed.append((oldp, newp))
    replaced = created & gone          # salvar "por cima" (temporario + rename): e uma alteracao
    modified |= replaced
    return {"created": created - replaced, "modified": modified - (created - replaced),
            "deleted": gone - created, "renamed": renamed}


def _entropy(path):
    try:
        with open(path, "rb") as f:
            data = f.read(65536)
    except OSError:
        return None
    if len(data) < 2048:
        return None
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in collections.Counter(data).values())


def _visible(p):
    """Arquivo pessoal de verdade: fora de pastas ocultas (cache, configuracao de programas)."""
    parts = p.split("/")
    return len(parts) >= 2 and not any(x.startswith(".") for x in parts[1:])


def _ransom_check(d, cur_home):
    """Heuristica de ransomware: muitos arquivos pessoais reescritos de uma vez e o conteudo novo e ruido."""
    mod = {p for p in d["modified"] if _visible(p)}
    ren = [(a, b) for a, b in d["renamed"] if _visible(b)]
    touched = mod | {b for _a, b in ren}
    if len(touched) < RANSOM_MIN:
        return None
    reasons = []
    exts = collections.Counter(os.path.splitext(b)[1].lower() for a, b in ren
                               if os.path.splitext(b)[1].lower() != os.path.splitext(a)[1].lower())
    if exts:
        ext, n = exts.most_common(1)[0]
        if ext and n >= 50 and n >= 0.6 * len(ren):
            reasons.append(f"{n} arquivos renomeados para a mesma extensão nova ({ext})")
    sample, high = 0, 0
    for p in sorted(touched):
        base = re.sub(r"\.[A-Za-z0-9_-]{2,12}$", "", p) if p in {b for _a, b in ren} else p
        if os.path.splitext(base)[1].lower() in COMPRESSED and os.path.splitext(p)[1].lower() in COMPRESSED:
            continue
        e = _entropy(f"{cur_home}/{p}")
        if e is None:
            continue
        sample += 1
        high += e >= RANSOM_ENTROPY
        if sample >= 60:
            break
    if sample >= 20 and high >= 0.7 * sample:
        reasons.append(f"{high} de {sample} arquivos examinados viraram dados sem padrão (cifrados ou corrompidos)")
    if not reasons:
        return None
    return {"files": len(touched), "reasons": reasons, "sample": sorted(touched)[:12]}


def _notify(title, body):
    """Aviso na area de trabalho de quem estiver logado (melhor esforco)."""
    for l in run(["loginctl", "list-sessions", "--no-legend"], check=False).splitlines():
        f = l.split()
        if len(f) < 3:
            continue
        uid, user = f[1], f[2]
        bus = f"/run/user/{uid}/bus"
        if uid.isdigit() and int(uid) >= 1000 and os.path.exists(bus):
            subprocess.Popen(["runuser", "-u", user, "--", "env", f"DBUS_SESSION_BUS_ADDRESS=unix:path={bus}",
                              "notify-send", "-u", "critical", "-a", "Heloisa", "-i", "heloisa", title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _pkdiff(old, new):
    return {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
            "changed": sorted(n for n in new.keys() & old.keys() if new[n] != old[n])}


def _pk(cid):
    try:
        return dict(l.split(" ", 1) for l in open(f"{SNAP}/{cid}/packages.txt").read().splitlines() if " " in l)
    except OSError:
        return {}


def _few(names, n=3):
    names = list(names)
    return ", ".join(names[:n]) + (f" (+{len(names) - n})" if len(names) > n else "")


def _describe(cid):
    """Mensagem automatica do ponto: o que mudou desde o ponto anterior. Tambem roda o alarme de ransomware."""
    prev = [i for i in items() if i["id"] < cid and "root" in i["parts"]]
    if not prev:
        return
    prev = prev[-1]
    a, b = f"{SNAP}/{prev['id']}", f"{SNAP}/{cid}"
    bits, stats = [], {}
    pk = _pkdiff(_pk(prev["id"]), _pk(cid))
    if pk["added"]:
        bits.append("instalou " + _few(pk["added"]))
    if pk["removed"]:
        bits.append("removeu " + _few(pk["removed"]))
    if pk["changed"]:
        bits.append(f"atualizou {_few(pk['changed'])}" if len(pk["changed"]) <= 3 else f"atualizou {len(pk['changed'])} pacotes")
    stats["packages"] = {k: len(v) for k, v in pk.items()}
    pkg_changed = any(pk.values())
    dr = _delta(f"{a}/root", f"{b}/root")
    if dr:
        etc = lambda s: sorted("/" + p for p in s if p.startswith("etc/") and not NOISE_ROOT.search(p))  # noqa
        ed, ne, de = etc(dr["modified"]), etc(dr["created"]), etc(dr["deleted"])
        if not pkg_changed:           # numa transacao de pacotes o /etc muda por tabela; o resumo ja diz o pacote
            if ed:
                bits.append("editou " + _few(ed, 2))
            if ne:
                bits.append("criou " + _few(ne, 2))
            if de:
                bits.append("apagou " + _few(de, 2))
        stats["etc"] = {"modified": len(ed), "created": len(ne), "deleted": len(de)}
    if os.path.isdir(f"{a}/home") and os.path.isdir(f"{b}/home"):
        dh = _delta(f"{a}/home", f"{b}/home")
        if dh:
            c = {k: len([p for p in dh[k] if _visible(p)]) for k in ("created", "modified", "deleted")}
            c["renamed"] = len([1 for _x, y in dh["renamed"] if _visible(y)])
            stats["home"] = c
            hb = []
            if c["created"]:
                hb.append(f"{c['created']} criado(s)")
            if c["modified"]:
                hb.append(f"{c['modified']} alterado(s)")
            if c["deleted"]:
                hb.append(f"{c['deleted']} apagado(s)")
            if c["renamed"]:
                hb.append(f"{c['renamed']} renomeado(s)")
            if hb:
                bits.append("arquivos pessoais: " + ", ".join(hb))
            hit = _ransom_check(dh, f"{b}/home")
            if hit:
                safe = [prev["id"]]
                _info_update(prev["id"], protected=True)
                hit.update(time=now().strftime("%Y-%m-%d %H:%M:%S"), point=cid, safe=prev["id"])
                _set_state("alert", hit)
                _notify("Heloisa: possível ransomware",
                        f"{hit['files']} arquivos pessoais foram reescritos de uma vez. O ponto #{safe[0]} "
                        "foi protegido. Abra a Heloisa para ver e voltar.")
    _info_update(cid, summary="; ".join(bits) if bits else "nada mudou desde o ponto anterior", stats=stats)


def alert_clear():
    need(write=False)
    with Top():
        _set_state("alert", None)


# ---------------------------------------------------------------- blame: a historia de um arquivo
def _sha(p, limit=None):
    h = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            n = 0
            while True:
                b = f.read(1 << 20)
                if not b:
                    break
                h.update(b)
                n += len(b)
                if limit and n >= limit:
                    break
    except OSError:
        return None
    return h.hexdigest()


def _fingerprint(p):
    try:
        st = os.lstat(p)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode):
        return ("link", os.readlink(p))
    if stat.S_ISDIR(st.st_mode):
        return ("dir",)
    if st.st_size <= 64 * 1024 * 1024:
        return ("file", st.st_size, _sha(p))
    return ("file", st.st_size, int(st.st_mtime))


def blame(path):
    """Quando um arquivo mudou, entre quais pontos, o que mudou e o que provavelmente causou."""
    need(write=False)
    path = os.path.abspath(path)
    with Top():
        its = items()
        seq = [(i, _snap_path(i, path)) for i in its]
        seq = [(i, sp) for i, sp in seq if sp]
        states = [(i, sp, _fingerprint(sp)) for i, sp in seq] + [(None, path, _fingerprint(path))]
        if any(fp and fp[0] == "dir" for _i, _p, fp in states):
            raise Error("o histórico detalhado é para arquivos; para pastas use a lista de versões")
        events = []
        for (ia, pa, fa), (ib, pb, fb) in zip(states, states[1:]):
            if fa == fb:
                continue
            ev = {"from": ia["id"], "from_time": ia["time"], "to": ib["id"] if ib else 0,
                  "to_time": ib["time"] if ib else now().strftime("%Y-%m-%d %H:%M:%S"),
                  "what": "criado" if fa is None else "apagado" if fb is None else "alterado",
                  "added": 0, "removed": 0, "cause": ""}
            if fa and fb and fa[0] == fb[0] == "file" and max(fa[1], fb[1]) <= TEXT_MAX and _is_text(pa) and _is_text(pb):
                d = subprocess.run(["diff", "-U0", pa, pb], capture_output=True, text=True, errors="replace").stdout
                ev["added"] = len([l for l in d.splitlines() if l.startswith("+") and not l.startswith("+++")])
                ev["removed"] = len([l for l in d.splitlines() if l.startswith("-") and not l.startswith("---")])
            if ia["kind"] == "dnf":
                ev["cause"] = ia["desc"].replace("antes de: ", "transação de pacotes: ")
            elif ia["kind"] == "antes":
                ev["cause"] = "volta no tempo: " + ia["desc"].replace("antes de ", "")
            events.append(ev)
        owner = run(["rpm", "-qf", "--qf", "%{NAME}-%{EVR}\n", path], check=False) if os.path.lexists(path) else ""
        if "\n" in owner or " " in owner:
            owner = owner.splitlines()[0] if owner and "não" not in owner and "not owned" not in owner else ""
        pristine = None
        if owner:
            v = run(["rpm", "-Vf", path], check=False)
            pristine = not any(l.rstrip().endswith(" " + path) for l in v.splitlines())
        return {"path": path, "points": len(seq), "events": list(reversed(events)), "owner": owner,
                "pristine": pristine, "exists": states[-1][2] is not None}


# ---------------------------------------------------------------- selo: provar que um ponto nao foi alterado
def _manifest(d, parts):
    """Uma linha por caminho: hash do conteudo, modo, dono, caminho. A ordem e fixa."""
    for part in parts:
        base = f"{d}/{part}"
        for root, dirs, files in os.walk(base):
            dirs.sort()
            for n in sorted(dirs + files):
                p = f"{root}/{n}"
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode):
                    h = _sha(p) or "ilegivel"
                elif stat.S_ISLNK(st.st_mode):
                    h = "link:" + hashlib.sha256(os.readlink(p).encode("utf-8", "surrogateescape")).hexdigest()
                elif stat.S_ISDIR(st.st_mode):
                    h = "dir"
                else:
                    h = "especial"
                yield f"{h} {st.st_mode:o} {st.st_uid}:{st.st_gid} {part}/{os.path.relpath(p, base)}\n", \
                    (st.st_size if stat.S_ISREG(st.st_mode) else 0)


def _seal_key():
    key, pub = f"{STATE}/seal.key", f"{STATE}/seal.pub"
    if not os.path.exists(key):
        os.makedirs(STATE, mode=0o755, exist_ok=True)
        old = os.umask(0o077)
        try:
            run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", key])
        finally:
            os.umask(old)
        run(["openssl", "pkey", "-in", key, "-pubout", "-out", pub])
    return key, pub


def _seal_msg(cid, s):
    return f"milizos-selo-v1 {s['host']} {cid} {s['time']} {s['hash']}".encode()


def _compute(cid, i, keep=None):
    h = hashlib.sha256()
    files = size = 0
    out = gzip.open(keep, "wt", encoding="utf-8", errors="surrogateescape") if keep else None
    try:
        for line, n in _manifest(f"{SNAP}/{cid}", i["parts"]):
            h.update(line.encode("utf-8", "surrogateescape"))
            files += 1
            size += n
            if out:
                out.write(line)
    finally:
        if out:
            out.close()
    return h.hexdigest(), files, size


def seal(cid):
    """Sela um ponto: calcula o hash de tudo o que ha nele e assina com a chave desta maquina."""
    need(write=False)
    with Top():
        i = next((x for x in items() if x["id"] == cid), None)
        if not i:
            raise Error(f"o ponto #{cid} não existe")
        d = f"{SNAP}/{cid}"
        if os.path.exists(f"{d}/seal.json"):
            raise Error(f"o ponto #{cid} já está selado")
        digest, files, size = _compute(cid, i, f"{d}/manifest.gz")
        s = {"algo": "sha256", "hash": digest, "files": files, "bytes": size, "parts": i["parts"],
             "time": now().strftime("%Y-%m-%d %H:%M:%S"), "host": socket.gethostname()}
        key, pub = _seal_key()
        msgf = f"{STATE}/msg.tmp"
        with open(msgf, "wb") as f:
            f.write(_seal_msg(cid, s))
        p = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", key, "-rawin", "-in", msgf], capture_output=True)
        os.unlink(msgf)
        if p.returncode != 0:
            raise Error("não foi possível assinar o selo: " + p.stderr.decode(errors="replace")[-200:])
        s["signature"] = p.stdout.hex()
        s["pubkey"] = open(pub).read()
        with open(f"{d}/seal.json", "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False)
        return s


def seal_verify(cid):
    """Recalcula o hash do ponto e confere com o selo e com a assinatura."""
    need(write=False)
    with Top():
        i = next((x for x in items() if x["id"] == cid), None)
        d = f"{SNAP}/{cid}"
        try:
            s = json.load(open(f"{d}/seal.json", encoding="utf-8"))
        except (OSError, ValueError):
            raise Error(f"o ponto #{cid} não tem selo")
        if not i:
            raise Error(f"o ponto #{cid} não existe")
        cur = f"{STATE}/verify-{cid}.gz"
        digest, files, _size = _compute(cid, i, cur)
        intact = digest == s["hash"]
        changed = []
        if not intact and os.path.exists(f"{d}/manifest.gz"):
            def load(f):
                with gzip.open(f, "rt", encoding="utf-8", errors="surrogateescape") as h:
                    return {l.rstrip("\n").split(" ", 3)[3]: l for l in h if l.count(" ") >= 3}
            old, new = load(f"{d}/manifest.gz"), load(cur)
            changed = sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p))[:60]
        os.unlink(cur)
        sig_ok = False
        pub = f"{STATE}/seal.pub"
        if os.path.exists(pub) and s.get("signature"):
            sigf, msgf = f"{STATE}/sig.tmp", f"{STATE}/msg.tmp"
            with open(sigf, "wb") as f:
                f.write(bytes.fromhex(s["signature"]))
            with open(msgf, "wb") as f:
                f.write(_seal_msg(cid, s))
            sig_ok = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", pub, "-rawin",
                                     "-in", msgf, "-sigfile", sigf], capture_output=True).returncode == 0
            os.unlink(sigf)
            os.unlink(msgf)
        return {"intact": intact, "signature": sig_ok, "hash": s["hash"], "now": digest, "files": files,
                "sealed_at": s["time"], "changed": changed}


def seal_info(cid):
    need(write=False)
    with Top():
        try:
            return json.load(open(f"{SNAP}/{cid}/seal.json", encoding="utf-8"))
        except (OSError, ValueError):
            raise Error(f"o ponto #{cid} não tem selo")


# ---------------------------------------------------------------- ramos da maquina
def branch_name():
    try:
        n = open(f"{STATE}/branch").read().strip()
    except OSError:
        n = ""
    return n or MAIN


def _set_branch(name):
    os.makedirs(STATE, mode=0o755, exist_ok=True)
    with open(f"{STATE}/branch", "w") as f:
        f.write(name + "\n")


def branches():
    cur = branch_name()
    meta = _state("branches", {}) or {}
    names = {cur}
    if os.path.isdir(BR):
        names |= {n for n in os.listdir(BR) if os.path.isdir(f"{BR}/{n}/root")}
    out = []
    for n in sorted(names, key=lambda x: (x != MAIN, x)):
        m = dict(meta.get(n) or {})
        m.update(name=n, active=(n == cur),
                 bootable=all(os.path.exists(f"{BOOTBR}/{n}/{f}") for f in ("vmlinuz", "initramfs.img")))
        m.setdefault("desc", "o sistema desde a instalação" if n == MAIN else "")
        out.append(m)
    return out


def _kvers(root):
    d = f"{root}/lib/modules"
    ks = [k for k in (os.listdir(d) if os.path.isdir(d) else []) if os.path.exists(f"{d}/{k}/vmlinuz")]
    return sorted(ks, key=lambda k: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", k)])


def _branch_boot(name):
    """Kernel e initramfs proprios do ramo em /boot/branches/<nome>, para ele aparecer no menu de boot.
    O initramfs e gerado agora, com o gancho que troca de ramo antes de a raiz ser montada."""
    root = f"{BR}/{name}/root"
    ks = _kvers(root)
    if not ks:
        return False
    k = os.uname().release if os.uname().release in ks else ks[-1]
    d = f"{BOOTBR}/{name}"
    os.makedirs(d, exist_ok=True)
    shutil.copyfile(f"{root}/lib/modules/{k}/vmlinuz", f"{d}/vmlinuz")
    p = subprocess.run(["dracut", "--force", "--kver", k, "--kmoddir", f"{root}/lib/modules/{k}",
                        "--add", "heloisa", f"{d}/initramfs.img"], capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(f"{d}/initramfs.img"):
        shutil.rmtree(d, ignore_errors=True)
        return False
    return True


def _cmdline():
    try:
        return open("/etc/kernel/cmdline").read().strip()
    except OSError:
        return ""


def branch_create(name, cid=0, desc=""):
    """Cria um ramo: uma copia gravavel do sistema (do estado atual ou de um ponto) que pode ser
    iniciada no lugar do sistema atual. Os arquivos pessoais e os logs sao os mesmos em todos os ramos."""
    need()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,23}", name or ""):
        raise Error("nome do ramo: letras minúsculas, números e hífen (até 24 caracteres)")
    with Top():
        if any(b["name"] == name for b in branches()):
            raise Error(f"já existe um ramo chamado {name}")
        if len(branches()) >= MAX_BRANCHES:
            raise Error(f"o limite é de {MAX_BRANCHES} ramos; apague um antes")
        if cid:
            src = f"{SNAP}/{cid}/root"
            if not os.path.isdir(src):
                raise Error(f"o ponto #{cid} não existe")
            cl = next((i.get("cmdline") for i in items() if i["id"] == cid), "") or _cmdline()
            origin = f"ponto #{cid}"
        else:
            src, cl, origin = "/", _cmdline(), f"estado do ramo {branch_name()}"
        os.makedirs(f"{BR}/{name}", exist_ok=True)
        try:
            run(["btrfs", "subvolume", "snapshot", src, f"{BR}/{name}/root"])
        except Error:
            shutil.rmtree(f"{BR}/{name}", ignore_errors=True)
            raise
        meta = _state("branches", {}) or {}
        meta[name] = {"created": now().strftime("%Y-%m-%d %H:%M:%S"), "from": origin, "desc": desc or f"criado de: {origin}",
                      "cmdline": cl}
        _set_state("branches", meta)
        ok = _branch_boot(name)
        gen_grub()
        return {"name": name, "bootable": ok}


def branch_switch(name):
    """Passa a usar outro ramo a partir da proxima inicializacao. O ramo atual fica guardado, intacto."""
    need()
    with Top():
        if _bisecting():
            raise Error("há uma busca do que quebrou em andamento; conclua ou cancele antes de trocar de ramo")
        cur = branch_name()
        if name == cur:
            raise Error(f"o ramo {name} já é o que está em uso")
        if not os.path.isdir(f"{BR}/{name}/root"):
            raise Error(f"o ramo {name} não existe")
        meta = _state("branches", {}) or {}
        meta.setdefault(cur, {})["cmdline"] = _cmdline()
        _set_state("branches", meta)
        os.makedirs(f"{BR}/{cur}", exist_ok=True)
        os.rename(f"{TOP}/root", f"{BR}/{cur}/root")          # continua montado em / ate reiniciar
        try:
            os.rename(f"{BR}/{name}/root", f"{TOP}/root")
        except OSError as e:
            os.rename(f"{BR}/{cur}/root", f"{TOP}/root")
            raise Error(f"não foi possível trocar de ramo: {e}")
        _set_branch(name)
        shutil.rmtree(f"{BR}/{name}", ignore_errors=True)
        shutil.rmtree(f"{BOOTBR}/{name}", ignore_errors=True)
        _branch_boot(cur)
        _sync_boot_in(f"{TOP}/root")
        gen_grub()
        return {"from": cur, "to": name}


def branch_delete(name):
    need()
    with Top():
        if name == branch_name():
            raise Error("não dá para apagar o ramo em uso")
        d = f"{BR}/{name}"
        if not os.path.isdir(f"{d}/root"):
            raise Error(f"o ramo {name} não existe")
        run(["btrfs", "subvolume", "delete", f"{d}/root"])
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(f"{BOOTBR}/{name}", ignore_errors=True)
        meta = _state("branches", {}) or {}
        meta.pop(name, None)
        _set_state("branches", meta)
        gen_grub()


# ---------------------------------------------------------------- bisect: achar o ponto em que quebrou
def _bisecting():
    b = _state("bisect")
    return bool(b and b.get("active"))


def _bisect_view(b):
    if not b:
        return None
    v = dict(b)
    v["pending"] = pending()
    v["left"] = max(0, math.ceil(math.log2(len(b.get("cand", [])) + 1))) if b.get("active") else 0
    return v


def bisect_status():
    need(write=False)
    with Top():
        return _bisect_view(_state("bisect"))


def _bisect_next(b):
    """Escolhe o ponto do meio e coloca o sistema nele (vale ao reiniciar), ou conclui."""
    cand = b["cand"]
    if not cand:
        first_bad = b["bad"]
        b.update(active=False, done=True, testing=None, first_bad=first_bad, last_good=b["good"])
        ch = changes(b["good"], first_bad)
        b["result"] = ch
        its = {i["id"]: i for i in items()}
        b["bad_desc"] = its.get(first_bad, {}).get("desc", "")
        b["good_desc"] = its.get(b["good"], {}).get("desc", "")
        b["bad_summary"] = its.get(first_bad, {}).get("summary", "")
        _swap(b["origin"], ["root"])          # devolve a maquina ao estado de antes da busca
        _set_state("bisect", b)
        return b
    mid = cand[len(cand) // 2]
    _swap(mid, ["root"])
    b["testing"] = mid
    b["steps"] = b.get("steps", 0) + 1
    _set_state("bisect", b)
    return b


def bisect_start(good):
    """'No ponto <good> funcionava; agora nao.' Procura, por bissecao, o ponto em que deixou de funcionar.
    So o sistema muda durante a busca; arquivos pessoais e logs ficam como estao."""
    need()
    with Top():
        if _bisecting():
            raise Error("já há uma busca em andamento")
        its = items()
        if not any(i["id"] == good and "root" in i["parts"] for i in its):
            raise Error(f"o ponto #{good} não existe")
        origin = create(f"estado antes da busca do que quebrou (funcionava no ponto #{good})", "antes")
        _info_update(origin, protected=True)
        cand = [i["id"] for i in items() if good < i["id"] < origin and "root" in i["parts"]]
        b = {"active": True, "done": False, "good": good, "bad": origin, "origin": origin, "cand": cand,
             "testing": None, "steps": 0, "started": now().strftime("%Y-%m-%d %H:%M:%S")}
        return _bisect_view(_bisect_next(b))


def bisect_mark(works):
    """Responde se o sistema em teste funciona. Avanca a busca."""
    need()
    with Top():
        b = _state("bisect")
        if not b or not b.get("active"):
            raise Error("não há busca em andamento")
        t = b["testing"]
        if works:
            b["good"] = t
            b["cand"] = [c for c in b["cand"] if c > t]
        else:
            b["bad"] = t
            b["cand"] = [c for c in b["cand"] if c < t]
        return _bisect_view(_bisect_next(b))


def bisect_abort():
    """Cancela a busca e devolve o sistema ao estado de antes dela (vale ao reiniciar)."""
    need(write=False)
    with Top():
        b = _state("bisect")
        if not b:
            return None
        if b.get("active"):
            if pending():
                raise Error("reinicie o computador antes de cancelar a busca")
            _swap(b["origin"], ["root"])
        if b.get("origin") and os.path.isdir(f"{SNAP}/{b['origin']}"):
            _info_update(b["origin"], protected=False)
        _set_state("bisect", None)
        return {"restored": b.get("origin") if b.get("active") else None}


# ---------------------------------------------------------------- experimentar um ponto sem voltar
def _try_cleanup(d):
    for part in ("root", "home"):
        if os.path.isdir(f"{d}/{part}"):
            run(["btrfs", "subvolume", "delete", f"{d}/{part}"], check=False)
    shutil.rmtree(d, ignore_errors=True)


def try_shell(cid):
    """Abre um terminal dentro de uma copia descartavel do ponto (conteiner). Nada do que for feito ali
    toca a maquina atual nem o ponto; ao sair, a copia e apagada."""
    need(write=False)
    with Top():
        i = next((x for x in items() if x["id"] == cid), None)
        if not i:
            raise Error(f"o ponto #{cid} não existe")
        d = f"{SNAP}/.try-{cid}-{os.getpid()}"
        os.makedirs(d)
        try:
            run(["btrfs", "subvolume", "snapshot", f"{SNAP}/{cid}/root", f"{d}/root"])
            cmd = ["systemd-nspawn", "-q", "-D", f"{d}/root", "-M", f"ponto-{cid}", "--resolv-conf=replace-host", "--link-journal=no",
                   "--setenv=PS1=[ponto #%d \\W]# " % cid]
            if "home" in i["parts"]:
                run(["btrfs", "subvolume", "snapshot", f"{SNAP}/{cid}/home", f"{d}/home"])
                cmd.append(f"--bind={d}/home:/home")
            print(f"\n  Heloisa: você está DENTRO do ponto #{cid} ({i['time'][:16]}: {i['desc']}).\n"
                  "  É uma cópia descartável do sistema e dos arquivos pessoais daquele momento.\n"
                  "  Nada aqui altera a máquina atual. Saia com 'exit' ou Ctrl+D.\n", flush=True)
            if shutil.which("systemd-nspawn"):
                rc = subprocess.call(cmd)
            else:
                rc = subprocess.call(["chroot", f"{d}/root", "/bin/bash"])
            print(f"\n  Heloisa: cópia do ponto #{cid} descartada.", flush=True)
            return rc
        finally:
            _try_cleanup(d)


# ---------------------------------------------------------------- enviar pontos para fora (outro disco ou servidor)
def _fsuuid(path):
    return run(["findmnt", "-no", "UUID", "-T", path], check=False)


def targets():
    """Discos btrfs montados que nao sao o do sistema: candidatos a receber os pontos."""
    need(write=False)
    mine = _fsuuid("/")
    out, seen = [], set()
    for l in run(["findmnt", "-rno", "TARGET,SOURCE,UUID,SIZE,AVAIL,LABEL", "-t", "btrfs"], check=False).splitlines():
        f = l.split(" ")
        if len(f) < 5 or f[2] == mine or f[2] in seen or f[0].startswith(("/run/heloisa", "/.heloisa")):
            continue
        seen.add(f[2])
        out.append({"path": f[0].replace("\\x20", " "), "dev": f[1], "size": f[3], "avail": f[4],
                    "label": f[5] if len(f) > 5 else ""})
    return out


class _Dest:
    def __init__(self, dest, host=None):
        m = re.fullmatch(r"ssh://([A-Za-z0-9_.@-]+)(?::(\d+))?(/.*)", dest)
        self.raw = dest
        if m:
            self.ssh = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
            if m.group(2):
                self.ssh += ["-p", m.group(2)]
            self.ssh.append(m.group(1))
            root = m.group(3)
        else:
            self.ssh = None
            root = os.path.abspath(dest)
            if not os.path.isdir(root):
                raise Error(f"{root} não é uma pasta")
            if run(["findmnt", "-no", "FSTYPE", "-T", root], check=False) != "btrfs":
                raise Error("o destino precisa estar em um disco btrfs (formate o disco externo como btrfs)")
            if _fsuuid(root) == _fsuuid("/"):
                raise Error("o destino está no mesmo disco do sistema; escolha outro disco")
        self.base = f"{root.rstrip('/')}/milizos-{host or socket.gethostname()}"

    def cmd(self, argv):
        return self.ssh + [shlex.join(argv)] if self.ssh else argv

    def run(self, argv, check=True, input=None):
        p = subprocess.run(self.cmd(argv), capture_output=True, input=input)
        if check and p.returncode != 0:
            raise Error(f"destino: {p.stderr.decode(errors='replace').strip()[-300:] or 'falhou ' + argv[0]}")
        return p.stdout.decode(errors="replace").strip()

    def have(self):
        """Pontos completos no destino; restos de envios interrompidos sao removidos."""
        self.run(["mkdir", "-p", self.base])
        sh = (f'cd {shlex.quote(self.base)} || exit 1; for d in *; do [ -d "$d" ] || continue; '
              'if [ -f "$d/info.json" ]; then echo "$d"; else for s in "$d"/*; do '
              '[ -d "$s" ] && btrfs subvolume delete "$s" >/dev/null 2>&1; done; rm -rf "$d"; fi; done')
        return sorted(int(x) for x in self.run(["sh", "-c", sh]).split() if x.isdigit())


def push(dest, ids=None):
    """Envia os pontos para outro disco btrfs ou para um servidor (ssh://usuario@host/caminho).
    So vai o que mudou desde o ultimo ponto que o destino ja tem (btrfs send incremental)."""
    need(write=False)
    with Top():
        d = _Dest(dest)
        there = d.have()
        its = [i for i in items() if (not ids or i["id"] in ids)]
        todo = [i for i in its if i["id"] not in there]
        sent, total = [], 0
        for i in todo:
            common = [x for x in items() if x["id"] in there and x["id"] < i["id"]]
            parent = common[-1] if common else None
            dd = f"{d.base}/{i['id']}"
            d.run(["mkdir", "-p", dd])
            for part in i["parts"]:
                cmd = ["btrfs", "-q", "send"]
                if parent and part in parent["parts"]:
                    cmd += ["-p", f"{SNAP}/{parent['id']}/{part}"]
                send = subprocess.Popen(cmd + [f"{SNAP}/{i['id']}/{part}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                recv = subprocess.Popen(d.cmd(["btrfs", "-q", "receive", dd]), stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    while True:
                        buf = send.stdout.read(1 << 20)
                        if not buf:
                            break
                        recv.stdin.write(buf)
                        total += len(buf)
                    recv.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
                rs, rr = send.wait(), recv.wait()
                if rs != 0 or rr != 0:
                    err = (recv.stderr.read() or send.stderr.read()).decode(errors="replace").strip()[-300:]
                    raise Error(f"o envio do ponto #{i['id']} falhou: {err}")
            for f in ("packages.txt", "info.json"):          # info.json por ultimo: marca o ponto como completo
                d.run(["sh", "-c", f"cat > {shlex.quote(dd + '/' + f)}"], input=open(f"{SNAP}/{i['id']}/{f}", "rb").read())
            there.append(i["id"])
            there.sort()
            pushed = sorted(set(i["pushed"]) | {d.raw})
            _info_update(i["id"], pushed=pushed)
            sent.append(i["id"])
        d.run(["sync"], check=False)
        return {"dest": d.base, "sent": sent, "already": len(its) - len(todo), "bytes": total}


def backups():
    """Copias de maquinas MilizOS (feitas pelo envio de pontos) nos discos ligados agora."""
    if os.geteuid() != 0:
        raise Error("é preciso ser administrador")
    found, T = [], "/run/heloisa/src"
    mine = None if live() else _fsuuid("/")
    for l in run(["lsblk", "-rno", "PATH,FSTYPE,UUID,LABEL,SIZE"], check=False).splitlines():
        f = l.split(" ")
        if len(f) < 3 or f[1] != "btrfs" or f[2] == mine:
            continue
        os.makedirs(T, exist_ok=True)
        if subprocess.call(["mount", "-t", "btrfs", "-o", "ro,subvolid=5", f[0], T], stderr=subprocess.DEVNULL) != 0:
            continue
        try:
            for root, dirs, _files in os.walk(T):
                depth = root[len(T):].count("/")
                for n in list(dirs):
                    if n.startswith("milizos-"):
                        pts = []
                        for c in os.listdir(f"{root}/{n}"):
                            try:
                                i = json.load(open(f"{root}/{n}/{c}/info.json", encoding="utf-8"))
                            except (OSError, ValueError):
                                continue
                            if os.path.isdir(f"{root}/{n}/{c}/root"):
                                pts.append({"id": i["id"], "time": i["time"], "desc": i["desc"],
                                            "summary": i.get("summary", ""),
                                            "home": os.path.isdir(f"{root}/{n}/{c}/home")})
                        if pts:
                            found.append({"dev": f[0], "label": f[3] if len(f) > 3 else "", "host": n[8:],
                                          "dir": (root[len(T):] + "/" + n).lstrip("/"),
                                          "points": sorted(pts, key=lambda p: p["id"])})
                        dirs.remove(n)
                if depth >= 2:
                    dirs[:] = []
                dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("root", "home", "log", "snapshots")]
        finally:
            run(["umount", T], check=False)
    return found


def clone(dev, bdir, cid, disk, hostname, home=True, encrypt=False, passphrase=""):
    """Monta uma maquina nova neste disco a partir de um ponto guardado em outro disco (so pela midia live).
    Usa o instalador do MilizOS: particiona, copia o sistema do ponto e instala o boot."""
    if os.geteuid() != 0:
        raise Error("é preciso ser administrador")
    if not live():
        raise Error("clonar uma máquina só é possível iniciando pelo pendrive do MilizOS")
    cfg = {"disk": disk, "filesystem": "btrfs", "encrypt": bool(encrypt), "passphrase": passphrase,
           "hostname": hostname, "clone": {"device": dev, "dir": bdir, "point": int(cid), "home": bool(home)}}
    os.makedirs("/run/heloisa", exist_ok=True)
    cf = "/run/heloisa/clone.json"
    with open(cf, "w") as f:
        json.dump(cfg, f)
    os.chmod(cf, 0o600)
    p = subprocess.run(["/usr/bin/python3", "/usr/lib/milizos-installer/engine.py", "--auto", cf],
                       capture_output=True, text=True, errors="replace")
    err = ""
    for l in p.stdout.splitlines():
        try:
            ev = json.loads(l)
        except ValueError:
            continue
        if ev.get("type") == "error":
            err = ev.get("msg", "")
    if p.returncode != 0:
        raise Error(err or "a clonagem falhou (veja /tmp/milizos-install.log)")
    return {"disk": disk, "hostname": hostname}


def disks():
    out = run(["/usr/bin/python3", "/usr/lib/milizos-installer/engine.py", "--list-disks"], check=False)
    try:
        return json.loads(out)
    except ValueError:
        return []


# ---------------------------------------------------------------- interface de linha / servidor
OPS = {
    "status": lambda a: status(),
    "create": lambda a: {"id": create(a.get("desc") or "ponto manual", a.get("kind", "manual"))},
    "delete": lambda a: delete(int(a["id"])),
    "rollback": lambda a: {"saved": rollback(int(a["id"]), a.get("parts") or ["root"])},
    "versions": lambda a: versions(a["path"], bool(a.get("deep"))),
    "listdir": lambda a: listdir(int(a.get("id") or 0), a["path"]),
    "diff": lambda a: diff(a["path"], int(a["id"]), int(a.get("other") or 0)),
    "restore": lambda a: restore(a["path"], int(a["id"]), bool(a.get("inplace", True)), a.get("stop") or ()),
    "precheck": lambda a: precheck(a["path"], int(a["id"])),
    "blame": lambda a: blame(a["path"]),
    "protect": lambda a: protect(int(a["id"]), bool(a.get("on", True))),
    "alert-clear": lambda a: alert_clear(),
    "seal": lambda a: seal(int(a["id"])),
    "seal-verify": lambda a: seal_verify(int(a["id"])),
    "seal-info": lambda a: seal_info(int(a["id"])),
    "branch-create": lambda a: branch_create(a["name"], int(a.get("id") or 0), a.get("desc") or ""),
    "branch-switch": lambda a: branch_switch(a["name"]),
    "branch-delete": lambda a: branch_delete(a["name"]),
    "bisect-start": lambda a: bisect_start(int(a["good"])),
    "bisect-mark": lambda a: bisect_mark(bool(a["works"])),
    "bisect-abort": lambda a: bisect_abort(),
    "bisect-status": lambda a: bisect_status(),
    "targets": lambda a: targets(),
    "push": lambda a: push(a["dest"], a.get("ids")),
    "backups": lambda a: backups(),
    "disks": lambda a: disks(),
    "clone": lambda a: clone(a["dev"], a["dir"], int(a["id"]), a["disk"], a["hostname"], bool(a.get("home", True)),
                             bool(a.get("encrypt")), a.get("passphrase") or ""),
    "changes": lambda a: changes(int(a["id"]), int(a.get("other") or 0)),
    "rescue-find": lambda a: rescue_find(),
    "rescue": lambda a: rescue(a["dev"], int(a["id"])),
    "reboot": lambda a: run(["systemctl", "reboot"], check=False),
}


def _auto_paused():
    """Durante a busca do que quebrou o sistema em uso e um ponto antigo: pontos automaticos so fariam ruido."""
    with Top():
        return _bisecting()


def serve():
    """Protocolo da interface grafica: uma requisicao JSON por linha, uma resposta por linha."""
    global SERVING
    SERVING = True
    try:
        for line in sys.stdin:
            try:
                req = json.loads(line)
            except ValueError:
                continue
            try:
                res = {"n": req.get("n"), "ok": True, "result": OPS[req["op"]](req)}
            except Error as e:
                res = {"n": req.get("n"), "ok": False, "error": str(e)}
            except Exception as e:  # noqa
                res = {"n": req.get("n"), "ok": False, "error": f"erro inesperado: {e!r}"}
            sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    finally:
        SERVING = False
        if os.path.ismount(TOP):
            run(["umount", TOP], check=False)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "serve":
            serve()
        elif cmd == "auto":            # ganchos (dnf, timer): nunca atrapalham quem chamou
            if supported() and os.geteuid() == 0 and not pending() and not _auto_paused():
                desc = " ".join(argv[3:]) or "automático"
                if argv[2] == "dnf":
                    # o processo pai e o dnf: a linha de comando dele descreve a transacao
                    try:
                        cl = open(f"/proc/{os.getppid()}/cmdline").read().split("\0")
                        desc = "antes de: " + " ".join(["dnf"] + [c for c in cl[1:] if c])[:70]
                    except OSError:
                        pass
                create(desc, argv[2])
        elif cmd == "finalize":
            finalize()
        elif cmd == "try-shell":
            return try_shell(int(argv[2]))
        elif cmd == "sync-boot":
            sync_boot()
        elif cmd == "gen-grub":
            with Top():
                gen_grub()
        elif cmd in OPS:
            args = json.loads(argv[2]) if len(argv) > 2 else {}
            print(json.dumps(OPS[cmd](args), ensure_ascii=False, indent=1))
        else:
            print("uso interno da Heloisa (abra o aplicativo Heloisa)", file=sys.stderr)
            return 64
    except Error as e:
        print(f"heloisa: {e}", file=sys.stderr)
        return 0 if cmd == "auto" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

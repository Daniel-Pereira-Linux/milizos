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
import datetime
import json
import os
import re
import shutil
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
            and re.search(r"subvol=/(root|snapshots/\.old-root-\d+)(,|$)", opts) is not None)


def pending():
    """Ha uma volta no tempo aplicada aguardando reinicializacao?"""
    for mp in ("/", "/home"):
        if "snapshots/.old-" in run(["findmnt", "-no", "OPTIONS", mp], check=False):
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
                "kernel": None, "cmdline": ""}
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
        prune()
        space_guard()
        gen_grub()
    return cid


def prune():
    its = items()
    for kind, keep in KEEP.items():
        for i in [x for x in its if x["kind"] == kind][:-keep]:
            _delete(i["id"])
    days = set()
    for i in reversed([x for x in its if x["kind"] == "hora"]):
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
    auto = [i for i in items() if i["kind"] in AUTO_KINDS][:-1]
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
        _delete(cid)
        gen_grub()


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
        what = " e ".join({"root": "sistema", "home": "arquivos pessoais", "log": "logs"}[p] for p in parts)
        saved = create(f"{what} antes de voltar ao ponto #{cid}", "antes")
        stamp = now().strftime("%Y%m%d%H%M%S")
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
            new = f"{TOP}/root"
            binds = [("/boot", True), ("/boot/efi", os.path.ismount("/boot/efi")), ("/proc", True),
                     ("/sys", True), ("/dev", True), ("/run", True)]
            mounted = []
            try:
                for m, want in binds:
                    if want:
                        run(["mount", "--rbind", m, new + m])
                        run(["mount", "--make-rslave", new + m])
                        mounted.append(new + m)
                if os.path.exists(new + SELF):
                    run(["chroot", new, SELF, "sync-boot"], check=False)
            finally:
                for m in reversed(mounted):
                    run(["umount", "-R", m], check=False)
    return saved


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
            elif n.startswith("pre-rollback-"):
                shutil.rmtree(p, ignore_errors=True)
        if changed or "heloisa.rollback=" in open("/proc/cmdline").read():
            sync_boot()
        if not pending():
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


def restore(path, cid, inplace=True):
    """Traz um arquivo ou pasta de volta de um ponto. Em 'inplace' o caminho fica identico ao do
    ponto (o estado atual vira um ponto antes); senao, uma copia e criada ao lado."""
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
            return {"saved": None, "dest": dst}
        saved = create(f"antes de restaurar {path} do ponto #{cid}", "antes")
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
        return {"saved": saved, "dest": path}


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
    st = {"live": live(), "supported": supported(), "pending": False, "points": [], "usage": None}
    if os.geteuid() != 0 or not st["supported"]:
        return st
    st["pending"] = pending()
    with Top():
        st["points"] = items()
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


# ---------------------------------------------------------------- interface de linha / servidor
OPS = {
    "status": lambda a: status(),
    "create": lambda a: {"id": create(a.get("desc") or "ponto manual", a.get("kind", "manual"))},
    "delete": lambda a: delete(int(a["id"])),
    "rollback": lambda a: {"saved": rollback(int(a["id"]), a.get("parts") or ["root"])},
    "versions": lambda a: versions(a["path"], bool(a.get("deep"))),
    "listdir": lambda a: listdir(int(a.get("id") or 0), a["path"]),
    "diff": lambda a: diff(a["path"], int(a["id"]), int(a.get("other") or 0)),
    "restore": lambda a: restore(a["path"], int(a["id"]), bool(a.get("inplace", True))),
    "changes": lambda a: changes(int(a["id"]), int(a.get("other") or 0)),
    "rescue-find": lambda a: rescue_find(),
    "rescue": lambda a: rescue(a["dev"], int(a["id"])),
    "reboot": lambda a: run(["systemctl", "reboot"], check=False),
}


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
            if supported() and os.geteuid() == 0 and not pending():
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

# MilizOS - checkpoints do sistema (snapshots btrfs com rollback)
#
# Layout no volume btrfs:  root (sistema)  home  log  snapshots/<id>/root (somente leitura)
# Cada checkpoint guarda tambem o kernel e o initramfs em /boot/checkpoints/<id>/ e ganha
# uma entrada no GRUB. Iniciar por essa entrada faz o rollback ainda no initramfs.
import datetime
import json
import os
import re
import shutil
import subprocess

TOP = "/run/milizos/top"
SNAP = TOP + "/snapshots"
BOOTCP = "/boot/checkpoints"
GRUBCFG = "/boot/grub2/checkpoints.cfg"
KEEP_AUTO = 10


class Error(Exception):
    pass


def run(cmd, check=True):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise Error(f"{' '.join(cmd[:3])}: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def rootdev():
    dev = os.environ.get("NOS_ROOTDEV") or run(["findmnt", "-no", "SOURCE", "/"], check=False)
    return re.sub(r"\[.*\]$", "", dev)


def supported():
    if os.environ.get("NOS_ROOTDEV"):
        return True
    if os.path.exists("/run/initramfs/live"):
        return False
    opts = run(["findmnt", "-no", "OPTIONS", "/"], check=False)
    # apos um rollback a quente (antes do reboot) a raiz em uso passa a ser snapshots/.old-root-*
    return (run(["findmnt", "-no", "FSTYPE", "/"], check=False) == "btrfs"
            and re.search(r"subvol=/(root|snapshots/\.old-root-\d+)(,|$)", opts) is not None)


def pending():
    """Ha um rollback aplicado aguardando reinicializacao?"""
    return "snapshots/.old-root-" in run(["findmnt", "-no", "OPTIONS", "/"], check=False)


def need():
    if os.geteuid() != 0:
        raise Error("é preciso ser root (use sudo)")
    if not supported():
        raise Error("checkpoints exigem a instalação em btrfs feita pelo instalador do MilizOS")


class Top:
    """Monta a raiz do volume btrfs (subvolid=5) enquanto durar o bloco."""
    def __enter__(self):
        os.makedirs(TOP, exist_ok=True)
        self.mine = not os.path.ismount(TOP)
        if self.mine:
            run(["mount", "-t", "btrfs", "-o", "subvolid=5", rootdev(), TOP])
        if not os.path.isdir(SNAP):
            run(["btrfs", "subvolume", "create", SNAP])
        return self

    def __exit__(self, *_a):
        if self.mine:
            run(["umount", TOP], check=False)


def items():
    out = []
    for n in os.listdir(SNAP):
        try:
            with open(f"{SNAP}/{n}/info.json", encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            pass
    return sorted(out, key=lambda i: i["id"])


def bootable(i):
    return os.path.exists(f"{BOOTCP}/{i['id']}/vmlinuz") and os.path.exists(f"{BOOTCP}/{i['id']}/initramfs.img")


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


def create(desc, kind="manual"):
    need()
    if pending():
        raise Error("há um rollback aguardando reinicialização; reinicie antes de criar checkpoints")
    with Top():
        cur = items()
        cid = (cur[-1]["id"] + 1) if cur else 1
        d = f"{SNAP}/{cid}"
        os.makedirs(d)
        run(["btrfs", "subvolume", "snapshot", "-r", "/", f"{d}/root"])
        info = {"id": cid, "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "kind": kind,
                "desc": desc, "kernel": None, "cmdline": ""}
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
        with open(f"{d}/packages.txt", "w") as f:
            f.write("\n".join(sorted(_pkgs().splitlines())) + "\n")
        with open(f"{d}/info.json", "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False)
        auto = [i for i in items() if i["kind"] == "auto"]
        for i in auto[:-KEEP_AUTO]:
            _delete(i["id"])
        gen_grub()
    return cid


def _delete(cid):
    d = f"{SNAP}/{cid}"
    if os.path.isdir(f"{d}/root"):
        run(["btrfs", "subvolume", "delete", f"{d}/root"])
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(f"{BOOTCP}/{cid}", ignore_errors=True)


def delete(cid):
    need()
    with Top():
        if not os.path.isdir(f"{SNAP}/{cid}"):
            raise Error(f"checkpoint #{cid} não existe")
        _delete(cid)
        gen_grub()


def gen_grub():
    """Reescreve o submenu de checkpoints lido pelo grub.cfg (sem precisar do grub2-mkconfig)."""
    if not os.path.isdir("/boot/grub2"):
        return
    uuid = os.environ.get("NOS_BOOTUUID") or run(["findmnt", "-no", "UUID", "/boot"], check=False)
    ents = [i for i in items() if bootable(i) and i.get("cmdline")]
    lines = []
    if ents and uuid:
        lines.append("submenu 'MilizOS: checkpoints (rollback do sistema)' {")
        for i in reversed(ents):
            title = f"#{i['id']}  {i['time']}  {i['desc']}".replace("'", "").replace("\\", "")[:90]
            cl = re.sub(r"\s*\bmilizos\.rollback=\S+", "", i["cmdline"])
            lines += [f"  menuentry '{title}' {{",
                      f"    search --no-floppy --fs-uuid --set=root {uuid}",
                      f"    linux /checkpoints/{i['id']}/vmlinuz {cl} milizos.rollback={i['id']}",
                      f"    initrd /checkpoints/{i['id']}/initramfs.img", "  }"]
        lines.append("}")
    tmp = GRUBCFG + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# gerado por 'nos checkpoint' - nao edite\n" + "\n".join(lines) + "\n")
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


def rollback(cid):
    """Rollback a quente: troca o subvolume 'root' pelo checkpoint; vale no proximo boot."""
    need()
    if pending():
        raise Error("já há um rollback aguardando reinicialização")
    with Top():
        src = f"{SNAP}/{cid}/root"
        if not os.path.isdir(src):
            raise Error(f"checkpoint #{cid} não existe")
    saved = create(f"estado antes do rollback para #{cid}", "auto")
    with Top():
        old = f"{SNAP}/.old-root-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        os.rename(f"{TOP}/root", old)
        try:
            run(["btrfs", "subvolume", "snapshot", src, f"{TOP}/root"])
        except Error:
            os.rename(old, f"{TOP}/root")
            raise
        new = f"{TOP}/root"
        open(f"{new}/.milizos-rollback", "w").write(f"{cid}\n")
        # alinha /boot aos kernels do sistema restaurado, de dentro dele
        binds = [("/boot", True), ("/boot/efi", os.path.ismount("/boot/efi")), ("/proc", True),
                 ("/sys", True), ("/dev", True), ("/run", True)]
        done = []
        try:
            for m, want in binds:
                if want:
                    run(["mount", "--rbind", m, new + m])
                    run(["mount", "--make-rslave", new + m])
                    done.append(new + m)
            run(["chroot", new, "/usr/bin/nos", "checkpoint", "sync-boot"], check=False)
        finally:
            for m in reversed(done):
                run(["umount", "-R", m], check=False)
    return saved


def finalize():
    """Primeiro boot apos um rollback: registra o estado anterior, limpa e alinha o /boot."""
    if not supported():
        return
    with Top():
        for n in sorted(os.listdir(SNAP)):
            p = f"{SNAP}/{n}"
            if n.startswith("pre-rollback-") and os.path.isdir(f"{p}/root"):
                cur = items()
                cid = (cur[-1]["id"] + 1) if cur else 1
                os.rename(p, f"{SNAP}/{cid}")
                run(["btrfs", "property", "set", "-ts", f"{SNAP}/{cid}/root", "ro", "true"], check=False)
                with open(f"{SNAP}/{cid}/packages.txt", "w") as f:
                    f.write("\n".join(sorted(_pkgs(f"{SNAP}/{cid}/root").splitlines())) + "\n")
                with open(f"{SNAP}/{cid}/info.json", "w", encoding="utf-8") as f:
                    json.dump({"id": cid, "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                               "kind": "auto", "desc": "estado anterior ao rollback feito pelo menu de boot",
                               "kernel": None, "cmdline": ""}, f, ensure_ascii=False)
            elif n.startswith(".old-root-"):
                run(["btrfs", "subvolume", "delete", p], check=False)
        sync_boot()
        gen_grub()
    if os.path.exists("/.milizos-rollback"):
        os.unlink("/.milizos-rollback")


def diff(cid, path=None):
    """Compara o sistema atual com um checkpoint: pacotes e arquivos de /etc."""
    need()
    with Top():
        d = f"{SNAP}/{cid}"
        if not os.path.isdir(f"{d}/root"):
            raise Error(f"checkpoint #{cid} não existe")
        if path:
            rel = os.path.abspath(path).lstrip("/")
            p = subprocess.run(["diff", "-u", "--label", f"checkpoint#{cid}/{rel}", "--label", f"atual/{rel}",
                                f"{d}/root/{rel}", f"/{rel}"], capture_output=True, text=True)
            return {"text": p.stdout or p.stderr}
        def parse(txt):
            return dict(l.split(" ", 1) for l in txt.splitlines() if " " in l)
        try:
            old = parse(open(f"{d}/packages.txt").read())
        except OSError:
            old = {}
        new = parse(_pkgs())
        pk = {"added": sorted(f"{n} {new[n]}" for n in new.keys() - old.keys()),
              "removed": sorted(f"{n} {old[n]}" for n in old.keys() - new.keys()),
              "changed": sorted(f"{n} {old[n]} → {new[n]}" for n in new.keys() & old.keys() if new[n] != old[n])}
        p = subprocess.run(["diff", "-rq", "--no-dereference", f"{d}/root/etc", "/etc"],
                           capture_output=True, text=True)
        et = {"added": [], "removed": [], "changed": []}
        pre = f"{d}/root"
        for l in p.stdout.splitlines():
            m = re.match(r"Only in (.+?): (.+)$", l)
            if m:
                full = m.group(1).rstrip("/") + "/" + m.group(2)
                if full.startswith(pre):
                    et["removed"].append(full[len(pre):])
                else:
                    et["added"].append(full)
                continue
            m = re.match(r"Files (.+?) and (.+?) differ$", l)
            if m:
                et["changed"].append(m.group(2))
        return {"packages": pk, "etc": et}


# ---------------------------------------------------------------- resgate pela midia live
def rescue_find():
    """Volumes btrfs com instalacao do MilizOS (abre LUKS se preciso). Retorna [(dev, [itens])]."""
    found = []
    devs = run(["lsblk", "-rno", "PATH,FSTYPE"], check=False).splitlines()
    for l in devs:
        dev, _, fs = l.partition(" ")
        if fs == "crypto_LUKS":
            name = "nos-rescue-" + os.path.basename(dev)
            if not os.path.exists(f"/dev/mapper/{name}"):
                print(f"  volume criptografado em {dev}")
                if subprocess.call(["cryptsetup", "open", dev, name]) != 0:
                    continue
            dev, fs = f"/dev/mapper/{name}", "btrfs"
        if fs != "btrfs":
            continue
        os.makedirs(TOP, exist_ok=True)
        if subprocess.call(["mount", "-t", "btrfs", "-o", "subvolid=5", dev, TOP], stderr=subprocess.DEVNULL) != 0:
            continue
        try:
            if os.path.isdir(SNAP):
                found.append((dev, items()))
        finally:
            run(["umount", TOP], check=False)
    return found


def rescue(dev, cid, log=print):
    """Restaura o checkpoint num sistema que nao inicia mais e reconstroi /boot e o GRUB."""
    if os.geteuid() != 0:
        raise Error("é preciso ser root (use sudo)")
    os.makedirs(TOP, exist_ok=True)
    run(["mount", "-t", "btrfs", "-o", "subvolid=5", dev, TOP])
    T = "/run/milizos/rescue"
    done = []
    try:
        src = f"{SNAP}/{cid}/root"
        if not os.path.isdir(src):
            raise Error(f"checkpoint #{cid} não existe")
        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        if os.path.isdir(f"{TOP}/root"):
            os.makedirs(f"{SNAP}/pre-rollback-{stamp}", exist_ok=True)
            os.rename(f"{TOP}/root", f"{SNAP}/pre-rollback-{stamp}/root")
            log("estado quebrado guardado (vira um checkpoint no próximo boot)")
        run(["btrfs", "subvolume", "snapshot", src, f"{TOP}/root"])
        log(f"checkpoint #{cid} restaurado como sistema")
        os.makedirs(T, exist_ok=True)
        run(["mount", "-t", "btrfs", "-o", "subvol=root", dev, T]); done.append(T)
        open(f"{T}/.milizos-rollback", "w").write(f"{cid}\n")
        boot = efi = None
        for l in open(f"{T}/etc/fstab"):
            f = l.split()
            if len(f) >= 2 and not l.startswith("#"):
                if f[1] == "/boot":
                    boot = f[0]
                elif f[1] == "/boot/efi":
                    efi = f[0]
        if not boot:
            raise Error("o fstab do checkpoint não tem /boot")
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
        # kernels e entradas de boot a partir do que o checkpoint tem em /lib/modules
        os.makedirs(f"{T}/boot/loader/entries", exist_ok=True)
        os.makedirs(f"{T}/boot/grub2", exist_ok=True)
        ch("/usr/bin/nos", "checkpoint", "sync-boot")
        log("kernels e initramfs reconstruídos em /boot")
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
        env = dict(os.environ, NOS_ROOTDEV=dev, NOS_BOOTUUID=buuid)
        subprocess.run(["chroot", T, "/usr/bin/python3", "-c",
                        "import sys; sys.path.insert(0,'/usr/lib/milizos'); import checkpoint as c\n"
                        "with c.Top(): c.gen_grub()"], env=env, capture_output=True)
        log(f"GRUB reinstalado em {disk}")
        if not os.listdir(f"{T}/boot/loader/entries"):
            raise Error("nenhuma entrada de boot foi recriada")
    finally:
        for m in reversed(done):
            run(["umount", "-R", m], check=False)
        run(["umount", TOP], check=False)


# ---------------------------------------------------------------- linha do tempo dos dados (/home)
DATA = SNAP + "/data"
KEEP_HOURLY_H = 24
KEEP_DAILY_D = 14


def data_items():
    if not os.path.isdir(DATA):
        return []
    return sorted(n for n in os.listdir(DATA) if re.fullmatch(r"\d{8}-\d{6}", n) and os.path.isdir(f"{DATA}/{n}/home"))


def data_snap(prune=True):
    """Snapshot somente leitura de /home; aplica a retencao (horarios por 24 h, diarios por 14 dias)."""
    need()
    with Top():
        if not os.path.isdir(f"{TOP}/home"):
            raise Error("este volume não tem o subvolume home")
        os.makedirs(DATA, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        os.makedirs(f"{DATA}/{stamp}")
        run(["btrfs", "subvolume", "snapshot", "-r", f"{TOP}/home", f"{DATA}/{stamp}/home"])
        if prune:
            now = datetime.datetime.now()
            days = set()
            for n in reversed(data_items()):
                t = datetime.datetime.strptime(n, "%Y%m%d-%H%M%S")
                age = now - t
                if age <= datetime.timedelta(hours=KEEP_HOURLY_H):
                    days.add(n[:8])
                    continue
                if age <= datetime.timedelta(days=KEEP_DAILY_D) and n[:8] not in days:
                    days.add(n[:8])
                    continue
                run(["btrfs", "subvolume", "delete", f"{DATA}/{n}/home"], check=False)
                shutil.rmtree(f"{DATA}/{n}", ignore_errors=True)
    return stamp


def data_pick(when):
    """Resolve 'ontem', 'YYYY-MM-DD[ HH:MM]', um id, ou None (o mais recente) para um snapshot."""
    its = data_items()
    if not its:
        raise Error("ainda não há snapshots de dados (crie um com: nos data snap)")
    if not when:
        return its[-1]
    if when in its:
        return when
    now = datetime.datetime.now()
    w = when.lower().strip()
    if w in ("ontem", "yesterday"):
        target = now - datetime.timedelta(days=1)
    elif re.fullmatch(r"\d+[hd]", w):
        target = now - (datetime.timedelta(hours=int(w[:-1])) if w.endswith("h") else datetime.timedelta(days=int(w[:-1])))
    else:
        target = None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                target = datetime.datetime.strptime(when, fmt)
                if fmt == "%Y-%m-%d":
                    target = target.replace(hour=23, minute=59, second=59)
                break
            except ValueError:
                pass
        if target is None:
            raise Error("use: ontem, 3h, 2d, AAAA-MM-DD, 'AAAA-MM-DD HH:MM' ou o id do snapshot")
    older = [n for n in its if datetime.datetime.strptime(n, "%Y%m%d-%H%M%S") <= target]
    if not older:
        raise Error(f"não há snapshot tão antigo; o primeiro é {its[0]}")
    return older[-1]


def data_restore(path, when=None, inplace=False):
    """Copia um arquivo ou pasta de um snapshot de volta. Retorna (snapshot, destino)."""
    need()
    path = os.path.abspath(path)
    if not (path + "/").startswith("/home/"):
        raise Error("a linha do tempo cobre apenas /home")
    rel = os.path.relpath(path, "/home")
    with Top():
        sid = data_pick(when)
        src = f"{DATA}/{sid}/home" + ("" if rel == "." else "/" + rel)
        if not os.path.lexists(src):
            raise Error(f"{path} não existia no snapshot {sid}")
        if inplace:
            dst = path
            if os.path.isdir(src) and not os.path.islink(src):
                os.makedirs(dst, exist_ok=True)
                run(["cp", "-a", "--reflink=auto", src + "/.", dst + "/"])
            else:
                run(["cp", "-a", "--reflink=auto", "--remove-destination", src, dst])
        else:
            dst = f"{path.rstrip('/')}.restaurado-{sid}"
            run(["cp", "-a", "--reflink=auto", src, dst])
    return sid, dst

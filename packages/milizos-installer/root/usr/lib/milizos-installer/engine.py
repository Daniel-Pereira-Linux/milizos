#!/usr/bin/python3
# MilizOS Installer - motor de instalacao (backend)
# Recebe uma configuracao (dict/JSON) e instala o sistema no disco alvo.
# Emite eventos de progresso em JSON (uma linha por evento) no stdout.
import json
import os
import re
import shutil
import subprocess
import sys
import time

TARGET = "/mnt/milizos-target"
LOG = "/var/log/milizos-install.log"

LOCALES = {
    "pt_BR.UTF-8": "Português (Brasil)",
    "en_US.UTF-8": "English (United States)",
    "es_ES.UTF-8": "Español (España)",
}

# (id, rotulo, layout X11, variante X11, keymap do console)
KEYMAPS = [
    ("br", "Português (Brasil, ABNT2)", "br", "", "br-abnt2"),
    ("us", "English (US)", "us", "", "us"),
    ("us-intl", "English (US, internacional com acentos)", "us", "intl", "us-acentos"),
    ("pt", "Português (Portugal)", "pt", "", "pt-latin1"),
    ("es", "Español (España)", "es", "", "es"),
    ("latam", "Español (Latinoamérica)", "latam", "", "la-latin1"),
    ("de", "Deutsch", "de", "", "de"),
    ("fr", "Français", "fr", "", "fr"),
    ("it", "Italiano", "it", "", "it"),
    ("gb", "English (UK)", "gb", "", "uk"),
]

PROFILES = {
    "soc": {
        "label": "Estação SOC",
        "desc": "Desktop completo para analistas: triagem, análise de tráfego, DFIR e auditoria. "
                "Firewall e auditoria do sistema ativos.",
        "target": "graphical.target",
        "enable": ["firewalld", "auditd", "NetworkManager", "chronyd"],
        "disable": ["sshd"],
        "groups": ["wheel", "wireshark"],
    },
    "neteng": {
        "label": "Engenharia de Redes",
        "desc": "Desktop para engenharia de redes: laboratório, automação, console serial e "
                "descoberta de vizinhos (LLDP). SSH habilitado.",
        "target": "graphical.target",
        "enable": ["firewalld", "NetworkManager", "chronyd", "sshd", "lldpd"],
        "disable": [],
        "groups": ["wheel", "wireshark", "dialout", "libvirt"],
    },
    "sensor": {
        "label": "Sensor de Rede (headless)",
        "desc": "Sem interface gráfica no boot: sensor IDS com Suricata, SSH e painel web "
                "Cockpit (porta 9090). Ideal para um espelhamento/TAP de rede.",
        "target": "multi-user.target",
        "enable": ["firewalld", "auditd", "NetworkManager", "chronyd", "sshd",
                   "milizos-sensor-setup", "suricata", "cockpit.socket"],
        "disable": [],
        "groups": ["wheel", "wireshark", "suricata"],
    },
}

STEPS = [
    ("prepare", "Preparando o disco", 1),
    ("partition", "Criando partições", 2),
    ("format", "Formatando sistemas de arquivos", 3),
    ("copy", "Copiando o sistema", 62),
    ("configure", "Configurando o sistema", 4),
    ("users", "Criando usuário", 1),
    ("bootloader", "Instalando kernel e gerenciador de boot", 18),
    ("selinux", "Aplicando rótulos de segurança (SELinux)", 8),
    ("finish", "Finalizando", 1),
]


class InstallError(Exception):
    pass


def emit(**ev):
    sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


def run(cmd, input=None, check=True, chroot=False, env=None):
    """Executa um comando, registrando a saida no log."""
    if chroot:
        cmd = ["chroot", TARGET] + list(cmd)
    log("$ " + " ".join(cmd))
    e = dict(os.environ, LC_ALL="C.UTF-8")
    if env:
        e.update(env)
    p = subprocess.run(cmd, input=input, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, env=e)
    if p.stdout and p.stdout.strip():
        log(p.stdout.rstrip())
    if check and p.returncode != 0:
        tail = "\n".join((p.stdout or "").strip().splitlines()[-6:])
        raise InstallError(f"Falha em: {' '.join(cmd[:4])}...\n{tail}")
    return p


def out(cmd, **kw):
    return run(cmd, **kw).stdout.strip()


def part(disk, n):
    return f"{disk}p{n}" if disk[-1].isdigit() else f"{disk}{n}"


def list_disks():
    """Discos elegiveis para instalacao (exclui a midia live, loops, zram e somente-leitura)."""
    p = subprocess.run(["lsblk", "-J", "-b", "-o",
                        "NAME,PATH,SIZE,MODEL,TYPE,RO,RM,TRAN,MOUNTPOINTS,FSTYPE,LABEL"],
                       capture_output=True, text=True)
    disks = []
    try:
        data = json.loads(p.stdout)
    except ValueError:
        return disks

    def mounts(dev):
        m = [x for x in (dev.get("mountpoints") or []) if x]
        for c in dev.get("children") or []:
            m += mounts(c)
        return m

    def labels(dev):
        l = [dev.get("label") or ""]
        for c in dev.get("children") or []:
            l += labels(c)
        return l

    for d in data.get("blockdevices", []):
        if d.get("type") != "disk" or d.get("ro"):
            continue
        if d["name"].startswith(("zram", "loop", "sr", "fd")):
            continue
        ms = mounts(d)
        if any(m.startswith("/run/initramfs") for m in ms):
            continue  # midia de instalacao
        if any(l.startswith("MILIZOS") for l in labels(d)) and d.get("fstype") == "iso9660":
            continue
        size = int(d.get("size") or 0)
        if size < 8 * 1024 ** 3:
            continue
        disks.append({
            "path": d["path"],
            "size": size,
            "model": (d.get("model") or "").strip() or "Disco",
            "tran": d.get("tran") or "",
            "removable": bool(d.get("rm")),
            "parts": len(d.get("children") or []),
        })
    return disks


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u in ("B", "KB", "MB") else f"{n:.1f} {u}"
        n /= 1024


def validate(cfg):
    errs = []
    if cfg.get("disk") == "auto":   # midias forjadas: o maior disco interno elegivel
        ds = sorted(list_disks(), key=lambda d: (d["removable"], -d["size"]))
        cfg["disk"] = ds[0]["path"] if ds else ""
    disk = cfg.get("disk", "")
    if not disk or not os.path.exists(disk):
        errs.append(f"Disco inválido: {disk!r}")
    if cfg.get("filesystem", "btrfs") not in ("btrfs", "xfs", "ext4"):
        errs.append("Sistema de arquivos deve ser btrfs, xfs ou ext4")
    if cfg.get("encrypt") and len(cfg.get("passphrase") or "") < 8:
        errs.append("A senha de criptografia precisa de ao menos 8 caracteres")
    u = cfg.get("user") or {}
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", u.get("name", "")):
        errs.append("Nome de usuário inválido (use minúsculas, números, - e _)")
    elif u["name"] in ("root", "liveuser", "bin", "daemon", "adm", "nobody"):
        errs.append("Nome de usuário reservado")
    if not u.get("password") and not str(u.get("password_hash", "")).startswith("$"):
        errs.append("Defina uma senha para o usuário")
    if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?", cfg.get("hostname", "")):
        errs.append("Nome da máquina inválido")
    if cfg.get("profile", "soc") not in PROFILES:
        errs.append("Perfil desconhecido")
    if cfg.get("locale", "pt_BR.UTF-8") not in LOCALES:
        errs.append("Idioma desconhecido")
    tz = cfg.get("timezone", "America/Sao_Paulo")
    if not os.path.exists(f"/usr/share/zoneinfo/{tz}"):
        errs.append("Fuso horário desconhecido")
    return errs


class Installer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.disk = cfg["disk"]
        self.fs = cfg.get("filesystem", "btrfs")
        self.encrypt = bool(cfg.get("encrypt"))
        self.total = sum(w for _, _, w in STEPS)
        self.done_w = 0
        self.cur_w = 0
        self.luks_name = None
        self.uuids = {}

    # ---------------------------------------------------------- progresso
    def frac(self, f):
        emit(type="progress", fraction=round((self.done_w + self.cur_w * f) / self.total, 4))

    def install(self):
        for i, (sid, label, w) in enumerate(STEPS):
            self.cur_w = w
            emit(type="step", id=sid, index=i + 1, total=len(STEPS), label=label)
            log(f"=== {sid}: {label}")
            self.frac(0)
            getattr(self, "step_" + sid)()
            self.done_w += w
        emit(type="progress", fraction=1.0)
        emit(type="done")

    # ---------------------------------------------------------- etapas
    def step_prepare(self):
        run(["swapoff", "-a"], check=False)
        run(["umount", "-R", TARGET], check=False)
        # desmonta qualquer particao do disco alvo
        mp = out(["lsblk", "-ln", "-o", "MOUNTPOINT", self.disk], check=False)
        for m in sorted(filter(None, mp.splitlines()), reverse=True):
            if m.startswith("/run/initramfs") or m == "/":
                raise InstallError("O disco selecionado está em uso pelo sistema live.")
            run(["umount", "-R", m], check=False)
        # fecha mapeamentos LUKS antigos sobre o disco
        holders = out(["lsblk", "-ln", "-o", "NAME,TYPE", self.disk], check=False)
        for line in holders.splitlines():
            f = line.split()
            if len(f) == 2 and f[1] == "crypt":
                run(["cryptsetup", "close", f[0]], check=False)
        os.makedirs(TARGET, exist_ok=True)

    def step_partition(self):
        d = self.disk
        for n in out(["lsblk", "-ln", "-o", "PATH", d], check=False).splitlines()[1:]:
            run(["wipefs", "-af", n], check=False)
        run(["wipefs", "-af", d], check=False)
        run(["sgdisk", "--zap-all", d])
        run(["sgdisk",
             "-n1:1MiB:+1MiB", "-t1:ef02", "-c1:BIOS boot",
             "-n2:0:+600MiB", "-t2:ef00", "-c2:EFI System",
             "-n3:0:+1GiB", "-t3:8300", "-c3:MilizOS boot",
             "-n4:0:0", "-t4:" + ("8309" if self.encrypt else "8304"), "-c4:MilizOS",
             d])
        run(["partprobe", d], check=False)
        run(["udevadm", "settle", "--timeout=20"], check=False)
        for n in (2, 3, 4):
            for _ in range(50):
                if os.path.exists(part(d, n)):
                    break
                time.sleep(0.2)
            else:
                raise InstallError(f"Partição {part(d, n)} não apareceu")
            run(["wipefs", "-af", part(d, n)], check=False)

    def step_format(self):
        d = self.disk
        esp, boot, rootp = part(d, 2), part(d, 3), part(d, 4)
        run(["mkfs.vfat", "-F", "32", "-n", "EFI", esp])
        self.frac(0.2)
        run(["mkfs.ext4", "-F", "-q", "-L", "boot", boot])
        self.frac(0.4)
        rootdev = rootp
        if self.encrypt:
            pw = self.cfg["passphrase"]
            run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode",
                 "--key-file", "-", rootp], input=pw)
            luks_uuid = out(["cryptsetup", "luksUUID", rootp])
            self.uuids["luks"] = luks_uuid
            self.luks_name = f"luks-{luks_uuid}"
            run(["cryptsetup", "open", "--key-file", "-", rootp, self.luks_name], input=pw)
            rootdev = f"/dev/mapper/{self.luks_name}"
        self.frac(0.6)
        if self.fs == "btrfs":
            run(["mkfs.btrfs", "-f", "-L", "milizos", rootdev])
            run(["mount", rootdev, TARGET])
            run(["btrfs", "subvolume", "create", f"{TARGET}/root"])
            run(["btrfs", "subvolume", "create", f"{TARGET}/home"])
            # logs e checkpoints ficam fora do subvolume raiz: sobrevivem a um rollback
            run(["btrfs", "subvolume", "create", f"{TARGET}/log"])
            run(["btrfs", "subvolume", "create", f"{TARGET}/snapshots"])
            run(["umount", TARGET])
            opts = "compress=zstd:1,noatime"
            run(["mount", "-o", f"subvol=root,{opts}", rootdev, TARGET])
            os.makedirs(f"{TARGET}/home", exist_ok=True)
            run(["mount", "-o", f"subvol=home,{opts}", rootdev, f"{TARGET}/home"])
            os.makedirs(f"{TARGET}/var/log", exist_ok=True)
            run(["mount", "-o", f"subvol=log,{opts}", rootdev, f"{TARGET}/var/log"])
        elif self.fs == "xfs":
            run(["mkfs.xfs", "-f", "-L", "milizos", rootdev])
            run(["mount", rootdev, TARGET])
        else:
            run(["mkfs.ext4", "-F", "-q", "-L", "milizos", rootdev])
            run(["mount", rootdev, TARGET])
        os.makedirs(f"{TARGET}/boot", exist_ok=True)
        run(["mount", boot, f"{TARGET}/boot"])
        os.makedirs(f"{TARGET}/boot/efi", exist_ok=True)
        run(["mount", "-o", "umask=0077,shortname=winnt", esp, f"{TARGET}/boot/efi"])
        run(["udevadm", "settle", "--timeout=20"], check=False)
        self.rootdev = rootdev
        self.uuids["root"] = out(["blkid", "-s", "UUID", "-o", "value", rootdev])
        self.uuids["boot"] = out(["blkid", "-s", "UUID", "-o", "value", boot])
        self.uuids["esp"] = out(["blkid", "-s", "UUID", "-o", "value", esp])
        if not all(self.uuids.get(k) for k in ("root", "boot", "esp")):
            raise InstallError("Não foi possível ler os UUIDs das partições")

    def _source(self):
        src = os.environ.get("MILIZOS_SOURCE")
        if src:
            return src
        if os.path.isdir("/run/rootfsbase/usr"):
            return "/run/rootfsbase"
        img = "/run/initramfs/live/LiveOS/squashfs.img"
        if os.path.exists(img):
            mnt = "/run/milizos-source"
            os.makedirs(mnt, exist_ok=True)
            if not os.path.isdir(f"{mnt}/usr"):
                run(["mount", "-o", "ro,loop", img, mnt])
            return mnt
        raise InstallError("Imagem do sistema não encontrada (o instalador deve rodar no modo live).")

    def step_copy(self):
        src = self._source()
        log(f"origem: {src}")
        cmd = ["rsync", "-aHAXS", "--numeric-ids", "--info=progress2", "--no-inc-recursive",
               "--exclude=/boot/efi", "--exclude=/boot/initramfs-*", "--exclude=/boot/loader/entries/*",
               "--exclude=/etc/machine-id", "--exclude=/var/lib/systemd/random-seed",
               f"{src}/", f"{TARGET}/"]
        log("$ " + " ".join(cmd))
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=dict(os.environ, LC_ALL="C"))
        buf = b""
        last = -1
        while True:
            ch = p.stdout.read(256)
            if not ch:
                break
            buf += ch
            *lines, buf = re.split(rb"[\r\n]", buf)
            for ln in lines:
                m = re.search(rb"(\d+)%", ln)
                if m:
                    pct = int(m.group(1))
                    if pct != last:
                        last = pct
                        self.frac(min(pct / 100 * 0.97, 0.97))
        err = p.stderr.read().decode(errors="replace")
        rc = p.wait()
        if err.strip():
            log(err.strip())
        if rc not in (0, 24):
            raise InstallError("Falha ao copiar o sistema (rsync %d)\n%s" % (rc, err.strip()[-400:]))
        # ESP (vfat): copia simples, sem atributos
        efi_src = f"{src}/boot/efi"
        if os.path.isdir(efi_src):
            shutil.copytree(efi_src, f"{TARGET}/boot/efi", dirs_exist_ok=True,
                            copy_function=shutil.copyfile)
        run(["sync"], check=False)

    def step_configure(self):
        c, u = self.cfg, self.uuids
        root = self.rootdev if self.encrypt else f"UUID={u['root']}"
        fstab = ["# /etc/fstab - gerado pelo MilizOS Installer"]
        if self.fs == "btrfs":
            o = "compress=zstd:1,noatime"
            fstab.append(f"{root}  /      btrfs  subvol=root,{o}  0 0")
            fstab.append(f"{root}  /home  btrfs  subvol=home,{o}  0 0")
            fstab.append(f"{root}  /var/log  btrfs  subvol=log,{o}  0 0")
        else:
            fstab.append(f"{root}  /      {self.fs}  defaults  0 1")
        fstab.append(f"UUID={u['boot']}  /boot      ext4  defaults  1 2")
        fstab.append(f"UUID={u['esp']}  /boot/efi  vfat  umask=0077,shortname=winnt  0 2")
        self._write("/etc/fstab", "\n".join(fstab) + "\n")
        if self.encrypt:
            self._write("/etc/crypttab", f"{self.luks_name} UUID={u['luks']} none discard\n", 0o600)

        self._write("/etc/hostname", c.get("hostname", "milizos") + "\n")
        self._write("/etc/locale.conf", f"LANG={c.get('locale', 'pt_BR.UTF-8')}\n")
        km = next((k for k in KEYMAPS if k[0] == c.get("keymap", "br")), KEYMAPS[0])
        self._write("/etc/vconsole.conf", f'KEYMAP="{km[4]}"\nFONT="eurlatgr"\n'
                    f'XKBLAYOUT="{km[2]}"\n' + (f'XKBVARIANT="{km[3]}"\n' if km[3] else ""))
        x11 = ('Section "InputClass"\n        Identifier "system-keyboard"\n'
               '        MatchIsKeyboard "on"\n'
               f'        Option "XkbLayout" "{km[2]}"\n')
        if km[3]:
            x11 += f'        Option "XkbVariant" "{km[3]}"\n'
        x11 += 'EndSection\n'
        os.makedirs(f"{TARGET}/etc/X11/xorg.conf.d", exist_ok=True)
        self._write("/etc/X11/xorg.conf.d/00-keyboard.conf", x11)
        tz = c.get("timezone", "America/Sao_Paulo")
        lt = f"{TARGET}/etc/localtime"
        if os.path.lexists(lt):
            os.unlink(lt)
        os.symlink(f"../usr/share/zoneinfo/{tz}", lt)

        self._mount_api()
        mid = f"{TARGET}/etc/machine-id"
        if os.path.lexists(mid):
            os.unlink(mid)
        run(["systemd-machine-id-setup"], chroot=True)

        prof = PROFILES[c.get("profile", "soc")]
        self._write("/etc/milizos-profile", c.get("profile", "soc") + "\n")
        run(["systemctl", "set-default", prof["target"]], chroot=True, check=False)
        for s in prof["enable"]:
            run(["systemctl", "enable", s], chroot=True, check=False)
        for s in prof["disable"]:
            run(["systemctl", "disable", s], chroot=True, check=False)

    def step_users(self):
        c = self.cfg
        u = c["user"]
        prof = PROFILES[c.get("profile", "soc")]
        existing = {l.split(":")[0] for l in open(f"{TARGET}/etc/group")}
        groups = [g for g in prof["groups"] if g in existing]
        if not u.get("admin", True) and "wheel" in groups:
            groups.remove("wheel")
        shell = "/usr/bin/zsh" if os.path.exists(f"{TARGET}/usr/bin/zsh") else "/bin/bash"
        cmd = ["useradd", "-m", "-s", shell, "-c", u.get("fullname") or u["name"]]
        if groups:
            cmd += ["-G", ",".join(groups)]
        run(cmd + [u["name"]], chroot=True)
        if u.get("password_hash"):
            run(["chpasswd", "-e"], input=f"{u['name']}:{u['password_hash']}\n", chroot=True)
        else:
            run(["chpasswd"], input=f"{u['name']}:{u['password']}\n", chroot=True)
        if c.get("root_password_hash"):
            run(["chpasswd", "-e"], input=f"root:{c['root_password_hash']}\n", chroot=True)
        elif c.get("root_password"):
            run(["chpasswd"], input=f"root:{c['root_password']}\n", chroot=True)
        else:
            run(["passwd", "-l", "root"], chroot=True, check=False)

    def step_bootloader(self):
        u = self.uuids
        root = self.rootdev if self.encrypt else f"UUID={u['root']}"
        extra = []
        if self.fs == "btrfs":
            extra.append("rootflags=subvol=root")
        if self.encrypt:
            extra.append(f"rd.luks.uuid={self.luks_name}")
        quiet = "rhgb quiet"
        if self.cfg.get("profile") == "sensor":
            quiet = "quiet"
        cmdline = " ".join([f"root={root}", "ro"] + extra + [quiet])
        os.makedirs(f"{TARGET}/etc/kernel", exist_ok=True)
        self._write("/etc/kernel/cmdline", cmdline + "\n")
        theme = ""
        if os.path.isdir(f"{TARGET}/usr/share/grub/themes/milizos"):
            shutil.copytree(f"{TARGET}/usr/share/grub/themes/milizos",
                            f"{TARGET}/boot/grub2/themes/milizos", dirs_exist_ok=True)
            theme = 'GRUB_THEME="/boot/grub2/themes/milizos/theme.txt"\nGRUB_TERMINAL_OUTPUT="gfxterm"\nGRUB_GFXMODE="1280x800,1024x768,auto"\n'
        self._write("/etc/default/grub",
                    'GRUB_TIMEOUT=5\nGRUB_DISTRIBUTOR="MilizOS"\nGRUB_DEFAULT=saved\n'
                    'GRUB_DISABLE_SUBMENU=true\nGRUB_DISABLE_RECOVERY="true"\n'
                    'GRUB_DISABLE_OS_PROBER=true\nGRUB_ENABLE_BLSCFG=true\n'
                    f'GRUB_CMDLINE_LINUX="{" ".join(extra + [quiet])}"\n' + theme)
        self.frac(0.05)

        kvers = sorted(k for k in os.listdir(f"{TARGET}/lib/modules")
                       if os.path.exists(f"{TARGET}/lib/modules/{k}/vmlinuz"))
        if not kvers:
            raise InstallError("Nenhum kernel encontrado na imagem")
        for i, k in enumerate(kvers):
            run(["kernel-install", "add", k, f"/lib/modules/{k}/vmlinuz"], chroot=True)
            if not os.path.exists(f"{TARGET}/boot/initramfs-{k}.img"):
                run(["dracut", "--force", "--kver", k, f"/boot/initramfs-{k}.img"], chroot=True)
            if not os.path.exists(f"{TARGET}/boot/vmlinuz-{k}"):
                shutil.copyfile(f"{TARGET}/lib/modules/{k}/vmlinuz", f"{TARGET}/boot/vmlinuz-{k}")
            self.frac(0.05 + 0.7 * (i + 1) / len(kvers))

        # BIOS (i386-pc): sempre que possivel, para o disco iniciar nos dois modos
        efi_boot = os.path.isdir("/sys/firmware/efi")
        p = run(["grub2-install", "--target=i386-pc", "--recheck", self.disk], chroot=True, check=False)
        if p.returncode != 0 and not efi_boot:
            raise InstallError("Falha ao instalar o GRUB (BIOS) no disco")
        self.frac(0.85)

        # UEFI: shim + grub assinados ja foram copiados para a ESP; grava o stub de configuracao
        stub = (f"search --no-floppy --fs-uuid --set=dev {u['boot']}\n"
                "set prefix=($dev)/grub2\nexport $prefix\nconfigfile $prefix/grub.cfg\n")
        efidir = f"{TARGET}/boot/efi/EFI"
        vendor = None
        if os.path.isdir(efidir):
            for dname in os.listdir(efidir):
                if dname.upper() != "BOOT" and os.path.exists(f"{efidir}/{dname}/grubx64.efi"):
                    vendor = dname
                    with open(f"{efidir}/{dname}/grub.cfg", "w") as f:
                        f.write(stub)
            if os.path.isdir(f"{efidir}/BOOT"):
                with open(f"{efidir}/BOOT/grub.cfg", "w") as f:
                    f.write(stub)
        if efi_boot and not vendor:
            raise InstallError("Arquivos de boot UEFI ausentes na imagem")
        run(["grub2-mkconfig", "-o", "/boot/grub2/grub.cfg"], chroot=True)
        if efi_boot and vendor:
            run(["efibootmgr", "-c", "-d", self.disk, "-p", "2", "-L", "MilizOS",
                 "-l", f"\\EFI\\{vendor}\\shimx64.efi"], check=False)
        if not os.listdir(f"{TARGET}/boot/loader/entries"):
            raise InstallError("Nenhuma entrada de boot foi criada")

    def step_selinux(self):
        fc = "/etc/selinux/targeted/contexts/files/file_contexts"
        if not os.path.exists(TARGET + fc):
            return
        ok = False
        if subprocess.run(["selinuxenabled"]).returncode == 0:
            paths = ["/", "/boot"] + (["/home", "/var/log"] if self.fs == "btrfs" else [])
            p = run(["setfiles", "-F", "-e", "/proc", "-e", "/sys", "-e", "/dev", "-e", "/run",
                     "-e", "/boot/efi", fc] + paths, chroot=True, check=False)
            ok = p.returncode == 0
        if not ok:
            log("setfiles indisponivel; agendando relabel no primeiro boot")
            open(f"{TARGET}/.autorelabel", "w").close()

    def step_finish(self):
        if self.fs == "btrfs" and os.path.exists(f"{TARGET}/usr/bin/nos"):
            # ponto de retorno "de fabrica": sempre da para voltar a instalacao limpa
            run(["nos", "checkpoint", "create", "--kind", "install", "instalação limpa"], chroot=True,
                check=False, env={"NOS_ROOTDEV": self.rootdev, "NOS_BOOTUUID": self.uuids["boot"]})
        try:
            os.makedirs(f"{TARGET}/var/log", exist_ok=True)
            shutil.copyfile(LOG, f"{TARGET}/var/log/milizos-install.log")
            os.chmod(f"{TARGET}/var/log/milizos-install.log", 0o600)
        except OSError:
            pass
        self.cleanup()

    # ---------------------------------------------------------- utilitarios
    def _write(self, path, data, mode=0o644):
        full = TARGET + path
        with open(full, "w") as f:
            f.write(data)
        os.chmod(full, mode)

    def _mount_api(self):
        for fs, src, dst in (("proc", "proc", "/proc"), ("sysfs", "sys", "/sys")):
            run(["mount", "-t", fs, src, TARGET + dst])
        run(["mount", "--rbind", "/dev", TARGET + "/dev"])
        run(["mount", "--make-rslave", TARGET + "/dev"])
        run(["mount", "--bind", "/run", TARGET + "/run"])
        if os.path.isdir("/sys/firmware/efi/efivars"):
            run(["mount", "-t", "efivarfs", "efivarfs",
                 TARGET + "/sys/firmware/efi/efivars"], check=False)

    def cleanup(self):
        run(["sync"], check=False)
        run(["umount", "-R", TARGET], check=False)
        if os.path.ismount(TARGET):
            run(["umount", "-Rl", TARGET], check=False)
        if self.luks_name:
            run(["cryptsetup", "close", self.luks_name], check=False)


def main_auto(path):
    if os.geteuid() != 0:
        emit(type="error", msg="O instalador precisa de privilégios de root.")
        return 1
    try:
        with open(path) as f:
            cfg = json.load(f)
    finally:
        if path.startswith(("/run/", "/tmp/")) and os.environ.get("MILIZOS_KEEP_CFG") != "1":
            try:
                os.unlink(path)
            except OSError:
                pass
    errs = validate(cfg)
    if errs:
        emit(type="error", msg="\n".join(errs))
        return 2
    open(LOG, "w").close()
    os.chmod(LOG, 0o600)
    safe = json.loads(json.dumps(cfg))
    safe["passphrase"] = "***" if safe.get("passphrase") else ""
    safe["root_password"] = "***" if safe.get("root_password") else None
    for k in ("password", "password_hash"):
        if safe.get("user", {}).get(k):
            safe["user"][k] = "***"
    if safe.get("root_password_hash"):
        safe["root_password_hash"] = "***"
    log("config: " + json.dumps(safe, ensure_ascii=False))
    inst = Installer(cfg)
    try:
        inst.install()
        return 0
    except InstallError as e:
        log(f"ERRO: {e}")
        emit(type="error", msg=str(e))
    except Exception as e:  # noqa
        import traceback
        log(traceback.format_exc())
        emit(type="error", msg=f"Erro inesperado: {e}")
    try:
        inst.cleanup()
    except Exception:
        pass
    return 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--auto":
        sys.exit(main_auto(sys.argv[2]))
    if len(sys.argv) == 2 and sys.argv[1] == "--list-disks":
        print(json.dumps(list_disks(), indent=1))
        sys.exit(0)
    print("uso: engine.py --auto config.json | --list-disks", file=sys.stderr)
    sys.exit(64)

#!/usr/bin/python3
# MilizOS Installer - interface grafica (GTK4 + libadwaita)
import json
import os
import re
import subprocess
import sys
import tempfile
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine  # noqa: E402

DEMO = "--demo" in sys.argv
LOGO = next((p for p in ("/usr/share/milizos/logo.svg", os.path.join(HERE, "logo.svg"))
             if os.path.exists(p)), None)

EN = {
    "Bem-vindo": "Welcome", "Região": "Region", "Disco": "Disk", "Usuário": "User",
    "Perfil": "Profile", "Resumo": "Summary", "Instalação": "Install", "Concluído": "Done",
    "Voltar": "Back", "Avançar": "Next", "Instalar agora": "Install now", "Sair": "Quit",
    "Bem-vindo ao MilizOS": "Welcome to MilizOS",
    "A distribuição para times de SOC, Blue Team e Redes.": "The distribution for SOC, Blue Team and Network teams.",
    "Idioma do sistema": "System language",
    "Teclado e fuso horário": "Keyboard and time zone",
    "Layout do teclado": "Keyboard layout", "Fuso horário": "Time zone",
    "Teste o teclado aqui": "Test your keyboard here",
    "Onde instalar": "Where to install",
    "O disco escolhido será totalmente apagado.": "The selected disk will be completely erased.",
    "Nenhum disco elegível encontrado (mínimo 8 GB).": "No eligible disk found (8 GB minimum).",
    "Sistema de arquivos": "File system",
    "btrfs habilita checkpoints e rollback do sistema": "btrfs enables system checkpoints and rollback",
    "Criptografar o disco (LUKS2)": "Encrypt the disk (LUKS2)",
    "Protege os dados se o equipamento for perdido ou roubado": "Protects data if the device is lost or stolen",
    "Senha de criptografia": "Encryption passphrase", "Confirmar senha": "Confirm password",
    "Quem vai usar": "Who will use it", "Nome completo": "Full name",
    "Nome de usuário": "Username", "Nome da máquina": "Hostname", "Senha": "Password",
    "Administrador (sudo)": "Administrator (sudo)",
    "Perfil de uso": "Usage profile",
    "Define os serviços ativos no primeiro boot. Todas as ferramentas ficam instaladas em qualquer perfil.":
        "Defines the services enabled on first boot. All tools are installed in every profile.",
    "Revise antes de instalar": "Review before installing",
    "Entendo que todos os dados do disco serão apagados": "I understand all data on the disk will be erased",
    "Instalando o MilizOS": "Installing MilizOS",
    "Instalação concluída": "Installation complete",
    "Remova a mídia de instalação e reinicie para começar a usar o MilizOS.":
        "Remove the installation media and restart to begin using MilizOS.",
    "Reiniciar agora": "Restart now", "Continuar no modo live": "Keep using live mode",
    "A instalação falhou": "Installation failed", "Detalhes": "Details",
    "As senhas não conferem": "Passwords do not match",
    "Idioma": "Language", "Teclado": "Keyboard", "Criptografia": "Encryption",
    "Ativada (LUKS2)": "Enabled (LUKS2)", "Desativada": "Disabled", "Máquina": "Hostname",
    "Selecione um disco": "Select a disk",
    "Preencha usuário e senha": "Fill in user and password",
    "A senha de criptografia precisa de ao menos 8 caracteres": "The encryption passphrase needs at least 8 characters",
}
LANG = ["pt_BR.UTF-8"]


def _(s):
    if LANG[0].startswith("en"):
        return EN.get(s, s)
    return s


CSS = """
window { background: #070B16; color: #E6ECFA; }
.sidebar { background: linear-gradient(180deg, #0D1428, #070B16); border-right: 1px solid #1B2744; }
.brand { font-family: Inter, 'Noto Sans', sans-serif; font-weight: 800; font-size: 22px; letter-spacing: -0.5px; }
.brand-accent { color: #00F0C8; }
.tagline { font-family: 'JetBrains Mono', monospace; font-size: 9px; letter-spacing: 2px; color: #62708F; }
.step { padding: 9px 14px; border-radius: 9px; color: #62708F; font-weight: 600; }
.step.active { background: alpha(#00F0C8, 0.10); color: #00F0C8; }
.step.done { color: #9FB0D0; }
.stepnum { font-family: 'JetBrains Mono', monospace; font-size: 11px; min-width: 22px; }
.page-title { font-family: Inter, 'Noto Sans', sans-serif; font-size: 28px; font-weight: 800; letter-spacing: -0.6px; }
.page-sub { color: #8D9BB9; font-size: 14px; }
.hero { font-family: Inter, 'Noto Sans', sans-serif; font-size: 38px; font-weight: 800; letter-spacing: -1px; }
.footer { border-top: 1px solid #1B2744; background: #0A1020; padding: 12px 22px; }
.version { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #445172; }
button.suggested-action { background: linear-gradient(135deg, #00D9B5, #2D7FF9); color: #04101C; font-weight: 700; }
button.suggested-action:disabled { background: #1B2744; color: #54617F; }
button.destructive-action { background: linear-gradient(135deg, #FF5C7A, #FF8A3D); color: #1A0508; font-weight: 800; }
button.destructive-action:disabled { background: #1B2744; color: #54617F; }
.card { background: #0E1730; border: 1px solid #1B2744; border-radius: 14px; padding: 16px 18px; }
.card.selected { border-color: #00F0C8; background: alpha(#00F0C8, 0.07); }
.card-title { font-weight: 700; font-size: 16px; }
.card-desc { color: #8D9BB9; }
.warn { background: alpha(#FFB020, 0.10); border: 1px solid alpha(#FFB020, 0.45); color: #FFCB6B; border-radius: 10px; padding: 10px 14px; }
.err { color: #FF6B81; font-weight: 600; }
.mono { font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.steplabel { font-size: 16px; font-weight: 600; }
.tip { color: #9FB0D0; font-size: 14px; }
progressbar > trough { min-height: 10px; border-radius: 6px; background: #121C38; }
progressbar > trough > progress { min-height: 10px; border-radius: 6px; background: linear-gradient(90deg, #00F0C8, #2D7FF9); }
preferencesgroup row, list.boxed-list { background: #0E1730; }
textview, textview text { background: #050810; color: #9FB0D0; }
"""

TIPS = [
    ("Captura e análise", "Wireshark, tshark, tcpdump, Zeek e Suricata prontos para uso — o usuário já entra no grupo de captura."),
    ("netos", "Use o comando “netos” no terminal: catálogo de ferramentas, estado da rede, captura em anel e triagem de incidentes."),
    ("Menu por disciplina", "As ferramentas ficam organizadas no menu por função: Detecção, Tráfego, DFIR, Hardening, Roteamento e Automação."),
    ("Base Red Hat", "Base Fedora/Red Hat com SELinux em modo enforcing, firewalld e dnf. Seus playbooks e RPMs funcionam aqui."),
    ("Sensor em minutos", "No perfil Sensor, “netos sensor” aponta o Suricata para a interface de espelhamento e liga os logs EVE JSON."),
    ("Automação de rede", "Ansible, Netmiko, NAPALM, Nornir e Scapy já instalados para automatizar switches, roteadores e firewalls."),
]


def timezones():
    zs = set()
    for tab in ("/usr/share/zoneinfo/zone1970.tab", "/usr/share/zoneinfo/zone.tab"):
        try:
            for line in open(tab):
                if not line.startswith("#"):
                    f = line.rstrip("\n").split("\t")
                    if len(f) >= 3:
                        zs.add(f[2])
        except OSError:
            pass
    zs.add("UTC")
    return sorted(zs)


class Card(Gtk.ToggleButton):
    def __init__(self, title, desc, icon=None):
        super().__init__()
        self.add_css_class("flat")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        box.add_css_class("card")
        self.box = box
        if icon:
            im = Gtk.Image.new_from_icon_name(icon)
            im.set_pixel_size(36)
            box.append(im)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        t = Gtk.Label(label=title, xalign=0)
        t.add_css_class("card-title")
        d = Gtk.Label(label=desc, xalign=0, wrap=True)
        d.add_css_class("card-desc")
        v.append(t)
        v.append(d)
        box.append(v)
        self.check = Gtk.Image.new_from_icon_name("object-select-symbolic")
        self.check.set_opacity(0)
        box.append(self.check)
        self.set_child(box)
        self.connect("toggled", self._tog)

    def _tog(self, *_):
        on = self.get_active()
        self.check.set_opacity(1 if on else 0)
        (self.box.add_css_class if on else self.box.remove_css_class)("selected")


class Installer(Adw.ApplicationWindow):
    PAGES = ["welcome", "region", "disk", "user", "profile", "summary", "install", "done"]
    TITLES = ["Bem-vindo", "Região", "Disco", "Usuário", "Perfil", "Resumo", "Instalação", "Concluído"]

    def __init__(self, app):
        super().__init__(application=app, title="MilizOS Installer")
        self.set_default_size(1000, 680)
        self.idx = 0
        self.disks = []
        self.proc = None
        self.tip_i = 0
        self.log_lines = []

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        handle = Gtk.WindowHandle(child=root)
        self.set_content(handle)

        # ---- barra lateral
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        side.add_css_class("sidebar")
        side.set_size_request(250, -1)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                       margin_top=24, margin_start=20, margin_end=16, margin_bottom=22)
        if LOGO:
            pic = Gtk.Image.new_from_file(LOGO)
            pic.set_pixel_size(46)
            head.append(pic)
        hv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        b = Gtk.Label(xalign=0, use_markup=True,
                      label='Miliz<span foreground="#00F0C8">OS</span>')
        b.add_css_class("brand")
        tg = Gtk.Label(label="INSTALLER", xalign=0)
        tg.add_css_class("tagline")
        hv.append(b)
        hv.append(tg)
        head.append(hv)
        side.append(head)
        self.step_rows = []
        for i, t in enumerate(self.TITLES):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          margin_start=12, margin_end=12)
            row.add_css_class("step")
            n = Gtk.Label(label=f"{i + 1:02d}")
            n.add_css_class("stepnum")
            l = Gtk.Label(label=t, xalign=0)
            row.append(n)
            row.append(l)
            side.append(row)
            self.step_rows.append((row, n, l))
        side.append(Gtk.Box(vexpand=True))
        ver = Gtk.Label(label=self._version(), xalign=0, margin_start=22, margin_bottom=16)
        ver.add_css_class("version")
        side.append(ver)
        root.append(side)

        # ---- conteudo
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                               transition_duration=220, vexpand=True)
        right.append(self.stack)
        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        foot.add_css_class("footer")
        self.btn_quit = Gtk.Button(label=_("Sair"))
        self.btn_quit.connect("clicked", lambda *_: self.close())
        self.err = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.err.add_css_class("err")
        self.btn_back = Gtk.Button(label=_("Voltar"))
        self.btn_back.connect("clicked", lambda *_: self.go(self.idx - 1))
        self.btn_next = Gtk.Button(label=_("Avançar"))
        self.btn_next.add_css_class("suggested-action")
        self.btn_next.connect("clicked", self.on_next)
        for w in (self.btn_quit, self.err, self.btn_back, self.btn_next):
            foot.append(w)
        self.foot = foot
        right.append(foot)
        root.append(right)

        self.build_pages()
        self.go(0)
        self.connect("close-request", self.on_close)

    @staticmethod
    def _version():
        try:
            for l in open("/etc/os-release"):
                if l.startswith("PRETTY_NAME=") and "MilizOS" in l:
                    return l.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return "MilizOS"

    # ------------------------------------------------------------ paginas
    def page(self, name, title, sub=None):
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=640, margin_top=34, margin_bottom=24,
                          margin_start=30, margin_end=30)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        if title:
            t = Gtk.Label(label=_(title), xalign=0)
            t.add_css_class("page-title")
            box.append(t)
        if sub:
            s = Gtk.Label(label=_(sub), xalign=0, wrap=True)
            s.add_css_class("page-sub")
            box.append(s)
        clamp.set_child(box)
        sc.set_child(clamp)
        old = self.stack.get_child_by_name(name)
        if old:
            self.stack.remove(old)
        self.stack.add_named(sc, name)
        return box

    def build_pages(self):
        self.build_welcome()
        self.build_region()
        self.build_disk()
        self.build_user()
        self.build_profile()
        self.page("summary", "Revise antes de instalar")
        self.build_install()
        self.page("done", None)

    def build_welcome(self):
        box = self.page("welcome", None)
        box.set_spacing(14)
        if LOGO:
            im = Gtk.Image.new_from_file(LOGO)
            im.set_pixel_size(150)
            im.set_margin_top(10)
            box.append(im)
        self.w_title = Gtk.Label(label=_("Bem-vindo ao MilizOS"))
        self.w_title.add_css_class("hero")
        self.w_sub = Gtk.Label(label=_("A distribuição para times de SOC, Blue Team e Redes."))
        self.w_sub.add_css_class("page-sub")
        box.append(self.w_title)
        box.append(self.w_sub)
        cred = Gtk.Label(use_markup=True, label='<small>Criado por <a href="https://www.linkedin.com/in/danielpereira-linux/">'
                                               'Daniel Pereira da Silva</a></small>')
        cred.add_css_class("dim-label")
        box.append(cred)
        grp = Adw.PreferencesGroup(margin_top=18)
        self.lang_row = Adw.ComboRow(title=_("Idioma do sistema"))
        self.lang_row.set_model(Gtk.StringList.new(list(engine.LOCALES.values())))
        self.lang_row.connect("notify::selected", self.on_lang)
        grp.add(self.lang_row)
        box.append(grp)

    def on_lang(self, row, _p):
        new = list(engine.LOCALES)[row.get_selected()]
        if new == LANG[0]:
            return
        LANG[0] = new
        self.retranslate()

    def retranslate(self):
        self.w_title.set_label(_("Bem-vindo ao MilizOS"))
        self.w_sub.set_label(_("A distribuição para times de SOC, Blue Team e Redes."))
        self.lang_row.set_title(_("Idioma do sistema"))
        for (row, n, l), t in zip(self.step_rows, self.TITLES):
            l.set_label(_(t))
        self.btn_quit.set_label(_("Sair"))
        self.btn_back.set_label(_("Voltar"))
        keep = (self.kb_row.get_selected(), self.tz_row.get_selected())
        self.build_region()
        self.kb_row.set_selected(keep[0])
        self.tz_row.set_selected(keep[1])
        self.build_disk()
        self.build_user()
        self.build_profile()
        self.build_install()
        self.stack.set_visible_child_name(self.PAGES[self.idx])
        self.go(self.idx)

    def build_region(self):
        box = self.page("region", "Teclado e fuso horário")
        grp = Adw.PreferencesGroup()
        self.kb_row = Adw.ComboRow(title=_("Layout do teclado"))
        self.kb_row.set_model(Gtk.StringList.new([k[1] for k in engine.KEYMAPS]))
        self.kb_row.connect("notify::selected", self.on_kb)
        grp.add(self.kb_row)
        self.tzs = timezones()
        self.tz_row = Adw.ComboRow(title=_("Fuso horário"))
        self.tz_row.set_model(Gtk.StringList.new(self.tzs))
        self.tz_row.set_enable_search(True)
        self.tz_row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        if "America/Sao_Paulo" in self.tzs:
            self.tz_row.set_selected(self.tzs.index("America/Sao_Paulo"))
        grp.add(self.tz_row)
        box.append(grp)
        grp2 = Adw.PreferencesGroup()
        grp2.add(Adw.EntryRow(title=_("Teste o teclado aqui")))
        box.append(grp2)

    def on_kb(self, row, _p):
        km = engine.KEYMAPS[row.get_selected()]
        cmd = ["setxkbmap", km[2]] + (["-variant", km[3]] if km[3] else [])
        try:
            subprocess.run(cmd, timeout=5, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            pass

    def build_disk(self):
        box = self.page("disk", "Onde instalar")
        warn = Gtk.Label(label="⚠  " + _("O disco escolhido será totalmente apagado."), xalign=0)
        warn.add_css_class("warn")
        box.append(warn)
        self.disk_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self.disk_box)
        self.disk_cards = []
        self.disks = self.fake_disks() if DEMO else engine.list_disks()
        if not self.disks:
            l = Gtk.Label(label=_("Nenhum disco elegível encontrado (mínimo 8 GB)."), xalign=0)
            l.add_css_class("err")
            self.disk_box.append(l)
        first = None
        for d in self.disks:
            kind = {"nvme": "NVMe", "usb": "USB", "sata": "SATA", "virtio": "VirtIO"}.get(d["tran"], d["tran"].upper())
            desc = f"{d['path']}  ·  {engine.human(d['size'])}" + (f"  ·  {kind}" if kind else "")
            if d["parts"]:
                desc += f"  ·  {d['parts']} partição(ões) existente(s)"
            c = Card(d["model"], desc, "drive-harddisk-symbolic")
            if first is None:
                first = c
            else:
                c.set_group(first)
            self.disk_cards.append(c)
            self.disk_box.append(c)
        if first is not None and len(self.disks) == 1:
            first.set_active(True)
        grp = Adw.PreferencesGroup()
        self.fs_row = Adw.ComboRow(title=_("Sistema de arquivos"),
                                     subtitle=_("btrfs habilita checkpoints e rollback do sistema"))
        self.fs_row.set_model(Gtk.StringList.new([
            "Btrfs — snapshots e compressão (recomendado)", "XFS — padrão Red Hat Enterprise", "ext4 — clássico"]))
        grp.add(self.fs_row)
        self.enc_row = Adw.SwitchRow(title=_("Criptografar o disco (LUKS2)"),
                                     subtitle=_("Protege os dados se o equipamento for perdido ou roubado"))
        grp.add(self.enc_row)
        self.enc_pw = Adw.PasswordEntryRow(title=_("Senha de criptografia"))
        self.enc_pw2 = Adw.PasswordEntryRow(title=_("Confirmar senha"))
        for r in (self.enc_pw, self.enc_pw2):
            r.set_visible(False)
            grp.add(r)
        self.enc_row.connect("notify::active", lambda *_: [
            r.set_visible(self.enc_row.get_active()) for r in (self.enc_pw, self.enc_pw2)])
        box.append(grp)

    @staticmethod
    def fake_disks():
        return [{"path": "/dev/nvme0n1", "size": 512 * 1000 ** 3, "model": "Samsung SSD 990 PRO",
                 "tran": "nvme", "removable": False, "parts": 3},
                {"path": "/dev/sda", "size": 2000 * 1000 ** 3, "model": "WDC WD20EZAZ",
                 "tran": "sata", "removable": False, "parts": 0}]

    def build_user(self):
        box = self.page("user", "Quem vai usar")
        grp = Adw.PreferencesGroup()
        self.full = Adw.EntryRow(title=_("Nome completo"))
        self.uname = Adw.EntryRow(title=_("Nome de usuário"))
        self.host = Adw.EntryRow(title=_("Nome da máquina"))
        self.host.set_text("milizos")
        self.uname_touched = False
        self.full.connect("changed", self.on_full)
        self.uname.connect("changed", self.on_uname)
        for r in (self.full, self.uname, self.host):
            grp.add(r)
        box.append(grp)
        grp2 = Adw.PreferencesGroup()
        self.pw = Adw.PasswordEntryRow(title=_("Senha"))
        self.pw2 = Adw.PasswordEntryRow(title=_("Confirmar senha"))
        self.pw.connect("changed", self.on_pw)
        self.strength = Gtk.LevelBar(min_value=0, max_value=4, mode=Gtk.LevelBarMode.DISCRETE,
                                     margin_top=8)
        self.admin = Adw.SwitchRow(title=_("Administrador (sudo)"))
        self.admin.set_active(True)
        for r in (self.pw, self.pw2, self.admin):
            grp2.add(r)
        box.append(grp2)
        box.append(self.strength)

    def on_full(self, row):
        if self.uname_touched:
            return
        import unicodedata
        s = unicodedata.normalize("NFKD", row.get_text()).encode("ascii", "ignore").decode().lower()
        first = re.sub(r"[^a-z0-9]", "", s.split(" ")[0]) if s.strip() else ""
        self._auto = True
        self.uname.set_text(first[:31])
        self._auto = False

    def on_uname(self, row):
        if not getattr(self, "_auto", False):
            self.uname_touched = bool(row.get_text())

    def on_pw(self, row):
        p = row.get_text()
        score = sum([len(p) >= 8, len(p) >= 12, bool(re.search(r"\d", p)) and bool(re.search(r"[a-zA-Z]", p)),
                     bool(re.search(r"[^A-Za-z0-9]", p))])
        self.strength.set_value(score if p else 0)

    def build_profile(self):
        box = self.page("profile", "Perfil de uso",
                        "Define os serviços ativos no primeiro boot. Todas as ferramentas ficam instaladas em qualquer perfil.")
        icons = {"soc": "security-high-symbolic", "neteng": "network-wired-symbolic",
                 "sensor": "network-server-symbolic"}
        prev = getattr(self, "prof_cards", None)
        active = next((k for k, c in prev.items() if c.get_active()), "soc") if prev else "soc"
        self.prof_cards = {}
        first = None
        for key, p in engine.PROFILES.items():
            c = Card(p["label"], p["desc"], icons[key])
            if first is None:
                first = c
            else:
                c.set_group(first)
            self.prof_cards[key] = c
            box.append(c)
        self.prof_cards[active].set_active(True)

    def build_summary(self):
        box = self.page("summary", "Revise antes de instalar")
        c = self.collect()
        d = next(x for x in self.disks if x["path"] == c["disk"])
        km = next(k for k in engine.KEYMAPS if k[0] == c["keymap"])
        rows = [
            (_("Disco"), f"{d['model']} — {d['path']} ({engine.human(d['size'])})"),
            (_("Sistema de arquivos"), c["filesystem"]),
            (_("Criptografia"), _("Ativada (LUKS2)") if c["encrypt"] else _("Desativada")),
            (_("Perfil"), engine.PROFILES[c["profile"]]["label"]),
            (_("Usuário"), c["user"]["name"] + (" (sudo)" if c["user"]["admin"] else "")),
            (_("Máquina"), c["hostname"]),
            (_("Idioma"), engine.LOCALES[c["locale"]]),
            (_("Teclado"), km[1]),
            (_("Fuso horário"), c["timezone"]),
        ]
        grp = Adw.PreferencesGroup()
        for k, v in rows:
            r = Adw.ActionRow(title=k)
            lab = Gtk.Label(label=v, xalign=1, ellipsize=Pango.EllipsizeMode.MIDDLE)
            lab.add_css_class("dim-label")
            r.add_suffix(lab)
            grp.add(r)
        box.append(grp)
        self.confirm = Gtk.CheckButton(label=_("Entendo que todos os dados do disco serão apagados"))
        self.confirm.connect("toggled", lambda b: self.btn_next.set_sensitive(b.get_active()))
        box.append(self.confirm)

    def build_install(self):
        box = self.page("install", "Instalando o MilizOS")
        self.step_label = Gtk.Label(label="…", xalign=0)
        self.step_label.add_css_class("steplabel")
        self.bar = Gtk.ProgressBar(show_text=False)
        self.pct = Gtk.Label(label="0%", xalign=1)
        self.pct.add_css_class("mono")
        box.append(self.step_label)
        box.append(self.bar)
        box.append(self.pct)
        tip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=16)
        tip.add_css_class("card")
        self.tip_title = Gtk.Label(xalign=0)
        self.tip_title.add_css_class("card-title")
        self.tip_text = Gtk.Label(xalign=0, wrap=True)
        self.tip_text.add_css_class("tip")
        tip.append(self.tip_title)
        tip.append(self.tip_text)
        box.append(tip)
        self.show_tip()
        exp = Gtk.Expander(label=_("Detalhes"))
        self.logview = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                    wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.logview.add_css_class("mono")
        sw = Gtk.ScrolledWindow(min_content_height=130, child=self.logview)
        exp.set_child(sw)
        box.append(exp)

    def show_tip(self):
        t = TIPS[self.tip_i % len(TIPS)]
        self.tip_title.set_label(t[0])
        self.tip_text.set_label(t[1])
        self.tip_i += 1
        return True

    def build_done(self, ok=True, msg=""):
        box = self.page("done", None)
        box.set_spacing(14)
        box.set_valign(Gtk.Align.CENTER)
        if ok:
            if LOGO:
                im = Gtk.Image.new_from_file(LOGO)
                im.set_pixel_size(130)
                im.set_margin_top(30)
                box.append(im)
            t = Gtk.Label(label=_("Instalação concluída"))
            t.add_css_class("hero")
            s = Gtk.Label(label=_("Remova a mídia de instalação e reinicie para começar a usar o MilizOS."),
                          wrap=True, justify=Gtk.Justification.CENTER)
            s.add_css_class("page-sub")
            box.append(t)
            box.append(s)
            hb = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=18)
            b1 = Gtk.Button(label=_("Continuar no modo live"))
            b1.connect("clicked", lambda *_: self.close())
            b2 = Gtk.Button(label=_("Reiniciar agora"))
            b2.add_css_class("suggested-action")
            b2.connect("clicked", self.reboot)
            hb.append(b1)
            hb.append(b2)
            box.append(hb)
        else:
            im = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
            im.set_pixel_size(72)
            im.set_margin_top(20)
            box.append(im)
            t = Gtk.Label(label=_("A instalação falhou"))
            t.add_css_class("hero")
            box.append(t)
            m = Gtk.Label(label=msg, wrap=True, selectable=True, xalign=0)
            m.add_css_class("err")
            box.append(m)
            tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            tv.add_css_class("mono")
            tv.get_buffer().set_text("\n".join(self.log_lines[-200:]) +
                                     "\n\nLog completo: /var/log/milizos-install.log")
            box.append(Gtk.ScrolledWindow(min_content_height=160, child=tv))
            b = Gtk.Button(label=_("Sair"), halign=Gtk.Align.CENTER)
            b.connect("clicked", lambda *_: self.close())
            box.append(b)

    def reboot(self, *_a):
        for cmd in (["systemctl", "reboot"], ["sudo", "-n", "systemctl", "reboot"]):
            try:
                if subprocess.run(cmd).returncode == 0:
                    return
            except OSError:
                pass

    # ------------------------------------------------------------ navegacao
    def go(self, i):
        self.err.set_label("")
        self.idx = i
        name = self.PAGES[i]
        if name == "summary":
            self.build_summary()
        self.stack.set_visible_child_name(name)
        for j, (row, n, l) in enumerate(self.step_rows):
            row.remove_css_class("active")
            row.remove_css_class("done")
            n.set_label("✓" if j < i else f"{j + 1:02d}")
            if j == i:
                row.add_css_class("active")
            elif j < i:
                row.add_css_class("done")
        self.btn_back.set_visible(0 < i < 6)
        self.btn_quit.set_visible(i < 6)
        self.foot.set_visible(i < 6)
        self.btn_next.remove_css_class("destructive-action")
        self.btn_next.add_css_class("suggested-action")
        self.btn_next.set_sensitive(True)
        self.btn_next.set_label(_("Avançar"))
        if name == "summary":
            self.btn_next.set_label(_("Instalar agora"))
            self.btn_next.remove_css_class("suggested-action")
            self.btn_next.add_css_class("destructive-action")
            self.btn_next.set_sensitive(False)

    def collect(self):
        di = next((i for i, c in enumerate(self.disk_cards) if c.get_active()), None)
        km = engine.KEYMAPS[self.kb_row.get_selected()]
        return {
            "disk": self.disks[di]["path"] if di is not None else "",
            "filesystem": ("btrfs", "xfs", "ext4")[self.fs_row.get_selected()],
            "encrypt": self.enc_row.get_active(),
            "passphrase": self.enc_pw.get_text() if self.enc_row.get_active() else "",
            "hostname": self.host.get_text().strip(),
            "locale": LANG[0],
            "keymap": km[0],
            "timezone": self.tzs[self.tz_row.get_selected()],
            "user": {"name": self.uname.get_text().strip(), "fullname": self.full.get_text().strip(),
                     "password": self.pw.get_text(), "admin": self.admin.get_active()},
            "root_password": None,
            "profile": next(k for k, c in self.prof_cards.items() if c.get_active()),
        }

    def check_page(self):
        name = self.PAGES[self.idx]
        c = self.collect()
        if name == "disk":
            if not c["disk"]:
                return _("Selecione um disco")
            if c["encrypt"]:
                if len(c["passphrase"]) < 8:
                    return _("A senha de criptografia precisa de ao menos 8 caracteres")
                if c["passphrase"] != self.enc_pw2.get_text():
                    return _("As senhas não conferem")
        if name == "user":
            if not c["user"]["name"] or not c["user"]["password"]:
                return _("Preencha usuário e senha")
            if c["user"]["password"] != self.pw2.get_text():
                return _("As senhas não conferem")
            errs = [e for e in engine.validate(c) if "Disco" not in e] if not DEMO else []
            if errs:
                return errs[0]
        return None

    def on_next(self, *_a):
        e = self.check_page()
        if e:
            self.err.set_label(e)
            return
        if self.PAGES[self.idx] == "summary":
            self.start_install()
        else:
            self.go(self.idx + 1)

    def on_close(self, *_a):
        return self.PAGES[self.idx] == "install"  # nao fecha durante a instalacao

    # ------------------------------------------------------------ instalacao
    def start_install(self):
        cfg = self.collect()
        self.go(6)
        self.tip_timer = GLib.timeout_add_seconds(9, self.show_tip)
        if DEMO:
            self._demo = 0.0
            GLib.timeout_add(60, self.demo_tick)
            return
        rundir = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
        fd, path = tempfile.mkstemp(prefix="milizos-install-", suffix=".json", dir=rundir)
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f)
        cmd = [sys.executable, os.path.join(HERE, "engine.py"), "--auto", path]
        if os.geteuid() != 0:
            cmd = ["sudo", "-n"] + cmd
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self.reader, daemon=True).start()

    def demo_tick(self):
        self._demo += 0.004
        i = min(int(self._demo * len(engine.STEPS)), len(engine.STEPS) - 1)
        self.on_event({"type": "step", "label": engine.STEPS[i][1], "index": i + 1, "total": len(engine.STEPS)})
        self.on_event({"type": "progress", "fraction": min(self._demo, 1)})
        if self._demo >= 1:
            self.on_event({"type": "done"})
            return False
        return True

    def reader(self):
        got_end = False
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                ev = {"type": "log", "msg": line}
            if ev.get("type") in ("done", "error"):
                got_end = True
            GLib.idle_add(self.on_event, ev)
        rc = self.proc.wait()
        if not got_end:
            GLib.idle_add(self.on_event, {"type": "error",
                                          "msg": f"O instalador terminou inesperadamente (código {rc})."})

    def append_log(self, s):
        self.log_lines.append(s)
        buf = self.logview.get_buffer()
        buf.insert(buf.get_end_iter(), s + "\n")

    def on_event(self, ev):
        t = ev.get("type")
        if t == "step":
            s = f"[{ev['index']}/{ev['total']}] {ev['label']}"
            self.step_label.set_label(ev["label"] + "…")
            self.append_log(s)
        elif t == "progress":
            self.bar.set_fraction(ev["fraction"])
            self.pct.set_label(f"{ev['fraction'] * 100:.0f}%")
        elif t == "log":
            self.append_log(ev.get("msg", ""))
        elif t == "done":
            self.build_done(True)
            self.go(7)
        elif t == "error":
            self.append_log("ERRO: " + ev.get("msg", ""))
            self.build_done(False, ev.get("msg", ""))
            self.go(7)
        return False


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.milizos.Installer")

    def do_activate(self):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = self.props.active_window or Installer(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run([sys.argv[0]]))

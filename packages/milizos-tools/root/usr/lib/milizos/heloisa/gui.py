#!/usr/bin/python3
# Heloisa - a maquina do tempo do MilizOS (GTK4/libadwaita).
# A interface roda como o usuario; um unico processo auxiliar (heloisa-engine serve) roda como
# administrador via polkit e responde requisicoes JSON, uma por linha.
import datetime
import json
import os
import subprocess
import sys
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402

ENGINE = os.environ.get("HELOISA_ENGINE", "/usr/libexec/milizos/heloisa-engine")
LOGO = "/usr/share/milizos/logo.svg"
KIND_ICON = {"install": "starred-symbolic", "manual": "bookmark-new-symbolic", "dnf": "package-x-generic-symbolic",
             "hora": "preferences-system-time-symbolic", "boot": "system-shutdown-symbolic",
             "antes": "edit-undo-symbolic"}
CSS = """
.hel-hero { font-size: 22px; font-weight: 800; }
.hel-dim { opacity: .65; }
.hel-mono { font-family: 'JetBrains Mono', monospace; font-size: 10.5pt; }
.hel-pill { padding: 2px 9px; border-radius: 99px; background: alpha(@accent_bg_color, .18); font-size: 9pt; font-weight: 600; }
.hel-same { opacity: .45; }
.hel-warn { background: alpha(#f5a623, .25); }
.hel-bad { background: alpha(#e5484d, .28); }
.hel-bar { padding: 8px 14px; background: alpha(@accent_bg_color, .16); }
.hel-bar.alert { background: alpha(#e5484d, .22); }
"""
STATE_DIR = "/.heloisa/.state"


def when(ts):
    try:
        t = datetime.datetime.strptime(ts[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return ts
    d = (datetime.date.today() - t.date()).days
    hm = t.strftime("%H:%M")
    if d == 0:
        return f"hoje, {hm}"
    if d == 1:
        return f"ontem, {hm}"
    meses = "jan fev mar abr mai jun jul ago set out nov dez".split()
    return f"{t.day} {meses[t.month - 1]} {t.year if t.year != datetime.date.today().year else ''} {hm}".replace("  ", " ")


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u in ("B", "KB") else f"{n:.1f} {u}"
        n /= 1024


class Engine:
    """Cliente do processo auxiliar privilegiado."""

    def __init__(self, on_dead):
        self.p = None
        self.n = 0
        self.lock = threading.Lock()
        self.on_dead = on_dead

    def start(self):
        cmd = [ENGINE, "serve"] if os.geteuid() == 0 or "HELOISA_ENGINE" in os.environ else ["pkexec", ENGINE, "serve"]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def call(self, op, cb, **args):
        def work():
            with self.lock:
                try:
                    if self.p is None or self.p.poll() is not None:
                        self.start()
                    self.n += 1
                    self.p.stdin.write(json.dumps(dict(args, op=op, n=self.n)) + "\n")
                    self.p.stdin.flush()
                    line = self.p.stdout.readline()
                    if not line:
                        raise OSError("sem resposta")
                    res = json.loads(line)
                except (OSError, ValueError):
                    self.p = None
                    GLib.idle_add(self.on_dead)
                    return
            GLib.idle_add(cb, res.get("ok"), res.get("result") if res.get("ok") else res.get("error"))
        threading.Thread(target=work, daemon=True).start()


class Window(Adw.ApplicationWindow):
    def __init__(self, app, start_path=None):
        super().__init__(application=app, title="Heloisa", default_width=1080, default_height=720)
        self.set_icon_name("heloisa")
        self.eng = Engine(self.on_dead)
        self.points = []
        self.view_id = 0                      # 0 = agora; N = navegando dentro do ponto N
        self.cwd = start_path or os.path.expanduser("~")
        self.sel = None
        if start_path and not os.path.isdir(start_path):
            self.cwd, self.sel = os.path.dirname(start_path), start_path

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        tv = Adw.ToolbarView()
        self.toasts.set_child(tv)
        hb = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        sw = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        hb.set_title_widget(sw)
        logo = Gtk.Image.new_from_file(LOGO) if os.path.exists(LOGO) else Gtk.Image.new_from_icon_name("heloisa")
        logo.set_pixel_size(28)
        hb.pack_start(logo)
        self.btn_new = Gtk.Button(label="Criar ponto agora", css_classes=["suggested-action"])
        self.btn_new.connect("clicked", self.on_create)
        hb.pack_end(self.btn_new)
        mm = Gio.Menu()
        mm.append("Ramos da máquina…", "win.branches")
        mm.append("Enviar pontos para outro disco…", "win.push")
        mm.append("Procurar o que quebrou…", "win.bisect")
        self.btn_menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=mm, tooltip_text="Mais")
        hb.pack_end(self.btn_menu)
        tv.add_top_bar(hb)
        self.banner = Adw.Banner(title="Volta no tempo aplicada. Reinicie o computador para concluir.",
                                 button_label="Reiniciar agora")
        self.banner.connect("button-clicked", lambda *_: self.eng.call("reboot", lambda *_a: None))
        tv.add_top_bar(self.banner)
        self.bars = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tv.add_top_bar(self.bars)
        self.st = {}

        self.root = Gtk.Stack()
        tv.set_content(self.root)
        self.status = Adw.StatusPage(icon_name="heloisa", title="Heloisa",
                                     description="Abrindo a linha do tempo…")
        self.root.add_named(self.status, "status")
        self.root.add_named(self.stack, "main")
        self.stack.add_titled_with_icon(self.build_timeline(), "time", "Linha do tempo", "document-open-recent-symbolic")
        self.stack.add_titled_with_icon(self.build_anything(), "any", "Qualquer coisa", "folder-symbolic")
        if start_path:
            self.stack.set_visible_child_name("any")
        self.rescue_box = None
        self.refresh()

    # ------------------------------------------------------------ infraestrutura
    def toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=msg, timeout=4))

    def fail(self, msg):
        d = Adw.AlertDialog(heading="Não deu certo", body=str(msg))
        d.add_response("ok", "Entendi")
        d.present(self)

    def on_dead(self):
        self.show_status("dialog-password-symbolic", "Permissão necessária",
                         "A Heloisa lê e restaura versões de qualquer arquivo do sistema; por isso pede a "
                         "senha de administrador.", "Tentar de novo", self.refresh)

    def show_status(self, icon, title, desc, button=None, cb=None):
        self.status.set_icon_name(icon)
        self.status.set_title(title)
        self.status.set_description(desc)
        if button:
            b = Gtk.Button(label=button, halign=Gtk.Align.CENTER, css_classes=["pill", "suggested-action"])
            b.connect("clicked", lambda *_: cb())
            self.status.set_child(b)
        else:
            self.status.set_child(None)
        self.root.set_visible_child_name("status")
        self.btn_new.set_sensitive(False)
        self.btn_menu.set_sensitive(False)

    def refresh(self, *_a):
        self.eng.call("status", self.on_status)

    def on_status(self, ok, st):
        if not ok:
            return self.fail(st)
        if st["live"]:
            return self.show_rescue()
        if not st["supported"]:
            return self.show_status("drive-harddisk-symbolic", "Sem linha do tempo neste sistema",
                                    "A Heloisa precisa do MilizOS instalado em btrfs, que é o padrão do instalador.")
        self.points = st["points"]
        self.st = st
        bis = st.get("bisect") or {}
        self.banner.set_revealed(st["pending"] and not bis.get("active"))
        self.btn_new.set_sensitive(not st["pending"] and not bis.get("active"))
        self.fill_bars(st)
        self.root.set_visible_child_name("main")
        self.btn_menu.set_sensitive(True)
        self.fill_timeline(st)
        self.fill_views()
        self.load_dir()

    # ------------------------------------------------------------ linha do tempo
    def build_timeline(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sc = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp(maximum_size=860, margin_top=18, margin_bottom=24, margin_start=12, margin_end=12)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.tl_head = Gtk.Label(xalign=0, wrap=True, css_classes=["hel-dim"])
        v.append(Gtk.Label(label="Cada ponto é a máquina inteira, congelada.", xalign=0, css_classes=["hel-hero"]))
        v.append(self.tl_head)
        self.tl_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        v.append(self.tl_list)
        clamp.set_child(v)
        sc.set_child(clamp)
        box.append(sc)
        return box

    def fill_timeline(self, st):
        self.tl_list.remove_all()
        u = st.get("usage")
        txt = ("Sistema, arquivos pessoais e logs. Pontos são criados sozinhos de hora em hora, a cada "
               "inicialização e antes de qualquer instalação de pacotes. Voltar nunca apaga a história: "
               "o estado atual vira um ponto antes. Um ponto só ocupa espaço pelo que mudou depois dele; "
               "se o disco encher, os automáticos mais antigos saem sozinhos.")
        if u:
            txt += f"\n{len(self.points)} pontos · {human(u['free'])} livres de {human(u['size'])}"
        self.tl_head.set_label(txt)
        if not self.points:
            self.tl_list.append(Adw.ActionRow(title="Ainda não há pontos", subtitle="Crie o primeiro com o botão acima."))
        for p in reversed(self.points):
            sub = f"#{p['id']} · {when(p['time'])}" + (" · no menu de boot" if p["bootable"] else "")
            if p.get("summary"):
                sub += "\n" + GLib.markup_escape_text(p["summary"])
            row = Adw.ActionRow(title=GLib.markup_escape_text(p["desc"]), subtitle=sub, subtitle_lines=3)
            row.add_prefix(Gtk.Image.new_from_icon_name(KIND_ICON.get(p["kind"], "bookmark-new-symbolic")))
            many = len(st.get("branches") or []) > 1
            for txt, on, cls in ((f"ramo {p.get('branch')}", many, []), ("enviado", bool(p.get("pushed")), []),
                                 ("selado", p.get("sealed"), ["hel-warn"]), ("protegido", p.get("protected"), ["hel-warn"])):
                if on:
                    row.add_suffix(Gtk.Label(label=txt, css_classes=["hel-pill"] + cls, valign=Gtk.Align.CENTER))
            row.add_suffix(Gtk.Label(label=p["label"], css_classes=["hel-pill"], valign=Gtk.Align.CENTER))
            b = Gtk.Button(label="Voltar para cá", valign=Gtk.Align.CENTER)
            b.connect("clicked", self.on_rollback, p)
            row.add_suffix(b)
            m = Gio.Menu()
            s1, s2, s3 = Gio.Menu(), Gio.Menu(), Gio.Menu()
            s1.append("Voltar só um arquivo ou pasta deste ponto", f"win.explore({p['id']})")
            s1.append("O que mudou desde este ponto", f"win.changes({p['id']})")
            s1.append("Experimentar este ponto sem voltar (terminal)", f"win.try({p['id']})")
            s2.append("Criar um ramo a partir deste ponto…", f"win.branchfrom({p['id']})")
            s2.append("Aqui funcionava: procurar o que quebrou…", f"win.bisectfrom({p['id']})")
            s3.append("Verificar o selo" if p.get("sealed") else "Selar este ponto (hash e assinatura)", f"win.seal({p['id']})")
            s3.append("Desproteger" if p.get("protected") else "Proteger (nunca apagar sozinho)",
                      f"win.protect({p['id']})")
            s3.append("Excluir este ponto", f"win.delete({p['id']})")
            for sec in (s1, s2, s3):
                m.append_section(None, sec)
            row.add_suffix(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=m, valign=Gtk.Align.CENTER,
                                          css_classes=["flat"]))
            self.tl_list.append(row)

    def on_create(self, *_a):
        d = Adw.AlertDialog(heading="Criar ponto agora", body="Dê um nome para lembrar depois por que este ponto existe.")
        e = Gtk.Entry(placeholder_text="ex.: antes de mexer no firewall", activates_default=True)
        d.set_extra_child(e)
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Criar")
        d.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("yes")

        def done(_d, r):
            if r == "yes":
                self.eng.call("create", lambda ok, res: (self.toast(f"Ponto #{res['id']} criado") if ok else self.fail(res),
                                                          self.refresh()), desc=e.get_text().strip())
        d.connect("response", done)
        d.present(self)

    def on_rollback(self, _b, p):
        d = Adw.AlertDialog(heading=f"Voltar para o ponto #{p['id']}?",
                            body=f"{p['desc']} — {when(p['time'])}\n\nEscolha o que volta. O estado de agora é guardado "
                                 "como um novo ponto, então dá para desfazer. A troca vale ao reiniciar.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        names = {"root": "Sistema: programas, configurações, /etc, /var", "home": "Arquivos pessoais: /home",
                 "log": "Logs: /var/log"}
        checks = {}
        for part in p["parts"]:
            c = Gtk.CheckButton(label=names[part], active=(part == "root"))
            checks[part] = c
            box.append(c)
        d.set_extra_child(box)
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Voltar no tempo")
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)

        def done(_d, r):
            parts = [k for k, c in checks.items() if c.get_active()]
            if r != "yes" or not parts:
                return
            self.toast("Voltando no tempo…")

            def after(ok, res):
                if not ok:
                    return self.fail(res)
                self.refresh()
                q = Adw.AlertDialog(heading="Pronto. Falta reiniciar.",
                                    body=f"O estado anterior ficou guardado no ponto #{res['saved']}.")
                q.add_response("later", "Depois")
                q.add_response("now", "Reiniciar agora")
                q.set_response_appearance("now", Adw.ResponseAppearance.SUGGESTED)
                q.connect("response", lambda _q, rr: rr == "now" and self.eng.call("reboot", lambda *_a: None))
                q.present(self)
            self.eng.call("rollback", after, id=p["id"], parts=parts)
        d.connect("response", done)
        d.present(self)

    def act_delete(self, _a, v):
        cid = v.get_int32()
        d = Adw.AlertDialog(heading=f"Excluir o ponto #{cid}?", body="Esta é a única ação da Heloisa que não tem volta.")
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Excluir")
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "yes" and self.eng.call(
            "delete", lambda ok, res: (None if ok else self.fail(res), self.refresh()), id=cid))
        d.present(self)

    def act_changes(self, _a, v):
        cid = v.get_int32()

        def show(ok, r):
            if not ok:
                return self.fail(r)
            out = []
            for title, grp in (("PACOTES", r["packages"]), ("ARQUIVOS DE /etc", r["etc"])):
                out.append(f"━━ {title}")
                n = 0
                for sign, key in (("+", "added"), ("-", "removed"), ("~", "changed")):
                    for x in grp[key]:
                        out.append(f"{sign} {x}")
                        n += 1
                if not n:
                    out.append("  nada mudou")
                out.append("")
            self.show_text(f"Do ponto #{cid} até agora", "\n".join(out),
                           "+ entrou depois do ponto   - saiu   ~ mudou")
        self.eng.call("changes", show, id=cid)

    def act_explore(self, _a, v):
        self.view_id = v.get_int32()
        self.fill_views()
        self.stack.set_visible_child_name("any")
        self.load_dir()

    # ------------------------------------------------------------ qualquer coisa
    def build_anything(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=6, margin_top=10, margin_bottom=10, margin_start=12, margin_end=12)
        up = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Pasta acima")
        up.connect("clicked", lambda *_: self.go(os.path.dirname(self.cwd.rstrip("/")) or "/"))
        bar.append(up)
        self.path = Gtk.Entry(hexpand=True, placeholder_text="/qualquer/caminho/do/sistema")
        self.path.connect("activate", lambda e: self.go(e.get_text().strip() or "/"))
        bar.append(self.path)
        for label, folder in (("Arquivo…", False), ("Pasta…", True)):
            b = Gtk.Button(label=label)
            b.connect("clicked", self.on_pick, folder)
            bar.append(b)
        self.views = Gtk.DropDown(tooltip_text="Ver as pastas como eram em um ponto (acha o que foi apagado)")
        self.views.connect("notify::selected", self.on_view)
        bar.append(self.views)
        box.append(bar)
        paned = Gtk.Paned(vexpand=True, position=430, shrink_start_child=False, shrink_end_child=False)
        sc = Gtk.ScrolledWindow(width_request=300)
        self.files = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.files.connect("row-selected", self.on_file_selected)
        self.files.connect("row-activated", self.on_file_activated)
        sc.set_child(self.files)
        paned.set_start_child(sc)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=14, margin_end=14, margin_top=4, spacing=8)
        self.ver_title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, css_classes=["title-3"])
        self.ver_sub = Gtk.Label(xalign=0, wrap=True, css_classes=["hel-dim"])
        right.append(self.ver_title)
        hrow = Gtk.Box(spacing=8)
        self.ver_sub.set_hexpand(True)
        hrow.append(self.ver_sub)
        self.btn_blame = Gtk.Button(label="Quando mudou?", valign=Gtk.Align.START,
                                    tooltip_text="Histórico do arquivo: em que ponto mudou, o que mudou e a causa provável")
        self.btn_blame.connect("clicked", self.on_blame)
        hrow.append(self.btn_blame)
        right.append(hrow)
        sc2 = Gtk.ScrolledWindow(vexpand=True)
        self.vers = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                                valign=Gtk.Align.START, margin_bottom=14, margin_top=4, margin_start=2, margin_end=2)
        sc2.set_child(self.vers)
        right.append(sc2)
        paned.set_end_child(right)
        box.append(paned)
        return box

    def fill_views(self):
        self._filling = True
        self.view_ids = [0] + [p["id"] for p in reversed(self.points)]
        if self.view_id not in self.view_ids:
            self.view_id = 0
        names = ["Ver: agora"] + [f"Ver: #{p['id']} · {when(p['time'])}" for p in reversed(self.points)]
        self.views.set_model(Gtk.StringList.new(names))
        self.views.set_selected(self.view_ids.index(self.view_id))
        self._filling = False

    def on_view(self, *_a):
        if getattr(self, "_filling", False):
            return
        i = self.views.get_selected()
        if 0 <= i < len(self.view_ids) and self.view_ids[i] != self.view_id:
            self.view_id = self.view_ids[i]
            self.load_dir()

    def on_pick(self, _b, folder):
        dlg = Gtk.FileDialog(title="Escolha o que quer ver no tempo")

        def done(d, res):
            try:
                f = (d.select_folder_finish(res) if folder else d.open_finish(res))
            except GLib.Error:
                return
            p = f.get_path()
            if p:
                if folder:
                    self.go(p)
                else:
                    self.sel = p
                    self.go(os.path.dirname(p))
        (dlg.select_folder if folder else dlg.open)(self, None, done)

    def go(self, path):
        self.cwd = os.path.normpath(os.path.join(self.cwd, os.path.expanduser(path)))
        if self.sel and os.path.dirname(self.sel) != self.cwd:
            self.sel = None
        self.load_dir()

    def load_dir(self):
        self.path.set_text(self.cwd)

        def got(ok, r):
            if not ok and self.sel is None and self.cwd != "/":
                # o caminho pode ser um arquivo: mostra a pasta e seleciona
                self.sel, self.cwd = self.cwd, os.path.dirname(self.cwd.rstrip("/")) or "/"
                return self.load_dir()
            self.files.remove_all()
            if not ok:
                self.files.append(Adw.ActionRow(title="Esta pasta não existe nesta visão",
                                                subtitle="Troque o ponto em “Ver:” ou suba um nível."))
            else:
                for e in r["entries"]:
                    row = Gtk.ListBoxRow()
                    row.entry = e
                    h = Gtk.Box(spacing=10, margin_top=5, margin_bottom=5)
                    h.append(Gtk.Image.new_from_icon_name(
                        {"dir": "folder-symbolic", "link": "emblem-symbolic-link-symbolic"}.get(e["type"], "text-x-generic-symbolic")))
                    h.append(Gtk.Label(label=e["name"], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE))
                    if e["type"] == "file":
                        h.append(Gtk.Label(label=human(e["size"]), css_classes=["hel-dim", "caption"]))
                    row.set_child(h)
                    self.files.append(row)
                    if self.sel and os.path.basename(self.sel) == e["name"]:
                        self.files.select_row(row)
            if not self.files.get_selected_row():
                self.load_versions(self.sel or self.cwd)
        self.eng.call("listdir", got, id=self.view_id, path=self.cwd)

    def on_file_selected(self, _l, row):
        if row is not None and hasattr(row, "entry"):
            self.sel = os.path.join(self.cwd, row.entry["name"])
            self.load_versions(self.sel)

    def on_file_activated(self, _l, row):
        if hasattr(row, "entry") and row.entry["type"] == "dir":
            self.sel = None
            self.go(os.path.join(self.cwd, row.entry["name"]))

    def load_versions(self, path):
        self.ver_title.set_label(path)
        self.ver_sub.set_label("Procurando versões…")
        self.cur_path = path

        def got(ok, r):
            if not ok:
                return self.ver_sub.set_label(str(r))
            if r["path"] != self.cur_path:
                return
            self.vers.remove_all()
            cur = r["current"]
            isdir = (cur or {}).get("type") == "dir" or any(v.get("type") == "dir" for v in r["versions"])
            alive = [v for v in r["versions"] if v["exists"]]
            distinct = [v for v in alive if v["same"] is False]
            if cur is None:
                state = "Não existe mais agora" if alive else "Nunca existiu em nenhum ponto"
            else:
                state = "Pasta" if isdir else f"{human(cur['size'])} · modificado {when(datetime.datetime.fromtimestamp(cur['mtime']).strftime('%Y-%m-%d %H:%M'))}"
            extra = "" if isdir else f" · {len(distinct)} versões diferentes da seguinte"
            self.btn_blame.set_visible(not isdir)
            self.ver_sub.set_label(f"{state} · presente em {len(alive)} de {len(r['versions'])} pontos{extra}")
            for v in r["versions"]:
                if not v["exists"]:
                    row = Adw.ActionRow(title=f"#{v['id']} · {when(v['time'])}", subtitle="não existia neste ponto",
                                        css_classes=["hel-same"])
                    self.vers.append(row)
                    continue
                sub = v["desc"] if isdir else f"{human(v['size'])} · {v['desc']}"
                row = Adw.ActionRow(title=f"#{v['id']} · {when(v['time'])}", subtitle=GLib.markup_escape_text(sub))
                if v["same"]:
                    row.add_suffix(Gtk.Label(label="igual à seguinte", css_classes=["hel-dim", "caption"]))
                elif v["same"] is False:
                    row.add_suffix(Gtk.Label(label="diferente", css_classes=["hel-pill"], valign=Gtk.Align.CENTER))
                b = Gtk.Button(icon_name="edit-find-symbolic", tooltip_text="Comparar com o estado de agora",
                               valign=Gtk.Align.CENTER, css_classes=["flat"])
                b.connect("clicked", self.on_diff, path, v["id"])
                row.add_suffix(b)
                b = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Trazer uma cópia desta versão (não mexe no atual)",
                               valign=Gtk.Align.CENTER, css_classes=["flat"])
                b.connect("clicked", self.on_restore, path, v, False)
                row.add_suffix(b)
                b = Gtk.Button(label="Voltar", tooltip_text="Deixar exatamente como era neste ponto", valign=Gtk.Align.CENTER)
                b.connect("clicked", self.on_restore, path, v, True)
                row.add_suffix(b)
                self.vers.append(row)
        self.eng.call("versions", got, path=path)

    def on_blame(self, *_a):
        path = getattr(self, "cur_path", None)
        if not path:
            return

        def show(ok, r):
            if not ok:
                return self.fail(r)
            out = [f"━━ {r['path']}", f"   acompanhado em {r['points']} pontos"]
            if r.get("owner"):
                out.append(f"   pertence ao pacote {r['owner']}" +
                           (" e está igual ao original do pacote" if r.get("pristine") else " e foi modificado em relação ao pacote"))
            out.append("")
            if not r["events"]:
                out.append("Nenhuma mudança registrada entre os pontos existentes.")
            for e in r["events"]:
                a = f"ponto #{e['from']} ({when(e['from_time'])})"
                b = f"ponto #{e['to']} ({when(e['to_time'])})" if e["to"] else "agora"
                sign = {"criado": "+", "apagado": "-"}.get(e["what"], "~")
                line = f"{sign} {e['what']} entre o {a} e {b}"
                if e["added"] or e["removed"]:
                    line += f"   [+{e['added']} linhas, -{e['removed']} linhas]"
                out.append(line)
                if e.get("cause"):
                    out.append(f"    causa provável: {e['cause']}")
            self.show_text(f"Quando mudou: {path}", "\n".join(out),
                           "Para ver o conteúdo de cada mudança, use a lupa na versão correspondente.")
        self.eng.call("blame", show, path=path)

    def on_diff(self, _b, path, cid):
        self.eng.call("diff", lambda ok, r: self.show_text(f"{path} — ponto #{cid} → agora", r["text"]) if ok else self.fail(r),
                      path=path, id=cid)

    def on_restore(self, _b, path, v, inplace):
        def go():
            def after(ok, r):
                if not ok:
                    return self.fail(r)
                if inplace:
                    self.toast(f"Voltou ao ponto #{v['id']}. O estado anterior ficou no ponto #{r['saved']}.")
                else:
                    self.toast(f"Cópia criada: {r['dest']}")
                self.refresh()
            self.eng.call("restore", after, path=path, id=v["id"], inplace=inplace)
        if not inplace:
            return go()

        def ask(ok, pc):
            if not ok:
                return self.fail(pc)
            body = (f"{path}\nficará exatamente como era no ponto #{v['id']} ({when(v['time'])}), agora mesmo, "
                    "sem reiniciar.\n\nO estado de agora é guardado em um novo ponto antes.")
            d = Adw.AlertDialog(heading="Voltar esta versão?")
            d.add_response("no", "Cancelar")
            ws, units = pc.get("writers") or [], pc.get("units") or []
            if ws:
                who = ", ".join(sorted({w["unit"] or f"{w['name']} (processo {w['pid']})" for w in ws}))
                body += (f"\n\n⚠ Em uso agora: {who} está escrevendo "
                         f"{'dentro desta pasta' if pc.get('isdir') else 'neste arquivo'}. Trocar o conteúdo por baixo de um "
                         "programa em execução pode corromper os dados"
                         + (" (" + pc["risky"] + ")." if pc.get("risky") else "."))
                if units:
                    body += "\n\nO caminho seguro: parar o serviço, voltar e religar."
                    d.add_response("stop", "Parar, voltar e religar")
                    d.set_response_appearance("stop", Adw.ResponseAppearance.SUGGESTED)
                else:
                    body += "\n\nFeche o programa antes, se puder."
                d.add_response("yes", "Voltar mesmo assim")
                d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
            else:
                if pc.get("risky"):
                    body += (f"\n\n⚠ Cuidado: isto parece ser {pc['risky']}. Nenhum programa está escrevendo nele agora, "
                             "mas confirme que o programa dono está parado"
                             + (" e prefira voltar a pasta inteira do banco, não um arquivo solto." if not pc.get("isdir") else "."))
                d.add_response("yes", "Voltar")
                d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
            d.set_body(body)

            def resp(_d, r):
                if r == "yes":
                    go()
                elif r == "stop":
                    def after(ok2, res):
                        if not ok2:
                            return self.fail(res)
                        msg = f"Voltou ao ponto #{v['id']}. Parado e religado: {', '.join(res['stopped']) or 'nada'}."
                        if res.get("failed"):
                            msg += f" NÃO religou: {', '.join(res['failed'])}."
                        self.toast(msg)
                        self.refresh()
                    self.eng.call("restore", after, path=path, id=v["id"], inplace=True, stop=units)
            d.connect("response", resp)
            d.present(self)
        self.eng.call("precheck", ask, path=path, id=v["id"])

    def show_text(self, title, text, hint=None, wrap=False):
        w = Adw.Window(transient_for=self, modal=True, title=title, default_width=900, default_height=640)
        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"), Gtk.CallbackAction.new(lambda *_a: w.close() or True)))
        w.add_controller(esc)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        view = Gtk.TextView(editable=False, monospace=True, left_margin=14, right_margin=14, top_margin=10,
                            bottom_margin=10, css_classes=["hel-mono"])
        if wrap:
            view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        buf = view.get_buffer()
        add = buf.create_tag("add", foreground="#26c281")
        rem = buf.create_tag("rem", foreground="#f0616d")
        hd = buf.create_tag("hd", foreground="#2D7FF9", weight=Pango.Weight.BOLD)
        for line in text.splitlines():
            tag = None
            if line.startswith(("+++", "---", "@@", "━━")):
                tag = hd
            elif line.startswith("+"):
                tag = add
            elif line.startswith("-"):
                tag = rem
            it = buf.get_end_iter()
            if tag:
                buf.insert_with_tags(it, line + "\n", tag)
            else:
                buf.insert(it, line + "\n")
        sc = Gtk.ScrolledWindow(vexpand=True)
        sc.set_child(view)
        tv.set_content(sc)
        if hint:
            tv.add_bottom_bar(Gtk.Label(label=hint, css_classes=["hel-dim", "caption"], margin_top=6, margin_bottom=6))
        w.set_content(tv)
        w.present()

    # ------------------------------------------------------------ barras de aviso
    def _bar(self, text, buttons, cls=()):
        b = Gtk.Box(spacing=10, css_classes=["hel-bar"] + list(cls))
        b.append(Gtk.Label(label=text, xalign=0, wrap=True, hexpand=True))
        for label, cb, style in buttons:
            bt = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=style)
            bt.connect("clicked", lambda _b, f=cb: f())
            b.append(bt)
        self.bars.append(b)

    def fill_bars(self, st):
        while (c := self.bars.get_first_child()) is not None:
            self.bars.remove(c)
        al = st.get("alert")
        if al:
            self._bar(f"Possível ransomware: {al['files']} arquivos pessoais foram reescritos de uma vez antes do ponto "
                      f"#{al['point']} ({when(al['time'])}). O ponto #{al['safe']}, anterior, foi protegido.",
                      [("Ver detalhes", lambda: self.show_alert(al), ["suggested-action"]),
                       ("Dispensar", lambda: self.eng.call("alert-clear", lambda *_a: self.refresh()), [])], ["alert"])
        b = st.get("bisect")
        if not b:
            return
        if b.get("done"):
            self._bar(f"Busca concluída: o problema entrou no ponto #{b['first_bad']}"
                      + (" (a troca de volta ao seu sistema vale ao reiniciar)." if st["pending"] else "."),
                      [("Ver o que mudou", lambda: self.show_bisect(b), ["suggested-action"])]
                      + ([("Reiniciar agora", lambda: self.eng.call("reboot", lambda *_a: None), [])] if st["pending"] else [])
                      + [("Encerrar", self.bisect_close, [])])
        elif b.get("active") and st["pending"]:
            self._bar(f"Procurando o que quebrou: reinicie para testar o ponto #{b['testing']} "
                      f"(faltam cerca de {b['left'] + 1} teste(s)).",
                      [("Reiniciar agora", lambda: self.eng.call("reboot", lambda *_a: None), ["suggested-action"])])
        elif b.get("active"):
            self._bar(f"Procurando o que quebrou: você está no sistema do ponto #{b['testing']}. "
                      "Teste o que estava com problema. Funciona aqui?",
                      [("Funciona", lambda: self.bisect_mark(True), ["suggested-action"]),
                       ("Não funciona", lambda: self.bisect_mark(False), ["destructive-action"]),
                       ("Cancelar a busca", self.bisect_close, [])])

    def show_alert(self, al):
        out = [f"━━ Alarme de {when(al['time'])}", "", f"{al['files']} arquivos pessoais reescritos entre o ponto "
               f"#{al['safe']} e o ponto #{al['point']}.", ""] + ["- " + x for x in al["reasons"]] + ["", "━━ Exemplos"]
        out += ["  /home/" + x for x in al.get("sample", [])]
        out += ["", f"O ponto #{al['safe']} é o último antes disso e está protegido contra expiração.",
                "Para recuperar: aba Qualquer coisa, escolha a pasta afetada e volte à versão do ponto "
                f"#{al['safe']}; ou volte os arquivos pessoais inteiros por 'Voltar para cá' naquele ponto.",
                "", "Isto é uma heurística: uma conversão em massa de arquivos também pode disparar o alarme."]
        self.show_text("Possível ransomware", "\n".join(out), wrap=True)

    # ------------------------------------------------------------ bisect
    def act_bisect(self, *_a):
        b = self.st.get("bisect")
        if b and b.get("done"):
            return self.show_bisect(b)
        if b and b.get("active"):
            return self.toast("Já há uma busca em andamento (veja a barra no topo)")
        pts = [p for p in self.points if "root" in p["parts"]]
        if len(pts) < 2:
            return self.fail("É preciso ter pelo menos dois pontos para procurar entre eles.")
        d = Adw.AlertDialog(
            heading="Procurar o que quebrou",
            body="Algo funcionava e parou? Escolha o ponto mais recente em que ainda funcionava. A Heloisa coloca o "
                 "sistema em pontos intermediários, um por vez; a cada reinício você responde se funciona ou não, "
                 "e ela aponta o ponto exato em que o problema entrou e o que mudou nele.\n\nSó o sistema muda "
                 "durante a busca; arquivos pessoais e logs ficam como estão. No fim, a máquina volta ao estado de agora.")
        dd = Gtk.DropDown(model=Gtk.StringList.new([f"#{p['id']} · {when(p['time'])} · {p['desc']}"[:80] for p in reversed(pts)]))
        d.set_extra_child(dd)
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Começar a busca")
        d.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        d.connect("response", lambda _d, r: r == "yes" and self.bisect_start(list(reversed(pts))[dd.get_selected()]["id"]))
        d.present(self)

    def act_bisectfrom(self, _a, v):
        cid = v.get_int32()
        d = Adw.AlertDialog(heading=f"No ponto #{cid} funcionava?",
                            body="A Heloisa vai procurar, entre esse ponto e agora, o ponto em que o problema entrou. "
                                 "Serão alguns reinícios; no fim a máquina volta ao estado de agora.")
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Começar a busca")
        d.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        d.connect("response", lambda _d, r: r == "yes" and self.bisect_start(cid))
        d.present(self)

    def bisect_start(self, good):
        self.toast("Preparando a busca…")
        self.eng.call("bisect-start", self.bisect_step, good=good)

    def bisect_mark(self, works):
        self.toast("Preparando o próximo teste…")
        self.eng.call("bisect-mark", self.bisect_step, works=works)

    def bisect_step(self, ok, b):
        if not ok:
            return self.fail(b)
        self.refresh()
        if b.get("done"):
            return self.show_bisect(b)
        q = Adw.AlertDialog(heading=f"Próximo teste: ponto #{b['testing']}",
                            body="Reinicie para entrar no sistema desse ponto. Depois de testar, abra a Heloisa e "
                                 f"responda se funciona. Faltam cerca de {b['left'] + 1} teste(s).")
        q.add_response("later", "Depois")
        q.add_response("now", "Reiniciar agora")
        q.set_response_appearance("now", Adw.ResponseAppearance.SUGGESTED)
        q.connect("response", lambda _q, rr: rr == "now" and self.eng.call("reboot", lambda *_a: None))
        q.present(self)

    def show_bisect(self, b):
        r = b.get("result") or {"packages": {}, "etc": {}}
        out = [f"━━ O problema entrou no ponto #{b['first_bad']}: {b.get('bad_desc', '')}",
               f"   último ponto em que funcionava: #{b['last_good']}: {b.get('good_desc', '')}",
               f"   testes feitos: {b.get('steps', 0)}"]
        if b.get("bad_summary"):
            out.append(f"   resumo do ponto #{b['first_bad']}: {b['bad_summary']}")
        out.append("")
        for title, grp in (("PACOTES que mudaram entre os dois", r.get("packages", {})),
                           ("ARQUIVOS DE /etc que mudaram entre os dois", r.get("etc", {}))):
            out.append(f"━━ {title}")
            n = 0
            for sign, key in (("+", "added"), ("-", "removed"), ("~", "changed")):
                for x in grp.get(key, []):
                    out.append(f"{sign} {x}")
                    n += 1
            if not n:
                out.append("  nada mudou")
            out.append("")
        out.append("A máquina voltou (ou volta, ao reiniciar) ao estado de antes da busca. Para desfazer só a mudança "
                   "culpada, use a aba Qualquer coisa no arquivo indicado, ou volte o sistema ao ponto "
                   f"#{b['last_good']}.")
        self.show_text("O que quebrou", "\n".join(out), "+ entrou   - saiu   ~ mudou")

    def bisect_close(self):
        self.eng.call("bisect-abort", lambda ok, r: (self.fail(r) if not ok else
                                                     self.toast("Busca encerrada" + (": reinicie para voltar ao seu sistema"
                                                                if r and r.get("restored") else "")), self.refresh()))

    # ------------------------------------------------------------ experimentar, selar, proteger
    def act_try(self, _a, v):
        cid = v.get_int32()
        cmd = (["pkexec"] if os.geteuid() != 0 else []) + [ENGINE, "try-shell", str(cid)]
        for term in (["ptyxis", "--new-window", "--"], ["kgx", "--"], ["gnome-terminal", "--"], ["xterm", "-e"]):
            if GLib.find_program_in_path(term[0]):
                subprocess.Popen(term + cmd, start_new_session=True)
                return self.toast(f"Abrindo um terminal dentro do ponto #{cid} (cópia descartável)")
        self.fail("Nenhum terminal encontrado.")

    def act_protect(self, _a, v):
        cid = v.get_int32()
        p = next((x for x in self.points if x["id"] == cid), None)
        self.eng.call("protect", lambda ok, r: (None if ok else self.fail(r), self.refresh()), id=cid,
                      on=not (p and p.get("protected")))

    def act_seal(self, _a, v):
        cid = v.get_int32()
        p = next((x for x in self.points if x["id"] == cid), None)
        if p and p.get("sealed"):
            self.toast("Recalculando o hash do ponto… pode levar um minuto")

            def got(ok, r):
                if not ok:
                    return self.fail(r)
                out = [f"━━ Ponto #{cid}, selado em {when(r['sealed_at'])}", "",
                       ("+ INTACTO: o conteúdo é exatamente o do momento do selo" if r["intact"]
                        else "- ALTERADO: o conteúdo do ponto não é mais o do momento do selo"),
                       ("+ assinatura confere com a chave desta máquina" if r["signature"]
                        else "- a assinatura NÃO confere com a chave desta máquina"), "",
                       f"hash no selo: {r['hash']}", f"hash agora:   {r['now']}", f"arquivos conferidos: {r['files']}"]
                if r["changed"]:
                    out += ["", "━━ O que difere"] + ["~ " + x for x in r["changed"]]
                self.show_text(f"Selo do ponto #{cid}", "\n".join(out),
                               "Guarde o hash fora desta máquina: é ele que prova, a terceiros, o estado do ponto.")
            return self.eng.call("seal-verify", got, id=cid)
        self.toast("Calculando o hash de todos os arquivos do ponto… pode levar um minuto")

        def done(ok, r):
            self.refresh()
            if not ok:
                return self.fail(r)
            d = Adw.AlertDialog(heading=f"Ponto #{cid} selado",
                                body=f"{r['files']} arquivos, {human(r['bytes'])}.\n\nSHA-256 do ponto:\n{r['hash']}\n\n"
                                     "O hash foi assinado com a chave desta máquina. Guarde-o também fora dela "
                                     "(e-mail, chamado, papel): é a prova de que a máquina estava neste estado. "
                                     "Ponto selado nunca é apagado sozinho.")
            d.add_response("copy", "Copiar o hash")
            d.add_response("ok", "Fechar")
            d.connect("response", lambda _d, rr: rr == "copy" and self.get_clipboard().set(r["hash"]))
            d.present(self)
        self.eng.call("seal", done, id=cid)

    # ------------------------------------------------------------ ramos
    def act_branchfrom(self, _a, v):
        self.new_branch(v.get_int32())

    def new_branch(self, cid=0):
        d = Adw.AlertDialog(
            heading="Novo ramo da máquina",
            body=("Um ramo é uma segunda linha do sistema, que nasce " +
                  (f"do ponto #{cid}" if cid else "do estado de agora") +
                  " e segue por conta própria: teste um kernel, um driver ou uma mudança grande nele, e escolha no "
                  "menu de boot qual ramo iniciar. Arquivos pessoais e logs são os mesmos em todos os ramos."))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        name = Gtk.Entry(placeholder_text="nome: ex. teste-kernel", activates_default=True)
        desc = Gtk.Entry(placeholder_text="para que serve (opcional)")
        box.append(name)
        box.append(desc)
        d.set_extra_child(box)
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Criar ramo")
        d.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("yes")

        def resp(_d, r):
            if r != "yes":
                return
            self.toast("Criando o ramo e preparando a entrada no menu de boot…")
            self.eng.call("branch-create", lambda ok, res: (
                self.fail(res) if not ok else self.toast(
                    f"Ramo {res['name']} criado" + ("" if res["bootable"] else " (sem entrada no menu de boot)")),
                self.refresh(), self.act_branches()), name=name.get_text().strip().lower(), id=cid,
                desc=desc.get_text().strip())
        d.connect("response", resp)
        d.present(self)

    def act_branches(self, *_a):
        old = getattr(self, "_brwin", None)
        if old:
            old.close()
        w = Adw.Window(transient_for=self, modal=True, title="Ramos da máquina", default_width=640, default_height=460)
        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"), Gtk.CallbackAction.new(lambda *_a: w.close() or True)))
        w.add_controller(esc)
        self._brwin = w
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        nb = Gtk.Button(label="Novo ramo", css_classes=["suggested-action"])
        nb.connect("clicked", lambda *_: (w.close(), self.new_branch(0)))
        hb.pack_start(nb)
        tv.add_top_bar(hb)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=14, margin_bottom=14,
                      margin_start=14, margin_end=14)
        box.append(Gtk.Label(
            label="Cada ramo é um sistema completo e independente no mesmo disco. O ramo em uso é o que recebe os "
                  "pontos novos. Para iniciar outro: troque aqui, ou escolha no menu de boot (Heloisa: iniciar outro ramo).",
            xalign=0, wrap=True, css_classes=["hel-dim"]))
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        for b in self.st.get("branches") or []:
            sub = b.get("desc") or ""
            if b.get("created"):
                sub += f" · criado {when(b['created'])}"
            row = Adw.ActionRow(title=b["name"], subtitle=GLib.markup_escape_text(sub.strip(" ·")))
            row.add_prefix(Gtk.Image.new_from_icon_name("media-playlist-consecutive-symbolic"))
            if b["active"]:
                row.add_suffix(Gtk.Label(label="em uso", css_classes=["hel-pill"], valign=Gtk.Align.CENTER))
            else:
                if b["bootable"]:
                    row.add_suffix(Gtk.Label(label="no menu de boot", css_classes=["hel-dim", "caption"]))
                u = Gtk.Button(label="Usar este ramo", valign=Gtk.Align.CENTER)
                u.connect("clicked", lambda _b, n=b["name"]: (w.close(), self.branch_switch(n)))
                row.add_suffix(u)
                x = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Apagar o ramo", valign=Gtk.Align.CENTER,
                               css_classes=["flat"])
                x.connect("clicked", lambda _b, n=b["name"]: (w.close(), self.branch_delete(n)))
                row.add_suffix(x)
            lb.append(row)
        box.append(lb)
        sc = Gtk.ScrolledWindow(vexpand=True)
        sc.set_child(box)
        tv.set_content(sc)
        w.set_content(tv)
        w.present()

    def branch_switch(self, name):
        d = Adw.AlertDialog(heading=f"Passar a usar o ramo “{name}”?",
                            body="O ramo de agora fica guardado, intacto, e você pode voltar a ele quando quiser. "
                                 "A troca vale ao reiniciar.")
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Trocar de ramo")
        d.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r):
            if r != "yes":
                return
            self.toast("Trocando de ramo…")

            def after(ok, res):
                self.refresh()
                if not ok:
                    return self.fail(res)
                q = Adw.AlertDialog(heading="Pronto. Falta reiniciar.",
                                    body=f"Ao reiniciar, o sistema será o do ramo {res['to']}. O ramo {res['from']} ficou guardado.")
                q.add_response("later", "Depois")
                q.add_response("now", "Reiniciar agora")
                q.set_response_appearance("now", Adw.ResponseAppearance.SUGGESTED)
                q.connect("response", lambda _q, rr: rr == "now" and self.eng.call("reboot", lambda *_a: None))
                q.present(self)
            self.eng.call("branch-switch", after, name=name)
        d.connect("response", resp)
        d.present(self)

    def branch_delete(self, name):
        d = Adw.AlertDialog(heading=f"Apagar o ramo “{name}”?",
                            body="O sistema desse ramo é apagado. Não tem volta. Os pontos criados nele continuam na "
                                 "linha do tempo.")
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Apagar")
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "yes" and self.eng.call(
            "branch-delete", lambda ok, res: (None if ok else self.fail(res), self.refresh()), name=name))
        d.present(self)

    # ------------------------------------------------------------ enviar pontos para fora
    def act_push(self, *_a):
        def got(ok, ts):
            if not ok:
                return self.fail(ts)
            d = Adw.AlertDialog(
                heading="Enviar os pontos para outro disco",
                body="Os pontos vivem no mesmo disco do sistema. Enviá-los para fora é o que os transforma em backup: "
                     "se o disco morrer, eles continuam lá. Só vai o que mudou desde o último envio.\n\n"
                     "Destino: um disco externo formatado em btrfs (monte-o no app Arquivos), ou um servidor com btrfs, "
                     "no formato ssh://root@servidor/caminho (usa a chave SSH do root desta máquina).")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            first, radios = None, []
            for t in ts:
                c = Gtk.CheckButton(label=f"{t['path']}   ({t.get('label') or t['dev']}, {t['avail']} livres)", group=first)
                first = first or c
                c.dest = t["path"]
                radios.append(c)
                box.append(c)
            if radios:
                radios[0].set_active(True)
            else:
                box.append(Gtk.Label(label="Nenhum disco btrfs externo montado agora.", xalign=0, css_classes=["hel-dim"]))
            e = Gtk.Entry(placeholder_text="ou: ssh://root@servidor/caminho  ·  /pasta/em/outro/disco/btrfs")
            box.append(e)
            d.set_extra_child(box)
            d.add_response("no", "Cancelar")
            d.add_response("yes", "Enviar")
            d.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)

            def resp(_d, r):
                dest = e.get_text().strip() or next((c.dest for c in radios if c.get_active()), "")
                if r != "yes" or not dest:
                    return
                self.toast("Enviando os pontos… o primeiro envio copia o sistema inteiro e pode demorar")

                def done(ok2, res):
                    self.refresh()
                    if not ok2:
                        return self.fail(res)
                    q = Adw.AlertDialog(
                        heading="Pontos enviados",
                        body=f"{len(res['sent'])} ponto(s) enviado(s), {res['already']} já estavam lá.\n"
                             f"{human(res['bytes'])} transferidos para {res['dest']}.\n\nCom essa cópia dá para montar "
                             "uma máquina igual em outro computador: inicie pelo pendrive do MilizOS, abra a Heloisa e "
                             "escolha “Clonar de uma cópia”.")
                    q.add_response("ok", "Fechar")
                    q.present(self)
                self.eng.call("push", done, dest=dest)
            d.connect("response", resp)
            d.present(self)
        self.eng.call("targets", got)

    # ------------------------------------------------------------ resgate (modo live)
    def show_rescue(self):
        self.show_status("heloisa", "Resgate e clonagem pela mídia",
                         "Você iniciou pelo pendrive. A Heloisa pode trazer de volta um ponto de um MilizOS instalado, "
                         "reconstruindo o boot mesmo que o sistema não inicie mais; ou montar neste computador uma "
                         "máquina igual a outra, a partir de uma cópia de pontos em disco externo.")
        box = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        for label, cb, cls in (("Procurar sistemas instalados", self.find_rescue, ["pill", "suggested-action"]),
                               ("Clonar de uma cópia", self.find_clone, ["pill"])):
            b = Gtk.Button(label=label, css_classes=cls)
            b.connect("clicked", lambda _b, f=cb: f())
            box.append(b)
        self.status.set_child(box)

    def find_clone(self):
        def got(ok, srcs):
            if not ok:
                return self.fail(srcs)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, width_request=680)
            if not srcs:
                box.append(Gtk.Label(label="Nenhuma cópia de pontos foi encontrada. Ligue o disco externo usado em "
                                           "“Enviar pontos para outro disco” e procure de novo.", wrap=True))
            for sdev in srcs:
                box.append(Gtk.Label(label=f"Máquina “{sdev['host']}” em {sdev['dev']} {sdev.get('label') or ''}", xalign=0,
                                     css_classes=["title-4"]))
                lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
                for p in list(reversed(sdev["points"]))[:12]:
                    row = Adw.ActionRow(title=GLib.markup_escape_text(p["desc"]),
                                        subtitle=f"#{p['id']} · {when(p['time'])}" +
                                        (("\n" + GLib.markup_escape_text(p["summary"])) if p.get("summary") else ""))
                    b = Gtk.Button(label="Clonar para este computador", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
                    b.connect("clicked", self.on_clone, sdev, p)
                    row.add_suffix(b)
                    lb.append(row)
                box.append(lb)
            b = Gtk.Button(label="Voltar", halign=Gtk.Align.CENTER, css_classes=["pill"])
            b.connect("clicked", lambda *_: self.show_rescue())
            box.append(b)
            sc = Gtk.ScrolledWindow(min_content_height=420, propagate_natural_height=True)
            sc.set_child(box)
            self.status.set_child(sc)
        self.eng.call("backups", got)

    def on_clone(self, _b, sdev, p):
        def got(ok, ds):
            ds = [d for d in (ds if ok else []) if d.get("path") != sdev["dev"] and not sdev["dev"].startswith(d.get("path", "?"))]
            if not ds:
                return self.fail("Não encontrei um disco de destino diferente do disco da cópia.")
            d = Adw.AlertDialog(
                heading=f"Clonar “{sdev['host']}” (ponto #{p['id']}) para este computador",
                body="O disco escolhido será APAGADO por inteiro e receberá o sistema, os usuários e as configurações "
                     "daquele ponto. Chaves SSH do servidor e identidade da máquina são geradas de novo.")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            first, radios = None, []
            for x in ds:
                c = Gtk.CheckButton(label=f"{x['path']}   {x.get('model') or ''}   {human(x.get('size') or 0)}", group=first)
                first = first or c
                c.disk = x["path"]
                radios.append(c)
                box.append(c)
            radios[0].set_active(True)
            host = Gtk.Entry(text=sdev["host"] + "-2", placeholder_text="nome da nova máquina")
            box.append(host)
            home = Gtk.CheckButton(label="Trazer também os arquivos pessoais (/home)", active=p.get("home", False),
                                   sensitive=p.get("home", False))
            box.append(home)
            d.set_extra_child(box)
            d.add_response("no", "Cancelar")
            d.add_response("yes", "Apagar o disco e clonar")
            d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)

            def resp(_d, r):
                if r != "yes":
                    return
                disk = next(c.disk for c in radios if c.get_active())
                self.show_status("heloisa", "Clonando…", "Particionando, copiando o sistema do ponto e instalando o boot. "
                                 "Leva alguns minutos; não desligue.")
                self.eng.call("clone", lambda ok2, res: self.show_status(
                    "object-select-symbolic", "Máquina clonada",
                    f"{res['hostname']} está instalada em {res['disk']}. Retire o pendrive e reinicie.") if ok2 else (
                        self.fail(res), self.show_rescue()),
                    dev=sdev["dev"], dir=sdev["dir"], id=p["id"], disk=disk, hostname=host.get_text().strip() or "milizos",
                    home=home.get_active())
            d.connect("response", resp)
            d.present(self)
        self.eng.call("disks", got)

    def find_rescue(self):
        def got(ok, vols):
            if not ok:
                return self.fail(vols)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, width_request=640)
            if not vols:
                box.append(Gtk.Label(label="Nenhuma instalação com pontos foi encontrada."))
            for v in vols:
                lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
                if v["locked"]:
                    lb.append(Adw.ActionRow(title=f"{v['dev']} está criptografado",
                                            subtitle="Desbloqueie o disco no app Arquivos ou Discos e procure de novo."))
                for p in reversed(v["points"]):
                    row = Adw.ActionRow(title=GLib.markup_escape_text(p["desc"]),
                                        subtitle=f"{v['dev']} · #{p['id']} · {when(p['time'])}")
                    b = Gtk.Button(label="Resgatar", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
                    b.connect("clicked", self.on_rescue, v["dev"], p)
                    row.add_suffix(b)
                    lb.append(row)
                box.append(lb)
            b = Gtk.Button(label="Procurar de novo", halign=Gtk.Align.CENTER, css_classes=["pill"])
            b.connect("clicked", lambda *_: self.find_rescue())
            box.append(b)
            self.status.set_child(box)
        self.eng.call("rescue-find", got)

    def on_rescue(self, _b, dev, p):
        self.toast("Restaurando e reconstruindo o boot… pode levar alguns minutos")
        self.eng.call("rescue", lambda ok, r: self.fail(r) if not ok else self.show_status(
            "object-select-symbolic", "Sistema resgatado",
            f"O ponto #{p['id']} voltou a ser o sistema e o boot foi reinstalado em {r['disk']}. "
            "Retire o pendrive e reinicie."), dev=dev, id=p["id"])


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.milizos.Heloisa", flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.path = None

    def do_open(self, files, _n, _hint):
        self.path = files[0].get_path()
        self.do_activate()

    def do_activate(self):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS)
        from gi.repository import Gdk
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        w = Window(self, self.path)
        for name, fn in (("changes", w.act_changes), ("explore", w.act_explore), ("delete", w.act_delete),
                         ("try", w.act_try), ("branchfrom", w.act_branchfrom), ("bisectfrom", w.act_bisectfrom),
                         ("seal", w.act_seal), ("protect", w.act_protect)):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new("i"))
            a.connect("activate", fn)
            w.add_action(a)
        for name, fn in (("branches", w.act_branches), ("push", w.act_push), ("bisect", w.act_bisect)):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", fn)
            w.add_action(a)
        w.present()


def needs_attention():
    """Ha busca do que quebrou em andamento ou alarme pendente? (lido sem privilegio, de /.heloisa)"""
    for name, key in (("bisect", "active"), ("bisect", "done"), ("alert", "files")):
        try:
            with open(f"{STATE_DIR}/{name}.json", encoding="utf-8") as f:
                if json.load(f).get(key):
                    return True
        except (OSError, ValueError, AttributeError):
            pass
    return False


if __name__ == "__main__":
    if "--check" in sys.argv:          # chamado no login: so aparece se houver algo esperando resposta
        if not needs_attention():
            sys.exit(0)
        sys.argv.remove("--check")
    sys.exit(App().run(sys.argv))

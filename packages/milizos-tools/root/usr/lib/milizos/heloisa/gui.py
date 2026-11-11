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
"""


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
        tv.add_top_bar(hb)
        self.banner = Adw.Banner(title="Volta no tempo aplicada. Reinicie o computador para concluir.",
                                 button_label="Reiniciar agora")
        self.banner.connect("button-clicked", lambda *_: self.eng.call("reboot", lambda *_a: None))
        tv.add_top_bar(self.banner)

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
        self.banner.set_revealed(st["pending"])
        self.btn_new.set_sensitive(not st["pending"])
        self.root.set_visible_child_name("main")
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
            row = Adw.ActionRow(title=GLib.markup_escape_text(p["desc"]),
                                subtitle=f"#{p['id']} · {when(p['time'])}" + (" · no menu de boot" if p["bootable"] else ""))
            row.add_prefix(Gtk.Image.new_from_icon_name(KIND_ICON.get(p["kind"], "bookmark-new-symbolic")))
            row.add_suffix(Gtk.Label(label=p["label"], css_classes=["hel-pill"], valign=Gtk.Align.CENTER))
            b = Gtk.Button(label="Voltar para cá", valign=Gtk.Align.CENTER)
            b.connect("clicked", self.on_rollback, p)
            row.add_suffix(b)
            m = Gio.Menu()
            m.append("O que mudou desde este ponto", f"win.changes({p['id']})")
            m.append("Explorar os arquivos deste ponto", f"win.explore({p['id']})")
            m.append("Excluir este ponto", f"win.delete({p['id']})")
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
        right.append(self.ver_sub)
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
        d = Adw.AlertDialog(heading="Voltar esta versão?",
                            body=f"{path}\nficará exatamente como era no ponto #{v['id']} ({when(v['time'])}).\n\n"
                                 "O estado de agora é guardado em um novo ponto antes.")
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Voltar")
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "yes" and go())
        d.present(self)

    def show_text(self, title, text, hint=None):
        w = Adw.Window(transient_for=self, modal=True, title=title, default_width=900, default_height=640)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        view = Gtk.TextView(editable=False, monospace=True, left_margin=14, right_margin=14, top_margin=10,
                            bottom_margin=10, css_classes=["hel-mono"])
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

    # ------------------------------------------------------------ resgate (modo live)
    def show_rescue(self):
        self.show_status("heloisa", "Resgate pela mídia",
                         "Você iniciou pelo pendrive. A Heloisa procura instalações do MilizOS nos discos e traz "
                         "de volta um ponto, reconstruindo o boot — mesmo que o sistema não inicie mais.",
                         "Procurar sistemas instalados", self.find_rescue)

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
            "emblem-ok-symbolic", "Sistema resgatado",
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
        for name, fn in (("changes", w.act_changes), ("explore", w.act_explore), ("delete", w.act_delete)):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new("i"))
            a.connect("activate", fn)
            w.add_action(a)
        w.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))

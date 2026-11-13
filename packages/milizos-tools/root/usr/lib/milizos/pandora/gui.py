#!/usr/bin/python3
# Pandora - caixas Linux descartaveis (GTK4/libadwaita). Tudo roda como o usuario, sem root.
import os
import subprocess
import sys
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine  # noqa: E402

CSS = """
.pan-hero { font-size: 22px; font-weight: 800; }
.pan-dim { opacity: .65; }
.pan-pill { padding: 2px 9px; border-radius: 99px; background: alpha(@accent_bg_color, .18); font-size: 9pt; font-weight: 600; }
.pan-iso { background: alpha(#f5a623, .22); }
.pan-log { font-family: 'JetBrains Mono', monospace; font-size: 9.5pt; }
"""


def bg(fn, done):
    def work():
        try:
            r, err = fn(), None
        except engine.Error as e:
            r, err = None, str(e)
        except Exception as e:  # noqa
            r, err = None, f"erro inesperado: {e!r}"
        GLib.idle_add(done, r, err)
    threading.Thread(target=work, daemon=True).start()


class LogDialog(Adw.Window):
    """Janela com o registro ao vivo de uma operacao demorada."""

    def __init__(self, parent, title):
        super().__init__(transient_for=parent, modal=True, title=title, default_width=760, default_height=460)
        tv = Adw.ToolbarView()
        self.hb = Adw.HeaderBar(show_end_title_buttons=False)
        self.spin = Gtk.Spinner(spinning=True)
        self.hb.pack_start(self.spin)
        self.close_btn = Gtk.Button(label="Fechar", sensitive=False, css_classes=["suggested-action"])
        self.close_btn.connect("clicked", lambda *_: self.close())
        self.hb.pack_end(self.close_btn)
        tv.add_top_bar(self.hb)
        self.view = Gtk.TextView(editable=False, cursor_visible=False, left_margin=12, right_margin=12, top_margin=8,
                                 bottom_margin=8, wrap_mode=Gtk.WrapMode.WORD_CHAR, css_classes=["pan-log"])
        sc = Gtk.ScrolledWindow(vexpand=True)
        sc.set_child(self.view)
        self.sc = sc
        tv.set_content(sc)
        self.set_content(tv)

    def log(self, line):
        GLib.idle_add(self._append, line)

    def _append(self, line):
        buf = self.view.get_buffer()
        buf.insert(buf.get_end_iter(), line + "\n")
        adj = self.sc.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) and False)

    def finish(self, err=None):
        self.spin.set_spinning(False)
        self.close_btn.set_sensitive(True)
        self._append("\n✖ " + err if err else "\n✔ concluído")


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Pandora", default_width=900, default_height=680)
        self.set_icon_name("pandora")
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        tv = Adw.ToolbarView()
        self.toasts.set_child(tv)
        hb = Adw.HeaderBar()
        img = Gtk.Image.new_from_icon_name("pandora")
        img.set_pixel_size(28)
        hb.pack_start(img)
        new = Gtk.Button(label="Nova caixa", css_classes=["suggested-action"])
        new.connect("clicked", self.on_new)
        hb.pack_end(new)
        ref = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Atualizar")
        ref.connect("clicked", lambda *_: self.refresh())
        hb.pack_end(ref)
        tv.add_top_bar(hb)
        sc = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp(maximum_size=820, margin_top=18, margin_bottom=24, margin_start=12, margin_end=12)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.box.append(Gtk.Label(label="Outro Linux dentro do seu, pronto para jogar fora.", xalign=0, css_classes=["pan-hero"]))
        self.box.append(Gtk.Label(
            label="Cada caixa é um Debian, Kali, Alma, Arch… completo. O que você instala dentro dela ganha atalho no "
                  "menu do GNOME sozinho, mas continua rodando na caixa: destruiu a caixa, sumiu tudo, e o MilizOS "
                  "segue intacto.", xalign=0, wrap=True, css_classes=["pan-dim"]))
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.box.append(self.list)
        clamp.set_child(self.box)
        sc.set_child(clamp)
        tv.set_content(sc)
        self.refresh()
        GLib.timeout_add_seconds(6, self.tick)

    def tick(self):
        if self.is_active():
            self.refresh()
        return True

    def toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=msg, timeout=4))

    def fail(self, msg):
        d = Adw.AlertDialog(heading="Não deu certo", body=str(msg))
        d.add_response("ok", "Entendi")
        d.present(self)

    def refresh(self):
        bg(engine.boxes, self.fill)

    def fill(self, boxes, err):
        if err:
            return
        key = repr(boxes)
        if key == getattr(self, "_key", None):
            return
        self._key = key
        while (c := self.list.get_first_child()) is not None:
            self.list.remove(c)
        if not boxes:
            sp = Adw.StatusPage(icon_name="pandora", title="Nenhuma caixa ainda",
                                description="Crie a primeira: escolha a distribuição e o modo de rede.")
            self.list.append(sp)
        for b in boxes:
            g = Adw.PreferencesGroup()
            row = Adw.ExpanderRow(title=b["name"], subtitle=f"{b['distro']} · {'ligada' if b['running'] else 'desligada'}"
                                  f" · {len(b['apps'])} aplicativo(s) no menu")
            row.add_prefix(Gtk.Image.new_from_icon_name("pandora"))
            pill = Gtk.Label(label=engine.MODES[b["mode"]][0] if b["mode"] in engine.MODES else b["mode"],
                             css_classes=["pan-pill"] + (["pan-iso"] if b["mode"] == "isolada" else []),
                             valign=Gtk.Align.CENTER, tooltip_text=engine.MODES.get(b["mode"], ("", ""))[1])
            row.add_suffix(pill)
            t = Gtk.Button(label="Terminal", valign=Gtk.Align.CENTER)
            t.connect("clicked", self.on_terminal, b)
            row.add_suffix(t)
            i = Gtk.Button(label="Instalar…", valign=Gtk.Align.CENTER)
            i.connect("clicked", self.on_install, b)
            row.add_suffix(i)
            for a in b["apps"]:
                ar = Adw.ActionRow(title=GLib.markup_escape_text(a["name"]), subtitle="atalho no menu do GNOME")
                lb = Gtk.Button(label="Abrir", valign=Gtk.Align.CENTER, css_classes=["flat"])
                lb.connect("clicked", self.on_launch, a)
                ar.add_suffix(lb)
                row.add_row(ar)
            ctl = Adw.ActionRow(title="Controle da caixa",
                                subtitle="Sincronizar confere o que está instalado; destruir apaga a caixa e seus atalhos")
            for label, cb, cls in (("Sincronizar menu", self.on_sync, []), ("Desligar", self.on_stop, []),
                                   ("Destruir", self.on_destroy, ["destructive-action"])):
                bt = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=cls)
                bt.connect("clicked", cb, b)
                ctl.add_suffix(bt)
            row.add_row(ctl)
            pr = Adw.ActionRow(title="Pontos da caixa",
                               subtitle="A caixa inteira congelada (programas"
                               + (" e pasta pessoal" if b["mode"] == "isolada" else "")
                               + "). Voltar nunca apaga: o estado de agora vira um ponto antes.")
            np = Gtk.Button(label="Criar ponto", valign=Gtk.Align.CENTER)
            np.connect("clicked", self.on_point_new, b)
            pr.add_suffix(np)
            row.add_row(pr)
            for p in reversed(b.get("points", [])):
                r = Adw.ActionRow(title=GLib.markup_escape_text(p["desc"]), subtitle=f"ponto #{p['id']} · {p['time'][:16]}")
                r.add_prefix(Gtk.Image.new_from_icon_name(
                    "edit-undo-symbolic" if p.get("kind") == "antes" else "bookmark-new-symbolic"))
                vb = Gtk.Button(label="Voltar", valign=Gtk.Align.CENTER)
                vb.connect("clicked", self.on_point_restore, b, p)
                r.add_suffix(vb)
                xb = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Excluir este ponto",
                                valign=Gtk.Align.CENTER, css_classes=["flat"])
                xb.connect("clicked", self.on_point_delete, b, p)
                r.add_suffix(xb)
                row.add_row(r)
            g.add(row)
            self.list.append(g)

    # ------------------------------------------------------------ acoes
    def on_terminal(self, _b, b):
        cmd = [engine.ENTER, b["name"]]
        for term in (["ptyxis", "--new-window", "--"], ["kgx", "--"], ["gnome-terminal", "--"], ["xterm", "-e"]):
            if GLib.find_program_in_path(term[0]):
                subprocess.Popen(term + cmd)
                return
        self.fail("Nenhum terminal encontrado.")

    def on_launch(self, _b, a):
        info = Gio.DesktopAppInfo.new_from_filename(a["file"])
        if info:
            info.launch([], None)

    def on_sync(self, _b, b):
        def work():
            engine.start(b["name"])
            return engine.sync(b["name"])

        def done(r, err):
            if err:
                return self.fail(err)
            self.toast(f"{len(r[0])} atalho(s) novo(s), {len(r[1])} removido(s)")
            self.refresh()
        bg(work, done)

    def on_stop(self, _b, b):
        bg(lambda: engine.stop(b["name"]), lambda *_: self.refresh())

    def on_destroy(self, _b, b):
        d = Adw.AlertDialog(heading=f"Destruir a caixa “{b['name']}”?",
                            body="Somem a caixa, tudo o que foi instalado nela, os atalhos no menu"
                                 + (" e a pasta pessoal dela." if b["mode"] == "isolada" else
                                    ". Seus arquivos pessoais, que ela compartilhava, ficam."))
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Destruir")
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)

        def resp(_d, r):
            if r == "yes":
                bg(lambda: engine.destroy(b["name"]),
                   lambda _r, err: (self.fail(err) if err else self.toast(f"Caixa {b['name']} destruída"), self.refresh()))
        d.connect("response", resp)
        d.present(self)

    def on_point_new(self, _b, b):
        d = Adw.AlertDialog(heading=f"Criar ponto de “{b['name']}”",
                            body="Dê um nome para lembrar depois, por exemplo o que você vai instalar ou testar.")
        e = Gtk.Entry(placeholder_text="ex.: antes de instalar o metasploit", activates_default=True)
        d.set_extra_child(e)
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Criar")
        d.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("yes")

        def resp(_d, r):
            if r != "yes":
                return
            self.toast("Criando o ponto da caixa…")
            bg(lambda: engine.point_create(b["name"], e.get_text().strip()),
               lambda p, err: (self.fail(err) if err else self.toast(f"Ponto #{p['id']} de {b['name']} criado"),
                               self.refresh()))
        d.connect("response", resp)
        d.present(self)

    def on_point_restore(self, _b, b, p):
        d = Adw.AlertDialog(heading=f"Voltar “{b['name']}” ao ponto #{p['id']}?",
                            body=f"{p['desc']} · {p['time'][:16]}\n\nA caixa é recriada como era neste ponto. O estado "
                                 "de agora é guardado em um novo ponto antes, então dá para desfazer. O que estiver "
                                 "rodando na caixa será encerrado.")
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Voltar a caixa")
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)

        def resp(_d, r):
            if r != "yes":
                return
            lg = LogDialog(self, f"Voltando {b['name']} ao ponto #{p['id']}")
            lg.present()
            bg(lambda: engine.point_restore(b["name"], p["id"], lg.log),
               lambda _r, err: (lg.finish(err), self.refresh()))
        d.connect("response", resp)
        d.present(self)

    def on_point_delete(self, _b, b, p):
        d = Adw.AlertDialog(heading=f"Excluir o ponto #{p['id']} de “{b['name']}”?", body="Excluir um ponto não tem volta.")
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Excluir")
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "yes" and bg(
            lambda: engine.point_delete(b["name"], p["id"]),
            lambda _r, err: (self.fail(err) if err else None, self.refresh())))
        d.present(self)

    def on_install(self, _b, b):
        d = Adw.AlertDialog(heading=f"Instalar em “{b['name']}”",
                            body="Nome do(s) pacote(s) na distribuição da caixa. Se trouxer um aplicativo, "
                                 "o atalho aparece no menu.")
        e = Gtk.Entry(placeholder_text="ex.: wireshark  ou  nmap zenmap", activates_default=True)
        d.set_extra_child(e)
        d.add_response("no", "Cancelar")
        d.add_response("yes", "Instalar")
        d.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("yes")

        def resp(_d, r):
            pk = e.get_text().strip()
            if r != "yes" or not pk:
                return
            lg = LogDialog(self, f"Instalando {pk} em {b['name']}")
            lg.present()

            def done(added, err):
                lg.finish(err)
                if added:
                    self.toast("No menu: " + ", ".join(a.removesuffix(".desktop") for a in added))
                self.refresh()
            bg(lambda: engine.install(b["name"], pk, lg.log), done)
        d.connect("response", resp)
        d.present(self)

    def on_new(self, *_a):
        w = Adw.Window(transient_for=self, modal=True, title="Nova caixa", default_width=560)
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancelar")
        cancel.connect("clicked", lambda *_: w.close())
        hb.pack_start(cancel)
        ok = Gtk.Button(label="Criar", css_classes=["suggested-action"])
        hb.pack_end(ok)
        tv.add_top_bar(hb)
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup()
        distro = Adw.ComboRow(title="Distribuição", model=Gtk.StringList.new([n for _i, n, _im in engine.IMAGES]))
        name = Adw.EntryRow(title="Nome da caixa")
        name.set_text(engine.IMAGES[0][0])
        distro.connect("notify::selected", lambda *_: name.set_text(engine.IMAGES[distro.get_selected()][0]))
        g.add(distro)
        g.add(name)
        page.add(g)
        g2 = Adw.PreferencesGroup(title="Rede")
        radios = {}
        first = None
        for key, (label, desc) in engine.MODES.items():
            r = Adw.ActionRow(title=label, subtitle=desc)
            c = Gtk.CheckButton(valign=Gtk.Align.CENTER, group=first)
            first = first or c
            c.set_active(key == "isolada")
            r.add_prefix(c)
            r.set_activatable_widget(c)
            radios[key] = c
            g2.add(r)
        page.add(g2)
        tv.set_content(page)
        w.set_content(tv)

        def go(*_):
            nm = name.get_text().strip()
            image = engine.IMAGES[distro.get_selected()][2]
            mode = next(k for k, c in radios.items() if c.get_active())
            w.close()
            lg = LogDialog(self, f"Criando a caixa {nm}")
            lg.present()
            lg.log("▍baixando a imagem e criando a caixa (depende da sua internet)…")

            def done(_r, err):
                lg.finish(err)
                self.refresh()
            bg(lambda: engine.create(nm, image, mode, lg.log), done)
        ok.connect("clicked", go)
        w.present()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.milizos.Pandora")

    def do_activate(self):
        w = self.get_active_window()
        if w:
            return w.present()
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Window(self).present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))

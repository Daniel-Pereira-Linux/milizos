// MilizOS FX - fundo animado (globo de rede 3D) para a area de trabalho e o login.
// Um unico fragment shader desenha o cenario; a logo e um ator Clutter inclinado em 3D.
// A malha e a mesma do tema de boot: esfera de Fibonacci com arestas i->i+5 e i->i+8.
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import Shell from 'gi://Shell';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const LOGO = '/usr/share/milizos/logo.svg';
// Com GPU: meia resolucao a 30 qps. Em renderizacao por software (VM sem 3D, llvmpipe)
// o shader roda na CPU, entao cai para 1/4 da resolucao a 10 qps para nao pesar.
const HW = {downscale: 2, fps: 30};
const SOFT = {downscale: 4, fps: 10};

const DECLARATIONS = `
uniform float uTime;
uniform vec2 uRes;
const int NN = 22;
const float GOLD = 2.39996323;

float seg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}
`;

const CODE = `
vec2 uv = cogl_tex_coord_in[0].st;
float asp = uRes.x / uRes.y;
vec2 p = (uv - 0.5) * vec2(asp, 1.0);
vec3 teal = vec3(0.0, 0.94, 0.78);
vec3 blue = vec3(0.176, 0.498, 0.976);

// ceu: gradiente azul-noite com um brilho atras do globo
vec3 col = mix(vec3(0.047, 0.078, 0.160), vec3(0.016, 0.027, 0.055), smoothstep(-0.55, 0.55, p.y));
col += blue * 0.10 * exp(-dot(p, p) * 5.0);

// piso: grade em perspectiva correndo em direcao a camera
float d = p.y - 0.17;
if (d > 0.0) {
    float z = 0.30 / d;
    vec2 g = vec2(p.x * z * 1.6, z * 1.6 + uTime * 0.45);
    vec2 f = abs(fract(g) - 0.5);
    float w = 0.012 + z * 0.012;
    float line = (1.0 - smoothstep(0.0, w, min(f.x, f.y)));
    col += mix(teal, blue, 0.55) * line * exp(-z * 0.33) * 0.42;
    col += blue * 0.07 * exp(-d * 9.0);
}

// globo de rede: nos em uma esfera, girando; projecao em perspectiva
vec3 P[NN];
float ca = cos(uTime * 0.22), sa = sin(uTime * 0.22);
float ct = cos(0.384), st = sin(0.384);
for (int i = 0; i < NN; i++) {
    float fi = float(i);
    float y = 1.0 - 2.0 * (fi + 0.5) / float(NN);
    float r = sqrt(1.0 - y * y);
    vec3 q = vec3(r * cos(fi * GOLD), y, r * sin(fi * GOLD));
    q = vec3(q.x * ca + q.z * sa, q.y, -q.x * sa + q.z * ca);
    q = vec3(q.x, q.y * ct - q.z * st, q.y * st + q.z * ct);
    float s = 3.2 / (3.2 + q.z);
    P[i] = vec3(q.xy * s * 0.30 + vec2(0.0, -0.06), q.z);
}
for (int k = 0; k < 2; k++) {
    int off = (k == 0) ? 5 : 8;
    for (int i = 0; i < NN - 5; i++) {
        int j = i + off;
        if (j < NN) {
            vec3 a = P[i];
            vec3 b = P[j];
            float near = 1.0 - (0.5 * (a.z + b.z) + 1.0) * 0.5;
            float dl = seg(p, a.xy, b.xy);
            col += blue * (1.0 - smoothstep(0.0, 0.0030, dl)) * (0.18 + 0.42 * near);
            float t = fract(uTime * 0.30 + float(i) * 0.37 + float(k) * 0.5);
            vec2 pp = mix(a.xy, b.xy, t);
            col += vec3(0.62, 1.0, 0.94) * 0.000022 / (dot(p - pp, p - pp) + 0.00003) * (0.35 + 0.65 * near);
        }
    }
}
for (int i = 0; i < NN; i++) {
    float near = 1.0 - (P[i].z + 1.0) * 0.5;
    float dd = dot(p - P[i].xy, p - P[i].xy);
    float pulse = 0.8 + 0.2 * sin(uTime * 1.7 + float(i));
    col += teal * (0.000050 + 0.000110 * near) / (dd + 0.00006) * pulse * 0.55;
}

// vinheta
col *= 1.0 - 0.38 * dot(p, p);
cogl_color_out = vec4(clamp(col, 0.0, 1.0), 1.0);
`;

const MeshEffect = GObject.registerClass(
class MilizOSMeshEffect extends Shell.GLSLEffect {
    _init(params) {
        super._init(params);
        this._uTime = this.get_uniform_location('uTime');
        this._uRes = this.get_uniform_location('uRes');
    }

    vfunc_build_pipeline() {
        this.add_glsl_snippet(Cogl.SnippetHook.FRAGMENT, DECLARATIONS, CODE, true);
    }

    update(time, width, height) {
        this.set_uniform_float(this._uTime, 1, [time]);
        this.set_uniform_float(this._uRes, 2, [width, height]);
        this.queue_repaint();
    }
});

export default class MilizOSFx extends Extension {
    enable() {
        this._layers = [];
        this._start = GLib.get_monotonic_time();
        let accel = true;
        try {
            accel = global.backend.is_rendering_hardware_accelerated();
        } catch (_e) {
            accel = true;
        }
        this._q = accel ? HW : SOFT;
        this._build();
        this._monitorsId = Main.layoutManager.connect('monitors-changed', () => {
            this._clear();
            this._build();
        });
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT_IDLE, 1000 / this._q.fps, () => {
            this._tick();
            return GLib.SOURCE_CONTINUE;
        });
    }

    disable() {
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = null;
        }
        if (this._monitorsId) {
            Main.layoutManager.disconnect(this._monitorsId);
            this._monitorsId = null;
        }
        this._clear();
        this._layers = null;
    }

    _parent() {
        // no login (GDM) o fundo fica no grupo da tela de bloqueio; no desktop, no grupo de fundo
        if (Main.sessionMode.isGreeter && Main.screenShield?._lockDialogGroup)
            return {group: Main.screenShield._lockDialogGroup, bottom: true};
        return {group: Main.layoutManager._backgroundGroup, bottom: false};
    }

    _build() {
        const {group, bottom} = this._parent();
        for (const m of Main.layoutManager.monitors) {
            const mesh = new Clutter.Actor({
                x: m.x, y: m.y,
                width: Math.ceil(m.width / this._q.downscale), height: Math.ceil(m.height / this._q.downscale),
                scale_x: this._q.downscale, scale_y: this._q.downscale,
                background_color: new Cogl.Color({red: 7, green: 11, blue: 22, alpha: 255}),
            });
            const effect = new MeshEffect();
            mesh.add_effect(effect);

            const side = Math.round(m.height * 0.20);
            const logo = new St.Icon({
                gicon: Gio.icon_new_for_string(LOGO),
                icon_size: side,
                x: m.x + Math.round(m.width / 2 - side / 2),
                y: m.y + Math.round(m.height * 0.44 - side / 2),
            });
            logo.set_pivot_point(0.5, 0.5);

            if (bottom) {
                group.insert_child_at_index(mesh, 0);
                group.insert_child_at_index(logo, 1);
            } else {
                group.add_child(mesh);
                group.add_child(logo);
            }
            this._layers.push({mesh, effect, logo, w: m.width, h: m.height});
        }
        this._tick();
    }

    _clear() {
        for (const l of this._layers ?? []) {
            l.mesh.destroy();
            l.logo.destroy();
        }
        this._layers = [];
    }

    _covered() {
        // com uma janela maximizada ou em tela cheia o fundo nao aparece: nao gasta quadros
        if (Main.sessionMode.isGreeter || Main.overview.visible)
            return false;
        const w = global.display.focus_window;
        if (!w)
            return false;
        const max = typeof w.is_maximized === 'function'
            ? w.is_maximized() : (w.maximized_horizontally && w.maximized_vertically);
        return w.is_fullscreen() || max;
    }

    _tick() {
        if (this._covered())
            return;
        const t = (GLib.get_monotonic_time() - this._start) / 1e6;
        for (const l of this._layers) {
            if (!l.mesh.mapped)
                continue;
            l.effect.update(t, l.w, l.h);
            // a logo acompanha o giro com uma inclinacao 3D suave e "respira"
            l.logo.rotation_angle_y = 16 * Math.sin(t * 0.44);
            l.logo.rotation_angle_x = 5 * Math.sin(t * 0.31 + 1.0);
            const s = 1 + 0.02 * Math.sin(t * 0.9);
            l.logo.set_scale(s, s);
        }
    }
}

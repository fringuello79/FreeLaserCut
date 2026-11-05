# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Anteprima 3D con la scheda grafica (OpenGL di Qt, già incluso: nessuna libreria in più).

Stessi comandi e stesse viste dell'anteprima fatta in casa (render3d), ma disegnata dalla scheda grafica: si gira in
tempo reale, bordi lisci (multicampionamento), luce calcolata punto per punto, venature del legno e bordi bruciati
nello shader, pavimento con la griglia e l'ombra morbida della scultura.

Le facce dei pezzi (contorni con i fori, anche concavi) si riempiono con lo stencil, pari-dispari: esatte, senza
dover dividere i contorni in triangoli. Se OpenGL manca o non funziona (PC vecchi, desktop remoto, macchine virtuali)
la finestra usa l'anteprima fatta in casa: vedi probe().
"""
import math
import os

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QMatrix4x4, QOffscreenSurface, QOpenGLContext, \
    QPainter, QSurfaceFormat, QVector3D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat, QOpenGLShader, \
    QOpenGLShaderProgram
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ..core import render3d
from freelasercut.i18n import tr  # noqa: E402

# costanti OpenGL (quelle che servono)
GL_FLOAT = 0x1406
GL_TRIANGLES = 0x0004
GL_DEPTH_TEST = 0x0B71
GL_STENCIL_TEST = 0x0B90
GL_BLEND = 0x0BE2
GL_CULL_FACE = 0x0B44
GL_MULTISAMPLE = 0x809D
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_COLOR_BUFFER_BIT = 0x4000
GL_DEPTH_BUFFER_BIT = 0x0100
GL_STENCIL_BUFFER_BIT = 0x0400
GL_ALWAYS = 0x0207
GL_NOTEQUAL = 0x0205
GL_LEQUAL = 0x0203
GL_KEEP = 0x1E00
GL_ZERO = 0
GL_ONE = 1
GL_LESS = 0x0201
GL_INVERT = 0x150A
GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE0 = 0x84C0
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_LINEAR = 0x2601
GL_CLAMP_TO_EDGE = 0x812F
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02

STRIDE = 10 * 4          # posizione 3, normale 3, colore 3, tipo 1 (0 liscio, 1 legno, 2 bordo bruciato)
MESH_LIMIT = 900_000     # triangoli del modello oltre i quali l'anteprima usa una copia alleggerita
SHADOW_PX = 512
KIND_CLAY, KIND_WOOD, KIND_BURNT = 0.0, 1.0, 2.0

VS_OBJ = """#version 120
attribute vec3 a_pos;
attribute vec3 a_nrm;
attribute vec3 a_col;
attribute float a_kind;
uniform mat4 u_mvp;
uniform vec3 u_offset;
varying vec3 v_pos;
varying vec3 v_nrm;
varying vec3 v_col;
varying float v_kind;
void main() {
    vec3 p = a_pos + u_offset;
    v_pos = p;
    v_nrm = a_nrm;
    v_col = a_col;
    v_kind = a_kind;
    gl_Position = u_mvp * vec4(p, 1.0);
}
"""

FS_OBJ = """#version 120
varying vec3 v_pos;
varying vec3 v_nrm;
varying vec3 v_col;
varying float v_kind;
uniform vec3 u_eye;
uniform vec3 u_light;
uniform float u_tint;
uniform float u_flat;
uniform float u_ground;
uniform float u_k;
uniform float u_lines;
float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}
float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
vec2 plane_uv(vec3 p, vec3 n) {
    vec3 a = abs(n);
    if (a.z >= a.x && a.z >= a.y) return p.xy;
    if (a.x >= a.y) return p.yz;
    return p.xz;
}
void main() {
    if (u_flat > 1.5) { gl_FragColor = vec4(exp(-max(v_pos.z - u_ground, 0.0) / u_k)); return; }
    if (u_flat > 0.5) { gl_FragColor = vec4(1.0); return; }
    vec3 n = normalize(v_nrm);
    vec3 vd = normalize(v_pos - u_eye);
    if (dot(n, vd) > 0.0) n = -n;
    vec3 base = v_col;
    if (v_kind > 0.5 && v_kind < 1.5) {
        vec2 uv = plane_uv(v_pos, n);
        float warp = 2.2 * sin(uv.y * 0.035) + 0.9 * sin(uv.x * 0.05 + uv.y * 0.02) + 1.6 * noise(uv * vec2(0.06, 0.012));
        float rings = sin(uv.x * 0.42 + warp);
        float fib = 0.6 * noise(uv * vec2(3.0, 0.08)) + 0.4 * noise(uv * vec2(9.0, 0.25));
        base *= 0.91 + 0.06 * rings + 0.10 * (fib - 0.5);
    } else if (v_kind > 1.5) {
        base *= 0.92 + 0.34 * noise(v_pos.xy * 0.9 + vec2(v_pos.z * 0.7, -v_pos.z * 0.4));
        if (u_lines > 0.0) {  // strati: si vede dove finisce una fetta e comincia l'altra
            float fz = fract((v_pos.z - u_ground) / u_lines);
            base *= 0.70 + 0.30 * smoothstep(0.0, 0.16, min(fz, 1.0 - fz));
        }
    }
    base *= u_tint;
    float diff = 0.72 * max(dot(n, u_light), 0.0) + 0.38 * max(-dot(n, vd), 0.0);
    vec3 h = normalize(u_light - vd);
    float spec = pow(max(dot(n, h), 0.0), 24.0);
    float sky = 0.5 + 0.5 * n.z;
    vec3 col = base * (0.30 + 0.10 * sky + 0.66 * diff) + 0.09 * spec;
    gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""

VS_GROUND = """#version 120
attribute vec3 a_pos;
uniform mat4 u_mvp;
varying vec3 v_pos;
void main() {
    v_pos = a_pos;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

FS_GROUND = """#version 120
varying vec3 v_pos;
uniform sampler2D u_shadow;
uniform vec3 u_c;
uniform float u_R;
uniform vec3 u_floor;
uniform float u_blur;
uniform float u_has_shadow;
void main() {
    vec2 d = v_pos.xy - u_c.xy;
    float fade = pow(clamp(1.0 - max(abs(d.x), abs(d.y)) / u_R, 0.0, 1.0), 0.6);
    vec2 g = v_pos.xy / 20.0;
    vec2 w = max(fwidth(g), vec2(1e-4));
    vec2 l = abs(fract(g - 0.5) - 0.5) / w;
    float line = 1.0 - clamp(min(l.x, l.y) - 0.3, 0.0, 1.0);
    line *= clamp(1.5 - 6.0 * max(w.x, w.y), 0.0, 1.0);
    float base = mix(0.97, 0.90, line);
    float s = 0.0;
    float ao = 0.0;
    if (u_has_shadow > 0.5) {
        vec2 uv = d / u_R * 0.5 + 0.5;
        for (int i = 0; i < 16; i++) {
            float a = float(i) * 2.39996;
            vec2 o = sqrt((float(i) + 0.5) / 16.0) * vec2(cos(a), sin(a));
            s += texture2D(u_shadow, uv + u_blur * o).r;
            ao += texture2D(u_shadow, uv + u_blur * 0.45 * o).g;
        }
        s /= 16.0;
        ao /= 16.0;
    }
    gl_FragColor = vec4(u_floor * base * (1.0 - 0.30 * s) * (1.0 - 0.42 * ao), fade);
}
"""

VS_BG = """#version 120
attribute vec2 a_xy;
varying float v_t;
void main() {
    v_t = a_xy.y * 0.5 + 0.5;
    gl_Position = vec4(a_xy, 0.0, 1.0);
}
"""

FS_BG = """#version 120
varying float v_t;
uniform vec3 u_top;
uniform vec3 u_bottom;
void main() {
    gl_FragColor = vec4(mix(u_bottom, u_top, v_t), 1.0);
}
"""

_PROBE = None


def surface_format():
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(4)
    return fmt


def _program(vs, fs, attrs):
    p = QOpenGLShaderProgram()
    if not p.addShaderFromSourceCode(QOpenGLShader.Vertex, vs):
        raise RuntimeError(p.log())
    if not p.addShaderFromSourceCode(QOpenGLShader.Fragment, fs):
        raise RuntimeError(p.log())
    for k, name in enumerate(attrs):
        p.bindAttributeLocation(name, k)
    if not p.link():
        raise RuntimeError(p.log())
    return p


def probe(force=False):
    """(True, «nome della scheda grafica») se la scheda grafica può fare l'anteprima, altrimenti (False, motivo).
    FLC_3D=software nell'ambiente obbliga l'anteprima fatta in casa."""
    global _PROBE
    if _PROBE is not None and not force:
        return _PROBE
    if os.environ.get("FLC_3D", "").lower() in ("software", "sw", "0", "no"):
        _PROBE = (False, "FLC_3D=software")
        return _PROBE
    if QGuiApplication.platformName() in ("offscreen", "minimal", "vnc", "linuxfb"):
        _PROBE = (False, QGuiApplication.platformName())
        return _PROBE
    try:
        ctx = QOpenGLContext()
        ctx.setFormat(surface_format())
        if not ctx.create():
            _PROBE = (False, "context")
            return _PROBE
        surf = QOffscreenSurface()
        surf.setFormat(ctx.format())
        surf.create()
        if not surf.isValid() or not ctx.makeCurrent(surf):
            _PROBE = (False, "surface")
            return _PROBE
        try:
            if ctx.isOpenGLES():
                _PROBE = (False, "OpenGL ES")
                return _PROBE
            fm = ctx.format()
            if (fm.majorVersion(), fm.minorVersion()) < (2, 1):
                _PROBE = (False, f"OpenGL {fm.majorVersion()}.{fm.minorVersion()}")
                return _PROBE
            progs = [_program(vs, fs, at) for vs, fs, at in (
                (VS_OBJ, FS_OBJ, ("a_pos", "a_nrm", "a_col", "a_kind")), (VS_GROUND, FS_GROUND, ("a_pos",)),
                (VS_BG, FS_BG, ("a_xy",)))]
            if not QOpenGLFramebufferObject.hasOpenGLFramebufferObjects():
                _PROBE = (False, "framebuffer")
                return _PROBE
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            fmt.setSamples(4)
            fbo = QOpenGLFramebufferObject(QSize(64, 64), fmt)
            valid = fbo.isValid()
            del fbo, progs  # liberati finché il contesto è attivo
            if not valid:
                _PROBE = (False, "framebuffer")
                return _PROBE
            name = str(ctx.functions().glGetString(GL_RENDERER) or "OpenGL").strip()
            _PROBE = (True, name)
        finally:
            ctx.doneCurrent()
    except Exception as ex:  # noqa: BLE001 - qualsiasi problema: anteprima fatta in casa
        _PROBE = (False, str(ex)[:120])
    return _PROBE


def is_emulated(name):
    """OpenGL fatto dal processore (desktop remoto, macchine virtuali, PC senza driver): funziona, ma più lento."""
    n = (name or "").lower()
    return any(k in n for k in ("llvmpipe", "softpipe", "gdi generic", "basic render", "swiftshader"))


def _mat(m):
    return QMatrix4x4(*[float(x) for x in np.asarray(m, np.float64).ravel()])


def _vec(v):
    return QVector3D(float(v[0]), float(v[1]), float(v[2]))


def _pack(tris, normals, color, kind):
    """Triangoli (T,3,3) -> dati intercalati float32 (T*3, 10)."""
    T = len(tris)
    out = np.empty((T * 3, 10), np.float32)
    out[:, 0:3] = tris.reshape(-1, 3)
    out[:, 3:6] = normals.reshape(-1, 3)
    out[:, 6:9] = np.broadcast_to(np.asarray(color, np.float32).reshape(-1, 3), (T * 3, 3)) if np.ndim(color) == 1 \
        else np.asarray(color, np.float32).reshape(-1, 3)
    out[:, 9] = kind
    return out


def _face_normals(tris):
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    return np.repeat(n[:, None, :], 3, axis=1)


def _fan(rings):
    """Ventagli dei contorni (per lo stencil pari-dispari): tutti i triangoli (r0, ri, ri+1) di ogni anello."""
    out = []
    for r in rings:
        r = np.asarray(r, np.float64)
        if len(r) < 3:
            continue
        i = np.arange(1, len(r) - 1)
        out.append(np.stack([np.repeat(r[:1], len(i), 0), r[i], r[i + 1]], 1))
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


class _Buf:
    """Un buffer di vertici sulla scheda grafica."""

    def __init__(self, data):
        self.count = len(data)
        self.buf = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.buf.create()
        self.buf.bind()
        raw = np.ascontiguousarray(data, np.float32).tobytes()
        self.buf.allocate(raw, len(raw))
        self.buf.release()

    def destroy(self):
        if self.buf is not None:
            self.buf.destroy()
            self.buf = None


class GLViewer(QOpenGLWidget):
    """Anteprima 3D con la scheda grafica: trascina per girare, rotella per avvicinare, doppio clic per tornare alla
    vista di partenza. Stessa interfaccia di Viewer3D (dialogs_sculpt)."""

    backend = "gpu"
    failed = Signal(str)   # OpenGL non va su questo PC: la finestra passa all'anteprima fatta in casa
    painted = Signal()     # primo disegno riuscito (la finestra sa che la scheda grafica regge)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFormat(surface_format())
        self.setMinimumSize(420, 330)
        self.setCursor(Qt.OpenHandCursor)
        self.mesh = None
        self.sculpture = None
        self.view = "sculpture"
        self.step = None
        self.lift = 0.0
        self.yaw, self.pitch, self.zoom = -35.0, 22.0, 1.0
        self.message = ""
        self.renderer_name = probe()[1]
        self._drag = None
        self._ok = None          # None: non ancora inizializzata; False: OpenGL non funziona
        self._progs = None
        self._gen = 0            # cresce a ogni set_data: i buffer caricati sono di questa versione?
        self._mesh_key = None
        self._sc_key = None
        self._ground_key = None
        self._pc_start = np.zeros(1, np.int64)
        self._mesh_buf = None
        self._mesh_bounds = None
        self._mesh_ground = 0.0
        self._wall_buf = None
        self._cap_buf = None
        self._piece_walls = []   # per pezzo: (primo, quanti) nel buffer dei bordi
        self._piece_caps = []    # per pezzo: [(primo, quanti, normale fuori, un punto)] nel buffer delle facce
        self._sc_bounds = None
        self._sc_ground = 0.0
        self._bg_buf = None
        self._ground_buf = None
        self._shadow_fbo = None
        self._shadow_key = None
        self._light = np.asarray(render3d.LIGHT, np.float64)
        self._mask = (True, True, True, True)
        self._painted_once = False
        self._idle = QTimer(self)  # compatibilità con Viewer3D (qui non serve: si disegna sempre a piena qualità)
        self._idle.setSingleShot(True)

    # ---------------------------------------------------------------- come Viewer3D
    def set_data(self, mesh, sculpture):
        self.mesh, self.sculpture = mesh, sculpture
        self._gen += 1
        self._shadow_key = None
        self.update()

    def set_view(self, view):
        self.view = view
        self._shadow_key = None
        self.update()

    def set_step(self, step, lift=0.0):
        self.step, self.lift = step, lift
        self.update()

    def reset_camera(self):
        self.yaw, self.pitch, self.zoom = -35.0, 22.0, 1.0
        self.update()

    def stop(self):
        self._idle.stop()

    def render_image(self, w, h, ss=2):
        """Immagine (QImage RGB) della vista attuale, disegnata dalla scheda grafica in un riquadro a parte."""
        if self.context() is None or not self.context().isValid():
            self.grabFramebuffer()  # crea il contesto (anche a finestra nascosta)
        if not self._ok:
            img = QImage(w, h, QImage.Format_RGB888)
            img.fill(QColor("#E6EAF0"))
            return img
        self.makeCurrent()
        img = None
        try:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            fmt.setSamples(4)
            fbo = QOpenGLFramebufferObject(QSize(w, h), fmt)
            if fbo.isValid():
                fbo.bind()
                self._draw(w, h, fbo_bind=fbo.bind)
                fbo.release()
                img = fbo.toImage().convertToFormat(QImage.Format_RGB888)
            del fbo  # liberato finché il contesto è attivo
        except Exception:  # noqa: BLE001 - un'immagine vuota, non un errore per chi la chiede
            img = None
        finally:
            self.doneCurrent()
        if img is None:
            img = QImage(w, h, QImage.Format_RGB888)
            img.fill(QColor("#E6EAF0"))
        return img

    # ---------------------------------------------------------------- OpenGL
    def _forget_gl(self):
        """Dimentica tutto quello che sta sulla scheda grafica (senza toccarla: il contesto non c'è più)."""
        self._progs = None
        self._bg_buf = self._ground_buf = self._shadow_fbo = None
        self._mesh_buf = self._wall_buf = self._cap_buf = None
        self._mesh_key = self._sc_key = self._shadow_key = self._ground_key = None

    def release_gl(self):
        """Libera buffer, riquadri e programmi sulla scheda grafica, con il contesto attivo (prima che sparisca: la
        finestra cambia anteprima, si chiude, o Qt ricrea il contesto)."""
        ctx = self.context()
        if ctx is None or not ctx.isValid() or self._progs is None:
            self._forget_gl()
            return
        self.makeCurrent()
        try:
            for b in (self._bg_buf, self._ground_buf, self._mesh_buf, self._wall_buf, self._cap_buf):
                if b is not None:
                    b.destroy()
            self._shadow_fbo = None
            self._progs = None
        finally:
            self._forget_gl()
            self.doneCurrent()

    def _emit_failed(self, why):
        try:
            self.failed.emit(why)
        except RuntimeError:  # anteprima già chiusa
            pass

    def _emit_painted(self):
        try:
            self.painted.emit()
        except RuntimeError:
            pass

    def initializeGL(self):
        self._forget_gl()  # un contesto nuovo (Qt lo ricrea se la finestra cambia): si ricarica tutto
        try:
            self.context().aboutToBeDestroyed.connect(self.release_gl)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._progs = {
                "obj": _program(VS_OBJ, FS_OBJ, ("a_pos", "a_nrm", "a_col", "a_kind")),
                "ground": _program(VS_GROUND, FS_GROUND, ("a_pos",)),
                "bg": _program(VS_BG, FS_BG, ("a_xy",)),
            }
            self._bg_buf = _Buf(np.array([[-1, -1], [1, -1], [1, 1], [-1, -1], [1, 1], [-1, 1]], np.float32))
            self._ok = True
        except Exception as ex:  # noqa: BLE001
            self._ok = False
            msg = str(ex)[:200]
            QTimer.singleShot(0, lambda: self._emit_failed(msg))

    def paintGL(self):
        if not self._ok:
            return
        p = QPainter(self)
        p.beginNativePainting()
        failed = None
        try:
            dpr = self.devicePixelRatioF()
            self._draw(math.floor(self.width() * dpr + 0.5), math.floor(self.height() * dpr + 0.5),
                       fbo_bind=lambda: self.context().functions().glBindFramebuffer(0x8D40,
                                                                                    self.defaultFramebufferObject()))
        except Exception as ex:  # noqa: BLE001 - un errore di disegno non deve bloccare la finestra
            failed = str(ex)[:200]
        finally:
            p.endNativePainting()
        if failed is not None:
            p.end()
            self._ok = False
            QTimer.singleShot(0, lambda: self._emit_failed(failed))
            return
        p.setPen(QColor("#5A6478"))
        ft = QFont(self.font())
        ft.setPointSizeF(8.5)
        p.setFont(ft)
        w, h = self.width(), self.height()
        p.drawText(QRectF(8, h - 22, w - 16, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("Trascina per girare · rotella per avvicinare · doppio clic: vista di partenza"))
        if self.message:
            p.drawText(QRectF(8, 6, w - 16, 18), Qt.AlignRight | Qt.AlignVCenter, self.message)
        p.end()
        if not self._painted_once:
            self._painted_once = True
            QTimer.singleShot(0, self._emit_painted)

    # ---------------------------------------------------------------- dati sulla scheda grafica
    def _upload(self, model):
        """Carica sulla scheda grafica solo quello che serve ora: il modello (vista Modello) o la scultura."""
        if model:
            if self._mesh_key == self._gen:
                return
            if self._mesh_buf is not None:
                self._mesh_buf.destroy()
            self._mesh_buf = None
            self._shadow_key = None
            if self.mesh is not None:
                sc = render3d.mesh_scene(self.mesh, render3d.CLAY, MESH_LIMIT)
                if sc.tris:
                    tri, color, vn = sc.tris[0]
                    self._mesh_buf = _Buf(_pack(tri, vn if vn is not None else _face_normals(tri), color, KIND_CLAY))
                    self._mesh_bounds = (tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0))
                    self._mesh_ground = float(self.mesh.vertices[:, 2].min())
            self._mesh_key = self._gen
            return
        if self._sc_key == self._gen:
            return
        for b in (self._wall_buf, self._cap_buf):
            if b is not None:
                b.destroy()
        self._wall_buf = self._cap_buf = None
        self._piece_walls, self._piece_caps = [], []
        self._pc_start = np.zeros(1, np.int64)
        self._shadow_key = None
        if self.sculpture is not None:
            parts = render3d.sculpture_parts(self.sculpture)
            walls, caps = [], []
            nw = nc = 0
            pts = []
            for tris, cp in parts:
                walls.append(_pack(tris, _face_normals(tris), render3d.BURNT, KIND_BURNT) if len(tris)
                             else np.zeros((0, 10), np.float32))
                self._piece_walls.append((nw, len(tris) * 3))
                nw += len(tris) * 3
                lst = []
                for rings3, nout in cp:
                    fan = _fan(rings3)
                    nrm = np.broadcast_to(np.asarray(nout, np.float64), fan.shape)
                    caps.append(_pack(fan, nrm, render3d.WOOD, KIND_WOOD))
                    lst.append((nc, len(fan) * 3, np.asarray(nout, np.float64), np.asarray(rings3[0][0], np.float64)))
                    nc += len(fan) * 3
                    pts.extend(r for r in rings3)
                self._piece_caps.append(lst)
            flat_caps = [c for lst in self._piece_caps for c in lst]
            self._caps_first = np.array([c[0] for c in flat_caps], np.int64)
            self._caps_count = np.array([c[1] for c in flat_caps], np.int64)
            self._caps_n = np.array([c[2] for c in flat_caps], np.float64).reshape(-1, 3)
            self._caps_p = np.array([c[3] for c in flat_caps], np.float64).reshape(-1, 3)
            self._pc_start = np.concatenate([[0], np.cumsum([len(lst) for lst in self._piece_caps])]).astype(np.int64)
            if nw:
                self._wall_buf = _Buf(np.concatenate(walls))
            if nc:
                self._cap_buf = _Buf(np.concatenate(caps))
            allp = np.vstack(pts) if pts else np.zeros((1, 3))
            self._sc_bounds = (allp.min(0), allp.max(0))
            self._sc_ground = render3d.sculpture_ground(self.sculpture, parts)
        self._sc_key = self._gen

    # ---------------------------------------------------------------- disegno
    def _what(self):
        """Cosa disegnare ora: ('model', None) oppure ('sculpture', (pezzi messi, indice e altezza del pezzo che arriva))."""
        if self.view == "model" or self.sculpture is None:
            return "model", None
        n = len(self._piece_walls)
        if self.view == "assembly":
            k = n if self.step is None else max(0, min(n, int(self.step)))
            lifted = (k, float(self.lift)) if (k < n and self.lift > 0) else None
            return "sculpture", (k, lifted)
        return "sculpture", (n, None)

    def _camera(self, what, W, H):
        lo, hi = self._mesh_bounds if what == "model" else self._sc_bounds
        c = (np.asarray(lo) + np.asarray(hi)) / 2
        r = float(np.linalg.norm(np.asarray(hi) - np.asarray(lo))) / 2 or 1.0
        cam = render3d.Camera(c, self.yaw, self.pitch, r / math.tan(math.radians(32.0) / 2) * 1.12)
        cam.dist /= max(self.zoom, 0.05)
        eye, right, up, fwd = cam.basis()
        view = np.eye(4)
        view[0, :3], view[1, :3], view[2, :3] = right, up, -fwd
        view[:3, 3] = -view[:3, :3] @ eye
        R = float(max(hi[0] - lo[0], hi[1] - lo[1])) * 1.4 + 40
        near = max(cam.dist - 3 * r, cam.dist * 0.02, 0.5)
        far = cam.dist + 3 * r + 2 * R
        fy = 1.0 / math.tan(math.radians(cam.fov) / 2)
        proj = np.zeros((4, 4))
        proj[0, 0] = fy / (W / max(H, 1))
        proj[1, 1] = fy
        proj[2, 2] = (far + near) / (near - far)
        proj[2, 3] = 2 * far * near / (near - far)
        proj[3, 2] = -1.0
        # luce «da studio» legata alla vista: da sinistra, un po' davanti e dall'alto. Le facce verso di noi sono
        # sempre illuminate e l'ombra cade dietro a destra, dove si vede
        fh = np.array([fwd[0], fwd[1], 0.0])
        fh /= np.linalg.norm(fh) + 1e-12
        light = -0.50 * right - 0.32 * fh + 0.80 * np.array([0.0, 0.0, 1.0])
        self._light = light / np.linalg.norm(light)
        return proj @ view, eye, c, R

    def _bind_obj(self, prog, buf):
        buf.buf.bind()
        prog.setAttributeBuffer(0, GL_FLOAT, 0, 3, STRIDE)
        prog.setAttributeBuffer(1, GL_FLOAT, 12, 3, STRIDE)
        prog.setAttributeBuffer(2, GL_FLOAT, 24, 3, STRIDE)
        prog.setAttributeBuffer(3, GL_FLOAT, 36, 1, STRIDE)
        for k in range(4):
            prog.enableAttributeArray(k)

    def _unbind_obj(self, prog, buf):
        for k in range(4):
            prog.disableAttributeArray(k)
        buf.buf.release()

    def _cap(self, f, first, count):
        """Una faccia con i fori: prima si segna nello stencil (pari-dispari), poi si colora dove è segnato."""
        f.glColorMask(False, False, False, False)
        f.glDepthMask(False)
        f.glStencilFunc(GL_ALWAYS, 0, 1)
        f.glStencilOp(GL_KEEP, GL_KEEP, GL_INVERT)
        f.glDrawArrays(GL_TRIANGLES, first, count)
        f.glColorMask(*self._mask)  # i canali che si stanno scrivendo (nelle ombre solo uno)
        f.glDepthMask(True)
        f.glStencilFunc(GL_NOTEQUAL, 0, 1)
        f.glStencilOp(GL_ZERO, GL_ZERO, GL_ZERO)
        f.glDrawArrays(GL_TRIANGLES, first, count)

    def _draw_objects(self, f, prog, what, sel, eye, flat=False):
        """Modello o pezzi della scultura. flat: tutto bianco, tutte le facce (per l'ombra)."""
        prog.setUniformValue1f("u_flat", float(flat))
        prog.setUniformValue1f("u_tint", 1.0)
        prog.setUniformValue("u_offset", QVector3D(0, 0, 0))
        if what == "model":
            if self._mesh_buf is not None:
                self._bind_obj(prog, self._mesh_buf)
                f.glDrawArrays(GL_TRIANGLES, 0, self._mesh_buf.count)
                self._unbind_obj(prog, self._mesh_buf)
            return
        k, lifted = sel
        groups = [(0, k, 0.0, 1.0)]
        if lifted is not None:
            groups.append((lifted[0], lifted[0] + 1, lifted[1], 1.06))
        if self._wall_buf is not None:
            self._bind_obj(prog, self._wall_buf)
            for a, b, dz, tint in groups:
                if b <= a:
                    continue
                first = self._piece_walls[a][0]
                last = self._piece_walls[b - 1][0] + self._piece_walls[b - 1][1]
                prog.setUniformValue("u_offset", QVector3D(0, 0, dz))
                prog.setUniformValue1f("u_tint", tint)
                f.glDrawArrays(GL_TRIANGLES, first, last - first)
            self._unbind_obj(prog, self._wall_buf)
        if self._cap_buf is not None:
            self._bind_obj(prog, self._cap_buf)
            f.glEnable(GL_STENCIL_TEST)
            for a, b, dz, tint in groups:
                if b <= a:
                    continue
                prog.setUniformValue("u_offset", QVector3D(0, 0, dz))
                prog.setUniformValue1f("u_tint", tint)
                i0, i1 = int(self._pc_start[a]), int(self._pc_start[b])
                if flat:  # ombre: basta la faccia girata verso la luce (o verso l'alto); i bordi fanno il resto
                    facing = self._light if flat < 1.5 else np.array([0.0, 0.0, 1.0])
                    idx = (i0 + np.nonzero(self._caps_n[i0:i1] @ facing > 1e-3)[0]).tolist()
                else:  # solo le facce girate verso chi guarda: l'altra faccia del pezzo è dietro
                    d = eye - (self._caps_p[i0:i1] + (0.0, 0.0, dz))
                    idx = (i0 + np.nonzero((d * self._caps_n[i0:i1]).sum(1) > 0)[0]).tolist()
                firsts, counts = self._caps_first, self._caps_count
                for i in idx:
                    self._cap(f, int(firsts[i]), int(counts[i]))
            f.glDisable(GL_STENCIL_TEST)
            self._unbind_obj(prog, self._cap_buf)

    def _shadow(self, f, what, sel, c, R, ground, fbo_bind):
        """Ombra sul pavimento, in un riquadro a parte visto dall'alto: canale verde quanto ogni punto è vicino al
        pavimento (ombra di contatto, cambia solo con i pezzi), canale rosso la scena schiacciata lungo la luce
        (ombra portata: la luce segue la vista, quindi si ridisegna solo questa girando)."""
        L = self._light
        base_key = (self._gen, what, sel, round(float(c[0]), 3), round(float(c[1]), 3), round(R, 3))
        light_key = tuple(np.round(L, 3))
        if self._shadow_fbo is not None and self._shadow_key == (base_key, light_key):
            return
        if self._shadow_fbo is None:
            self._shadow_fbo = QOpenGLFramebufferObject(QSize(SHADOW_PX, SHADOW_PX),
                                                        QOpenGLFramebufferObject.CombinedDepthStencil)
        full = self._shadow_key is None or self._shadow_key[0] != base_key
        fbo = self._shadow_fbo
        fbo.bind()
        f.glViewport(0, 0, SHADOW_PX, SHADOW_PX)
        f.glDisable(GL_BLEND)
        f.glClearColor(0, 0, 0, 1)
        f.glClearStencil(0)
        prog = self._progs["obj"]
        prog.bind()
        prog.setUniformValue("u_eye", QVector3D(0, 0, 1e6))
        prog.setUniformValue("u_light", _vec(L))
        top_eye = np.array([0, 0, 1e6])
        if full:
            f.glColorMask(True, True, True, True)
            f.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
            # contatto: dall'alto, vince il punto più basso (profondità = altezza dal pavimento)
            lo, hi = self._mesh_bounds if what == "model" else self._sc_bounds
            top = max(float(hi[2]) - ground, 1.0) + 50.0
            V = np.zeros((4, 4))
            V[0, 0], V[0, 3] = 1 / R, -c[0] / R
            V[1, 1], V[1, 3] = 1 / R, -c[1] / R
            V[2, 2], V[2, 3] = 2 / top, -1 - 2 * ground / top
            V[3, 3] = 1.0
            prog.setUniformValue("u_mvp", _mat(V))
            prog.setUniformValue1f("u_ground", float(ground))
            prog.setUniformValue1f("u_k", float(max(2.0, 0.05 * (float(hi[2]) - ground))))
            f.glEnable(GL_DEPTH_TEST)
            f.glDepthFunc(GL_LESS)
            self._mask = (False, True, False, False)
            f.glColorMask(*self._mask)
            self._draw_objects(f, prog, what, sel, top_eye, flat=2.0)
            f.glDisable(GL_DEPTH_TEST)
        else:
            f.glColorMask(True, False, False, False)
            f.glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
        M = np.zeros((4, 4))
        M[0] = [1 / R, 0, -L[0] / L[2] / R, (L[0] / L[2] * ground - c[0]) / R]
        M[1] = [0, 1 / R, -L[1] / L[2] / R, (L[1] / L[2] * ground - c[1]) / R]
        M[3, 3] = 1.0
        prog.setUniformValue("u_mvp", _mat(M))
        self._mask = (True, False, False, False)
        f.glColorMask(*self._mask)
        self._draw_objects(f, prog, what, sel, top_eye, flat=1.0)
        self._mask = (True, True, True, True)
        f.glColorMask(*self._mask)
        prog.release()
        fbo.release()
        fbo_bind()
        f.glBindTexture(GL_TEXTURE_2D, fbo.texture())
        f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        f.glBindTexture(GL_TEXTURE_2D, 0)
        self._shadow_key = (base_key, light_key)

    def _draw(self, W, H, fbo_bind):
        W, H = int(W), int(H)
        f = QOpenGLContext.currentContext().functions()
        self._upload(self.view == "model" or self.sculpture is None)
        what, sel = self._what()
        has = self._mesh_buf is not None if what == "model" else self._wall_buf is not None
        bg = self._progs["bg"]
        f.glViewport(0, 0, W, H)
        f.glClearColor(0.9, 0.92, 0.95, 1)
        f.glClearStencil(0)
        f.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
        f.glDisable(GL_DEPTH_TEST)
        f.glDisable(GL_CULL_FACE)
        bg.bind()
        bg.setUniformValue("u_top", _vec(render3d.BG_TOP / 255.0))
        bg.setUniformValue("u_bottom", _vec(render3d.BG_BOTTOM / 255.0))
        self._bg_buf.buf.bind()
        bg.setAttributeBuffer(0, GL_FLOAT, 0, 2, 8)
        bg.enableAttributeArray(0)
        f.glDrawArrays(GL_TRIANGLES, 0, 6)
        bg.disableAttributeArray(0)
        self._bg_buf.buf.release()
        bg.release()
        if not has:
            return
        mvp, eye, c, R = self._camera(what, W, H)
        ground = self._mesh_ground if what == "model" else self._sc_ground
        floor = eye[2] > ground + 1e-6  # da sotto il pavimento non si vede (come nell'anteprima semplice)
        if floor:
            try:
                self._shadow(f, what, sel, c, R, ground, fbo_bind)
            finally:
                self._mask = (True, True, True, True)
                f.glColorMask(True, True, True, True)
        f.glViewport(0, 0, W, H)
        f.glEnable(GL_DEPTH_TEST)
        f.glDepthFunc(GL_LEQUAL)
        f.glEnable(GL_MULTISAMPLE)
        if floor:
            self._floor(f, mvp, c, R, ground)
        # modello o scultura
        prog = self._progs["obj"]
        prog.bind()
        prog.setUniformValue("u_mvp", _mat(mvp))
        prog.setUniformValue("u_eye", _vec(eye))
        prog.setUniformValue("u_light", _vec(self._light))
        prog.setUniformValue1f("u_ground", float(ground))
        layered = what != "model" and self.sculpture is not None and self.sculpture.style == "layers"
        prog.setUniformValue1f("u_lines", float(self.sculpture.thickness) if layered else 0.0)
        self._draw_objects(f, prog, what, sel, eye)
        prog.release()
        f.glDisable(GL_DEPTH_TEST)

    def _floor(self, f, mvp, c, R, ground):
        """Pavimento con la griglia e l'ombra, sfumato verso lo sfondo."""
        gp = self._progs["ground"]
        key = (round(float(c[0]), 4), round(float(c[1]), 4), round(float(R), 4), round(float(ground), 4))
        if self._ground_buf is None or self._ground_key != key:
            if self._ground_buf is not None:
                self._ground_buf.destroy()
            q = np.array([[c[0] - R, c[1] - R, ground], [c[0] + R, c[1] - R, ground], [c[0] + R, c[1] + R, ground],
                          [c[0] - R, c[1] - R, ground], [c[0] + R, c[1] + R, ground], [c[0] - R, c[1] + R, ground]],
                         np.float32)
            self._ground_buf = _Buf(q)
            self._ground_key = key
        f.glEnable(GL_BLEND)
        # colore sfumato sullo sfondo, ma la trasparenza dell'immagine resta piena (niente buchi nella finestra)
        f.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO, GL_ONE)
        gp.bind()
        gp.setUniformValue("u_mvp", _mat(mvp))
        gp.setUniformValue("u_c", _vec(c))
        gp.setUniformValue1f("u_R", float(R))
        gp.setUniformValue("u_floor", _vec(np.array([236, 233, 228]) / 255.0))
        gp.setUniformValue1f("u_blur", 0.022)
        gp.setUniformValue1f("u_has_shadow", 1.0)
        gp.setUniformValue1i("u_shadow", 0)
        f.glActiveTexture(GL_TEXTURE0)
        f.glBindTexture(GL_TEXTURE_2D, self._shadow_fbo.texture())
        self._ground_buf.buf.bind()
        gp.setAttributeBuffer(0, GL_FLOAT, 0, 3, 12)
        gp.enableAttributeArray(0)
        f.glDepthMask(False)  # il pavimento non nasconde nulla (è sotto a tutto)
        f.glDrawArrays(GL_TRIANGLES, 0, 6)
        f.glDepthMask(True)
        gp.disableAttributeArray(0)
        self._ground_buf.buf.release()
        f.glBindTexture(GL_TEXTURE_2D, 0)
        gp.release()
        f.glDisable(GL_BLEND)

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._drag is None:
            return
        d = ev.position() - self._drag
        self._drag = ev.position()
        self.yaw = (self.yaw + d.x() * 0.5) % 360.0
        self.pitch = max(-10.0, min(85.0, self.pitch + d.y() * 0.35))
        self.update()

    def mouseReleaseEvent(self, _ev):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, ev):
        k = 1.12 if ev.angleDelta().y() > 0 else 1 / 1.12
        self.zoom = max(0.4, min(4.0, self.zoom * k))
        self.update()

    def mouseDoubleClickEvent(self, _ev):
        self.reset_camera()

# -*- coding: utf-8 -*-
"""
Tela gráfica (tkinter) do Instalador Automático MSI
---------------------------------------------------
Abre depois da conversão EXE -> MSI para você escolher O QUE instalar:
  * pastas inteiras (instala tudo que existe dentro delas), ou
  * programas individuais (caixas de seleção).

Este módulo só cuida da interface; a lógica de instalação é injetada por
instalador_msi.py (veja `abrir()`), o que permite testar a tela sem Windows.

Desenvolvido por Eduardo Falabella
"""
from __future__ import annotations

import ctypes
import os
import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

# ----------------------------------------------------------------------------
# Tema
# ----------------------------------------------------------------------------
C = dict(
    bg="#0B1220", card="#111A2E", linha="#16213A", pasta="#1B2947", hover="#22345C",
    borda="#26365C", texto="#E8EEF9", suave="#9AA8C7", fraco="#64748B",
    acento="#22D3EE", acento_hover="#67E8F9", acento_txt="#06222B", indigo="#6366F1",
    ok="#34D399", erro="#F87171", aviso="#FBBF24", desab="#1E2A47",
)
SCALE = 1.0


def px(n: float) -> int:
    return max(1, int(round(n * SCALE)))


def fmt_tam(b: int) -> str:
    if b >= 1 << 30:
        return f"{b / (1 << 30):.1f} GB".replace(".", ",")
    return f"{max(1, round(b / (1 << 20)))} MB" if b else "—"


def fmt_dur(seg: int) -> str:
    return f"{seg // 60}m{seg % 60:02d}s" if seg >= 60 else f"{seg}s"


def rr(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Retângulo com cantos arredondados."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


# ----------------------------------------------------------------------------
# Widgets próprios
# ----------------------------------------------------------------------------
class Botao(tk.Canvas):
    """Botão arredondado. estilo: 'pri' (destaque), 'sec' (discreto)."""

    def __init__(self, master, texto, comando, estilo="sec", largura=170, altura=40,
                 fonte=None, bg=None):
        super().__init__(master, width=px(largura), height=px(altura), bg=bg or C["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self.texto, self.comando, self.estilo = texto, comando, estilo
        self.fonte, self.habilitado, self._hover = fonte, True, False
        self.bind("<Configure>", lambda e: self._desenhar())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._soltou)

    def _set_hover(self, v):
        self._hover = v
        self._desenhar()

    def _soltou(self, e):
        if self.habilitado and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.comando()

    def configurar(self, texto=None, habilitado=None):
        if texto is not None:
            self.texto = texto
        if habilitado is not None:
            self.habilitado = habilitado
            self.configure(cursor="hand2" if habilitado else "arrow")
        self._desenhar()

    def _desenhar(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        if not self.habilitado:
            fundo, borda, cor = C["desab"], C["desab"], C["fraco"]
        elif self.estilo == "pri":
            fundo = C["acento_hover"] if self._hover else C["acento"]
            borda, cor = fundo, C["acento_txt"]
        else:
            fundo = C["hover"] if self._hover else C["pasta"]
            borda, cor = C["borda"], C["texto"]
        rr(self, 1, 1, w - 1, h - 1, px(10), fill=fundo, outline=borda)
        self.create_text(w // 2, h // 2, text=self.texto, fill=cor, font=self.fonte)


class Check(tk.Canvas):
    """Caixa de seleção com 3 estados: 0 vazio, 1 marcado, 2 parcial."""

    def __init__(self, master, bg, tam=20):
        t = px(tam)
        super().__init__(master, width=t, height=t, bg=bg, highlightthickness=0, bd=0)
        self.t, self.estado = t, 0
        self.set(0)

    def set(self, estado: int):
        self.estado = estado
        t = self.t
        self.delete("all")
        if estado == 0:
            rr(self, 1, 1, t - 1, t - 1, px(5), fill=C["bg"], outline=C["fraco"])
            return
        rr(self, 1, 1, t - 1, t - 1, px(5), fill=C["acento"], outline=C["acento"])
        if estado == 1:
            self.create_line(t * .24, t * .53, t * .43, t * .72, t * .78, t * .30,
                             fill=C["acento_txt"], width=px(2.4), capstyle="round", joinstyle="round")
        else:
            self.create_line(t * .27, t * .5, t * .73, t * .5,
                             fill=C["acento_txt"], width=px(2.6), capstyle="round")


class Barra(tk.Canvas):
    def __init__(self, master, bg, altura=14):
        super().__init__(master, height=px(altura), bg=bg, highlightthickness=0, bd=0)
        self.frac, self.cor = 0.0, C["acento"]
        self.bind("<Configure>", lambda e: self._desenhar())

    def set(self, frac: float, cor: str | None = None):
        self.frac = max(0.0, min(1.0, frac))
        if cor:
            self.cor = cor
        self._desenhar()

    def _desenhar(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        rr(self, 0, 0, w, h, h // 2, fill=C["linha"], outline=C["borda"])
        if self.frac > 0:
            fw = max(h, int(w * self.frac))
            rr(self, 0, 0, fw, h, h // 2, fill=self.cor, outline=self.cor)


def ligar(widget, evento, fn):
    """Liga um evento ao widget e a todos os seus filhos."""
    widget.bind(evento, fn)
    for f in widget.winfo_children():
        ligar(f, evento, fn)


# ----------------------------------------------------------------------------
# Tela principal
# ----------------------------------------------------------------------------
class Tela:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._dpi()
        global SCALE
        self.root = tk.Tk()
        SCALE = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.fam = self._escolher_fonte()
        self.root.title(f"{cfg['titulo']}  v{cfg['versao']}  —  {cfg['desenvolvedor']}")
        self.root.configure(bg=C["bg"])
        self._geometria()
        self._estilos()

        self.subtitulo = "Escolha as pastas ou os programas que deseja instalar"
        self.dirs: list = []
        self.sel: dict[Path, bool] = {}
        self.expandido: dict[Path, bool] = {}
        self.checks_pasta: dict[Path, Check] = {}
        self.checks_msi: dict[Path, Check] = {}
        self.setas: dict[Path, tk.Label] = {}
        self.info: dict[Path, tuple] = {}
        self.direto = tk.BooleanVar(value=True)
        self.rodando = False
        self.cancelar = threading.Event()
        self.fila: queue.Queue = queue.Queue()
        self.resultados: list = []

        self._montar_cabecalho()
        self.corpo = tk.Frame(self.root, bg=C["bg"])
        self.corpo.pack(fill="both", expand=True, padx=px(28), pady=(px(18), px(8)))
        self._montar_rodape()          # empacota antes de 'corpo' expandir? (side=bottom)
        self._montar_selecao()
        self._montar_progresso()
        self.root.protocol("WM_DELETE_WINDOW", self._fechar)
        if cfg.get("preparar"):
            self.root.after(150, self._preparar)      # converte/repara .exe -> .msi DENTRO desta tela
        else:
            self.mostrar_selecao()
        self.root.bind("<Control-a>", lambda e: self.marcar_todos(True))

    # ------------------------------------------------------------ infraestrutura
    @staticmethod
    def _dpi():
        if os.name != "nt":
            return
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def _escolher_fonte(self) -> str:
        disp = set(tkfont.families(self.root))
        for f in ("Segoe UI", "Inter", "Helvetica Neue", "Arial", "DejaVu Sans"):
            if f in disp:
                return f
        return "TkDefaultFont"

    def F(self, tam: int, peso: str = "normal"):
        return (self.fam, tam, peso)

    def _geometria(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(px(1060), sw - px(40)), min(px(720), sh - px(80))
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(10, (sh - h) // 2 - px(20))}")
        self.root.minsize(min(px(900), w), min(px(620), h))

    def _estilos(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Dark.Vertical.TScrollbar", background=C["borda"], troughcolor=C["card"],
                     bordercolor=C["card"], arrowcolor=C["suave"], lightcolor=C["borda"],
                     darkcolor=C["borda"], gripcount=0, relief="flat")
        st.map("Dark.Vertical.TScrollbar", background=[("active", C["fraco"])])

    # ------------------------------------------------------------ cabeçalho / rodapé
    def _montar_cabecalho(self):
        h = px(92)
        self.cab = tk.Canvas(self.root, height=h, bg=C["bg"], highlightthickness=0, bd=0)
        self.cab.pack(fill="x")
        self.cab.bind("<Configure>", self._desenhar_cabecalho)

    def _desenhar_cabecalho(self, e=None):
        c = self.cab
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        # degradê horizontal  #0E1B38 -> #123A5E
        a, b = (0x0E, 0x1B, 0x38), (0x12, 0x3A, 0x5E)
        passos = 64
        for i in range(passos):
            cor = "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * i / (passos - 1)) for k in range(3))
            c.create_rectangle(w * i / passos, 0, w * (i + 1) / passos + 1, h, fill=cor, outline=cor)
        c.create_line(0, h - 1, w, h - 1, fill=C["acento"], width=px(2))
        # selo
        x0, y0, t = px(28), (h - px(52)) // 2, px(52)
        rr(c, x0, y0, x0 + t, y0 + t, px(13), fill=C["acento"], outline=C["acento"])
        c.create_text(x0 + t // 2, y0 + t // 2, text="MSI", fill=C["acento_txt"], font=self.F(14, "bold"))
        c.create_text(x0 + t + px(16), h // 2 - px(13), anchor="w", text=self.cfg["titulo"],
                      fill=C["texto"], font=self.F(20, "bold"))
        c.create_text(x0 + t + px(16), h // 2 + px(15), anchor="w", text=self.subtitulo,
                      fill=C["suave"], font=self.F(10))
        # selo de privilégio
        adm = self.cfg.get("admin", True)
        txt, cor = ("●  Administrador", C["ok"]) if adm else ("●  Sem privilégios de administrador", C["aviso"])
        c.create_text(w - px(28), h // 2, anchor="e", text=txt, fill=cor, font=self.F(10, "bold"))

    def _montar_rodape(self):
        rod = tk.Frame(self.root, bg=C["bg"])
        rod.pack(side="bottom", fill="x", before=self.corpo)
        tk.Frame(rod, bg=C["borda"], height=1).pack(fill="x")
        interno = tk.Frame(rod, bg=C["bg"])
        interno.pack(fill="x", pady=px(9))
        tk.Label(interno, text=f"v{self.cfg['versao']}", bg=C["bg"], fg=C["fraco"],
                 font=self.F(9)).pack(side="left", padx=px(28))
        tk.Label(interno, text=f"Desenvolvido por  {self.cfg['desenvolvedor']}", bg=C["bg"],
                 fg=C["suave"], font=self.F(10, "bold")).place(relx=0.5, rely=0.5, anchor="center")

    # ------------------------------------------------------------ tela 1: seleção
    def _montar_selecao(self):
        self.v_sel = tk.Frame(self.corpo, bg=C["bg"])

        # coluna direita (resumo)
        dir_ = tk.Frame(self.v_sel, bg=C["card"], highlightbackground=C["borda"], highlightthickness=1,
                        width=px(300))
        dir_.pack(side="right", fill="y", padx=(px(18), 0))
        dir_.pack_propagate(False)
        tk.Label(dir_, text="RESUMO DA SELEÇÃO", bg=C["card"], fg=C["suave"], font=self.F(9, "bold")
                 ).pack(anchor="w", padx=px(20), pady=(px(20), px(2)))
        self.l_qtd = tk.Label(dir_, text="0", bg=C["card"], fg=C["acento"], font=self.F(44, "bold"))
        self.l_qtd.pack(anchor="w", padx=px(20))
        self.l_qtd_txt = tk.Label(dir_, text="programas selecionados", bg=C["card"], fg=C["texto"],
                                  font=self.F(11))
        self.l_qtd_txt.pack(anchor="w", padx=px(20))
        tk.Frame(dir_, bg=C["borda"], height=1).pack(fill="x", padx=px(20), pady=px(16))
        self.l_pastas = tk.Label(dir_, text="", bg=C["card"], fg=C["suave"], font=self.F(10), anchor="w")
        self.l_pastas.pack(fill="x", padx=px(20))
        self.l_tam = tk.Label(dir_, text="", bg=C["card"], fg=C["suave"], font=self.F(10), anchor="w")
        self.l_tam.pack(fill="x", padx=px(20), pady=(px(4), 0))

        opt = tk.Frame(dir_, bg=C["card"])
        opt.pack(fill="x", padx=px(20), pady=(px(18), 0))
        self.ck_direto = Check(opt, C["card"], 18)
        self.ck_direto.pack(side="left", anchor="n", pady=px(2))
        self.ck_direto.set(1)
        tk.Label(opt, text="Executar instaladores embutidos diretamente (recomendado: evita o erro 1603)",
                 bg=C["card"], fg=C["suave"], font=self.F(9), justify="left", anchor="w",
                 wraplength=px(215)).pack(side="left", padx=(px(10), 0))
        ligar(opt, "<Button-1>", self._alternar_direto)

        self.aviso_adm = tk.Label(dir_, text="", bg=C["card"], fg=C["aviso"], font=self.F(9),
                                  wraplength=px(250), justify="left")
        self.aviso_adm.pack(anchor="w", padx=px(20), pady=(px(10), 0))
        if not self.cfg.get("admin", True):
            self.aviso_adm.configure(text="Execute como administrador para instalar.")

        base = tk.Frame(dir_, bg=C["card"])
        base.pack(side="bottom", fill="x", padx=px(20), pady=px(20))
        self.b_instalar = Botao(base, "INSTALAR SELECIONADOS", self.instalar_selecionados, "pri",
                                altura=50, fonte=self.F(11, "bold"), bg=C["card"])
        self.b_instalar.pack(fill="x")
        linha = tk.Frame(base, bg=C["card"])
        linha.pack(fill="x", pady=(px(10), 0))
        Botao(linha, "Selecionar tudo", lambda: self.marcar_todos(True), "sec", altura=36,
              fonte=self.F(9), bg=C["card"]).pack(side="left", fill="x", expand=True, padx=(0, px(5)))
        Botao(linha, "Limpar", lambda: self.marcar_todos(False), "sec", altura=36,
              fonte=self.F(9), bg=C["card"]).pack(side="left", fill="x", expand=True, padx=(px(5), 0))
        Botao(base, "Atualizar lista", self.recarregar, "sec", altura=36, fonte=self.F(9),
              bg=C["card"]).pack(fill="x", pady=(px(10), 0))

        # coluna esquerda (lista)
        esq = tk.Frame(self.v_sel, bg=C["card"], highlightbackground=C["borda"], highlightthickness=1)
        esq.pack(side="left", fill="both", expand=True)
        topo = tk.Frame(esq, bg=C["card"])
        topo.pack(fill="x", padx=px(16), pady=px(14))
        tk.Label(topo, text="Programas disponíveis", bg=C["card"], fg=C["texto"],
                 font=self.F(13, "bold")).pack(side="left")
        self.filtro = tk.StringVar()
        self.filtro.trace_add("write", lambda *a: self._construir_lista())
        caixa = tk.Frame(topo, bg=C["linha"], highlightbackground=C["borda"], highlightthickness=1)
        caixa.pack(side="right")
        self.entrada = tk.Entry(caixa, textvariable=self.filtro, bg=C["linha"], fg=C["texto"],
                                insertbackground=C["acento"], relief="flat", font=self.F(10), width=24,
                                highlightthickness=0)
        self.entrada.pack(padx=px(10), pady=px(6))
        tk.Label(topo, text="Filtrar:", bg=C["card"], fg=C["fraco"], font=self.F(9)
                 ).pack(side="right", padx=(0, px(8)))
        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x")

        area = tk.Frame(esq, bg=C["card"])
        area.pack(fill="both", expand=True)
        self.cv = tk.Canvas(area, bg=C["card"], highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(area, orient="vertical", command=self.cv.yview, style="Dark.Vertical.TScrollbar")
        self.cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.cv, bg=C["card"])
        self._janela = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self._janela, width=e.width))
        self.root.bind_all("<MouseWheel>", self._rolar)
        self.root.bind_all("<Button-4>", self._rolar)
        self.root.bind_all("<Button-5>", self._rolar)

    def _rolar(self, e):
        if not str(e.widget).startswith(str(self.cv)) or not self.v_sel.winfo_ismapped():
            return
        if self.inner.winfo_reqheight() <= self.cv.winfo_height():
            return
        passo = -1 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 1
        self.cv.yview_scroll(passo * 3, "units")

    def _alternar_direto(self, e=None):
        self.direto.set(not self.direto.get())
        self.ck_direto.set(1 if self.direto.get() else 0)

    # ------------------------------------------------------------ dados / lista
    def recarregar(self):
        self.dirs = self.cfg["obter_dirs"]()
        antigos = dict(self.sel)
        self.sel = {}
        self.info = {}
        for pasta, msis in self.dirs:
            self.expandido.setdefault(pasta, True)
            for m in msis:
                self.sel[m] = antigos.get(m, False)
                try:
                    self.info[m] = self.cfg["classificar"](m)
                except Exception:
                    self.info[m] = ("MSI", 0)
        self._construir_lista()

    def _construir_lista(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.checks_pasta.clear()
        self.checks_msi.clear()
        self.setas.clear()
        termo = self.filtro.get().strip().lower()
        mostrou = False
        for pasta, msis in self.dirs:
            vis = [m for m in msis if not termo or termo in m.name.lower() or termo in pasta.name.lower()]
            if not vis:
                continue
            mostrou = True
            self._linha_pasta(pasta, msis, vis)
            if self.expandido.get(pasta, True):
                for m in vis:
                    self._linha_msi(pasta, m)
        if not mostrou:
            msg = ("Nenhum programa corresponde ao filtro." if termo else
                   "Nenhuma pasta com arquivos .msi foi encontrada.\nColoque as pastas ao lado do INSTALAR.bat "
                   "e clique em “Atualizar lista”.")
            tk.Label(self.inner, text=msg, bg=C["card"], fg=C["suave"], font=self.F(11),
                     justify="center").pack(pady=px(60), padx=px(20))
        self._atualizar_estados()
        self.cv.yview_moveto(0)

    def _hover(self, linha, cor_base):
        def entra(e): linha.configure(bg=C["hover"]); [w.configure(bg=C["hover"]) for w in linha.winfo_children()
                                                        if isinstance(w, (tk.Label, tk.Frame))]
        def sai(e): linha.configure(bg=cor_base); [w.configure(bg=cor_base) for w in linha.winfo_children()
                                                    if isinstance(w, (tk.Label, tk.Frame))]
        linha.bind("<Enter>", entra)
        linha.bind("<Leave>", sai)

    def _linha_pasta(self, pasta, todos, visiveis):
        base = C["pasta"]
        linha = tk.Frame(self.inner, bg=base, cursor="hand2")
        linha.pack(fill="x", pady=(px(6), 0))
        seta = tk.Label(linha, text="▾" if self.expandido.get(pasta, True) else "▸", bg=base,
                        fg=C["acento"], font=self.F(12, "bold"), width=2, cursor="hand2")
        seta.pack(side="left", padx=(px(10), 0), pady=px(10))
        seta.bind("<Button-1>", lambda e, p=pasta: self._alternar_expansao(p))
        self.setas[pasta] = seta
        ck = Check(linha, base, 20)
        ck.pack(side="left", padx=(px(2), px(12)))
        self.checks_pasta[pasta] = ck
        tk.Label(linha, text=pasta.name, bg=base, fg=C["texto"], font=self.F(12, "bold")
                 ).pack(side="left")
        tam = sum(self.info.get(m, ("", 0))[1] for m in todos)
        tk.Label(linha, text=f"{len(todos)} pacote(s) · {fmt_tam(tam)}", bg=base, fg=C["suave"],
                 font=self.F(9)).pack(side="right", padx=px(16))
        for w in (ck, *[x for x in linha.winfo_children() if isinstance(x, tk.Label) and x is not seta]):
            w.bind("<Button-1>", lambda e, p=pasta: self._alternar_pasta(p))
        linha.bind("<Button-1>", lambda e, p=pasta: self._alternar_pasta(p))

    def _linha_msi(self, pasta, msi):
        base = C["linha"]
        linha = tk.Frame(self.inner, bg=base, cursor="hand2")
        linha.pack(fill="x", pady=(1, 0))
        tk.Frame(linha, bg=base, width=px(40)).pack(side="left")
        ck = Check(linha, base, 18)
        ck.pack(side="left", padx=(px(2), px(12)), pady=px(9))
        self.checks_msi[msi] = ck
        nome = msi.stem
        tk.Label(linha, text=nome, bg=base, fg=C["texto"], font=self.F(10), anchor="w").pack(side="left")
        try:
            rel = msi.parent.relative_to(pasta)
            if str(rel) != ".":
                tk.Label(linha, text=f"  ›  {rel}", bg=base, fg=C["fraco"], font=self.F(9)).pack(side="left")
        except ValueError:
            pass
        tag, tam = self.info.get(msi, ("MSI", 0))
        tk.Label(linha, text=fmt_tam(tam), bg=base, fg=C["suave"], font=self.F(9), width=9, anchor="e"
                 ).pack(side="right", padx=(0, px(16)))
        fg, bgc = ("#A5B4FC", "#262B63") if tag.startswith("EXE") else ("#6EE7B7", "#123A31")
        tk.Label(linha, text=f" {tag} ", bg=bgc, fg=fg, font=self.F(8, "bold")).pack(side="right", padx=px(8))
        ligar(linha, "<Button-1>", lambda e, m=msi: self._alternar_msi(m))

    # ------------------------------------------------------------ seleção
    def _alternar_expansao(self, pasta):
        self.expandido[pasta] = not self.expandido.get(pasta, True)
        pos = self.cv.yview()[0]
        self._construir_lista()
        self.cv.yview_moveto(pos)

    def _alternar_msi(self, msi):
        self.sel[msi] = not self.sel.get(msi, False)
        self._atualizar_estados()

    def _alternar_pasta(self, pasta):
        msis = next(m for p, m in self.dirs if p == pasta)
        novo = not all(self.sel.get(m) for m in msis)
        for m in msis:
            self.sel[m] = novo
        self._atualizar_estados()

    def marcar_todos(self, valor: bool):
        if self.rodando:
            return
        for m in self.sel:
            self.sel[m] = valor
        self._atualizar_estados()

    def _atualizar_estados(self):
        for pasta, msis in self.dirs:
            if pasta in self.checks_pasta:
                n = sum(1 for m in msis if self.sel.get(m))
                self.checks_pasta[pasta].set(0 if n == 0 else (1 if n == len(msis) else 2))
        for m, ck in self.checks_msi.items():
            ck.set(1 if self.sel.get(m) else 0)
        escolhidos = [m for m, v in self.sel.items() if v]
        n = len(escolhidos)
        self.l_qtd.configure(text=str(n))
        self.l_qtd_txt.configure(text="programa selecionado" if n == 1 else "programas selecionados")
        pastas_sel = sum(1 for _, ms in self.dirs if any(self.sel.get(m) for m in ms))
        self.l_pastas.configure(text=f"Pastas envolvidas:  {pastas_sel} de {len(self.dirs)}")
        self.l_tam.configure(text=f"Tamanho total:  {fmt_tam(sum(self.info.get(m, ('', 0))[1] for m in escolhidos))}")
        self.b_instalar.configurar(habilitado=n > 0 and self.cfg.get("admin", True))

    # ------------------------------------------------------------ tela 2: progresso
    def _montar_progresso(self):
        self.v_prog = tk.Frame(self.corpo, bg=C["bg"])
        topo = tk.Frame(self.v_prog, bg=C["card"], highlightbackground=C["borda"], highlightthickness=1)
        topo.pack(fill="x")
        self.p_titulo = tk.Label(topo, text="Instalando…", bg=C["card"], fg=C["texto"], font=self.F(16, "bold"))
        self.p_titulo.pack(anchor="w", padx=px(22), pady=(px(18), 0))
        self.p_atual = tk.Label(topo, text="", bg=C["card"], fg=C["acento"], font=self.F(12, "bold"),
                                anchor="w", justify="left")
        self.p_atual.pack(fill="x", padx=px(22), pady=(px(4), 0))
        self.p_detalhe = tk.Label(topo, text="", bg=C["card"], fg=C["suave"], font=self.F(10), anchor="w")
        self.p_detalhe.pack(fill="x", padx=px(22), pady=(px(2), px(12)))
        self.barra = Barra(topo, C["card"], 16)
        self.barra.pack(fill="x", padx=px(22))
        info = tk.Frame(topo, bg=C["card"])
        info.pack(fill="x", padx=px(22), pady=(px(10), px(18)))
        self.p_cont = tk.Label(info, text="", bg=C["card"], fg=C["suave"], font=self.F(10))
        self.p_cont.pack(side="left")
        self.p_falhas = tk.Label(info, text="", bg=C["card"], fg=C["erro"], font=self.F(10, "bold"))
        self.p_falhas.pack(side="right")
        self.p_oks = tk.Label(info, text="", bg=C["card"], fg=C["ok"], font=self.F(10, "bold"))
        self.p_oks.pack(side="right", padx=(0, px(18)))

        self.acoes = tk.Frame(self.v_prog, bg=C["bg"])
        self.acoes.pack(side="bottom", fill="x")          # reservado antes do log (que é elástico)
        logbox = tk.Frame(self.v_prog, bg=C["card"], highlightbackground=C["borda"], highlightthickness=1)
        logbox.pack(fill="both", expand=True, pady=(px(14), px(14)))
        sb = ttk.Scrollbar(logbox, orient="vertical", style="Dark.Vertical.TScrollbar")
        self.log = tk.Text(logbox, bg=C["card"], fg=C["texto"], relief="flat", wrap="word", bd=0,
                           font=(("Consolas" if os.name == "nt" else "DejaVu Sans Mono"), 10),
                           padx=px(16), pady=px(12), state="disabled", highlightthickness=0, height=6,
                           yscrollcommand=sb.set, cursor="arrow")
        sb.configure(command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        for tag, cor in (("ok", C["ok"]), ("erro", C["erro"]), ("info", C["suave"]),
                         ("aviso", C["aviso"]), ("nome", C["texto"]), ("hora", C["fraco"])):
            self.log.tag_configure(tag, foreground=cor)

        self.b_logs = Botao(self.acoes, "Abrir pasta de logs", self.cfg["abrir_logs"], "sec", 190, 40,
                            self.F(10))
        self.b_cancelar = Botao(self.acoes, "Cancelar após o item atual", self._cancelar, "sec", 230, 40,
                                self.F(10))
        self.b_fechar = Botao(self.acoes, "Fechar", self._fechar, "sec", 120, 40, self.F(10))
        self.b_voltar = Botao(self.acoes, "Voltar à seleção", self._voltar, "pri", 180, 40, self.F(10, "bold"))
        self.b_refazer = Botao(self.acoes, "Reinstalar falhas", self._reinstalar_falhas, "sec", 170, 40,
                               self.F(10))

    def _log(self, partes: list):
        self.log.configure(state="normal")
        for txt, tag in partes:
            self.log.insert("end", txt, tag)
        self.log.insert("end", "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ navegação
    def _subtitulo(self, txt: str):
        self.subtitulo = txt
        self._desenhar_cabecalho()

    def mostrar_selecao(self):
        self._subtitulo("Escolha as pastas ou os programas que deseja instalar")
        self.v_prog.pack_forget()
        self.v_sel.pack(fill="both", expand=True)
        self.recarregar()

    def _mostrar_progresso(self):
        self._subtitulo("Instalação em andamento — acompanhe o progresso abaixo")
        self.v_sel.pack_forget()
        self.v_prog.pack(fill="both", expand=True)

    def _voltar(self):
        if not self.rodando:
            self.mostrar_selecao()

    def _fechar(self):
        if self.rodando and not messagebox.askyesno(
                "Operação em andamento",
                "Há uma operação em andamento (conversão ou instalação).\n"
                "Sair agora pode deixá-la incompleta.\n\nDeseja sair mesmo assim?"):
            return
        self.cancelar.set()
        self.root.destroy()

    def _cancelar(self):
        self.cancelar.set()
        self.b_cancelar.configurar("Cancelando após o item atual…", False)

    # ------------------------------------------------------------ preparação (EXE -> MSI)
    def _preparar(self):
        self.resultados = []
        self.rodando = True
        self.fila = queue.Queue()
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.p_titulo.configure(text="Preparando os pacotes…", fg=C["texto"])
        self.p_atual.configure(text="Verificando e convertendo instaladores .exe em .msi")
        self.p_detalhe.configure(text="Só leva tempo quando há .exe novos nas pastas.")
        for w in (self.p_oks, self.p_falhas, self.p_cont):
            w.configure(text="")
        self.barra.set(0, C["acento"])
        for b in (self.b_logs, self.b_cancelar, self.b_fechar, self.b_voltar, self.b_refazer):
            b.pack_forget()
        self.b_logs.pack(side="left")
        self.v_sel.pack_forget()
        self.v_prog.pack(fill="both", expand=True)
        self._subtitulo("Preparando — aguarde, a seleção abre em seguida")
        cb = lambda ev, **kw: self.fila.put((ev, kw))   # noqa: E731

        def trabalho():
            try:
                self.cfg["preparar"](cb)
            except Exception as exc:  # noqa: BLE001
                self.fila.put(("erro", {"msg": f"preparação: {exc}"}))
            self.fila.put(("preparado", {}))

        threading.Thread(target=trabalho, daemon=True).start()
        self.root.after(120, self._bombear)

    def _ev_aviso(self, msg, nivel="info", **_):
        tag = {"ok": "ok", "erro": "erro", "aviso": "aviso"}.get(nivel, "info")
        self._log([(f"{self._hora()}  ", "hora"), (str(msg), tag)])

    def _ev_prep_item(self, i, total, nome, **_):
        self.p_atual.configure(text=nome)
        self.p_detalhe.configure(text=f"Convertendo .exe em .msi   ·   {i} de {total}")
        self.barra.set((i - 1) / max(total, 1), C["acento"])
        self.p_cont.configure(text=f"{i} de {total}")

    def _ev_preparado(self, **_):
        self.rodando = False
        self.mostrar_selecao()

    # ------------------------------------------------------------ instalação
    def instalar_selecionados(self):
        itens = []
        for pasta, msis in self.dirs:
            marcados = [m for m in msis if self.sel.get(m)]
            if marcados:
                itens.append((pasta, marcados))
        if not itens:
            return
        qtd = sum(len(m) for _, m in itens)
        if not messagebox.askyesno("Confirmar instalação",
                                   f"Instalar {qtd} programa(s) em {len(itens)} pasta(s)?\n\n"
                                   "Os instaladores rodam em modo silencioso e podem levar vários minutos."):
            return
        self._iniciar(itens)

    def _reinstalar_falhas(self):
        falhas: dict[Path, list] = {}
        for pasta, msi, ok in self.resultados:
            if not ok:
                falhas.setdefault(pasta, []).append(msi)
        if falhas:
            self._iniciar(list(falhas.items()))

    def _iniciar(self, itens):
        self.resultados = []
        self.rodando = True
        self.cancelar = threading.Event()
        self.fila = queue.Queue()
        self.total = sum(len(m) for _, m in itens)
        self.n_ok = self.n_falha = 0
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.p_titulo.configure(text="Instalando…", fg=C["texto"])
        self.p_atual.configure(text="Preparando…")
        self.p_detalhe.configure(text="")
        self.p_oks.configure(text="")
        self.p_falhas.configure(text="")
        self.p_cont.configure(text=f"0 de {self.total}")
        self.barra.set(0, C["acento"])
        for b in (self.b_logs, self.b_cancelar, self.b_fechar, self.b_voltar, self.b_refazer):
            b.pack_forget()
        self.b_cancelar.configurar("Cancelar após o item atual", True)
        self.b_cancelar.pack(side="right")
        self.b_logs.pack(side="left")
        self._mostrar_progresso()

        cb = lambda ev, **kw: self.fila.put((ev, kw))   # noqa: E731
        direto = self.direto.get()

        def trabalho():
            try:
                self.cfg["instalar"](itens, cb, self.cancelar, direto)
            except Exception as exc:  # noqa: BLE001
                self.fila.put(("erro", {"msg": str(exc)}))
            self.fila.put(("terminou", {}))

        threading.Thread(target=trabalho, daemon=True).start()
        self.root.after(120, self._bombear)

    def _bombear(self):
        try:
            while True:
                ev, kw = self.fila.get_nowait()
                fn = getattr(self, "_ev_" + ev, None)
                if fn:
                    fn(**kw)
        except queue.Empty:
            pass
        if self.rodando or not self.fila.empty():
            self.root.after(120, self._bombear)

    @staticmethod
    def _hora() -> str:
        return datetime.now().strftime("%H:%M:%S")

    # -- eventos vindos do instalador (thread de trabalho)
    def _ev_inicio(self, total, **_):
        self.total = total
        self.p_cont.configure(text=f"0 de {total}")

    def _ev_item(self, i, total, pasta, msi, modo, **_):
        self.p_atual.configure(text=msi.stem)
        modo_txt = "instalador embutido (modo direto)" if modo == "direto" else "msiexec"
        self.p_detalhe.configure(text=f"{pasta.name}   ·   {modo_txt}   ·   item {i} de {total}")
        self._log([(f"{self._hora()}  ", "hora"), ("▶ ", "info"), (f"{pasta.name} › {msi.name}", "nome")])

    def _ev_batimento(self, seg, etapa, **_):
        extra = f"   ·   etapa: {etapa}" if etapa and etapa != "instalador embutido" else ""
        base = self.p_detalhe.cget("text").split("   ·   há ")[0]
        self.p_detalhe.configure(text=f"{base}   ·   há {fmt_dur(seg)}{extra}")

    def _ev_resultado(self, i, total, pasta, msi, codigo, status, dur, ok, **_):
        self.resultados.append((pasta, msi, ok))
        if ok:
            self.n_ok += 1
        else:
            self.n_falha += 1
        self._log([(f"{self._hora()}  ", "hora"), ("●" + " ", "ok" if ok else "erro"),
                   (f"{status}", "ok" if ok else "erro"), (f"   ({fmt_dur(dur)})", "hora")])
        self.barra.set(i / max(total, 1), C["acento"] if not self.n_falha else C["aviso"])
        self.p_cont.configure(text=f"{i} de {total}")
        self.p_oks.configure(text=f"{self.n_ok} com sucesso")
        self.p_falhas.configure(text=f"{self.n_falha} com falha" if self.n_falha else "")

    def _ev_fim(self, ok, falhas, reboot, cancelado, **_):
        self._subtitulo("Instalação finalizada")
        if cancelado:
            self.p_titulo.configure(text="Instalação cancelada", fg=C["aviso"])
        elif falhas:
            self.p_titulo.configure(text="Concluída com falhas", fg=C["aviso"])
        else:
            self.p_titulo.configure(text="Instalação concluída com sucesso", fg=C["ok"])
            self.barra.set(1.0, C["ok"])
        self.p_atual.configure(text=f"{ok} com sucesso  ·  {falhas} com falha")
        self.p_detalhe.configure(text="Detalhes de cada instalador ficam na pasta de logs.")
        if reboot:
            self._log([("", "info")])
            self._log([("Reinicie o computador para concluir algumas instalações.", "aviso")])

    def _ev_erro(self, msg, **_):
        self._log([(f"{self._hora()}  ERRO: {msg}", "erro")])

    def _ev_terminou(self, **_):
        self.rodando = False
        self.b_cancelar.pack_forget()
        self.b_fechar.pack(side="right")
        self.b_voltar.pack(side="right", padx=(0, px(10)))
        if any(not ok for _, _, ok in self.resultados):
            self.b_refazer.pack(side="right", padx=(0, px(10)))

    def executar(self):
        self.root.mainloop()


def abrir(cfg: dict) -> None:
    """Abre a tela. cfg:
        titulo, versao, desenvolvedor : textos
        admin        : bool
        obter_dirs() : -> [(Path pasta, [Path msi, ...]), ...]
        classificar(msi) : -> (rótulo 'MSI'/'EXE→MSI', tamanho_bytes)
        instalar(itens, callback, cancelar, direto) : roda a instalação (bloqueante)
        abrir_logs() : abre a pasta de logs
    """
    Tela(cfg).executar()

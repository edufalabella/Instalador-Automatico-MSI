# -*- coding: utf-8 -*-
"""
Análise rápida de um .exe: É INSTALADOR, PROGRAMA PORTÁTIL ou MENU DE AUTORUN?
------------------------------------------------------------------------------
Nada é executado. Lê só o necessário (cabeçalho PE, tabela de seções, recursos, início dos dados
anexados ao final do executável e o fim do arquivo) - em geral poucos MB, mesmo para um .exe de 5 GB.

Indícios usados (nesta ordem):
  1. Assinatura de um motor de instalação conhecido (WiX Burn, Inno Setup, NSIS, InstallShield,
     Advanced Installer, InstallAware, Wise, Setup Factory, Squirrel, Qt IFW, IExpress, SFX do WinRAR/7-Zip)
     -> INSTALADOR, com o argumento silencioso certo.
  2. Aplicativo empacotado em um único .exe (Launch4j/Java, PyInstaller, .NET single-file) -> PORTÁTIL.
  3. Menu de CD/pen drive (AutoPlay Media Studio, autorun.exe) -> MENU (só funciona com cliques).
  4. Nome/descrição com "setup", "install", "redist", "runtime", "update"... -> INSTALADOR.
  5. Dados anexados grandes ou recursos grandes (o "pacote" do instalador) -> INSTALADOR.
  6. Nada disso -> PORTÁTIL (o próprio programa: abre e fica aberto; não deve ser "instalado").
"""
from __future__ import annotations

import re
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

VERSAO_ANALISE = "1.1"
LER_CABECA = 1 << 20        # início do arquivo (stub do instalador)
LER_RSRC = 6 << 20          # seção de recursos (versão, manifesto)
LER_OVERLAY = 1 << 20       # começo dos dados anexados (onde ficam as marcas do NSIS/Inno/SFX)
LER_CAUDA = 256 << 10       # fim do arquivo (PyInstaller, .NET single-file)

# (bytes procurados, tipo, argumentos silenciosos) - ordem = prioridade
ASSINATURAS = [
    (b"Inno Setup Setup Data", "Inno Setup", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-"),
    (b"InnoSetupLdrWindow", "Inno Setup", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-"),
    (b"NullsoftInst", "NSIS", "/S"),
    (b"Nullsoft Install System", "NSIS", "/S"),
    (b"Nullsoft.NSIS", "NSIS", "/S"),
    (b"InstallShield", "InstallShield", '/s /v"/qn REBOOT=ReallySuppress"'),
    (b"Advanced Installer", "Advanced Installer", "/exenoui /qn /norestart"),
    (b"Caphyon", "Advanced Installer", "/exenoui /qn /norestart"),
    (b"InstallAware", "InstallAware", "/s"),
    (b"WiseMain", "Wise", "/s"),
    (b"Wise Installation", "Wise", "/s"),
    (b"Setup Factory", "Setup Factory", "/S"),
    (b"SquirrelSetup", "Squirrel", "--silent"),
    (b"Squirrel.Windows", "Squirrel", "--silent"),
    (b"QtInstallerFramework", "Qt Installer Framework",
     "--accept-licenses --default-answer --confirm-command install"),
    (b"ifw.installer", "Qt Installer Framework",
     "--accept-licenses --default-answer --confirm-command install"),
]
# empacotadores de APLICATIVO (o .exe é o próprio programa, não instala nada)
PORTATEIS = [
    (b"launch4j", "Java (Launch4j)"),
    (b"MEI\x0c\x0b\x0a\x0b\x0e", "PyInstaller"),
    (bytes.fromhex("8b1202b96a612038727b930214d7a03213f5b9e6efae3318ee3b2dce24b36aae"), ".NET (arquivo único)"),
]
MENUS = [b"AutoPlay Media Studio", b"AutoPlay Menu", b"Autorun Pro", b"AutoRun Menu"]
NOMES_MENU = {"autorun", "autoplay", "autorun_menu", "menu"}
NOMES_INSTALADOR = re.compile(
    r"setup|instal|redist|runtime|bootstrap|update|upgrade|deploy|downloader|wextract|self[- ]?extract|"
    r"\bsfx\b|prereq|_full_|driver[ _-]?(?:pack|install)|vcredist|dotnetfx|ndp\d|\bkb\d{5,}", re.I)
# na DESCRIÇÃO só palavras fortes (".NET Runtime Crash Dump Generator" não é instalador)
DESCRICAO_INSTALADOR = re.compile(r"setup|instal|redistributable|bootstrapper|self[- ]?extract|downloader", re.I)
NOMES_NAO_INSTALADOR = re.compile(r"uninst|unins\d|unwise|^uninstall", re.I)

CHAVES_VERSAO = ("FileDescription", "ProductName", "CompanyName", "OriginalFilename", "InternalName",
                 "Comments", "FileVersion", "ProductVersion")


@dataclass
class AnaliseExe:
    categoria: str = "instalador"      # instalador | portatil | menu | desinstalador | invalido
    tipo: str = ""                     # motor detectado (NSIS, Inno Setup...) ou empacotador do portátil
    args: str = ""                     # argumento silencioso preferido ("" = desconhecido)
    motivo: str = ""                   # por que foi classificado assim (vai para o relatório)
    descricao: str = ""                # FileDescription / ProductName (nome bonito para atalhos)
    empresa: str = ""
    versao: str = ""
    admin: bool = False                # manifesto pede administrador
    bits: int = 0                      # 32 / 64
    gui: bool = True                   # subsistema gráfico (False = console)
    overlay: int = 0                   # bytes anexados ao final (fora o certificado digital)
    extra: dict = field(default_factory=dict)

    def para_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def de_dict(d: dict) -> "AnaliseExe":
        campos = {k: v for k, v in (d or {}).items() if k in AnaliseExe.__dataclass_fields__}
        return AnaliseExe(**campos)

    @property
    def rotulo(self) -> str:
        return {"portatil": "PORTÁTIL", "menu": "MENU", "desinstalador": "DESINSTALADOR"}.get(self.categoria, "EXE")


# ----------------------------------------------------------------------------
# PE
# ----------------------------------------------------------------------------
@dataclass
class _PE:
    secoes: list            # [(nome, va, vsize, raw_ptr, raw_size)]
    fim_imagem: int
    cert: tuple             # (offset, tamanho) no arquivo
    rsrc_rva: int
    bits: int
    gui: bool


def _ler_pe(cab: bytes) -> Optional[_PE]:
    if len(cab) < 0x40 or cab[:2] != b"MZ":
        return None
    e_lfanew = struct.unpack_from("<I", cab, 0x3C)[0]
    if e_lfanew + 24 > len(cab) or cab[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return None
    coff = e_lfanew + 4
    n_sec, tam_opt = struct.unpack_from("<H", cab, coff + 2)[0], struct.unpack_from("<H", cab, coff + 16)[0]
    opt = coff + 20
    if opt + 2 > len(cab):
        return None
    magic = struct.unpack_from("<H", cab, opt)[0]
    pe64 = magic == 0x20B
    subsistema = struct.unpack_from("<H", cab, opt + 68)[0] if opt + 70 <= len(cab) else 2
    dd = opt + (112 if pe64 else 96)
    n_dd = struct.unpack_from("<I", cab, dd - 4)[0] if dd <= len(cab) else 0

    def dir_(i: int) -> tuple:
        if i >= n_dd or dd + 8 * i + 8 > len(cab):
            return 0, 0
        return struct.unpack_from("<II", cab, dd + 8 * i)

    rsrc_rva, _ = dir_(2)
    cert = dir_(4)
    secoes, fim = [], 0
    tab = opt + tam_opt
    for i in range(min(n_sec, 96)):
        p = tab + 40 * i
        if p + 40 > len(cab):
            break
        nome = cab[p:p + 8].rstrip(b"\0").decode("latin-1", "replace")
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", cab, p + 8)
        secoes.append((nome, va, vsize, raw_ptr, raw_size))
        if raw_size:
            fim = max(fim, raw_ptr + raw_size)
    return _PE(secoes, fim, cert, rsrc_rva, 64 if pe64 else 32, subsistema == 2)


def _texto_versao(rsrc: bytes, chave: str) -> str:
    """Valor de uma chave do VS_VERSIONINFO (procura a chave em UTF-16 e lê o valor que vem depois)."""
    alvo = chave.encode("utf-16-le") + b"\0\0"
    i = rsrc.find(alvo)
    if i < 0:
        return ""
    p = i + len(alvo)
    while p + 1 < len(rsrc) and rsrc[p:p + 2] == b"\0\0" and p - i < len(alvo) + 8:
        p += 2
    if (p - i) % 2:
        p += 1
    fim = p
    while fim + 1 < len(rsrc) and rsrc[fim:fim + 2] != b"\0\0" and fim - p < 520:
        fim += 2
    try:
        return rsrc[p:fim].decode("utf-16-le", "ignore").strip()
    except Exception:  # noqa: BLE001
        return ""


def _ler(f, pos: int, n: int) -> bytes:
    if n <= 0:
        return b""
    f.seek(max(pos, 0))
    return f.read(n)


# ----------------------------------------------------------------------------
# Análise
# ----------------------------------------------------------------------------
def analisar(exe: Path) -> AnaliseExe:
    exe = Path(exe)
    a = AnaliseExe()
    nome = exe.stem.lower()
    try:
        tam = exe.stat().st_size
        with open(exe, "rb") as f:
            cab = f.read(min(tam, LER_CABECA))
            pe = _ler_pe(cab[:1 << 16] if len(cab) > 1 << 16 else cab)
            if pe is None:
                a.categoria, a.motivo = "invalido", "não é um executável do Windows"
                return a
            a.bits, a.gui = pe.bits, pe.gui

            # recursos (versão + manifesto)
            rsrc = b""
            for nome_s, va, vsize, raw_ptr, raw_size in pe.secoes:
                if pe.rsrc_rva and va <= pe.rsrc_rva < va + max(vsize, raw_size):
                    ini = raw_ptr + (pe.rsrc_rva - va)
                    rsrc = _ler(f, ini, min(raw_size - (pe.rsrc_rva - va), LER_RSRC))
                    a.extra["rsrc"] = raw_size
                    break

            # dados anexados (overlay) - o certificado digital (no fim) não conta
            fim_dados = tam
            c_off, c_tam = pe.cert
            if c_off and c_tam and c_off >= pe.fim_imagem and c_off + c_tam >= tam - 16:
                fim_dados = c_off
            a.overlay = max(fim_dados - pe.fim_imagem, 0)
            ov = _ler(f, pe.fim_imagem, min(a.overlay, LER_OVERLAY)) if a.overlay else b""
            cauda = _ler(f, max(fim_dados - LER_CAUDA, 0), min(LER_CAUDA, fim_dados)) if tam > LER_CABECA else b""
    except OSError as exc:
        a.categoria, a.motivo = "invalido", f"não foi possível ler ({exc.strerror or exc})"
        return a

    a.descricao = _texto_versao(rsrc, "FileDescription") or _texto_versao(rsrc, "ProductName")
    a.empresa = _texto_versao(rsrc, "CompanyName")
    a.versao = _texto_versao(rsrc, "ProductVersion") or _texto_versao(rsrc, "FileVersion")
    original = _texto_versao(rsrc, "OriginalFilename")
    interno = _texto_versao(rsrc, "InternalName")
    comentarios = _texto_versao(rsrc, "Comments")
    produto = _texto_versao(rsrc, "ProductName")
    m = re.search(rb'requestedExecutionLevel[^>]*level\s*=\s*["\'](\w+)', rsrc)
    a.admin = bool(m and m.group(1).lower() == b"requireadministrator")
    nomes_arq = " | ".join(x for x in (exe.name, original, interno) if x)
    descricoes = " | ".join(x for x in (a.descricao, produto) if x)
    tudo = cab + rsrc + ov + cauda

    # 0) desinstalador
    if NOMES_NAO_INSTALADOR.search(exe.name) or NOMES_NAO_INSTALADOR.search(original or ""):
        a.categoria, a.motivo = "desinstalador", "é um desinstalador"
        return a

    # 1) motores de instalação
    if any(s[0] == ".wixburn" for s in pe.secoes):
        a.tipo, a.args, a.motivo = "WiX Burn", "/quiet /norestart", "seção .wixburn (pacote WiX Burn)"
        return a
    if "inno setup" in comentarios.lower():
        a.tipo, a.args = "Inno Setup", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-"
        a.motivo = "informação de versão: Inno Setup"
        return a
    for assinatura, tipo, args in ASSINATURAS:
        if assinatura in tudo:
            a.tipo, a.args, a.motivo = tipo, args, f"assinatura do {tipo}"
            return a
    if ov[:6] == b"Rar!\x1a\x07":
        a.tipo, a.args, a.motivo = "SFX WinRAR", "/S", "arquivo autoextraível do WinRAR"
        return a
    if b"7z\xbc\xaf\x27\x1c" in ov[:4096] or b";!@Install@!UTF-8!" in tudo:
        a.tipo, a.args, a.motivo = "SFX 7-Zip", "/S", "arquivo autoextraível do 7-Zip"
        return a
    if (original or "").lower().startswith("wextract") or b"WEXTRACT" in rsrc.upper()[:1 << 20]:
        a.tipo, a.args, a.motivo = "IExpress", "/Q", "pacote IExpress (wextract)"
        return a
    if ".net framework" in (a.descricao + produto).lower() and "setup" in (a.descricao + produto + exe.name).lower():
        a.tipo, a.args, a.motivo = ".NET Framework", "/q /norestart", "instalador do .NET Framework"
        return a

    # 2) aplicativos empacotados em um .exe (portáteis)
    for assinatura, tipo in PORTATEIS:
        if assinatura in tudo:
            a.categoria, a.tipo, a.motivo = "portatil", tipo, f"aplicativo {tipo} em um único .exe"
            return a

    # 3) menu de autorun
    if nome in NOMES_MENU or any(s in tudo for s in MENUS):
        a.categoria, a.tipo, a.motivo = "menu", "Menu", "menu de CD/pen drive (só funciona com cliques)"
        return a

    # 4) nome / descrição
    m = NOMES_INSTALADOR.search(nomes_arq) or DESCRICAO_INSTALADOR.search(descricoes)
    if m:
        a.motivo = f"nome/descrição indica instalador ('{m.group(0)}')"
        return a

    # 5) "pacote" grande anexado ou nos recursos
    rs = a.extra.get("rsrc", 0)
    if a.overlay >= (512 << 10) and a.overlay >= tam * 0.25:
        a.motivo = f"tem {a.overlay // 1048576 or 1} MB de dados anexados (pacote do instalador)"
        return a
    if rs >= (2 << 20) and rs >= tam * 0.5:
        a.motivo = f"tem {rs // 1048576} MB de dados embutidos nos recursos (pacote do instalador)"
        return a

    # 6) nada indica instalador
    a.categoria = "portatil"
    a.motivo = ("nenhum sinal de instalador (sem motor de instalação, sem pacote anexado): "
                "é o próprio programa")
    return a

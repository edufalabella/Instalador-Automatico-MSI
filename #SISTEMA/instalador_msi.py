# -*- coding: utf-8 -*-
"""
Instalador MSI automatizado
---------------------------
Coloque este script na pasta raiz. Cada subpasta com arquivos .msi vira
uma opção da tela de seleção (interface gráfica; --console usa o menu de texto).

Estrutura esperada:
    instalador_msi.py
    Office\\       -> *.msi
    Drivers\\      -> *.msi
    Utilitarios\\  -> *.msi

Desenvolvido por Eduardo Falabella
"""

import argparse
import contextlib
import ctypes
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import quoteattr

import exec_silencioso as ex   # execução oculta, árvore de processos, watchdog (mesma pasta)
import validacao_msi as val    # validação rigorosa dos pacotes MSI (mesma pasta)

# ----------------------------------------------------------------------------
# Configurações
# ----------------------------------------------------------------------------
TITULO = "INSTALADOR AUTOMÁTICO MSI"
VERSAO = "2.2"
DESENVOLVEDOR = "Eduardo Falabella"
PASTAS_IGNORADAS = {"logs", "__pycache__", "build", "dist"}
BUSCA_RECURSIVA = True          # procura .msi também dentro de subpastas
MODO_SILENCIOSO = True          # /qn (sem interface). False = /qb (barra de progresso)
ANIMACAO = True                 # False = pula as animações da tela inicial

AUTO = False                    # True = modo automático (sem menu/ENTER/confirmação)
GUI_ATIVA = False               # True enquanto a tela gráfica está aberta (saída de console linear)
MODO_DIRETO = True              # MSI gerado por este programa: roda o .exe embutido FORA do msiexec
TIMEOUT_EXE_MIN = 120           # tempo máximo (min) para cada instalador embutido
FABRICANTE_WRAPPER = "Instalador Automatico"   # marca dos MSI gerados por este programa
TENTATIVAS_1618 = 5             # re-tentativas quando há outra instalação em andamento
ESPERA_1618 = 30                # segundos entre as tentativas

# --- blindagem contra telas (v2.1) ---
OCULTAR_JANELAS = True          # qualquer janela criada por um instalador é ocultada na hora
VIGIAR_UI = True                # janela + instalador parado (esperando clique) => encerra e tenta o próximo argumento
UI_OCIOSO_S = 60                # segundos de "tela aberta e sem atividade" para considerar travado
MAX_TENTATIVAS_ARGS = 5         # quantos conjuntos de argumentos silenciosos tentar por instalador
POS_OCIOSO_S = 45               # após o processo principal sair: espera filhos até ficarem ociosos
POS_MAX_S = 600                 # teto de espera pelos processos filhos
ESPERA_MSI_LIVRE_S = 900        # espera máxima pelo Windows Installer ficar livre entre pacotes
VERIFICAR_HASH_ATE_MB = 300     # na conversão, confere SHA-256 do .exe dentro do MSI até este tamanho
LIMITE_BINARY_BYTES = 2_000_000_000   # limite prático de um stream na tabela Binary do MSI

# --- validação dos pacotes (v2.2) ---
VALIDAR = True                  # valida TODOS os .msi depois da conversão e antes de instalar
VALIDACAO_COMPLETA = True       # True = lê cada .exe/.cab embutido por inteiro (SHA-256); False = só estrutura
BLOQUEAR_INVALIDOS = True       # pacote com ERRO na validação NÃO é instalado
PRESELECIONAR_VALIDOS = True    # na tela de seleção, já deixa marcados os pacotes que passaram na validação
CODIGO_BLOQUEADO = 1620         # código registrado para pacote bloqueado (ERROR_INSTALL_PACKAGE_INVALID)

CONVERTER_EXE = True            # procura .exe nas pastas e converte para .msi antes de instalar
EXCLUIR_EXE_APOS_CONVERTER = True   # apaga o .exe SÓ depois que o MSI foi gerado e verificado
EXE_IGNORAR_PREFIXOS = ("unins", "uninst", "uninstall")   # nunca converte desinstaladores
WIX_DIRNAME = "wix3"            # pasta (dentro de #SISTEMA) com candle.exe e light.exe

# Códigos de retorno do msiexec considerados "sucesso"
CODIGOS_OK = {
    0: "Instalado com sucesso",
    1641: "Instalado (reinicialização iniciada)",
    3010: "Instalado (reinicialização necessária)",
    0x80070BC2: "Instalado (reinicialização necessária)",   # HRESULT que o Burn pode devolver
    1638: "Já existe outra versão instalada",
    0x80070666: "Já existe outra versão instalada",    # HRESULT do 1638 (Burn)
    1707: "Instalado com sucesso",
}

# ----------------------------------------------------------------------------
# Visual (cores ANSI 256)
# ----------------------------------------------------------------------------
W = 64  # largura da interface


def fg(n: int) -> str:
    return f"\033[38;5;{n}m"


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CIANO = fg(45)
AZUL = fg(39)
VERDE = fg(78)
AMARELO = fg(221)
VERMELHO = fg(203)
CINZA = fg(244)
BRANCO = fg(255)

BANNER = [
    "███╗   ███╗███████╗██╗",
    "████╗ ████║██╔════╝██║",
    "██╔████╔██║███████╗██║",
    "██║╚██╔╝██║╚════██║██║",
    "██║ ╚═╝ ██║███████║██║",
    "╚═╝     ╚═╝╚══════╝╚═╝",
]
GRADIENTE = [27, 33, 39, 45, 51, 87]


def desativar_cores() -> None:
    """Remove códigos ANSI (útil quando a saída vai para arquivo/log)."""
    global RESET, BOLD, DIM, CIANO, AZUL, VERDE, AMARELO, VERMELHO, CINZA, BRANCO
    RESET = BOLD = DIM = CIANO = AZUL = VERDE = AMARELO = VERMELHO = CINZA = BRANCO = ""


def habilitar_ansi() -> None:
    """Ativa cores ANSI e UTF-8 no console do Windows."""
    if os.name == "nt":
        try:
            k32 = ctypes.windll.kernel32
            handle = k32.GetStdHandle(-11)
            modo = ctypes.c_ulong()
            if k32.GetConsoleMode(handle, ctypes.byref(modo)):
                k32.SetConsoleMode(handle, modo.value | 0x0004)
        except Exception:
            pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass


def centro(texto: str, cor: str = "") -> None:
    pad = max(0, (W - len(texto)) // 2)
    print(" " * pad + cor + texto + RESET)


def linha(char: str = "─", cor: Optional[str] = None) -> None:
    cor = CINZA if cor is None else cor  # lido na chamada (respeita desativar_cores)
    print(cor + char * W + RESET)


def rodape() -> None:
    linha()
    centro(f"desenvolvido por {DESENVOLVEDOR}", DIM + CINZA)


def pausa(segundos: float) -> None:
    if ANIMACAO:
        time.sleep(segundos)


def barra(atual: int, total: int, largura: int = 30) -> str:
    total = max(total, 1)
    cheio = int(largura * atual / total)
    pct = int(100 * atual / total)
    return f"{CIANO}{'█' * cheio}{CINZA}{'░' * (largura - cheio)}{RESET} {pct:>3}%"


# ----------------------------------------------------------------------------
# Utilitários
# ----------------------------------------------------------------------------
def diretorio_base() -> Path:
    """Pasta onde o script/.exe está (funciona com PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SCRIPT_DIR = diretorio_base()          # onde ficam o .py, os .bat e o instalador do Python


def diretorio_msi() -> Path:
    """Pasta que contém as subpastas com os MSI.

    Se o programa está dentro de uma pasta de sistema (nome começando com '#',
    ex.: '#SISTEMA'), os MSI ficam na pasta PAI. Caso contrário, ao lado do programa.
    """
    if SCRIPT_DIR.name.startswith("#"):
        return SCRIPT_DIR.parent
    return SCRIPT_DIR


BASE = diretorio_msi()                  # pode ser alterado com --raiz
LOG_DIR = SCRIPT_DIR / "logs"           # logs ficam junto do sistema, a raiz fica limpa


def eh_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def reexecutar_como_admin() -> None:
    """Relança o programa pedindo elevação (UAC)."""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, str(BASE), 1)
    sys.exit(0)


def saida_linear() -> bool:
    """True quando não devemos limpar a tela/animar (modo automático ou tela gráfica aberta)."""
    return AUTO or GUI_ATIVA


SEM_CONSOLE = False                     # True quando rodando com pythonw (sem janela de console)


def limpar_tela() -> None:
    if saida_linear() or SEM_CONSOLE:
        return
    os.system("cls" if os.name == "nt" else "clear")


def cabecalho() -> None:
    limpar_tela()
    print(CIANO + "╭" + "─" * (W - 2) + "╮" + RESET)
    interno = f"{TITULO}  v{VERSAO}"
    pad_e = (W - 2 - len(interno)) // 2
    pad_d = W - 2 - len(interno) - pad_e
    print(f"{CIANO}│{RESET}{' ' * pad_e}{BOLD}{BRANCO}{interno}{RESET}{' ' * pad_d}{CIANO}│{RESET}")
    print(CIANO + "╰" + "─" * (W - 2) + "╯" + RESET)
    print(f"{CINZA}  Pasta dos MSI: {BASE}{RESET}")
    linha()


def pausar() -> None:
    input(f"\n{CINZA}  Pressione ENTER para continuar...{RESET}")


# ----------------------------------------------------------------------------
# Tela de apresentação
# ----------------------------------------------------------------------------
def tela_apresentacao() -> None:
    limpar_tela()
    print("\n")
    for i, texto in enumerate(BANNER):
        centro(texto, BOLD + fg(GRADIENTE[i]))
        pausa(0.07)
    print()
    centro("I N S T A L A D O R   A U T O M Á T I C O", BOLD + BRANCO)
    centro("instalação em lote de pacotes MSI", CINZA)
    print()
    linha()
    print()

    dirs = descobrir_diretorios()
    total_msi = sum(len(m) for _, m in dirs)
    etapas = [
        ("Verificando privilégios de administrador", "OK" if eh_admin() else "AVISO"),
        ("Localizando diretórios de instalação", f"{len(dirs)} pasta(s)"),
        ("Contando pacotes MSI", f"{total_msi} pacote(s)"),
        ("Preparando ambiente", "OK"),
    ]
    for texto, resultado in etapas:
        cor = VERDE if resultado != "AVISO" else AMARELO
        for frame in "|/-\\|/":
            print(f"\r  {CIANO}{frame}{RESET} {texto}...", end="", flush=True)
            pausa(0.05)
        print(f"\r  {cor}●{RESET} {texto:<42} {cor}{resultado}{RESET}      ")

    print()
    for passo in range(0, 101, 4):
        print(f"\r  {barra(passo, 100, 44)}", end="", flush=True)
        pausa(0.015)
    print("\n")
    linha()
    centro("Bem-vindo! Tudo pronto para começar.", VERDE)
    print()
    rodape()
    input(f"\n{AMARELO}  Pressione ENTER para iniciar...{RESET}")


# ----------------------------------------------------------------------------
# Descoberta de diretórios e MSIs
# ----------------------------------------------------------------------------
def listar_msi(pasta: Path) -> list[Path]:
    padrao = pasta.rglob("*") if BUSCA_RECURSIVA else pasta.glob("*")
    return sorted(
        (p for p in padrao if p.is_file() and p.suffix.lower() == ".msi"),
        key=lambda p: str(p).lower(),
    )


def descobrir_diretorios() -> list[tuple[Path, list[Path]]]:
    """Retorna [(pasta, [msi, ...])] apenas para pastas que têm MSI."""
    resultado = []
    for item in sorted(BASE.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir() or item.name.lower() in PASTAS_IGNORADAS:
            continue
        if item.name.startswith(".") or item.name.startswith("#"):
            continue
        msis = listar_msi(item)
        if msis:
            resultado.append((item, msis))
    return resultado


# ----------------------------------------------------------------------------
# Status ao vivo (logs\status.txt)
# ----------------------------------------------------------------------------
ESTADO = {"estado": "AGUARDANDO", "inicio": None, "total": 0, "atual": 0,
          "pacote": "", "acao": "", "tipo": "", "resultados": [], "conversoes": [], "validacoes": []}


def ts() -> str:
    """Hora [HH:MM:SS] para prefixar linhas no modo automático."""
    return f"{CINZA}{datetime.now():%H:%M:%S}{RESET} " if saida_linear() else ""


def gravar_status() -> None:
    """Grava logs\\status.txt (leia de outro lugar com VER_STATUS.bat)."""
    try:
        LOG_DIR.mkdir(exist_ok=True)
        e = ESTADO
        dec = int((datetime.now() - e["inicio"]).total_seconds()) if e["inicio"] else 0
        ok = sum(1 for _, c, _ in e["resultados"] if c in CODIGOS_OK)
        falhas = len(e["resultados"]) - ok
        linhas = [
            f"Estado     : {e['estado']}",
            f"Início     : {e['inicio']:%d/%m/%Y %H:%M:%S}" if e["inicio"] else "Início     : -",
            f"Decorrido  : {dec // 60}m{dec % 60:02d}s",
            f"Progresso  : {e['atual']}/{e['total']}   (OK: {ok} | Falhas: {falhas})",
            f"Instalando : {e['pacote'] or '-'}",
            f"Etapa MSI  : {e['acao'] or '-'}",
            f"Atualizado : {datetime.now():%H:%M:%S}",
            "",
            "Concluídos:",
        ]
        linhas += [f"  [{c:>5}] {n} -> {st}" for n, c, st in e["resultados"]]
        if e.get("validacoes"):
            linhas += ["", "Validação dos pacotes:"]
            linhas += [f"  [{n_.upper():>5}] {nome} -> {resumo}" for nome, n_, resumo in e["validacoes"]]
        if e["conversoes"]:
            linhas += ["", "Conversões EXE -> MSI:"]
            linhas += [f"  [{st}] {n} {det}" for n, st, det in e["conversoes"]]
        tmp = LOG_DIR / "status.tmp"
        tmp.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        os.replace(tmp, LOG_DIR / "status.txt")
    except Exception:  # noqa: BLE001 - status nunca pode derrubar a instalação
        pass


def ultima_etapa_msi(log_file: Path) -> str:
    """Lê o fim do log verboso do msiexec e devolve a última 'Action start'."""
    try:
        with open(log_file, "rb") as f:
            f.seek(0, os.SEEK_END)
            ini = max(0, f.tell() - 65536)
            ini -= ini % 2  # alinhamento p/ UTF-16
            f.seek(ini)
            bruto = f.read()
        if bruto.count(b"\x00") > len(bruto) // 4:
            texto = bruto.decode("utf-16-le", "ignore")
        else:
            texto = bruto.decode("cp1252", "replace")
        achados = re.findall(r"Action start \d+:\d+:\d+: (\w+)\.", texto)
        return achados[-1] if achados else ""
    except Exception:  # noqa: BLE001
        return ""


_CB_BATIMENTO = None   # callable(seg, etapa) - usado pela tela gráfica para mostrar sinal de vida
_CB_EVENTO = None      # callable(evento, **dados) - tela gráfica (instalação e preparação)


def evento(*args, **dados) -> None:
    """Envia um evento para a tela gráfica (se houver). Nunca levanta exceção.
    O tipo do evento é o 1º argumento posicional; assim os dados podem ter uma chave chamada 'nome'
    (antes isso dava TypeError e derrubava a conversão na tela gráfica)."""
    if _CB_EVENTO and args:
        with contextlib.suppress(Exception):
            _CB_EVENTO(args[0], **dados)


def aviso(msg: str, nivel: str = "info") -> None:
    """Mensagem para o console (modo texto/auto) e para o log da tela gráfica."""
    cor = {"ok": VERDE, "erro": VERMELHO, "aviso": AMARELO}.get(nivel, CINZA)
    print(f"        {ts()}{cor}{msg}{RESET}", flush=True)
    evento("aviso", msg=msg, nivel=nivel)


def _matar_arvore(pid: int) -> None:
    ex.rodar_oculto(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def aguardar_com_status(proc: "subprocess.Popen", log_file: Optional[Path] = None,
                        timeout_s: Optional[int] = None) -> int:
    """Espera o processo, grava status.txt, avisa a tela gráfica e imprime sinal de vida a cada 15 s.
    Se passar de timeout_s, encerra a árvore de processos e devolve 1460 (ERROR_TIMEOUT)."""
    inicio = time.time()
    ultimo = 0
    while True:
        try:
            return proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        seg = int(time.time() - inicio)
        if timeout_s and seg > timeout_s:
            _matar_arvore(proc.pid)
            with contextlib.suppress(Exception):
                proc.wait(timeout=30)
            return 1460
        ESTADO["acao"] = ultima_etapa_msi(log_file) if log_file else "instalador embutido"
        gravar_status()
        if _CB_BATIMENTO:
            with contextlib.suppress(Exception):
                _CB_BATIMENTO(seg, ESTADO["acao"])
        if seg - ultimo >= 15:
            ultimo = seg
            etapa = f" | etapa: {ESTADO['acao']}" if ESTADO["acao"] else ""
            print(f"        {ts()}{CINZA}... ainda instalando ({seg}s){etapa}{RESET}", flush=True)


# ----------------------------------------------------------------------------
# Instalação
# ----------------------------------------------------------------------------
_DICAS = {
    2: "arquivo não encontrado",
    5: "acesso negado",
    87: "parâmetro inválido (argumentos silenciosos desconhecidos)",
    112: "sem espaço em disco",
    1223: "cancelado",
    1460: "tempo limite excedido (instalador travado?)",
    1602: "o instalador abriu uma tela e esperou interação (encerrado pelo vigia) ou foi cancelado",
    1603: "erro fatal no pacote MSI",
    1618: "outra instalação MSI em andamento (ou instalador aninhado dentro do msiexec)",
    1620: "não foi possível abrir/extrair o pacote",
    1639: "argumento de linha de comando inválido",
    1625: "bloqueado por política do sistema",
    0xC0000005: "violação de acesso (crash do instalador)",
    0xC0000409: "falha interna do instalador (crash; comum ao rodar como SYSTEM/sessão 0)",
}
_INNO = {
    1: "falha ao inicializar", 2: "cancelado antes de instalar",
    3: "erro fatal ao preparar a instalação", 4: "erro fatal durante a instalação",
    5: "cancelado/encerrado durante a instalação",
    7: "a preparação barrou a instalação (programa em uso, pré-requisito ou reinício pendente)",
    8: "é preciso reiniciar o Windows antes de instalar",
}


def descrever_codigo(codigo: int, tipo: str = "") -> str:
    c = codigo & 0xFFFFFFFF
    if tipo == "Inno Setup" and c in _INNO:
        return _INNO[c]
    return _DICAS.get(c, "")


def texto_falha(codigo: int, tipo: str = "") -> str:
    c = codigo & 0xFFFFFFFF
    cod = f"0x{c:08X}" if c > 0xFFFF else str(codigo)
    dica = descrever_codigo(codigo, tipo)
    return f"FALHA (código {cod}{' - ' + dica if dica else ''})"


def tipo_por_args(args: str) -> str:
    a = args.lower().strip()
    if "/verysilent" in a:
        return "Inno Setup"
    if "/exenoui" in a:
        return "Advanced Installer"
    if "/quiet" in a:
        return "Burn"
    if a.startswith("/s") and "/v" in a:
        return "InstallShield"
    if "--accept-licenses" in a:
        return "Qt Installer Framework"
    if a in ("/s", "/silent", "/s /norestart"):
        return "NSIS"
    return ""


def _ler_linhas_args(arq: Path) -> list:
    """Linhas úteis de um arquivo .args (ignora vazias e comentários iniciados por # ou ;)."""
    try:
        linhas = arq.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return []
    return [l.strip() for l in linhas if l.strip() and not l.strip().startswith(("#", ";"))]


def _executar_msiexec(msi: Path, log_file: Path) -> int:
    """msiexec 100% silencioso. Extras opcionais ao lado do MSI:
       <nome>.mst        -> transform (TRANSFORMS=...)
       <nome>.msi.args   -> 1ª linha = propriedades extras (ex.: ACCEPTEULA=1 LICENSEKEY=XXXX)."""
    modo = "/qn" if MODO_SILENCIOSO else "/qb"
    cmd = f'msiexec /i "{msi}" {modo} /norestart /L*v "{log_file}" REBOOT=ReallySuppress'
    mst = msi.with_suffix(".mst")
    if mst.is_file():
        cmd += f' TRANSFORMS="{mst}"'
    extra = _ler_linhas_args(msi.with_name(msi.name + ".args"))
    if extra:
        cmd += " " + extra[0]
    try:
        proc = subprocess.Popen(cmd, env=ex.ambiente_silencioso(), **ex.kwargs_ocultos())
    except FileNotFoundError:
        print(f"  {VERMELHO}[ERRO] msiexec não encontrado (somente Windows).{RESET}")
        return -1
    except Exception as exc:  # noqa: BLE001
        print(f"  {VERMELHO}[ERRO] Falha ao executar: {exc}{RESET}")
        return -2
    return aguardar_com_status(proc, log_file)


def _com_retentativa(executar) -> int:
    """Roda 'executar()'; se houver outra instalação em curso (1618), espera e tenta de novo."""
    codigo = executar()
    tentativa = 0
    while codigo == 1618 and tentativa < TENTATIVAS_1618:
        tentativa += 1
        print(f"        {AMARELO}[1618] Outra instalação em andamento. "
              f"Nova tentativa {tentativa}/{TENTATIVAS_1618} em {ESPERA_1618}s...{RESET}")
        time.sleep(ESPERA_1618)
        codigo = executar()
    return codigo


def instalar_msi(msi: Path, log_file: Path) -> int:
    """Instala via msiexec (MSI de verdade). Re-tenta se houver outra instalação em curso (1618)."""
    ex.aguardar_msi_livre(ESPERA_MSI_LIVRE_S)
    return _com_retentativa(lambda: _executar_msiexec(msi, log_file))


# ---- instalação "direta" dos MSI gerados por este programa ------------------
# Por que existe: o MSI gerado só embrulha um .exe numa Custom Action. Rodando dentro do msiexec,
# o .exe herda a transação do Windows Installer (mutex global) e roda como SYSTEM. Instaladores
# WiX Burn, Advanced Installer, InstallShield etc. precisam chamar o PRÓPRIO msiexec e falham
# (1618/1602/5/0xC0000409) e o msiexec devolve o genérico 1603. Aqui o .exe embutido é extraído e
# executado fora do msiexec, como o administrador atual - e devolve o código de saída real.
def pacote_embutido(msi: Path) -> bool:
    """True se o MSI foi gerado por este programa (tem o .exe na tabela Binary)."""
    try:
        if msi_texto(msi, "SELECT `Value` FROM `Property` WHERE `Property`='Manufacturer'") != FABRICANTE_WRAPPER:
            return False
        return msi_texto(msi, "SELECT `Name` FROM `Binary` WHERE `Name`='SetupExe'") is not None
    except Exception:  # noqa: BLE001
        return False


def classificar_pacote(msi: Path) -> tuple:
    """(rótulo, tamanho em bytes) para exibir na tela de seleção."""
    try:
        tam = msi.stat().st_size
    except OSError:
        tam = 0
    return ("EXE→MSI" if pacote_embutido(msi) else "MSI"), tam


# Argumentos silenciosos por tipo de instalador. A PRIMEIRA linha é a preferida; as seguintes só são
# tentadas se a anterior fizer o instalador abrir uma tela e travar (vigia) ou rejeitar o argumento.
ESCADAS = {
    "Inno Setup": ["/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-",
                   "/SILENT /SUPPRESSMSGBOXES /NORESTART /SP-"],
    "NSIS": ["/S"],
    "Burn": ["/quiet /norestart", "/passive /norestart"],
    "Advanced Installer": ["/exenoui /qn /norestart", "/exenoui /qb /norestart", "/qn /norestart"],
    "InstallShield": ['/s /v"/qn REBOOT=ReallySuppress"', '/s /sms /v"/qn REBOOT=ReallySuppress"',
                      '/s /v"/qb REBOOT=ReallySuppress"'],
    "Qt Installer Framework": ["--accept-licenses --default-answer --confirm-command install"],
}
# Tipo desconhecido (ou ladder esgotada): tenta estes, do mais para o menos comum.
GENERICOS = [
    "/S",
    "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-",
    "/quiet /norestart",
    "/silent /norestart",
    "/qn /norestart",
    '/s /v"/qn REBOOT=ReallySuppress"',
]


def _chave_tipo(tipo: str) -> str:
    return "Burn" if tipo in ("Burn", "WiX Burn") else tipo


def candidatos_args(msi: Path, exe: Path) -> list:
    """Lista ordenada de argumentos silenciosos a tentar para o .exe embutido.

    1) '<nome>.exe.args' ao lado do MSI: se existir, vale SÓ ele (1 argumento por linha = 1 tentativa);
    2) senão: o gravado no MSI, o detectado no .exe, a escada do tipo e, por fim, os genéricos."""
    lado = msi.with_name(msi.stem + ".exe.args")
    if lado.is_file():
        linhas = [l for l in _ler_linhas_args(lado) if l.upper() != "IGNORAR"]
        if linhas:
            return linhas
    lista: list = []
    try:
        alvo = msi_texto(msi, "SELECT `Target` FROM `CustomAction` WHERE `Action`='RunInstall'")
    except OSError:
        alvo = None
    if alvo:
        lista.append(alvo)
    achado = detectar_instalador(exe)
    tipo = achado[0] if achado else tipo_por_args(alvo or "")
    if achado:
        lista.append(achado[1])
    lista += ESCADAS.get(_chave_tipo(tipo), [])
    lista += GENERICOS
    vistos, final = set(), []
    for a in lista:
        k = a.strip().lower()
        if k and k not in vistos:
            vistos.add(k)
            final.append(a.strip())
    return final


def _args_com_log(args: str, tipo: str, log_file: Path, n: int = 1) -> str:
    """Pede ao instalador um log próprio (Burn e Inno suportam) - ajuda a diagnosticar falhas."""
    destino = log_file.with_suffix(".instalador.log" if n == 1 else f".instalador{n}.log")
    if "/log" in args.lower():
        return args
    if tipo == "Burn":
        return f'{args} /log "{destino}"'
    if tipo == "Inno Setup":
        return f'{args} /LOG="{destino}"'
    return args


def _fazer_tick():
    """Callback de sinal de vida (status.txt, tela gráfica e linha no console a cada 15 s)."""
    ultimo = [0]

    def tick(seg: int) -> None:
        ESTADO["acao"] = "instalador embutido"
        gravar_status()
        if _CB_BATIMENTO:
            with contextlib.suppress(Exception):
                _CB_BATIMENTO(seg, ESTADO["acao"])
        if seg - ultimo[0] >= 15:
            ultimo[0] = seg
            print(f"        {ts()}{CINZA}... ainda instalando ({seg}s){RESET}", flush=True)
    return tick


def _rejeitou_argumentos(res, codigo: int) -> bool:
    """True quando vale tentar o próximo argumento: o instalador abriu tela e travou, rejeitou o
    argumento ou saiu na hora com erro. NÃO tenta de novo se ele já estava instalando e falhou."""
    if res.motivo == "ui_travada":
        return True
    if res.motivo == "timeout":
        return False
    c = codigo & 0xFFFFFFFF
    if c in (87, 1639):
        return True
    return res.duracao < 6 and c not in (1618,)


def instalar_embutido(msi: Path, log_file: Path) -> int:
    """Extrai o .exe de dentro do MSI e executa fora do msiexec, 100% oculto, esperando a ÁRVORE de
    processos. Se o instalador abrir uma tela e travar, encerra e tenta o próximo argumento silencioso."""
    tmp = Path(tempfile.mkdtemp(prefix="msi_direto_"))
    anotacoes: list = []

    def anotar(txt: str) -> None:
        anotacoes.append(f"[{datetime.now():%H:%M:%S}] {txt}")

    try:
        anotar(f"Modo direto | pacote: {msi}")
        exe = tmp / f"{msi.stem}.exe"        # mesmo nome do .exe original
        if shutil.disk_usage(tmp).free < msi.stat().st_size * 1.15 + (200 << 20):
            anotar("Espaço insuficiente em %TEMP% para extrair o instalador.")
            aviso("Sem espaço em disco para extrair o instalador.", "erro")
            return 112
        t0 = time.time()
        if not msi_extrair_stream(msi, "SELECT `Data` FROM `Binary` WHERE `Name`='SetupExe'", exe):
            anotar("Falha ao extrair o .exe da tabela Binary.")
            return 1620
        anotar(f"Instalador extraído ({exe.stat().st_size // 1048576} MB em {time.time() - t0:.0f}s)")
        candidatos = candidatos_args(msi, exe)[:MAX_TENTATIVAS_ARGS]
        if not candidatos:
            anotar(f"Sem argumentos silenciosos. Crie '{msi.stem}.exe.args' ao lado do MSI.")
            aviso(f"Argumentos silenciosos desconhecidos; crie '{msi.stem}.exe.args'.", "erro")
            return 87
        anotar("Tentativas de argumentos: " + " || ".join(candidatos))

        codigo = 1
        for n, args in enumerate(candidatos, start=1):
            if not ex.aguardar_msi_livre(ESPERA_MSI_LIVRE_S):
                anotar("Windows Installer continuou ocupado por muito tempo.")
            tipo = tipo_por_args(args)
            ESTADO["tipo"] = tipo
            linha_cmd = f'"{exe}" {_args_com_log(args, tipo, log_file, n)}'
            anotar(f"Tentativa {n}/{len(candidatos)} | tipo: {tipo or 'desconhecido'} | {linha_cmd}")
            if len(candidatos) > 1 and n > 1:
                aviso(f"tentativa {n}/{len(candidatos)}: {args}", "aviso")
            guarda: dict = {}
            tick = _fazer_tick()

            def rodar() -> int:
                res = ex.executar_arvore(
                    linha_cmd, str(tmp), TIMEOUT_EXE_MIN * 60, tick=tick,
                    ocultar=OCULTAR_JANELAS, vigiar_ui=VIGIAR_UI, ui_ocioso_s=UI_OCIOSO_S,
                    pos_ocioso_s=POS_OCIOSO_S, pos_max_s=POS_MAX_S,
                    ao_janela=lambda d: (anotar(f"Janela detectada e ocultada: {d}"),
                                         aviso(f"janela ocultada: {d}", "aviso")))
                guarda["res"] = res
                anotar(f"Código de saída: {res.codigo} (0x{res.codigo & 0xFFFFFFFF:08X}) | motivo: {res.motivo} | "
                       f"{res.duracao:.0f}s{' | deixou processos filhos' if res.deixou_filhos else ''}")
                return res.codigo

            codigo = _com_retentativa(rodar)
            res = guarda["res"]
            if codigo in CODIGOS_OK:
                return codigo
            if res.motivo == "ui_travada":
                aviso("o instalador abriu uma tela e esperou clique "
                      f"({'; '.join(res.janelas[-2:]) or 'janela sem título'}); encerrado.", "aviso")
                ex.aguardar_msi_livre(120)
            if n < len(candidatos) and _rejeitou_argumentos(res, codigo):
                continue
            break
        return codigo
    except Exception as exc:  # noqa: BLE001
        anotar(f"EXCEÇÃO: {exc}\n{traceback.format_exc()}")
        aviso(f"{exc}", "erro")
        return 1
    finally:
        with contextlib.suppress(Exception):
            log_file.write_text("\n".join(anotacoes) + "\n", encoding="utf-8")
        for _ in range(3):                       # o instalador pode demorar a soltar o arquivo
            shutil.rmtree(tmp, ignore_errors=True)
            if not tmp.exists():
                break
            time.sleep(2)


def instalar_lista(itens: list[tuple[Path, list[Path]]], callback=None, cancelar=None,
                   direto: Optional[bool] = None) -> tuple[int, bool]:
    """Instala os pacotes. callback(evento, **dados) alimenta a tela gráfica; 'cancelar' é um
    threading.Event checado entre um pacote e outro. Devolve (falhas, reinicio_necessario)."""
    global _CB_BATIMENTO
    direto = MODO_DIRETO if direto is None else direto
    linear = saida_linear()

    def emit(ev: str, **kw) -> None:
        if callback:
            with contextlib.suppress(Exception):
                callback(ev, **kw)

    global _CB_EVENTO
    _CB_BATIMENTO = (lambda seg, etapa: emit("batimento", seg=seg, etapa=etapa)) if callback else None
    _CB_EVENTO = callback
    try:
        LOG_DIR.mkdir(exist_ok=True)
        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
        resumo_path = LOG_DIR / f"resumo_{carimbo}.txt"

        todos = [(pasta, msi) for pasta, msis in itens for msi in msis]
        total = len(todos)
        resultados: list[tuple[str, int, str]] = []
        modos: list[str] = []

        ESTADO.update(estado="EM ANDAMENTO", inicio=datetime.now(), total=total,
                      atual=0, pacote="", acao="", resultados=resultados)
        gravar_status()

        if not linear:
            cabecalho()
        print(f"  {ts()}{BOLD}Instalando {total} pacote(s)...{RESET}\n")
        emit("inicio", total=total)
        cancelado = False

        for i, (pasta, msi) in enumerate(todos, start=1):
            if cancelar is not None and cancelar.is_set():
                cancelado = True
                break
            nome_log = f"{pasta.name}_{msi.stem}_{carimbo}.log".replace(" ", "_")
            log_file = LOG_DIR / nome_log
            bloqueio = ""
            if VALIDAR and BLOQUEAR_INVALIDOS:
                # confere de novo na hora (usa o resultado da etapa de validação se o arquivo não mudou)
                rv = validar_msi(msi, progresso=_progresso("instalação"))
                if rv.nivel == "erro":
                    bloqueio = rv.resumo
            embutido = direto and not bloqueio and pacote_embutido(msi)
            modo = "bloqueado" if bloqueio else ("direto" if embutido else "msiexec")
            print(f"  {barra(i - 1, total)}")
            print(f"  {ts()}{CIANO}[{i}/{total}]{RESET} {pasta.name} {CINZA}›{RESET} {BRANCO}{msi.name}{RESET}"
                  f" {CINZA}[{modo}]{RESET}")
            ESTADO.update(atual=i, pacote=f"{pasta.name}\\{msi.name}", acao="", tipo="")
            gravar_status()
            emit("item", i=i, total=total, pasta=pasta, msi=msi, modo=modo)
            t0 = time.time()
            if bloqueio:
                codigo = CODIGO_BLOQUEADO
                aviso(f"BLOQUEADO pela validação: {bloqueio}", "erro")
            else:
                codigo = instalar_embutido(msi, log_file) if embutido else instalar_msi(msi, log_file)
            dur = int(time.time() - t0)
            ok = codigo in CODIGOS_OK
            status = (f"BLOQUEADO pela validação ({bloqueio})" if bloqueio
                      else CODIGOS_OK.get(codigo) or texto_falha(codigo, ESTADO.get("tipo", "")))
            cor, marca = (VERDE, " OK ") if ok else (VERMELHO, "ERRO")
            print(f"        {ts()}{cor}[{marca}] {status}{RESET} {CINZA}({dur}s){RESET}\n")
            resultados.append((f"{pasta.name}\\{msi.name}", codigo, status))
            modos.append(modo)
            gravar_status()
            emit("resultado", i=i, total=total, pasta=pasta, msi=msi, codigo=codigo,
                 status=status, dur=dur, ok=ok)

        print(f"  {barra(len(resultados), total)}\n")

        ok = sum(1 for _, c, _ in resultados if c in CODIGOS_OK)
        falhas = len(resultados) - ok
        reboot = any(c in (1641, 3010, 0x80070BC2) for _, c, _ in resultados)
        ESTADO.update(estado="CANCELADO" if cancelado else ("CONCLUÍDO" if falhas == 0 else "CONCLUÍDO COM FALHAS"),
                      pacote="", acao="")
        gravar_status()

        linha("═", CIANO)
        print(f"  {BOLD}RESUMO:{RESET} {VERDE}{ok} sucesso(s){RESET} | "
              f"{VERMELHO if falhas else CINZA}{falhas} falha(s){RESET} | total {total}"
              f"{' | CANCELADO' if cancelado else ''}")
        linha("═", CIANO)
        for nome, codigo, status in resultados:
            cor = VERDE if codigo in CODIGOS_OK else VERMELHO
            print(f"  {cor}[{codigo & 0xFFFFFFFF if codigo < 0 else codigo:>5}]{RESET} {nome} {CINZA}→ {status}{RESET}")
        if reboot:
            print(f"\n  {AMARELO}>> Reinicie o computador para concluir algumas instalações.{RESET}")
        print(f"\n  {CINZA}Logs detalhados em: {LOG_DIR}{RESET}")

        with open(resumo_path, "w", encoding="utf-8") as f:
            f.write(f"Instalação em {datetime.now():%d/%m/%Y %H:%M:%S}\n\n")
            for (nome, codigo, status), modo in zip(resultados, modos):
                f.write(f"[{codigo}] {nome} -> {status}  ({modo})\n")
            f.write(f"\nSucessos: {ok} | Falhas: {falhas}{' | CANCELADO' if cancelado else ''}\n")
        emit("fim", ok=ok, falhas=falhas, reboot=reboot, cancelado=cancelado, resumo=resumo_path)
        return falhas, reboot
    finally:
        _CB_BATIMENTO = None
        _CB_EVENTO = None


# ----------------------------------------------------------------------------
# Conversão EXE -> MSI (empacota o .exe dentro de um .msi com WiX 3)
# ----------------------------------------------------------------------------
# (assinatura dentro do .exe, tipo de instalador, argumentos silenciosos)
ASSINATURAS_EXE = [
    (b".wixburn", "WiX Burn", "/quiet /norestart"),
    (b"Inno Setup Setup Data", "Inno Setup", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-"),
    (b"Nullsoft Install System", "NSIS", "/S"),
    (b"NullsoftInst", "NSIS", "/S"),
    (b"Advanced Installer", "Advanced Installer", "/exenoui /qn /norestart"),
    (b"InstallShield", "InstallShield", '/s /v"/qn REBOOT=ReallySuppress"'),
]

WXS3 = """<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name={nome} Language="1033" Version={versao}
           Manufacturer="Instalador Automatico" UpgradeCode="{upgrade}">
    <Property Id="ExeSha256" Value={sha256} />
    <Property Id="ExeBytes" Value={bytes} />
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine"
             Description={nome} />
    <MajorUpgrade DowngradeErrorMessage="Ja existe uma versao mais nova instalada." />
    <Media Id="1" Cabinet="media1.cab" EmbedCab="yes" />
    <Binary Id="SetupExe" SourceFile={exe} />
    <CustomAction Id="RunInstall" BinaryKey="SetupExe" ExeCommand={args}
                  Execute="deferred" Impersonate="no" Return="check" />
    <InstallExecuteSequence>
      <Custom Action="RunInstall" Before="InstallFinalize">NOT Installed AND NOT REMOVE</Custom>
    </InstallExecuteSequence>
    <!-- CORRECAO (erro 1603): uma Feature SEM Component e tratada pelo Windows Installer como
         vazia (REMOVE=ALL) e a instalacao aborta em InstallInitialize. Este Component (so uma
         chave de registro) e o que torna a Feature instalavel. -->
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Component Id="MarcadorRegistro" Guid="*">
        <RegistryValue Root="HKLM" Key="SOFTWARE\\InstaladorAutomaticoMSI\\{upgrade}"
                       Name="Versao" Type="string" Value={versao} KeyPath="yes" />
      </Component>
    </Directory>
    <Feature Id="Main" Title="Main" Level="1">
      <ComponentRef Id="MarcadorRegistro" />
    </Feature>
  </Product>
</Wix>
"""
NS_UPGRADE = uuid.UUID("6f1c2b5e-9b7a-4a52-8d57-2a3c1e4f7a10")


def pastas_validas() -> list[Path]:
    """Subpastas de BASE que o programa examina (ignora logs, '#...' e '.…')."""
    return [
        i for i in sorted(BASE.iterdir(), key=lambda p: p.name.lower())
        if i.is_dir() and i.name.lower() not in PASTAS_IGNORADAS
        and not i.name.startswith((".", "#"))
    ]


def listar_exe(pasta: Path) -> list[Path]:
    padrao = pasta.rglob("*") if BUSCA_RECURSIVA else pasta.glob("*")
    return sorted(
        (p for p in padrao
         if p.is_file() and p.suffix.lower() == ".exe"
         and not p.name.lower().startswith(EXE_IGNORAR_PREFIXOS)),
        key=lambda p: str(p).lower(),
    )


def detectar_instalador(exe: Path) -> Optional[tuple]:
    """Procura assinaturas de instaladores conhecidos. Devolve (tipo, args) ou None."""
    # CORREÇÃO (tela "Não respondendo" / fechando): antes era mmap.find() no arquivo inteiro, uma
    # varredura por assinatura. mmap.find SEGURA o GIL enquanto o Windows lê o arquivo do disco
    # (pen drive/HD lento + antivírus), então a thread da tela gráfica ficava congelada por dezenas
    # de segundos em .exe grandes; o Windows marcava a janela como "Não respondendo" e ela era
    # encerrada. Agora: leitura em blocos (f.read libera o GIL), uma única passada, com sobreposição
    # para não perder assinatura dividida entre dois blocos. A prioridade da lista é mantida.
    bloco = 8 << 20
    sobra = max(len(a) for a, _, _ in ASSINATURAS_EXE) - 1
    achadas: set = set()
    try:
        with open(exe, "rb") as f:
            anterior = b""
            while True:
                dados = f.read(bloco)
                if not dados:
                    break
                janela = anterior + dados
                for idx, (assinatura, _, _) in enumerate(ASSINATURAS_EXE):
                    if idx not in achadas and assinatura in janela:
                        achadas.add(idx)
                if 0 in achadas:              # a de maior prioridade já apareceu: não precisa ler mais
                    break
                anterior = janela[-sobra:]
                time.sleep(0)                 # devolve a vez para a tela gráfica
    except (OSError, ValueError):
        return None
    if achadas:
        _, tipo, args = ASSINATURAS_EXE[min(achadas)]
        return tipo, args
    return None


def argumentos_do_exe(exe: Path) -> Optional[tuple]:
    """(origem, args, conhecido). '<nome>.exe.args' (1ª linha útil) tem prioridade; 'IGNORAR' pula o
    arquivo. Sem arquivo, detecta o instalador. Tipo desconhecido NÃO é mais descartado: converte com
    o 1º argumento genérico e, na hora de instalar, a escada de argumentos + vigia de tela resolvem
    (conhecido=False => o .exe original é mantido)."""
    lado = exe.with_name(exe.name + ".args")
    if lado.is_file():
        linhas = _ler_linhas_args(lado)
        if linhas and linhas[0].upper() == "IGNORAR":
            return "IGNORAR", "", True
        if linhas:
            return f"arquivo {lado.name}", linhas[0], True
    achado = detectar_instalador(exe)
    if achado:
        return achado[0], achado[1], True
    return "tipo desconhecido (escada genérica na instalação)", GENERICOS[0], False


def localizar_wix() -> Optional[tuple]:
    candidatos = [SCRIPT_DIR / WIX_DIRNAME]
    if os.environ.get("WIX"):
        candidatos.append(Path(os.environ["WIX"]) / "bin")
    for d in candidatos:
        if (d / "candle.exe").is_file() and (d / "light.exe").is_file():
            return d / "candle.exe", d / "light.exe"
    c, l = shutil.which("candle"), shutil.which("light")
    return (Path(c), Path(l)) if c and l else None


def versao_exe(exe: Path) -> str:
    """Versão do arquivo (x.y.z) lida do .exe; '1.0.0' se não conseguir."""
    try:
        v = ctypes.windll.version
        dummy = ctypes.c_ulong(0)
        tam = v.GetFileVersionInfoSizeW(str(exe), ctypes.byref(dummy))
        if not tam:
            return "1.0.0"
        buf = ctypes.create_string_buffer(tam)
        if not v.GetFileVersionInfoW(str(exe), 0, tam, buf):
            return "1.0.0"
        ptr, tamanho = ctypes.c_void_p(), ctypes.c_uint()
        if not v.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(tamanho)) or not ptr.value:
            return "1.0.0"
        info = (ctypes.c_uint32 * 4).from_address(ptr.value)  # VS_FIXEDFILEINFO
        ms, ls = info[2], info[3]
        major, minor, build = min(ms >> 16, 255), min(ms & 0xFFFF, 255), min(ls >> 16, 65535)
        return f"{major}.{minor}.{build}" if (major or minor or build) else "1.0.0"
    except Exception:  # noqa: BLE001
        return "1.0.0"


def _rodar(cmd: list, log: list) -> int:
    r = ex.rodar_oculto(cmd, capture_output=True, text=True, errors="replace")
    log.append("> " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    log.append(r.stdout or "")
    log.append(r.stderr or "")
    return r.returncode


def construir_msi(exe: Path, msi: Path, args: str, wix: tuple, log_path: Path) -> tuple:
    """Gera o MSI com candle+light. Devolve (ok, mensagem)."""
    candle, light = wix
    log: list = []
    try:
        if exe.stat().st_size >= LIMITE_BINARY_BYTES:
            return False, (f"o .exe tem {exe.stat().st_size / 2**30:.1f} GB; acima de ~2 GB não cabe "
                           "num MSI (deixe-o como .exe e instale por outro meio)")
        with tempfile.TemporaryDirectory(prefix="exe2msi_") as tmp_s:
            tmp = Path(tmp_s)
            wxs, obj = tmp / "pkg.wxs", tmp / "obj"
            obj.mkdir()
            wxs.write_text(WXS3.format(
                nome=quoteattr(exe.stem), versao=quoteattr(versao_exe(exe)),
                upgrade=str(uuid.uuid5(NS_UPGRADE, exe.stem.lower())).upper(),
                exe=quoteattr(str(exe.resolve())), args=quoteattr(args),
                sha256=quoteattr(_sha256(exe)), bytes=quoteattr(str(exe.stat().st_size))), encoding="utf-8")
            if _rodar([str(candle), "-nologo", "-out", str(obj) + os.sep, str(wxs)], log) != 0:
                return False, "candle falhou (veja o log)"
            saida = tmp / "pkg.msi"
            if _rodar([str(light), "-nologo", "-sval", "-spdb", "-sw1079", "-out", str(saida),
                       str(obj / "pkg.wixobj")], log) != 0:
                return False, "light falhou (veja o log)"
            if not saida.is_file():
                return False, "MSI não foi gerado"
            shutil.move(str(saida), str(msi))
        return True, "MSI gerado"
    except Exception as exc:  # noqa: BLE001
        log.append(f"EXCEÇÃO: {exc}")
        return False, f"erro: {exc}"
    finally:
        try:
            LOG_DIR.mkdir(exist_ok=True)
            log_path.write_text("\n".join(log), encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _sha256(arq: Path) -> str:
    h = hashlib.sha256()
    with open(arq, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


VALIDACOES: dict = {}           # Path do .msi -> val.Resultado (validado nesta execução)


def validar_msi(msi: Path, exe: Optional[Path] = None, forcar: bool = False, progresso=None):
    """Valida um .msi e guarda o resultado. Reaproveita o resultado se o arquivo não mudou
    (mesmo tamanho e data) e a validação anterior já cobriu o mesmo nível de leitura."""
    msi = Path(msi)
    antigo = VALIDACOES.get(msi)
    if (not forcar and antigo is not None and antigo.assinatura == val.assinatura_arquivo(msi)
            and antigo.info.get("completa", False) >= VALIDACAO_COMPLETA):
        return antigo
    r = val.validar_pacote(msi, exe=exe, completo=VALIDACAO_COMPLETA, progresso=progresso)
    r.info["completa"] = VALIDACAO_COMPLETA
    VALIDACOES[msi] = r
    return r


def verificar_msi(msi: Path, exe: Path) -> bool:
    """Atalho: True só se a validação completa (comparando com o .exe original) der OK, sem avisos."""
    return validar_msi(msi, exe=exe, forcar=True).nivel == "ok"


# ----------------------------------------------------------------------------
# Leitura direta de MSI (msi.dll via ctypes) - usada pelo reparo de MSIs antigos
# ----------------------------------------------------------------------------
def _msi_api():
    """msi.dll com as assinaturas declaradas (MSIHANDLE = 32 bits, mesmo em Python 64)."""
    m = ctypes.windll.msi
    h, pu = ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)
    m.MsiOpenDatabaseW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, pu]
    m.MsiDatabaseOpenViewW.argtypes = [h, ctypes.c_wchar_p, pu]
    m.MsiViewExecute.argtypes = [h, h]
    m.MsiViewFetch.argtypes = [h, pu]
    m.MsiRecordGetStringW.argtypes = [h, ctypes.c_uint, ctypes.c_void_p, pu]
    m.MsiRecordDataSize.argtypes = [h, ctypes.c_uint]
    m.MsiRecordDataSize.restype = ctypes.c_uint
    m.MsiRecordReadStream.argtypes = [h, ctypes.c_uint, ctypes.c_void_p, pu]
    m.MsiCloseHandle.argtypes = [h]
    return m


@contextlib.contextmanager
def _msi_primeiro_registro(caminho: Path, sql: str):
    """Abre o MSI (somente leitura), roda a consulta e entrega (api, registro) da 1ª linha,
    ou (api, None) se não houver linha. Levanta OSError se a tabela não existir / consulta inválida."""
    api = _msi_api()
    hdb, hview, hrec = ctypes.c_ulong(0), ctypes.c_ulong(0), ctypes.c_ulong(0)
    try:
        rc = api.MsiOpenDatabaseW(str(caminho), None, ctypes.byref(hdb))  # None = somente leitura
        if rc:
            raise OSError(rc, f"MsiOpenDatabase falhou ({rc})")
        rc = api.MsiDatabaseOpenViewW(hdb.value, sql, ctypes.byref(hview))
        if rc:
            raise OSError(rc, f"consulta inválida/tabela ausente ({rc})")
        rc = api.MsiViewExecute(hview.value, 0)
        if rc:
            raise OSError(rc, f"MsiViewExecute falhou ({rc})")
        rc = api.MsiViewFetch(hview.value, ctypes.byref(hrec))
        yield api, (hrec if rc == 0 else None)
    finally:
        for hnd in (hrec, hview, hdb):
            if hnd.value:
                api.MsiCloseHandle(hnd.value)


def msi_texto(caminho: Path, sql: str) -> Optional[str]:
    """Primeira coluna (texto) da primeira linha da consulta; None se não houver linha."""
    with _msi_primeiro_registro(caminho, sql) as (api, rec):
        if rec is None:
            return None
        tam = 4096
        while True:
            buf = ctypes.create_unicode_buffer(tam)
            n = ctypes.c_ulong(tam)
            rc = api.MsiRecordGetStringW(rec.value, 1, buf, ctypes.byref(n))
            if rc == 234:               # ERROR_MORE_DATA: n = tamanho necessário
                tam = n.value + 1
                continue
            if rc:
                raise OSError(rc, f"MsiRecordGetString falhou ({rc})")
            return buf.value


def msi_tamanho_stream(caminho: Path, sql: str) -> int:
    """Tamanho (bytes) do fluxo binário da 1ª coluna da 1ª linha; 0 se não houver."""
    with _msi_primeiro_registro(caminho, sql) as (api, rec):
        return int(api.MsiRecordDataSize(rec.value, 1)) if rec is not None else 0


def msi_extrair_stream(caminho: Path, sql: str, destino: Path) -> bool:
    """Grava em 'destino' o fluxo binário da 1ª coluna (ex.: Binary.Data). True se gravou tudo."""
    with _msi_primeiro_registro(caminho, sql) as (api, rec):
        if rec is None:
            return False
        esperado = api.MsiRecordDataSize(rec.value, 1)
        buf = ctypes.create_string_buffer(1 << 20)
        total = 0
        with open(destino, "wb") as f:
            while True:
                n = ctypes.c_ulong(len(buf))
                rc = api.MsiRecordReadStream(rec.value, 1, buf, ctypes.byref(n))
                if rc:
                    raise OSError(rc, f"MsiRecordReadStream falhou ({rc})")
                if n.value == 0:
                    break
                f.write(buf.raw[:n.value])
                total += n.value
        return total == esperado and total > 0


def msi_defeituoso(msi: Path) -> bool:
    """True se o MSI foi gerado por este programa (versões <= 1.4) e não tem nenhum Component
    (o defeito que causava o erro 1603). MSIs de terceiros nunca são considerados defeituosos."""
    try:
        if msi_texto(msi, "SELECT `Value` FROM `Property` WHERE `Property`='Manufacturer'") != "Instalador Automatico":
            return False
        if msi_texto(msi, "SELECT `Name` FROM `Binary` WHERE `Name`='SetupExe'") is None:
            return False
    except OSError:
        return False
    try:
        return msi_texto(msi, "SELECT `Component` FROM `Component`") is None
    except OSError:
        return True      # tabela Component nem existe


def reparar_msis_antigos(simular: bool = False) -> tuple:
    """Refaz os MSI defeituosos das versões antigas: extrai o .exe embutido (tabela Binary),
    reconstrói o pacote com o Component e só então substitui o MSI. Devolve (reparados, pendencias).
    Argumentos silenciosos: 1) '<nome>.exe.args' ao lado do MSI; 2) os já gravados no MSI; 3) detecção."""
    candidatos = []
    for pasta in pastas_validas():
        for msi in listar_msi(pasta):
            try:
                if msi_defeituoso(msi):
                    candidatos.append((pasta, msi))
            except Exception:  # noqa: BLE001
                continue
    if not candidatos:
        return 0, 0

    print(f"  {ts()}{BOLD}{'SIMULAÇÃO: ' if simular else ''}Reparo: {len(candidatos)} MSI(s) "
          f"gerado(s) por versão antiga (sem Component, falhavam com 1603){RESET}\n")
    wix = None if simular else localizar_wix()
    if not simular and wix is None:
        print(f"  {VERMELHO}[ERRO] WiX não encontrado em {SCRIPT_DIR / WIX_DIRNAME}; reparo adiado.{RESET}\n")
        ESTADO["conversoes"].extend((f"{p.name}\\{m.name}", "ERRO", "reparo: WiX ausente") for p, m in candidatos)
        gravar_status()
        return 0, len(candidatos)

    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    reparados = pendencias = 0
    for pasta, msi in candidatos:
        nome = f"{pasta.name}\\{msi.name}"
        print(f"  {ts()}{CIANO}[REPARO]{RESET} {nome} {CINZA}({msi.stat().st_size // 1048576} MB){RESET}")
        if simular:
            ESTADO["conversoes"].append((nome, "SIMULADO", "seria reparado"))
            print(f"        {ts()}{CINZA}[SIMULADO] seria reparado{RESET}\n")
            continue
        backup = msi.with_name(msi.name + ".antigo")
        try:
            with tempfile.TemporaryDirectory(prefix="reparo_") as t:
                exe = Path(t) / f"{msi.stem}.exe"        # mesmo nome => mesmo UpgradeCode/Nome
                if not msi_extrair_stream(msi, "SELECT `Data` FROM `Binary` WHERE `Name`='SetupExe'", exe):
                    raise RuntimeError("não foi possível extrair o .exe de dentro do MSI antigo")
                args = ""
                sidecar = msi.with_name(msi.stem + ".exe.args")
                if sidecar.is_file():
                    linhas = sidecar.read_text(encoding="utf-8-sig", errors="replace").strip().splitlines()
                    args = linhas[0].strip() if linhas else ""
                if not args:
                    args = msi_texto(msi, "SELECT `Target` FROM `CustomAction` WHERE `Action`='RunInstall'") or ""
                if not args:
                    achado = detectar_instalador(exe)
                    args = achado[1] if achado else ""
                if not args:
                    raise RuntimeError(f"argumentos silenciosos desconhecidos; crie '{msi.stem}.exe.args'")
                novo = Path(t) / msi.name
                ok, msg = construir_msi(exe, novo, args, wix, LOG_DIR / f"reparo_{msi.stem}_{carimbo}.log")
                if not ok:
                    raise RuntimeError(msg)
                rv = val.validar_pacote(novo, exe=exe, completo=VALIDACAO_COMPLETA, progresso=_progresso("reparo"))
                if rv.nivel != "ok":
                    raise RuntimeError(f"MSI reconstruído não passou na validação ({rv.resumo})")
                shutil.move(str(msi), str(backup))        # só troca depois de tudo verificado
                try:
                    shutil.move(str(novo), str(msi))
                except Exception:
                    shutil.move(str(backup), str(msi))    # desfaz
                    raise
            backup.unlink(missing_ok=True)
            reparados += 1
            ESTADO["conversoes"].append((nome, " OK ", f"MSI reparado (argumentos: {args})"))
            print(f"        {ts()}{VERDE}[ OK ] MSI reparado{RESET} {CINZA}(argumentos: {args}){RESET}\n")
        except Exception as exc:  # noqa: BLE001
            pendencias += 1
            ESTADO["conversoes"].append((nome, "FALHA", f"reparo: {exc}; MSI antigo mantido"))
            print(f"        {ts()}{VERMELHO}[FALHA] {exc}; MSI antigo mantido{RESET}\n")
        gravar_status()
    return reparados, pendencias


def converter_exes(simular: bool = False, manter: bool = False) -> tuple:
    """Varre as pastas, converte cada .exe em .msi e (opcional) apaga o .exe.

    Devolve (encontrados, pendencias). Em modo simular só mostra o que faria.
    Um .exe só é apagado se o MSI foi gerado E verificado; qualquer dúvida mantém o .exe.
    """
    exes = [(pasta, exe) for pasta in pastas_validas() for exe in listar_exe(pasta)]
    if not exes:
        print(f"  {ts()}{CINZA}Nenhum .exe encontrado para converter.{RESET}")
        return 0, 0

    titulo = "SIMULAÇÃO" if simular else "Convertendo"
    print(f"  {ts()}{BOLD}{titulo}: {len(exes)} arquivo(s) .exe encontrado(s){RESET}\n")
    wix = None if simular else localizar_wix()
    if not simular and wix is None:
        print(f"  {VERMELHO}[ERRO] WiX não encontrado. Coloque candle.exe e light.exe em:{RESET}")
        print(f"         {SCRIPT_DIR / WIX_DIRNAME}")
        print(f"  {CINZA}(ou use --sem-converter para pular esta etapa){RESET}\n")
        ESTADO["conversoes"].extend((f"{p.name}\\{e.name}", "ERRO", "WiX ausente") for p, e in exes)
        gravar_status()
        return len(exes), len(exes)

    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    ESTADO.update(estado="CONVERTENDO EXE -> MSI", inicio=datetime.now(), total=len(exes),
                  atual=0, pacote="", acao="", resultados=[])
    pendencias = 0

    def registrar(nome: str, status: str, detalhe: str, cor: str) -> None:
        ESTADO["conversoes"].append((nome, status, detalhe))
        print(f"        {ts()}{cor}[{status}]{RESET} {detalhe}\n")
        gravar_status()
        nivel = {VERDE: "ok", VERMELHO: "erro", AMARELO: "aviso"}.get(cor, "info")
        evento("aviso", msg=f"[{status.strip()}] {detalhe}", nivel=nivel)

    for i, (pasta, exe) in enumerate(exes, start=1):
        nome = f"{pasta.name}\\{exe.relative_to(pasta)}"
        print(f"  {ts()}{CIANO}[{i}/{len(exes)}]{RESET} {nome} {CINZA}({exe.stat().st_size // 1048576} MB){RESET}")
        ESTADO.update(atual=i, pacote=nome, acao="convertendo")
        gravar_status()
        evento("prep_item", i=i, total=len(exes), nome=nome)
        msi = exe.with_suffix(".msi")

        origem, args, conhecido = argumentos_do_exe(exe)
        if origem == "IGNORAR":
            registrar(nome, "IGNORADO", "marcado como IGNORAR no .args", CINZA)
            continue
        if msi.exists():
            if pacote_embutido(msi):
                registrar(nome, "JÁ FEITO", f"{msi.name} já foi gerado antes por este programa", CINZA)
            else:
                pendencias += 1
                registrar(nome, "PULADO", f"já existe {msi.name} (de outra origem) com esse nome; "
                          f".exe mantido", AMARELO)
            continue
        if any(c.suffix.lower() == ".cab" for c in exe.parent.iterdir() if c.is_file()):
            pendencias += 1
            registrar(nome, "PULADO", "há arquivos .cab na pasta (parece bootstrapper de um MSI "
                      "existente); .exe mantido", AMARELO)
            continue

        print(f"        {CINZA}tipo: {origem} | argumentos: {args}{RESET}")
        if simular:
            registrar(nome, "SIMULADO", f"geraria {msi.name}", CINZA)
            continue

        ok, msg = construir_msi(exe, msi, args, wix, LOG_DIR / f"conv_{exe.stem}_{carimbo}.log")
        if not ok:
            pendencias += 1
            msi.unlink(missing_ok=True)
            registrar(nome, "FALHA", f"{msg}; .exe mantido (log em logs\\conv_{exe.stem}_{carimbo}.log)", VERMELHO)
            continue
        ESTADO["acao"] = "validando o MSI gerado"
        rv = validar_msi(msi, exe=exe, forcar=True, progresso=_progresso("conversão"))
        if rv.nivel == "erro":
            pendencias += 1
            VALIDACOES.pop(msi, None)
            registrar(nome, "FALHA", f"{msi.name} gerado mas REPROVADO na validação ({rv.resumo}); "
                      f"MSI removido e .exe mantido", VERMELHO)
            msi.unlink(missing_ok=True)
            continue
        if rv.nivel == "aviso":
            pendencias += 1
            registrar(nome, "AVISO", f"{msi.name} criado com aviso na validação ({rv.resumo}); "
                      f".exe mantido por segurança", AMARELO)
            continue

        if not conhecido:
            registrar(nome, " OK ", f"{msi.name} criado e verificado. Tipo de instalador DESCONHECIDO: o "
                      f".exe foi MANTIDO. Na instalação serão tentados vários argumentos silenciosos; "
                      f"se um deles funcionar, grave-o em '{exe.name}.args'", AMARELO)
        elif EXCLUIR_EXE_APOS_CONVERTER and not manter:
            try:
                exe.unlink()      # o '<nome>.exe.args' é MANTIDO: a instalação lê as tentativas dele
                registrar(nome, " OK ", f"{msi.name} criado e verificado; .exe excluído", VERDE)
            except OSError as exc:
                pendencias += 1
                registrar(nome, " OK ", f"{msi.name} criado, mas não foi possível excluir o .exe ({exc})", AMARELO)
        else:
            registrar(nome, " OK ", f"{msi.name} criado e verificado; .exe mantido", VERDE)

    ESTADO.update(estado="CONVERSÃO CONCLUÍDA", pacote="", acao="")
    gravar_status()
    return len(exes), pendencias


# ----------------------------------------------------------------------------
# Etapa de VALIDAÇÃO (depois da conversão, antes da instalação)
# ----------------------------------------------------------------------------
def _progresso(origem: str = ""):
    """Callback (fração, texto) para a validação: limita a ~7 eventos/s para não inundar a tela."""
    ultimo = [0.0]

    def cb(frac: float, texto: str) -> None:
        agora = time.time()
        if frac < 1.0 and agora - ultimo[0] < 0.15:
            return
        ultimo[0] = agora
        evento("prog", frac=frac, texto=texto)
    return cb


def status_validacao(msi: Path):
    """(nivel, resumo) do último resultado deste .msi, ou None se ainda não foi validado."""
    r = VALIDACOES.get(Path(msi))
    return (r.nivel, r.resumo) if r is not None else None


def exes_sem_msi() -> list:
    """.exe que continuam sem .msi ao lado (conversão falhou/foi pulada) e, portanto, NÃO serão instalados."""
    achados = []
    for pasta in pastas_validas():
        for exe in listar_exe(pasta):
            if exe.with_suffix(".msi").exists():
                continue
            try:
                if argumentos_do_exe(exe)[0] == "IGNORAR":
                    continue
            except Exception:  # noqa: BLE001
                pass
            achados.append((pasta, exe))
    return achados


def validar_todos(simular: bool = False) -> tuple:
    """Valida TODOS os .msi de todas as pastas (um por um, com progresso), confere colisões entre eles,
    grava logs\\validacao_*.txt e atualiza VALIDACOES/status. Devolve (ok, avisos, erros)."""
    pacotes = [(pasta, msi) for pasta, msis in descobrir_diretorios() for msi in msis]
    if not pacotes:
        print(f"  {ts()}{CINZA}Nenhum .msi para validar.{RESET}")
        return 0, 0, 0
    total = len(pacotes)
    modo = "completa (lê cada instalador por inteiro)" if VALIDACAO_COMPLETA else "rápida (estrutura e tamanhos)"
    print(f"  {ts()}{BOLD}Validando {total} pacote(s) MSI - validação {modo}{RESET}\n")
    ESTADO.update(estado="VALIDANDO PACOTES", inicio=datetime.now(), total=total, atual=0, pacote="", acao="")
    ESTADO["validacoes"] = []
    evento("etapa", numero=2, titulo="Validando os pacotes", total=total)
    resultados = []
    cores = {"ok": (VERDE, " OK "), "aviso": (AMARELO, "AVISO"), "erro": (VERMELHO, "ERRO")}

    def mostrar(i: int, nome: str, r, a_partir: int = 0) -> None:
        """Escreve no console e na tela o veredito (e só os itens com problema) a partir da verificação N."""
        problemas = [v for v in r.verificacoes[a_partir:] if v.nivel in ("aviso", "erro")]
        if a_partir == 0:
            cor, marca = cores[r.nivel]
            print(f"        {ts()}{cor}[{marca}] {r.resumo}{RESET} {CINZA}({r.duracao:.0f}s){RESET}", flush=True)
        else:
            print(f"        {ts()}{AMARELO}[AVISO] {nome}: conflito com outro pacote{RESET}", flush=True)
        for v in problemas:
            c = VERMELHO if v.nivel == "erro" else AMARELO
            print(f"              {c}- {v.nome}: {v.detalhe}{RESET}", flush=True)
        evento("val_resultado", i=i, total=total, nome=nome, nivel=r.nivel, resumo=r.resumo, tardio=a_partir > 0,
               problemas=[(v.nivel, v.nome, v.detalhe) for v in problemas])

    for i, (pasta, msi) in enumerate(pacotes, start=1):
        nome = f"{pasta.name}\\{msi.relative_to(pasta)}"
        tam = msi.stat().st_size // 1048576 if msi.exists() else 0
        print(f"  {ts()}{CIANO}[{i}/{total}]{RESET} {nome} {CINZA}({tam} MB){RESET}", flush=True)
        ESTADO.update(atual=i, pacote=nome, acao="validando")
        gravar_status()
        evento("val_item", i=i, total=total, nome=nome)
        r = validar_msi(msi, progresso=_progresso("validação"))
        val.limpar_lote(r)
        resultados.append((i, nome, r, len(r.verificacoes)))
        mostrar(i, nome, r)
    val.checar_lote([r for _, _, r, _ in resultados])    # colisões entre pacotes (ProductCode / UpgradeCode)
    for i, nome, r, n_antes in resultados:
        if len(r.verificacoes) > n_antes:                 # ganhou aviso de colisão com outro pacote
            mostrar(i, nome, r, a_partir=n_antes)

    ok = avisos = erros = 0
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    relatorio = [f"Validação em {datetime.now():%d/%m/%Y %H:%M:%S} - validador {val.VERSAO_VALIDADOR} - "
                 f"modo {'completo' if VALIDACAO_COMPLETA else 'rápido'}", ""]
    for i, nome, r, _ in resultados:
        _, marca = cores[r.nivel]
        ok, avisos, erros = ok + (r.nivel == "ok"), avisos + (r.nivel == "aviso"), erros + (r.nivel == "erro")
        ESTADO["validacoes"].append((nome, r.nivel, r.resumo))
        relatorio += [f"[{marca}] {nome}  ({r.tamanho / 1048576:.1f} MB, {r.duracao:.1f}s)"]
        relatorio += ["      " + l for l in r.linhas()] + [""]
    pendentes = exes_sem_msi()
    for pasta, exe in pendentes:
        txt = f"{pasta.name}\\{exe.name}: .exe SEM .msi - não será instalado (veja a conversão)"
        print(f"        {ts()}{AMARELO}[AVISO] {txt}{RESET}")
        relatorio.append(f"[AVISO] {txt}")
        evento("aviso", msg=txt, nivel="aviso")
    resumo = (f"RESUMO DA VALIDAÇÃO: {ok} OK | {avisos} com aviso | {erros} BLOQUEADO(S)"
              f"{f' | {len(pendentes)} .exe sem .msi' if pendentes else ''} | total {total}")
    print(f"\n  {BOLD}{resumo}{RESET}\n")
    relatorio += ["", resumo]
    try:
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / f"validacao_{carimbo}.txt").write_text("\n".join(relatorio) + "\n", encoding="utf-8")
    except OSError:
        pass
    ESTADO.update(estado="VALIDAÇÃO CONCLUÍDA", pacote="", acao="")
    gravar_status()
    evento("val_fim", ok=ok, avisos=avisos, erros=erros, sem_msi=len(pendentes), total=total)
    return ok, avisos, erros


# ----------------------------------------------------------------------------
# Menu
# ----------------------------------------------------------------------------
def interpretar_escolha(escolha: str, dirs: list[tuple[Path, list[Path]]]):
    """Aceita: 'A' (todos), '2' ou '1,3,4'. Retorna lista ou None se inválido."""
    escolha = escolha.strip().lower()
    if escolha in ("a", "t", "todos", "all"):
        return dirs
    try:
        indices = {int(x) for x in escolha.replace(" ", "").split(",") if x}
    except ValueError:
        return None
    if not indices or any(i < 1 or i > len(dirs) for i in indices):
        return None
    return [dirs[i - 1] for i in sorted(indices)]


def interpretar_indices(escolha: str, total: int):
    """Aceita '2', '1,3,5' e intervalos '4-7'. Retorna lista ordenada de índices (1..total) ou None."""
    indices = set()
    try:
        for parte in escolha.replace(" ", "").split(","):
            if not parte:
                continue
            if "-" in parte:
                a, b = (int(x) for x in parte.split("-", 1))
                indices.update(range(min(a, b), max(a, b) + 1))
            else:
                indices.add(int(parte))
    except ValueError:
        return None
    if not indices or any(i < 1 or i > total for i in indices):
        return None
    return sorted(indices)


def escolher_softwares(dirs: list[tuple[Path, list[Path]]]):
    """Tela de seleção individual: lista TODOS os MSI (agrupados por pasta) com numeração única.
    Devolve [(pasta, [msi, ...])] com o que foi marcado, ou None se o usuário cancelar (0)."""
    while True:
        cabecalho()
        print(f"\n  {BOLD}Selecione os SOFTWARES que deseja instalar:{RESET}\n")
        itens: list[tuple[Path, Path]] = []
        for pasta, msis in dirs:
            print(f"   {AMARELO}{pasta.name}{RESET}")
            for msi in msis:
                itens.append((pasta, msi))
                mb = max(1, msi.stat().st_size // 1048576) if msi.exists() else 0
                print(f"     {CIANO}[{len(itens):>2}]{RESET} {msi.name} {CINZA}({mb} MB){RESET}")
            print()
        print(f"   {VERDE}[A]{RESET} Todos    {CIANO}[0]{RESET} Voltar")
        print(f"\n  {CINZA}Dica: vários separados por vírgula ou intervalo, ex: 1,3 ou 2-5{RESET}\n")
        rodape()
        escolha = input(f"\n{AMARELO}  Opção: {RESET}").strip()
        if escolha == "0":
            return None
        if escolha.lower() in ("a", "t", "todos", "all"):
            return dirs
        idx = interpretar_indices(escolha, len(itens))
        if idx is None:
            print(f"\n  {VERMELHO}Opção inválida.{RESET}")
            pausar()
            continue
        agrupado: dict[Path, list[Path]] = {}
        for i in idx:
            pasta, msi = itens[i - 1]
            agrupado.setdefault(pasta, []).append(msi)
        return list(agrupado.items())


def menu() -> None:
    while True:
        dirs = descobrir_diretorios()
        cabecalho()

        if not dirs:
            print(f"\n  {AMARELO}Nenhuma pasta com arquivos .msi foi encontrada ao lado")
            print(f"  deste programa. Adicione as pastas e tente novamente.{RESET}")
            print(f"\n  {CIANO}[R]{RESET} Reescanear   {CIANO}[0]{RESET} Sair\n")
            rodape()
            op = input(f"\n{AMARELO}  Opção: {RESET}").strip().lower()
            if op == "0":
                return
            continue

        total_msi = sum(len(m) for _, m in dirs)
        print(f"\n  {BOLD}Selecione o que deseja instalar:{RESET}\n")
        for i, (pasta, msis) in enumerate(dirs, start=1):
            print(f"   {CIANO}[{i}]{RESET} {pasta.name:<30} {CINZA}({len(msis)} MSI){RESET}")
        print()
        print(f"   {VERDE}[A]{RESET} {BOLD}INSTALAR TUDO{RESET}"
              f"                    {CINZA}({total_msi} MSI){RESET}")
        print(f"   {VERDE}[S]{RESET} {BOLD}ESCOLHER SOFTWARES UM A UM{RESET}")
        print(f"   {CIANO}[R]{RESET} Reescanear diretórios")
        print(f"   {CIANO}[0]{RESET} Sair")
        print(f"\n  {CINZA}Dica: para várias pastas use vírgula, ex: 1,3{RESET}\n")
        rodape()
        escolha = input(f"\n{AMARELO}  Opção: {RESET}").strip()

        if escolha == "0":
            return
        if escolha.lower() == "r":
            continue

        if escolha.lower() == "s":
            selecionados = escolher_softwares(dirs)
            if selecionados is None:
                continue
        else:
            selecionados = interpretar_escolha(escolha, dirs)
            if selecionados is None:
                print(f"\n  {VERMELHO}Opção inválida.{RESET}")
                pausar()
                continue

        qtd = sum(len(m) for _, m in selecionados)
        print(f"\n  {BOLD}Será instalado ({qtd} MSI):{RESET}")
        for pasta, msis in selecionados:
            for msi in msis:
                print(f"    {CINZA}•{RESET} {pasta.name} {CINZA}›{RESET} {BRANCO}{msi.name}{RESET}")
        if input(f"  {AMARELO}Confirmar? (S/N): {RESET}").strip().lower() not in ("s", "sim", "y"):
            continue

        instalar_lista(selecionados)
        print()
        rodape()
        pausar()


def preparar_pacotes(cb=None, manter: bool = False, converter: bool = True) -> tuple:
    """Repara MSIs antigos, converte .exe -> .msi e VALIDA todos os .msi. 'cb' recebe eventos da tela gráfica.
    Devolve (reparados, exes_encontrados, pendencias)."""
    global _CB_EVENTO
    _CB_EVENTO = cb
    try:
        reparados = encontrados = pend_reparo = pend_conv = 0
        if converter:
            evento("etapa", numero=1, titulo="Convertendo EXE em MSI", total=0)
            reparados, pend_reparo = reparar_msis_antigos()
            encontrados, pend_conv = converter_exes(manter=manter)
        pend_val = 0
        if VALIDAR:
            _, avisos, erros = validar_todos()
            pend_val = avisos + erros
        return reparados, encontrados, pend_reparo + pend_conv + pend_val
    finally:
        _CB_EVENTO = None


def _marcar_tela_aberta() -> None:
    """Avisa o INICIAR.bat que a janela apareceu de fato (ele espera por este arquivo)."""
    with contextlib.suppress(Exception):
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / "tela_aberta.flag").write_text(f"{os.getpid()}\n", encoding="utf-8")
    print(f"  {datetime.now():%H:%M:%S} Tela gráfica aberta.", flush=True)


def abrir_interface(preparar=None) -> bool:
    """Abre a tela gráfica. 'preparar(callback)' (opcional) roda ANTES da seleção, dentro da própria tela
    (conversão/reparo de .exe -> .msi), para o técnico ver só ela. False = não foi possível abrir."""
    global GUI_ATIVA
    try:
        import tela_instalacao   # mesma pasta deste arquivo
        import tkinter           # noqa: F401  (vem com o Python do Windows; Include_tcltk=1)
    except Exception as exc:  # noqa: BLE001
        print(f"  {AMARELO}[AVISO] Tela gráfica indisponível ({exc}); usando o menu de texto.{RESET}")
        return False

    def abrir_logs() -> None:
        LOG_DIR.mkdir(exist_ok=True)
        with contextlib.suppress(Exception):
            os.startfile(str(LOG_DIR))   # type: ignore[attr-defined]

    def instalar(itens, callback, cancelar, direto):
        return instalar_lista(itens, callback=callback, cancelar=cancelar, direto=direto)

    GUI_ATIVA = True
    try:
        tela_instalacao.abrir({
            "titulo": "Instalador Automático MSI", "versao": VERSAO, "desenvolvedor": DESENVOLVEDOR,
            "admin": eh_admin(), "obter_dirs": descobrir_diretorios,
            "classificar": classificar_pacote, "instalar": instalar, "abrir_logs": abrir_logs,
            "preparar": preparar, "status_validacao": status_validacao,
            "preselecionar": PRESELECIONAR_VALIDOS and VALIDAR,
            "ao_abrir": _marcar_tela_aberta,
        })
    except Exception as exc:  # noqa: BLE001
        GUI_ATIVA = False
        print(f"  {VERMELHO}[ERRO] A tela gráfica falhou ({exc}); usando o menu de texto.{RESET}")
        return False
    finally:
        GUI_ATIVA = False
    return True


def selecionar_pastas(dirs, nomes: Optional[str] = None):
    """Filtra as pastas pelo nome (separados por vírgula). None = todas."""
    if not nomes:
        return dirs
    pedidos = [n.strip().lower() for n in nomes.split(",") if n.strip()]
    por_nome = {p.name.lower(): (p, m) for p, m in dirs}
    faltando = [n for n in pedidos if n not in por_nome]
    if faltando:
        print(f"{VERMELHO}[ERRO] Pasta(s) não encontrada(s) ou sem MSI: {', '.join(faltando)}{RESET}")
        return None
    return [por_nome[n] for n in pedidos]


def modo_automatico(args: argparse.Namespace) -> int:
    """Instala sem nenhuma interação. Retorna o código de saída do processo."""
    pendencias = 0
    if CONVERTER_EXE and not args.sem_converter:
        _, pend_reparo = reparar_msis_antigos(simular=args.listar)
        _, pendencias = converter_exes(simular=args.listar, manter=args.manter_exe)
        pendencias += pend_reparo

    dirs = descobrir_diretorios()
    if args.listar:
        for pasta, msis in dirs:
            print(f"{pasta.name} ({len(msis)} MSI)")
            for m in msis:
                print(f"   - {m.relative_to(BASE)}")
        return 0
    if not dirs:
        print("Nenhuma pasta com arquivos .msi encontrada.")
        return 4
    if VALIDAR:
        validar_todos()          # relatório completo; pacotes com ERRO são bloqueados na instalação
    selecionados = selecionar_pastas(dirs, args.pastas)
    if selecionados is None:
        return 2
    falhas, reboot = instalar_lista(selecionados)
    if falhas:
        return 1
    if pendencias:
        return 6
    return 3010 if reboot else 0


def ler_argumentos() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=TITULO)
    ap.add_argument("--auto", action="store_true",
                    help="modo automático: sem apresentação, menu ou confirmação")
    ap.add_argument("--pastas", default=None,
                    help='pastas a instalar, separadas por vírgula (padrão: todas). Ex.: "Office,Drivers"')
    ap.add_argument("--listar", action="store_true",
                    help="apenas lista as pastas/MSIs encontrados (com --auto)")
    ap.add_argument("--sem-converter", action="store_true",
                    help="não converte .exe em .msi (só instala os .msi existentes)")
    ap.add_argument("--manter-exe", action="store_true",
                    help="converte, mas NÃO apaga os .exe originais")
    ap.add_argument("--sem-validar", action="store_true",
                    help="não valida os pacotes antes de instalar (não recomendado)")
    ap.add_argument("--validacao-rapida", action="store_true",
                    help="valida só estrutura e tamanhos (não lê cada instalador por inteiro / sem SHA-256)")
    ap.add_argument("--ignorar-bloqueio", action="store_true",
                    help="valida e mostra o relatório, mas instala mesmo os pacotes reprovados (emergência)")
    ap.add_argument("--console", action="store_true",
                    help="usa o menu de texto em vez da tela gráfica")
    ap.add_argument("--via-msiexec", action="store_true",
                    help="instala os MSI gerados pelo programa via msiexec (padrão: roda o .exe embutido direto)")
    ap.add_argument("--ver-janelas", action="store_true",
                    help="diagnóstico: NÃO oculta nem encerra telas dos instaladores (só registra título/classe)")
    ap.add_argument("--lancador", action="store_true", help=argparse.SUPPRESS)  # uso interno do .bat
    ap.add_argument("--menu", action="store_true", help=argparse.SUPPRESS)      # uso interno do .bat
    ap.add_argument("--raiz", default=None,
                    help="pasta que contém as subpastas de MSI (padrão: pasta pai de #SISTEMA)")
    ap.add_argument("--sem-pausa", action="store_true",
                    help="(usado pelo .bat) não pausa ao final; use em tarefas agendadas/GPO")
    ap.add_argument("--sem-cores", action="store_true", help="desativa cores ANSI")
    return ap.parse_args()


def _garantir_streams() -> None:
    """Com pythonw.exe (sem console) sys.stdout/sys.stderr são None e qualquer print() derrubaria o
    programa. Redireciona para logs\\console.log."""
    global SEM_CONSOLE
    if sys.stdout is not None and sys.stderr is not None:
        return
    SEM_CONSOLE = True
    try:
        LOG_DIR.mkdir(exist_ok=True)
        f = open(LOG_DIR / "console.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        f = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f
    desativar_cores()
    _ativar_diagnostico()


_ARQ_FALHA = None


def _ativar_diagnostico() -> None:
    """Com pythonw, um travamento nativo (ctypes/msi.dll/Tk) ou um erro numa thread fechava a tela SEM
    deixar rastro. Agora: falha nativa -> logs\\falha_nativa.txt; erro em thread -> logs\\erro_fatal.txt."""
    global _ARQ_FALHA
    with contextlib.suppress(Exception):
        import faulthandler
        LOG_DIR.mkdir(exist_ok=True)
        _ARQ_FALHA = open(LOG_DIR / "falha_nativa.txt", "a", encoding="utf-8")
        _ARQ_FALHA.write(f"\n=== início {datetime.now():%d/%m/%Y %H:%M:%S} | Python {sys.version.split()[0]} "
                         f"| {sys.executable}\n")
        _ARQ_FALHA.flush()
        faulthandler.enable(file=_ARQ_FALHA, all_threads=True)

    import threading

    def _gancho_thread(a) -> None:
        if a.exc_type is SystemExit:
            return
        texto = "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback))
        with contextlib.suppress(Exception):
            (LOG_DIR / "erro_fatal.txt").open("a", encoding="utf-8").write(
                f"{datetime.now():%d/%m/%Y %H:%M:%S} [thread {getattr(a.thread, 'name', '?')}]\n{texto}\n")
        with contextlib.suppress(Exception):
            print(texto, flush=True)
    threading.excepthook = _gancho_thread


def _erro_fatal(exc: BaseException) -> None:
    """Registra o erro e, sem console, mostra uma caixa de mensagem (senão ninguém veria)."""
    texto = traceback.format_exc()
    with contextlib.suppress(Exception):
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / "erro_fatal.txt").write_text(f"{datetime.now():%d/%m/%Y %H:%M:%S}\n{texto}", encoding="utf-8")
    print(texto)
    if SEM_CONSOLE:
        with contextlib.suppress(Exception):
            import tkinter
            from tkinter import messagebox
            raiz = tkinter.Tk()
            raiz.withdraw()
            messagebox.showerror(TITULO, f"Erro inesperado:\n{exc}\n\nDetalhes em:\n{LOG_DIR / 'erro_fatal.txt'}")
            raiz.destroy()


def main() -> None:
    global AUTO, ANIMACAO, BASE, MODO_DIRETO, OCULTAR_JANELAS, VIGIAR_UI
    global VALIDAR, VALIDACAO_COMPLETA, BLOQUEAR_INVALIDOS
    _garantir_streams()          # PRIMEIRO: com pythonw, qualquer erro antes disto sumia sem rastro
    print(f"  {datetime.now():%d/%m/%Y %H:%M:%S} Iniciando ({Path(sys.executable).name}) argumentos: "
          f"{' '.join(sys.argv[1:]) or '-'}", flush=True)
    try:
        args = ler_argumentos()
    except SystemExit:
        print("  [ERRO] Argumentos inválidos na linha de comando (veja acima).", flush=True)
        raise
    if args.sem_validar:
        VALIDAR = False
    if args.validacao_rapida:
        VALIDACAO_COMPLETA = False
    if args.ignorar_bloqueio:
        BLOQUEAR_INVALIDOS = False
    if args.via_msiexec:
        MODO_DIRETO = False
    if args.ver_janelas:
        OCULTAR_JANELAS = VIGIAR_UI = False
    if args.raiz:
        BASE = Path(args.raiz).resolve()
    if args.auto:
        AUTO, ANIMACAO = True, False
    if args.sem_cores or (AUTO and not sys.stdout.isatty()):
        desativar_cores()

    if os.name != "nt":
        print("Este instalador só funciona no Windows.")
        sys.exit(1)
    if not eh_admin():
        if AUTO:
            print("[ERRO] Execute como administrador (modo automático não usa UAC).")
            sys.exit(5)
        print("Solicitando privilégios de administrador...")
        reexecutar_como_admin()
    habilitar_ansi()
    if AUTO:
        sys.exit(modo_automatico(args))
    try:
        usar_prep = CONVERTER_EXE and not args.sem_converter
        if args.console:
            if usar_prep:
                limpar_tela()
                reparados, pend_reparo = reparar_msis_antigos()
                encontrados, pend_conv = converter_exes(manter=args.manter_exe)
            _, av_val, er_val = validar_todos() if VALIDAR else (0, 0, 0)
            if usar_prep and (pend_reparo or pend_conv or encontrados or reparados) or av_val or er_val:
                pausar()
            tela_apresentacao()
            menu()
        else:
            prep = ((lambda cb: preparar_pacotes(cb, args.manter_exe, usar_prep))
                    if (usar_prep or VALIDAR) else None)
            if not abrir_interface(prep):
                if SEM_CONSOLE:
                    raise RuntimeError("Não foi possível abrir a tela gráfica (tkinter ausente?). "
                                       "Veja logs\\console.log ou use INSTALAR.bat --console.")
                if usar_prep or VALIDAR:
                    preparar_pacotes(None, args.manter_exe, usar_prep)
                tela_apresentacao()
                menu()
    except KeyboardInterrupt:
        print(f"\n\n{AMARELO}Interrompido pelo usuário.{RESET}")
    except Exception as exc:  # noqa: BLE001
        _erro_fatal(exc)
        sys.exit(3)
    limpar_tela()
    print(f"\n{CIANO}Obrigado por usar o {TITULO}!{RESET}")
    print(f"{DIM}{CINZA}desenvolvido por {DESENVOLVEDOR}{RESET}\n")


if __name__ == "__main__":
    try:
        main()
    except (SystemExit, KeyboardInterrupt):
        raise
    except BaseException as _exc:  # noqa: BLE001 - erro na partida: registra e mostra (com pythonw seria invisível)
        _erro_fatal(_exc)
        sys.exit(3)

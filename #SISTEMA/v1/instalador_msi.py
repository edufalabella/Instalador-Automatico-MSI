# -*- coding: utf-8 -*-
"""
Instalador automatizado (MSI e EXE)
-----------------------------------
Cada subpasta com arquivos .msi e/ou .exe vira uma opção da tela de seleção
(interface gráfica; --console usa o menu de texto).

  * .msi -> msiexec /qn (silencioso)
  * .exe -> executado DIRETAMENTE (sem conversão para MSI), em modo silencioso, com
            escada de argumentos por tipo de instalador. Se nenhum argumento silencioso
            funcionar, o instalador pode ser aberto normalmente para concluir com cliques.

Estrutura esperada:
    instalador_msi.py
    Office\\       -> *.msi / *.exe
    Drivers\\      -> *.msi / *.exe
    Utilitarios\\  -> *.msi / *.exe

Desenvolvido por Eduardo Falabella
"""

import argparse
import contextlib
import ctypes
import os
import re
import shutil
import subprocess
import threading
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import exec_silencioso as ex   # execução oculta, árvore de processos, watchdog (mesma pasta)
import validacao_msi as val    # validação rigorosa dos pacotes MSI/EXE (mesma pasta)
import analise_exe as ae       # instalador x portátil x menu, tipo e argumento silencioso (mesma pasta)

# ----------------------------------------------------------------------------
# Configurações
# ----------------------------------------------------------------------------
TITULO = "INSTALADOR AUTOMÁTICO"
VERSAO = "3.1"
DESENVOLVEDOR = "Eduardo Falabella"
PASTAS_IGNORADAS = {"logs", "__pycache__", "build", "dist"}
BUSCA_RECURSIVA = True          # procura .msi/.exe também dentro de subpastas
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

# --- validação dos pacotes (v2.2) ---
VALIDAR = True                  # valida TODOS os pacotes (.msi e .exe) antes de instalar
VALIDACAO_COMPLETA = False      # False = rápida (estrutura, tamanho, início e fim do arquivo); True = lê tudo
TRABALHADORES = max(4, min(32, (os.cpu_count() or 4) * 2))   # validação/análise em paralelo (todos os núcleos)
CACHE_ARQ = "cache_pacotes.json"   # em logs\: resultado de validação/análise por arquivo (tamanho+data)
BLOQUEAR_INVALIDOS = True       # pacote com ERRO na validação NÃO é instalado
PRESELECIONAR_VALIDOS = True    # na tela de seleção, já deixa marcados os pacotes que passaram na validação
CODIGO_BLOQUEADO = 1620         # código registrado para pacote bloqueado (ERROR_INSTALL_PACKAGE_INVALID)

# --- instalação de .exe (v3.0: SEM conversão para MSI) ---
INSTALAR_EXE = True             # .exe das pastas aparecem na lista e são executados diretamente
EXE_IGNORAR_PREFIXOS = ("unins", "uninst", "uninstall", "unwise")   # nunca executa desinstaladores
ESCONDER_COMPONENTES = True     # pasta com Setup.exe/Install.exe = MÍDIA de instalação: só o lançador aparece
LANCADORES_MIDIA = ("setup.exe", "install.exe", "installer.exe", "start.exe")   # (os componentes internos
                                # - 3rdParty, redistribuíveis, ferramentas - ficam escondidos)
PORTATEIS_ACAO = "copiar"       # programa PORTÁTIL: "copiar" = copia para PASTA_PORTATEIS + atalho na Área de
                                # Trabalho pública e no Menu Iniciar | "ignorar" = não faz nada
PASTA_PORTATEIS = r"C:\Portateis"
LIMITE_COPIA_PORTATIL_MB = 1024 # pasta do portátil maior que isso: copia só o .exe
PARADO_S = 180                  # .exe aberto SEM janela e SEM atividade por este tempo => encerrado
PULAR_EXE_COM_CAB = True        # pasta com .cab = .exe é bootstrapper de um .msi: só o .msi aparece
FALLBACK_INTERATIVO = True      # tela gráfica/menu: se o silencioso falhar, abre o instalador para clicar
                                # (no modo --auto fica desligado: não há ninguém para clicar)

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
    print(f"{CINZA}  Pasta dos pacotes: {BASE}{RESET}")
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
    centro("instalação em lote de pacotes MSI e EXE", CINZA)
    print()
    linha()
    print()

    dirs = descobrir_diretorios()
    total_msi = sum(len(m) for _, m in dirs)
    etapas = [
        ("Verificando privilégios de administrador", "OK" if eh_admin() else "AVISO"),
        ("Localizando diretórios de instalação", f"{len(dirs)} pasta(s)"),
        ("Contando pacotes MSI/EXE", f"{total_msi} pacote(s)"),
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


def exe_ignorado(exe: Path) -> bool:
    """True se o .exe NÃO deve aparecer na lista (desinstalador, IGNORAR no .args, bootstrapper...)."""
    if exe.name.lower().startswith(EXE_IGNORAR_PREFIXOS):
        return True
    args = _ler_linhas_args(exe.with_name(exe.name + ".args"))
    if args and args[0].upper() == "IGNORAR":
        return True
    if args:                       # .args explícito: o técnico quer este .exe
        return False
    irmao = exe.with_suffix(".msi")
    if irmao.is_file() and not pacote_embutido(irmao):
        return True                # já existe um .msi de verdade com o mesmo nome (usa o .msi)
    if PULAR_EXE_COM_CAB and exe.name.lower() not in LANCADORES_MIDIA:
        with contextlib.suppress(OSError):
            if any(c.suffix.lower() == ".cab" for c in exe.parent.iterdir() if c.is_file()):
                return True        # setup.exe + .msi + .cab: o .exe só chamaria o .msi (instalaria 2x)
    return False


ESCONDIDOS: dict = {}           # pasta da categoria -> quantos componentes internos foram escondidos


def listar_pacotes(pasta: Path) -> list[Path]:
    """.msi e .exe instaláveis da pasta.

    MÍDIA DE INSTALAÇÃO: uma subpasta com Setup.exe/Install.exe/Start.exe (AutoCAD, Inventor, TIA Portal,
    FluidSim...) mostra SÓ o lançador; os componentes internos (3rdParty, redistribuíveis, .msi das
    partes, ferramentas) ficam escondidos - quem instala tudo é o próprio Setup, na ordem certa.
    Um MSI antigo gerado pela conversão (versões <= 2.2) é escondido quando o .exe original está ao lado."""
    msis: list = []
    exes: list = []
    escondidos = 0
    for raiz, dirs, arqs in os.walk(pasta):
        r = Path(raiz)
        dirs[:] = sorted((d for d in dirs if not d.startswith(".") and d.lower() not in PASTAS_IGNORADAS),
                         key=str.lower)
        if not BUSCA_RECURSIVA and r != pasta:
            dirs[:] = []
            continue
        por_nome = {a.lower(): a for a in arqs}
        lancador = next((por_nome[l] for l in LANCADORES_MIDIA if l in por_nome), None)
        if ESCONDER_COMPONENTES and r != pasta and lancador and INSTALAR_EXE:
            exes.append(r / lancador)
            escondidos += sum(1 for a in arqs if a.lower().endswith((".exe", ".msi"))) - 1
            for d in dirs:
                for _, _, sub in os.walk(r / d):
                    escondidos += sum(1 for a in sub if a.lower().endswith((".exe", ".msi")))
            dirs[:] = []          # não desce: o resto é componente da mídia
            continue
        for a in arqs:
            al = a.lower()
            if al.endswith(".msi"):
                msis.append(r / a)
            elif al.endswith(".exe") and INSTALAR_EXE and not exe_ignorado(r / a):
                exes.append(r / a)
    # ferramentas de linha de comando portáteis (7za.exe, ffmpeg.exe...) e desinstaladores não aparecem:
    # não são programas para o usuário abrir nem instaladores. (.args explícito sempre aparece)
    if exes:
        def _an(e: Path):
            try:
                return analise(e)
            except Exception:  # noqa: BLE001
                return None
        with ThreadPoolExecutor(max_workers=TRABALHADORES) as pool:
            ans = list(pool.map(_an, exes))
        manter = []
        for e, a in zip(exes, ans):
            if a and not _ler_linhas_args(_arquivo_args(e)) and \
                    (a.categoria == "desinstalador" or (a.categoria == "portatil" and not a.gui)):
                escondidos += 1
                continue
            manter.append(e)
        exes = manter
    ESCONDIDOS[pasta] = escondidos
    stems_exe = {e.with_suffix("").as_posix().lower() for e in exes}
    msis = [m for m in msis
            if not (m.with_suffix("").as_posix().lower() in stems_exe and pacote_embutido(m))]
    return sorted(msis + exes, key=lambda p: str(p).lower())


def descobrir_diretorios() -> list[tuple[Path, list[Path]]]:
    """Retorna [(pasta, [pacote, ...])] apenas para pastas que têm .msi ou .exe instalável."""
    resultado = []
    for item in sorted(BASE.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir() or item.name.lower() in PASTAS_IGNORADAS:
            continue
        if item.name.startswith(".") or item.name.startswith("#"):
            continue
        pacotes = listar_pacotes(item)
        if pacotes:
            resultado.append((item, pacotes))
    return resultado


# ----------------------------------------------------------------------------
# Status ao vivo (logs\status.txt)
# ----------------------------------------------------------------------------
ESTADO = {"estado": "AGUARDANDO", "inicio": None, "total": 0, "atual": 0,
          "pacote": "", "acao": "", "tipo": "", "diag": "", "resultados": [], "validacoes": []}


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
            f"Etapa      : {e['acao'] or '-'}",
            f"Atualizado : {datetime.now():%H:%M:%S}",
            "",
            "Concluídos:",
        ]
        linhas += [f"  [{c:>5}] {n} -> {st}" for n, c, st in e["resultados"]]
        if e.get("validacoes"):
            linhas += ["", "Validação dos pacotes:"]
            linhas += [f"  [{n_.upper():>5}] {nome} -> {resumo}" for nome, n_, resumo in e["validacoes"]]
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
    1460: "tempo limite excedido ou programa parado sem janela (era um programa portátil?)",
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


_NSIS = {
    1: "cancelado (o instalador foi fechado ou pediu confirmação)",
    2: "abortado pelo próprio instalador (pré-requisito não atendido, versão já instalada, programa "
       "aberto ou reinício pendente) - veja a janela no modo com cliques",
}


def descrever_codigo(codigo: int, tipo: str = "") -> str:
    c = codigo & 0xFFFFFFFF
    if tipo == "Inno Setup" and c in _INNO:
        return _INNO[c]
    if tipo == "NSIS" and c in _NSIS:
        return _NSIS[c]
    if tipo in ("Burn", "WiX Burn") and c not in _DICAS and c not in CODIGOS_OK:
        return "falhou um pacote interno do instalador (veja o log *.instalador.log)"
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


# ---- instalação direta de .exe ----------------------------------------------
# v3.0: os .exe NÃO são mais convertidos em MSI. O .exe é executado direto, como o administrador
# atual, fora do msiexec (sem mutex, sem SYSTEM, código de saída real). MSIs gerados pela conversão das
# versões antigas (<= 2.2) continuam funcionando: o .exe é extraído da tabela Binary e roda do mesmo jeito.
def pacote_embutido(msi: Path) -> bool:
    """True se o MSI foi gerado pela conversão das versões antigas (tem o .exe na tabela Binary)."""
    if msi.suffix.lower() != ".msi":
        return False
    try:
        if msi_texto(msi, "SELECT `Value` FROM `Property` WHERE `Property`='Manufacturer'") != FABRICANTE_WRAPPER:
            return False
        return msi_texto(msi, "SELECT `Name` FROM `Binary` WHERE `Name`='SetupExe'") is not None
    except Exception:  # noqa: BLE001
        return False


# ---- cache em disco (validação + análise), chaveado por caminho + tamanho + data -----------------------
_CACHE: dict = {}
_CACHE_TRAVA = threading.Lock()
_CACHE_CARREGADO = False
VERSAO_CACHE = f"{VERSAO}|{val.VERSAO_VALIDADOR}|{ae.VERSAO_ANALISE}"


def _cache_carregar() -> None:
    global _CACHE_CARREGADO
    with _CACHE_TRAVA:
        if _CACHE_CARREGADO:
            return
        _CACHE_CARREGADO = True
        with contextlib.suppress(Exception):
            dados = json.loads((LOG_DIR / CACHE_ARQ).read_text(encoding="utf-8"))
            if dados.get("versao") == VERSAO_CACHE:
                _CACHE.update(dados.get("itens", {}))


def _cache_salvar() -> None:
    with _CACHE_TRAVA:
        with contextlib.suppress(Exception):
            LOG_DIR.mkdir(exist_ok=True)
            tmp = LOG_DIR / (CACHE_ARQ + ".tmp")
            tmp.write_text(json.dumps({"versao": VERSAO_CACHE, "itens": _CACHE}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, LOG_DIR / CACHE_ARQ)


def _cache_ler(arq: Path, campo: str):
    _cache_carregar()
    with _CACHE_TRAVA:
        item = _CACHE.get(str(arq))
    if item and tuple(item.get("sig", ())) == val.assinatura_arquivo(arq):
        return item.get(campo)
    return None


def _cache_gravar(arq: Path, campo: str, valor) -> None:
    sig = list(val.assinatura_arquivo(arq))
    with _CACHE_TRAVA:
        item = _CACHE.get(str(arq))
        if not item or item.get("sig") != sig:
            item = _CACHE[str(arq)] = {"sig": sig}
        item[campo] = valor


_ANALISES: dict = {}


def analise(exe: Path) -> "ae.AnaliseExe":
    """Instalador / portátil / menu + tipo e argumento silencioso (cache em memória e em disco)."""
    exe = Path(exe)
    sig = val.assinatura_arquivo(exe)
    em_mem = _ANALISES.get(exe)
    if em_mem and em_mem[0] == sig:
        return em_mem[1]
    d = _cache_ler(exe, "analise")
    a = ae.AnaliseExe.de_dict(d) if d else ae.analisar(exe)
    if not d:
        _cache_gravar(exe, "analise", a.para_dict())
    _ANALISES[exe] = (sig, a)
    return a


def eh_exe(p: Path) -> bool:
    return p.suffix.lower() == ".exe"


def classificar_pacote(pac: Path) -> tuple:
    """(rótulo, tamanho em bytes) para exibir na tela de seleção: MSI, EXE, PORTÁTIL, MENU."""
    try:
        tam = pac.stat().st_size
    except OSError:
        tam = 0
    if eh_exe(pac):
        try:
            return analise(pac).rotulo, tam
        except Exception:  # noqa: BLE001
            return "EXE", tam
    return ("EXE (MSI antigo)" if pacote_embutido(pac) else "MSI"), tam


ESCADAS = {
    "Inno Setup": ["/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-",
                   "/SILENT /SUPPRESSMSGBOXES /NORESTART /SP-"],
    "NSIS": ["/S"],
    "Burn": ["/quiet /norestart", "/passive /norestart"],
    "Advanced Installer": ["/exenoui /qn /norestart", "/exenoui /qb /norestart", "/qn /norestart"],
    "InstallShield": ['/s /v"/qn REBOOT=ReallySuppress"', '/s /sms /v"/qn REBOOT=ReallySuppress"',
                      '/s /v"/qb REBOOT=ReallySuppress"'],
    "Qt Installer Framework": ["--accept-licenses --default-answer --confirm-command install"],
    "SFX 7-Zip": ["/S", "-y"],
    "SFX WinRAR": ["/S"],
    "IExpress": ["/Q", "/Q /C"],
    ".NET Framework": ["/q /norestart", "/passive /norestart"],
    "InstallAware": ["/s"],
    "Wise": ["/s"],
    "Setup Factory": ["/S"],
    "Squirrel": ["--silent", "-s"],
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
INTERATIVO = "INTERATIVO"       # linha especial do .args: abre o instalador normal (com cliques)


def _chave_tipo(tipo: str) -> str:
    return "Burn" if tipo in ("Burn", "WiX Burn") else tipo


def _arquivo_args(pac: Path) -> Path:
    """'<nome>.exe.args' - ao lado do .exe, ou ao lado do MSI antigo que embrulha esse .exe."""
    return pac.with_name(pac.name + ".args") if eh_exe(pac) else pac.with_name(pac.stem + ".exe.args")


def candidatos_args(pac: Path, exe: Path) -> list:
    """Lista ordenada de argumentos a tentar para o .exe.

    1) '<nome>.exe.args': se existir, vale SÓ ele (1 argumento por linha = 1 tentativa; a linha
       INTERATIVO abre o instalador normal, com cliques);
    2) menu de autorun: só INTERATIVO (não há modo silencioso);
    3) senão: o gravado no MSI antigo (se for o caso), o detectado no .exe, a escada do tipo e os genéricos."""
    linhas = [l for l in _ler_linhas_args(_arquivo_args(pac)) if l.upper() != "IGNORAR"]
    if linhas:
        return linhas
    lista: list = []
    alvo = None
    if not eh_exe(pac):
        try:
            alvo = msi_texto(pac, "SELECT `Target` FROM `CustomAction` WHERE `Action`='RunInstall'")
        except OSError:
            alvo = None
        if alvo:
            lista.append(alvo)
    a = None
    with contextlib.suppress(Exception):
        a = analise(exe)
    if a is not None and a.categoria == "menu":
        return [INTERATIVO]
    tipo = (a.tipo if a and a.categoria == "instalador" else "") or tipo_por_args(alvo or "")
    if a is not None and a.args:
        lista.append(a.args)
    lista += ESCADAS.get(_chave_tipo(tipo), [])
    lista += GENERICOS
    vistos, final = set(), []
    for x in lista:
        k = x.strip().lower()
        if k and k not in vistos:
            vistos.add(k)
            final.append(x.strip())
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


def _fazer_tick(etapa: str = "instalador .exe"):
    """Callback de sinal de vida (status.txt, tela gráfica e linha no console a cada 15 s)."""
    ultimo = [0]

    def tick(seg: int) -> None:
        ESTADO["acao"] = etapa
        gravar_status()
        if _CB_BATIMENTO:
            with contextlib.suppress(Exception):
                _CB_BATIMENTO(seg, ESTADO["acao"])
        if seg - ultimo[0] >= 15:
            ultimo[0] = seg
            print(f"        {ts()}{CINZA}... ainda instalando ({seg}s){RESET}", flush=True)
    return tick


def _rejeitou_argumentos(res, codigo: int) -> bool:
    """True quando vale tentar o PRÓXIMO argumento silencioso: o instalador abriu tela e travou, ficou
    parado, rejeitou o argumento ou saiu na hora com erro. NÃO tenta outro se já estava instalando."""
    if res.motivo in ("ui_travada", "parado"):
        return True
    if res.motivo == "timeout":
        return False
    c = codigo & 0xFFFFFFFF
    if c in (87, 1639):
        return True
    return res.duracao < 6 and c not in (1618,)


# códigos que NÃO abrem o modo com cliques (não adiantaria: reinício pendente, outro MSI rodando, timeout)
SEM_PLANO_B = {1618, 1641, 3010, 1460, 0x80070BC2}


def _diagnostico_burn(log_burn: Path) -> str:
    """Do log de um pacote WiX Burn: qual pacote INTERNO falhou e com que código (+ dica conhecida)."""
    try:
        texto = log_burn.read_text(encoding="utf-8", errors="replace")
    except OSError:
        try:
            texto = log_burn.read_text(encoding="utf-16", errors="replace")
        except OSError:
            return ""
    falhas = re.findall(r"Applied execute package: ([^,]+), result: (0x[0-9a-fA-F]+)", texto)
    falhas = [(n, c) for n, c in falhas if c.lower() not in ("0x0", "0x00000000")]
    if not falhas:
        m = re.search(r"Error (0x[0-9a-fA-F]+): (.+)", texto)
        return f"erro {m.group(1)}: {m.group(2).strip()[:120]}" if m else ""
    nome, cod = falhas[-1]
    dica = ""
    if "webview2" in nome.lower():
        dica = (" - o WebView2 desse pacote baixa da internet: conecte o PC à internet ou instale antes o "
                "WebView2 Runtime offline (MicrosoftEdgeWebView2RuntimeInstallerX64.exe)")
    elif re.search(r"vc|redist|vcpp", nome, re.I):
        dica = " - Visual C++ Redistributable: instale o VC_redist mais novo antes"
    elif re.search(r"netfx|dotnet|\.net", nome, re.I):
        dica = " - .NET: instale o .NET necessário antes (pode exigir internet/reinício)"
    return f"falhou o pacote interno '{nome}' ({cod}){dica}"


def _desbloquear(arq: Path) -> None:
    """Remove a marca 'baixado da internet' (Zone.Identifier): evita o aviso de segurança do Windows."""
    if os.name == "nt":
        with contextlib.suppress(OSError):
            os.remove(f"{arq}:Zone.Identifier")


def _rodar_exe(exe: Path, cwd: Path, candidatos: list, log_file: Path, anotar, interativo: bool,
               tipo_detectado: str = "") -> int:
    """Executa o .exe com cada conjunto de argumentos (silencioso, oculto, vigiado) até um funcionar.
    Se nenhum funcionar e 'interativo' for True, abre o instalador NORMAL para o técnico concluir."""
    _desbloquear(exe)
    ESTADO["diag"] = ""

    def uma_vez(args: str, n: int, total: int, visivel: bool) -> tuple:
        if not ex.aguardar_msi_livre(ESPERA_MSI_LIVRE_S):
            anotar("Windows Installer continuou ocupado por muito tempo.")
        tipo = "" if visivel else (tipo_detectado if tipo_detectado and n == 1 else tipo_por_args(args))
        ESTADO["tipo"] = tipo_detectado or tipo
        linha_cmd = f'"{exe}" {_args_com_log(args, _chave_tipo(tipo), log_file, n)}'.strip()
        anotar(f"Tentativa {n}/{total} | {'INTERATIVO' if visivel else 'tipo: ' + (tipo or 'desconhecido')}"
               f" | {linha_cmd}")
        guarda: dict = {}
        tick = _fazer_tick("aguardando você concluir na janela do instalador" if visivel else "instalador .exe")

        def rodar() -> int:
            res = ex.executar_arvore(
                linha_cmd, str(cwd), TIMEOUT_EXE_MIN * 60, tick=tick,
                ocultar=OCULTAR_JANELAS, vigiar_ui=VIGIAR_UI, ui_ocioso_s=UI_OCIOSO_S,
                pos_ocioso_s=POS_OCIOSO_S, pos_max_s=POS_MAX_S, visivel=visivel, parado_s=PARADO_S,
                ao_janela=lambda d: (anotar(f"Janela detectada e ocultada: {d}"),
                                     aviso(f"janela ocultada: {d}", "aviso")))
            guarda["res"] = res
            anotar(f"Código de saída: {res.codigo} (0x{res.codigo & 0xFFFFFFFF:08X}) | motivo: {res.motivo} | "
                   f"{res.duracao:.0f}s{' | deixou processos filhos' if res.deixou_filhos else ''}")
            return res.codigo

        codigo = _com_retentativa(rodar)
        res = guarda["res"]
        if codigo not in CODIGOS_OK and _chave_tipo(tipo) == "Burn":
            diag = _diagnostico_burn(log_file.with_suffix(".instalador.log" if n == 1 else f".instalador{n}.log"))
            if diag:
                ESTADO["diag"] = diag
                anotar(f"Diagnóstico: {diag}")
                aviso(diag, "erro")
        return codigo, res

    silenciosos = [a for a in candidatos if a.strip().upper() != INTERATIVO][:MAX_TENTATIVAS_ARGS]
    pediu_interativo = any(a.strip().upper() == INTERATIVO for a in candidatos)
    total = len(silenciosos) + (1 if (pediu_interativo or interativo) else 0)
    codigo, res = 1, None
    janelas_antes: Optional[set] = None
    for n, args in enumerate(silenciosos, start=1):
        if n > 1:
            aviso(f"tentativa {n}/{total}: {args}", "aviso")
        codigo, res = uma_vez(args, n, total, visivel=False)
        if codigo in CODIGOS_OK:
            return codigo
        if res.motivo == "ui_travada":
            aviso("o instalador abriu uma tela e esperou clique "
                  f"({'; '.join(res.janelas[-2:]) or 'janela sem título'}); encerrado.", "aviso")
            ex.aguardar_msi_livre(120)
            janelas = {j.split(" [")[0] for j in res.janelas}
            if janelas_antes is not None and janelas == janelas_antes:
                anotar("A mesma tela apareceu com argumentos diferentes: este .exe ignora argumentos "
                       "silenciosos. Parando as tentativas.")
                aviso("este .exe ignora os argumentos silenciosos (mesma tela de novo)", "aviso")
                break
            janelas_antes = janelas
        elif res.motivo == "parado":
            msg = (f"ficou aberto {PARADO_S}s sem janela e sem atividade: parece um programa PORTÁTIL "
                   "ou de bandeja (não é instalador); encerrado")
            anotar(msg)
            aviso(msg, "aviso")
            ESTADO["diag"] = ("ficou aberto sem janela e sem instalar nada: parece um programa PORTÁTIL - "
                              "crie '<nome>.exe.args' com INTERATIVO se for mesmo um instalador")
            return codigo                 # outro argumento não muda nada; abrir com cliques só abriria o programa
        if n < len(silenciosos) and _rejeitou_argumentos(res, codigo):
            continue
        break

    # Modo com cliques: pedido no .args (linha INTERATIVO) ou o silencioso não funcionou
    c = codigo & 0xFFFFFFFF
    falhou = res is None or (codigo not in CODIGOS_OK and c not in SEM_PLANO_B and res.motivo != "timeout")
    if pediu_interativo or (interativo and falhou):
        if res is not None:
            aviso("o modo silencioso não funcionou: abrindo o instalador NORMAL - conclua clicando na "
                  "janela dele (o programa espera você terminar).", "aviso")
        else:
            aviso("abrindo o instalador NORMAL - conclua clicando na janela dele.", "aviso")
        evento("interativo", exe=str(exe))
        codigo, res = uma_vez("", total, total, visivel=True)
    return codigo


def instalar_exe(exe: Path, log_file: Path, interativo: bool = False) -> int:
    """Instala um .exe DIRETAMENTE (sem conversão), na pasta dele (cwd = pasta do .exe: muitos setup.exe
    precisam dos arquivos que estão ao lado)."""
    anotacoes: list = []

    def anotar(txt: str) -> None:
        anotacoes.append(f"[{datetime.now():%H:%M:%S}] {txt}")

    try:
        anotar(f"Instalação direta de .exe | {exe}")
        tipo = ""
        with contextlib.suppress(Exception):
            a = analise(exe)
            tipo = a.tipo if a.categoria == "instalador" else ""
            anotar(f"Análise: {a.rotulo} | tipo: {a.tipo or 'desconhecido'} | {a.motivo}"
                   f"{' | ' + a.descricao if a.descricao else ''}")
        candidatos = candidatos_args(exe, exe)
        anotar("Tentativas de argumentos: " + " || ".join(candidatos))
        return _rodar_exe(exe, exe.parent, candidatos, log_file, anotar, interativo, tipo)
    except Exception as exc:  # noqa: BLE001
        anotar(f"EXCEÇÃO: {exc}\n{traceback.format_exc()}")
        aviso(f"{exc}", "erro")
        return 1
    finally:
        with contextlib.suppress(Exception):
            log_file.write_text("\n".join(anotacoes) + "\n", encoding="utf-8")


def _tamanho_pasta(pasta: Path, limite: int) -> int:
    total = 0
    for raiz, _, arqs in os.walk(pasta):
        for a in arqs:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(raiz, a))
            if total > limite:
                return total
    return total


def _criar_atalho(lnk: Path, alvo: Path, pasta_trabalho: Path, descricao: str) -> bool:
    """Cria um atalho .lnk (WScript.Shell via PowerShell oculto)."""
    if os.name != "nt":
        return False
    q = lambda t: "'" + str(t).replace("'", "''") + "'"   # noqa: E731 - aspas simples do PowerShell
    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({q(lnk)});"
              f"$s.TargetPath={q(alvo)};$s.WorkingDirectory={q(pasta_trabalho)};"
              f"$s.IconLocation={q(str(alvo) + ',0')};$s.Description={q(descricao)};$s.Save()")
    try:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        r = ex.rodar_oculto(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", script], capture_output=True, timeout=60)
        return r.returncode == 0 and lnk.exists()
    except Exception:  # noqa: BLE001
        return False


def instalar_portatil(exe: Path, log_file: Path) -> int:
    """Programa PORTÁTIL: copia para PASTA_PORTATEIS e cria atalhos (Área de Trabalho pública e Menu
    Iniciar > Portáteis). Nada é executado."""
    anotacoes: list = []

    def anotar(txt: str) -> None:
        anotacoes.append(f"[{datetime.now():%H:%M:%S}] {txt}")

    try:
        a = analise(exe)
        anotar(f"Programa PORTÁTIL | {exe} | {a.motivo}")
        categorias = {p.resolve() for p in pastas_validas()} if BASE.exists() else set()
        origem = exe.parent
        sozinho = origem.resolve() in categorias or \
            _tamanho_pasta(origem, LIMITE_COPIA_PORTATIL_MB << 20) > (LIMITE_COPIA_PORTATIL_MB << 20)
        nome_pasta = exe.stem if sozinho else origem.name
        destino = Path(PASTA_PORTATEIS) / re.sub(r'[<>:"/\\|?*]', "_", nome_pasta)
        destino.mkdir(parents=True, exist_ok=True)
        ESTADO["acao"] = "copiando o programa portátil"
        gravar_status()
        if sozinho:
            shutil.copy2(exe, destino / exe.name)
            anotar(f"Copiado só o .exe para {destino}")
        else:
            shutil.copytree(origem, destino, dirs_exist_ok=True)
            anotar(f"Copiada a pasta {origem} para {destino}")
        alvo = destino / exe.name
        nome = (a.descricao if a.descricao and len(a.descricao) <= 60 else exe.stem).strip()
        nome = re.sub(r'[<>:"/\\|?*]', "_", nome) or exe.stem
        publico = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
        menu = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs\Portáteis"
        criados = [str(l) for l in (publico / "Desktop" / f"{nome}.lnk", menu / f"{nome}.lnk")
                   if _criar_atalho(l, alvo, destino, a.descricao or exe.stem)]
        anotar("Atalhos: " + (", ".join(criados) or "nenhum (não foi possível criar)"))
        aviso(f"portátil copiado para {destino}" + (" + atalho na Área de Trabalho" if criados else ""), "info")
        return 0
    except Exception as exc:  # noqa: BLE001
        anotar(f"EXCEÇÃO: {exc}\n{traceback.format_exc()}")
        aviso(f"não foi possível copiar o portátil: {exc}", "erro")
        return 1
    finally:
        with contextlib.suppress(Exception):
            log_file.write_text("\n".join(anotacoes) + "\n", encoding="utf-8")


def instalar_embutido(msi: Path, log_file: Path, interativo: bool = False) -> int:
    """MSI antigo (gerado pela conversão das versões <= 2.2): extrai o .exe da tabela Binary e o executa
    direto, do mesmo jeito que um .exe comum."""
    tmp = Path(tempfile.mkdtemp(prefix="msi_direto_"))
    anotacoes: list = []

    def anotar(txt: str) -> None:
        anotacoes.append(f"[{datetime.now():%H:%M:%S}] {txt}")

    try:
        anotar(f"MSI antigo (EXE embutido) | pacote: {msi}")
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
        candidatos = candidatos_args(msi, exe)
        anotar("Tentativas de argumentos: " + " || ".join(candidatos))
        return _rodar_exe(exe, tmp, candidatos, log_file, anotar, interativo)
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
                   direto: Optional[bool] = None, interativo: Optional[bool] = None) -> tuple[int, bool]:
    """Instala os pacotes (.msi e .exe). callback(evento, **dados) alimenta a tela gráfica; 'cancelar' é
    um threading.Event checado entre um pacote e outro. interativo=True: se o modo silencioso de um .exe
    falhar, abre o instalador normal para concluir com cliques. Devolve (falhas, reinicio_necessario)."""
    global _CB_BATIMENTO
    direto = MODO_DIRETO if direto is None else direto
    interativo = (FALLBACK_INTERATIVO and not AUTO) if interativo is None else interativo
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
            exe = eh_exe(msi)
            categoria = ""
            if exe and not bloqueio:
                with contextlib.suppress(Exception):
                    categoria = analise(msi).categoria
                if _ler_linhas_args(_arquivo_args(msi)):
                    categoria = "instalador"          # .args explícito: o técnico manda
            embutido = not exe and direto and not bloqueio and pacote_embutido(msi)
            modo = ("bloqueado" if bloqueio else
                    {"portatil": "portátil", "menu": "menu"}.get(categoria) or
                    ("exe" if exe else ("direto" if embutido else "msiexec")))
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
                ESTADO["diag"] = ""
                if modo == "portátil":
                    if PORTATEIS_ACAO == "copiar":
                        codigo = instalar_portatil(msi, log_file)
                    else:
                        codigo = 0
                        aviso("programa portátil: nada a instalar (PORTATEIS_ACAO = ignorar)", "info")
                elif modo == "menu" and not interativo:
                    codigo = 1602
                    ESTADO["diag"] = "menu de CD/pen drive: só funciona com cliques (ative o modo com cliques)"
                    aviso(ESTADO["diag"], "erro")
                elif exe:
                    codigo = instalar_exe(msi, log_file, interativo)
                elif embutido:
                    codigo = instalar_embutido(msi, log_file, interativo)
                else:
                    codigo = instalar_msi(msi, log_file)
            dur = int(time.time() - t0)
            ok = codigo in CODIGOS_OK
            status = (f"BLOQUEADO pela validação ({bloqueio})" if bloqueio
                      else CODIGOS_OK.get(codigo) or texto_falha(codigo, ESTADO.get("tipo", "")))
            if modo == "portátil" and ok:
                status = f"Portátil copiado para {PASTA_PORTATEIS}" if PORTATEIS_ACAO == "copiar" else "Portátil (ignorado)"
            elif not ok and ESTADO.get("diag"):
                status += f" - {ESTADO['diag']}"
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
# Detecção do tipo de instalador .exe (para escolher os argumentos silenciosos)
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
    """(tipo, argumentos silenciosos) do motor de instalação detectado no .exe, ou None.
    Usa analise_exe (lê só cabeçalho/recursos/início dos dados anexados - poucos MB, com cache)."""
    try:
        a = analise(exe)
    except Exception:  # noqa: BLE001
        return None
    return (a.tipo, a.args) if a.categoria == "instalador" and a.args else None


VALIDACOES: dict = {}           # Path do pacote -> val.Resultado (validado nesta execução)


def _info_args_exe(exe: Path) -> str:
    """Texto curto: o que é o .exe e como será instalado (para o relatório de validação e --listar)."""
    lado = _arquivo_args(exe)
    linhas = [l for l in _ler_linhas_args(lado) if l.upper() != "IGNORAR"]
    if linhas:
        return f"arquivo {lado.name}: {' || '.join(linhas)}"
    a = analise(exe)
    if a.categoria == "portatil":
        acao = f"será copiado para {PASTA_PORTATEIS} com atalho" if PORTATEIS_ACAO == "copiar" else "não será instalado"
        return f"PROGRAMA PORTÁTIL ({a.motivo}) - {acao}"
    if a.categoria == "menu":
        return "MENU de CD/pen drive - só funciona com cliques (abre a janela normal)"
    if a.args:
        return f"instalador {a.tipo}: {a.args}"
    return (f"instalador de tipo desconhecido ({a.motivo}): serão tentados {', '.join(GENERICOS[:3])}..."
            + (" e, se nada funcionar, o instalador abre para você clicar" if FALLBACK_INTERATIVO else ""))


_TRAVA_MSI = threading.BoundedSemaphore(4)     # msi.dll: no máximo 4 bancos abertos ao mesmo tempo


def _resultado_do_cache(arq: Path):
    d = _cache_ler(arq, "validacao")
    if not d or bool(d.get("completa")) < VALIDACAO_COMPLETA:
        return None
    r = val.Resultado(msi=arq, embutido=bool(d.get("embutido")), tamanho=int(d.get("tamanho", 0)),
                      duracao=0.0, assinatura=val.assinatura_arquivo(arq), info=dict(d.get("info", {})))
    for nome, nivel, detalhe in d.get("verificacoes", []):
        r.adicionar(nome, nivel, detalhe)
    r.info["cache"] = True
    return r


def validar_msi(msi: Path, exe: Optional[Path] = None, forcar: bool = False, progresso=None):
    """Valida um pacote (.msi ou .exe) e guarda o resultado. Reaproveita o resultado (memória ou o cache em
    disco de execuções anteriores) se o arquivo não mudou (mesmo tamanho e data) e a validação anterior já
    cobriu o mesmo nível de leitura. Pode ser chamada de várias threads ao mesmo tempo."""
    msi = Path(msi)
    antigo = VALIDACOES.get(msi)
    if (not forcar and antigo is not None and antigo.assinatura == val.assinatura_arquivo(msi)
            and antigo.info.get("completa", False) >= VALIDACAO_COMPLETA):
        return antigo
    if not forcar:
        r = _resultado_do_cache(msi)
        if r is not None:
            VALIDACOES[msi] = r
            return r
    if eh_exe(msi):
        r = val.validar_exe(msi, completo=VALIDACAO_COMPLETA, progresso=progresso)
        if r.nivel != "erro":
            with contextlib.suppress(Exception):
                a = analise(msi)
                r.info["categoria"] = a.categoria
                r.adicionar("Tipo", "info", _info_args_exe(msi))
    else:
        with _TRAVA_MSI:
            r = val.validar_pacote(msi, exe=exe, completo=VALIDACAO_COMPLETA, progresso=progresso)
    r.info["completa"] = VALIDACAO_COMPLETA
    VALIDACOES[msi] = r
    val.limpar_lote(r)
    _cache_gravar(msi, "validacao", {
        "completa": VALIDACAO_COMPLETA, "embutido": r.embutido, "tamanho": r.tamanho,
        "info": {k: v for k, v in r.info.items() if isinstance(v, (str, int, float, bool)) and k != "cache"},
        "verificacoes": [[v.nome, v.nivel, v.detalhe] for v in r.verificacoes
                         if v.nome not in ("Duplicado", "Conflito")]})
    return r


# ----------------------------------------------------------------------------
# Leitura direta de MSI (msi.dll via ctypes) - usada para os MSI antigos com EXE embutido
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


# ----------------------------------------------------------------------------
# Etapa de VALIDAÇÃO (antes da instalação)
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


def validar_todos(simular: bool = False) -> tuple:
    """Valida TODOS os pacotes (.msi e .exe) de todas as pastas (um por um, com progresso), confere colisões entre eles,
    grava logs\\validacao_*.txt e atualiza VALIDACOES/status. Devolve (ok, avisos, erros)."""
    ESCONDIDOS.clear()
    pacotes = [(pasta, msi) for pasta, msis in descobrir_diretorios() for msi in msis]
    if not pacotes:
        print(f"  {ts()}{CINZA}Nenhum pacote para validar.{RESET}")
        return 0, 0, 0
    total = len(pacotes)
    modo = "completa (lê cada instalador por inteiro)" if VALIDACAO_COMPLETA else "rápida (estrutura, início e fim)"
    print(f"  {ts()}{BOLD}Validando {total} pacote(s) MSI/EXE - validação {modo}{RESET}\n")
    ESTADO.update(estado="VALIDANDO PACOTES", inicio=datetime.now(), total=total, atual=0, pacote="", acao="")
    ESTADO["validacoes"] = []
    evento("etapa", numero=1, titulo="Validando os pacotes", total=total)
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

    # EM PARALELO: todos os núcleos (análise/estrutura) - o resultado de cada pacote aparece assim que sai
    _cache_carregar()
    t_ini = time.time()
    nomes = {msi: f"{pasta.name}\\{msi.relative_to(pasta)}" for pasta, msi in pacotes}
    ordem = {msi: n for n, (_, msi) in enumerate(pacotes, start=1)}
    feitos = 0
    do_cache = 0
    with ThreadPoolExecutor(max_workers=TRABALHADORES, thread_name_prefix="valida") as pool:
        futuros = {pool.submit(validar_msi, msi): msi for _, msi in pacotes}
        for fut in as_completed(futuros):
            msi = futuros[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001 - falha do validador nunca bloqueia por engano
                r = val.Resultado(msi=msi)
                r.adicionar("Validador", "aviso", f"falha interna ao validar ({type(exc).__name__}: {exc})")
            feitos += 1
            do_cache += bool(r.info.get("cache"))
            nome = nomes[msi]
            print(f"  {ts()}{CIANO}[{feitos}/{total}]{RESET} {nome}", flush=True)
            ESTADO.update(atual=feitos, pacote=nome, acao="validando")
            if feitos % 10 == 0 or feitos == total:
                gravar_status()
            evento("val_item", i=feitos, total=total, nome=nome)
            val.limpar_lote(r)
            resultados.append((ordem[msi], nome, r, len(r.verificacoes)))
            mostrar(feitos, nome, r)
    resultados.sort(key=lambda x: x[0])
    _cache_salvar()
    dur_val = time.time() - t_ini
    print(f"  {ts()}{CINZA}Validação em {dur_val:.1f}s com {TRABALHADORES} tarefas em paralelo"
          f"{f' ({do_cache} do cache)' if do_cache else ''}{RESET}", flush=True)
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
    portateis = sum(1 for _, _, r, _ in resultados if r.info.get("categoria") == "portatil")
    menus = sum(1 for _, _, r, _ in resultados if r.info.get("categoria") == "menu")
    ocultos = sum(ESCONDIDOS.values())
    resumo = (f"RESUMO DA VALIDAÇÃO: {ok} OK | {avisos} com aviso | {erros} BLOQUEADO(S) | total {total}"
              f"{f' | {portateis} portátil(is)' if portateis else ''}{f' | {menus} menu(s)' if menus else ''}"
              f" | {dur_val:.1f}s"
              f"{f' | {ocultos} componente(s)/ferramenta(s) escondido(s)' if ocultos else ''}")
    print(f"\n  {BOLD}{resumo}{RESET}\n")
    relatorio += ["", resumo]
    try:
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / f"validacao_{carimbo}.txt").write_text("\n".join(relatorio) + "\n", encoding="utf-8")
    except OSError:
        pass
    ESTADO.update(estado="VALIDAÇÃO CONCLUÍDA", pacote="", acao="")
    gravar_status()
    evento("val_fim", ok=ok, avisos=avisos, erros=erros, sem_msi=0, total=total)
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
            print(f"\n  {AMARELO}Nenhuma pasta com arquivos .msi/.exe foi encontrada ao lado")
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
            print(f"   {CIANO}[{i}]{RESET} {pasta.name:<30} {CINZA}({len(msis)} pacote(s)){RESET}")
        print()
        print(f"   {VERDE}[A]{RESET} {BOLD}INSTALAR TUDO{RESET}"
              f"                    {CINZA}({total_msi} pacote(s)){RESET}")
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
        print(f"\n  {BOLD}Será instalado ({qtd} pacote(s)):{RESET}")
        for pasta, msis in selecionados:
            for msi in msis:
                print(f"    {CINZA}•{RESET} {pasta.name} {CINZA}›{RESET} {BRANCO}{msi.name}{RESET}")
        if input(f"  {AMARELO}Confirmar? (S/N): {RESET}").strip().lower() not in ("s", "sim", "y"):
            continue

        instalar_lista(selecionados)
        print()
        rodape()
        pausar()


def preparar_pacotes(cb=None) -> int:
    """VALIDA todos os pacotes (.msi e .exe) antes da seleção. 'cb' recebe eventos da tela gráfica.
    Devolve a quantidade de pacotes com aviso ou erro."""
    global _CB_EVENTO
    _CB_EVENTO = cb
    try:
        if not VALIDAR:
            return 0
        _, avisos, erros = validar_todos()
        return avisos + erros
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
    (validação dos pacotes), para o técnico ver só ela. False = não foi possível abrir."""
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

    def instalar(itens, callback, cancelar, interativo):
        return instalar_lista(itens, callback=callback, cancelar=cancelar, interativo=interativo)

    GUI_ATIVA = True
    try:
        tela_instalacao.abrir({
            "titulo": "Instalador Automático", "interativo": FALLBACK_INTERATIVO, "versao": VERSAO, "desenvolvedor": DESENVOLVEDOR,
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
        print(f"{VERMELHO}[ERRO] Pasta(s) não encontrada(s) ou sem pacotes: {', '.join(faltando)}{RESET}")
        return None
    return [por_nome[n] for n in pedidos]


def modo_automatico(args: argparse.Namespace) -> int:
    """Instala sem nenhuma interação. Retorna o código de saída do processo."""
    dirs = descobrir_diretorios()
    if args.listar:
        for pasta, pacotes in dirs:
            print(f"{pasta.name} ({len(pacotes)} pacote(s))")
            for m in pacotes:
                extra = ""
                if eh_exe(m):
                    with contextlib.suppress(Exception):
                        extra = f"   [EXE | {_info_args_exe(m)}]"
                else:
                    extra = "   [EXE (MSI antigo)]" if pacote_embutido(m) else "   [MSI]"
                print(f"   - {m.relative_to(BASE)}{extra}")
        return 0
    if not dirs:
        print("Nenhuma pasta com arquivos .msi/.exe encontrada.")
        return 4
    if VALIDAR:
        validar_todos()          # relatório completo; pacotes com ERRO são bloqueados na instalação
    selecionados = selecionar_pastas(dirs, args.pastas)
    if selecionados is None:
        return 2
    falhas, reboot = instalar_lista(selecionados, interativo=args.interativo)
    if falhas:
        return 1
    return 3010 if reboot else 0


def ler_argumentos() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=TITULO)
    ap.add_argument("--auto", action="store_true",
                    help="modo automático: sem apresentação, menu ou confirmação")
    ap.add_argument("--pastas", default=None,
                    help='pastas a instalar, separadas por vírgula (padrão: todas). Ex.: "Office,Drivers"')
    ap.add_argument("--listar", action="store_true",
                    help="apenas lista as pastas/MSIs encontrados (com --auto)")
    ap.add_argument("--validacao-completa", action="store_true",
                    help="lê cada pacote por inteiro na validação (mais lento; padrão: rápida)")
    ap.add_argument("--sem-cache", action="store_true",
                    help="ignora o cache de validação/análise (logs\\cache_pacotes.json)")
    ap.add_argument("--mostrar-componentes", action="store_true",
                    help="lista também os componentes internos das mídias (pastas com Setup.exe)")
    ap.add_argument("--sem-exe", action="store_true",
                    help="não instala .exe (só os .msi)")
    ap.add_argument("--interativo", action="store_true",
                    help="modo automático: se o silencioso de um .exe falhar, abre o instalador para clicar")
    ap.add_argument("--sem-interativo", action="store_true",
                    help="nunca abre a janela do instalador (falha se o modo silencioso não funcionar)")
    # aceitos por compatibilidade com tarefas agendadas antigas; não fazem mais nada (não há conversão)
    ap.add_argument("--sem-converter", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--manter-exe", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--sem-validar", action="store_true",
                    help="não valida os pacotes antes de instalar (não recomendado)")
    ap.add_argument("--validacao-rapida", action="store_true",
                    help="valida só estrutura e tamanhos (não lê cada instalador por inteiro / sem SHA-256)")
    ap.add_argument("--ignorar-bloqueio", action="store_true",
                    help="valida e mostra o relatório, mas instala mesmo os pacotes reprovados (emergência)")
    ap.add_argument("--console", action="store_true",
                    help="usa o menu de texto em vez da tela gráfica")
    ap.add_argument("--via-msiexec", action="store_true",
                    help="MSI antigos (gerados pela conversão das versões <= 2.2) via msiexec, e não direto")
    ap.add_argument("--ver-janelas", action="store_true",
                    help="diagnóstico: NÃO oculta nem encerra telas dos instaladores (só registra título/classe)")
    ap.add_argument("--lancador", action="store_true", help=argparse.SUPPRESS)  # uso interno do .bat
    ap.add_argument("--menu", action="store_true", help=argparse.SUPPRESS)      # uso interno do .bat
    ap.add_argument("--elevado", action="store_true", help=argparse.SUPPRESS)   # uso interno do .bat
    ap.add_argument("--raiz", default=None,
                    help="pasta que contém as subpastas de pacotes (padrão: pasta pai de #SISTEMA)")
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


_MUTEX = None


def _instancia_unica() -> bool:
    """Impede DUAS cópias abertas ao mesmo tempo (clique duplo no INSTALAR.bat: as duas validavam e as
    duas podiam instalar juntas). A segunda só traz a primeira para a frente e sai."""
    global _MUTEX
    if os.name != "nt":
        return True
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        _MUTEX = k32.CreateMutexW(None, False, "Local\\InstaladorAutomatico_EF")
        if ctypes.get_last_error() != 183:       # ERROR_ALREADY_EXISTS
            return True
        u32 = ctypes.WinDLL("user32")
        hwnd = u32.FindWindowW(None, "Instalador Automático")
        if hwnd:
            u32.ShowWindow(hwnd, 9)              # SW_RESTORE
            u32.SetForegroundWindow(hwnd)
        else:
            u32.MessageBoxW(None, "O Instalador Automático já está aberto.", "Instalador Automático", 0x40)
        print("  Outra cópia do instalador já está aberta - esta foi encerrada.", flush=True)
        return False
    except Exception:  # noqa: BLE001
        return True


def main() -> None:
    global AUTO, ANIMACAO, BASE, MODO_DIRETO, OCULTAR_JANELAS, VIGIAR_UI
    global VALIDAR, VALIDACAO_COMPLETA, BLOQUEAR_INVALIDOS, INSTALAR_EXE, FALLBACK_INTERATIVO
    global ESCONDER_COMPONENTES, _CACHE_CARREGADO
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
    if args.sem_exe:
        INSTALAR_EXE = False
    if args.validacao_completa:
        VALIDACAO_COMPLETA = True
    if args.sem_cache:
        _CACHE_CARREGADO = True          # não lê o arquivo (o resultado novo é gravado no fim)
    if args.mostrar_componentes:
        ESCONDER_COMPONENTES = False
    if args.sem_interativo:
        FALLBACK_INTERATIVO = False
        args.interativo = False
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
    if not args.listar and not _instancia_unica():
        sys.exit(0)
    habilitar_ansi()
    if AUTO:
        sys.exit(modo_automatico(args))
    try:
        if args.console:
            _, av_val, er_val = validar_todos() if VALIDAR else (0, 0, 0)
            if av_val or er_val:
                pausar()
            tela_apresentacao()
            menu()
        else:
            prep = preparar_pacotes if VALIDAR else None
            if not abrir_interface(prep):
                if SEM_CONSOLE:
                    raise RuntimeError("Não foi possível abrir a tela gráfica (tkinter ausente?). "
                                       "Veja logs\\console.log ou use INSTALAR.bat --console.")
                if VALIDAR:
                    preparar_pacotes(None)
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

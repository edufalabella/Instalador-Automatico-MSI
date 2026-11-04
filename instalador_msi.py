# -*- coding: utf-8 -*-
"""
Instalador MSI automatizado
---------------------------
Coloque este script na pasta raiz. Cada subpasta com arquivos .msi vira
uma opção do menu.

Estrutura esperada:
    instalador_msi.py
    Office\\       -> *.msi
    Drivers\\      -> *.msi
    Utilitarios\\  -> *.msi

Desenvolvido por Eduardo Falabella
"""

import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ----------------------------------------------------------------------------
# Configurações
# ----------------------------------------------------------------------------
TITULO = "INSTALADOR AUTOMÁTICO MSI"
VERSAO = "1.0"
DESENVOLVEDOR = "Eduardo Falabella"
PASTAS_IGNORADAS = {"logs", "__pycache__", "build", "dist"}
BUSCA_RECURSIVA = True          # procura .msi também dentro de subpastas
MODO_SILENCIOSO = True          # /qn (sem interface). False = /qb (barra de progresso)
ANIMACAO = True                 # False = pula as animações da tela inicial

# Códigos de retorno do msiexec considerados "sucesso"
CODIGOS_OK = {
    0: "Instalado com sucesso",
    1641: "Instalado (reinicialização iniciada)",
    3010: "Instalado (reinicialização necessária)",
    1638: "Já existe outra versão instalada",
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
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def centro(texto: str, cor: str = "") -> None:
    pad = max(0, (W - len(texto)) // 2)
    print(" " * pad + cor + texto + RESET)


def linha(char: str = "─", cor: str = CINZA) -> None:
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


BASE = diretorio_base()
LOG_DIR = BASE / "logs"


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


def limpar_tela() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def cabecalho() -> None:
    limpar_tela()
    print(CIANO + "╭" + "─" * (W - 2) + "╮" + RESET)
    interno = f"{TITULO}  v{VERSAO}"
    pad_e = (W - 2 - len(interno)) // 2
    pad_d = W - 2 - len(interno) - pad_e
    print(f"{CIANO}│{RESET}{' ' * pad_e}{BOLD}{BRANCO}{interno}{RESET}{' ' * pad_d}{CIANO}│{RESET}")
    print(CIANO + "╰" + "─" * (W - 2) + "╯" + RESET)
    print(f"{CINZA}  Pasta base: {BASE}{RESET}")
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
        if item.name.startswith("."):
            continue
        msis = listar_msi(item)
        if msis:
            resultado.append((item, msis))
    return resultado


# ----------------------------------------------------------------------------
# Instalação
# ----------------------------------------------------------------------------
def instalar_msi(msi: Path, log_file: Path) -> int:
    modo = "/qn" if MODO_SILENCIOSO else "/qb"
    cmd = ["msiexec", "/i", str(msi), modo, "/norestart", "/L*v", str(log_file)]
    try:
        proc = subprocess.Popen(cmd)
    except FileNotFoundError:
        print(f"  {VERMELHO}[ERRO] msiexec não encontrado (somente Windows).{RESET}")
        return -1
    except Exception as exc:  # noqa: BLE001
        print(f"  {VERMELHO}[ERRO] Falha ao executar: {exc}{RESET}")
        return -2

    frames = "|/-\\"
    i = 0
    inicio = time.time()
    while proc.poll() is None:
        seg = int(time.time() - inicio)
        print(f"\r        {CIANO}{frames[i % 4]}{RESET} instalando... {CINZA}{seg}s{RESET}   ",
              end="", flush=True)
        i += 1
        time.sleep(0.15)
    print("\r" + " " * 50 + "\r", end="")
    return proc.returncode


def instalar_lista(itens: list[tuple[Path, list[Path]]]) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    resumo_path = LOG_DIR / f"resumo_{carimbo}.txt"

    todos = [(pasta, msi) for pasta, msis in itens for msi in msis]
    total = len(todos)
    resultados: list[tuple[str, int, str]] = []

    cabecalho()
    print(f"  {BOLD}Instalando {total} pacote(s)...{RESET}\n")

    for i, (pasta, msi) in enumerate(todos, start=1):
        nome_log = f"{pasta.name}_{msi.stem}_{carimbo}.log".replace(" ", "_")
        log_file = LOG_DIR / nome_log
        print(f"  {barra(i - 1, total)}")
        print(f"  {CIANO}[{i}/{total}]{RESET} {pasta.name} {CINZA}›{RESET} {BRANCO}{msi.name}{RESET}")
        codigo = instalar_msi(msi, log_file)
        ok = codigo in CODIGOS_OK
        status = CODIGOS_OK.get(codigo, f"FALHA (código {codigo})")
        cor, marca = (VERDE, " OK ") if ok else (VERMELHO, "ERRO")
        print(f"        {cor}[{marca}] {status}{RESET}\n")
        resultados.append((f"{pasta.name}\\{msi.name}", codigo, status))

    print(f"  {barra(total, total)}\n")

    ok = sum(1 for _, c, _ in resultados if c in CODIGOS_OK)
    falhas = total - ok
    reboot = any(c in (1641, 3010) for _, c, _ in resultados)

    linha("═", CIANO)
    cor_res = VERDE if falhas == 0 else AMARELO
    print(f"  {BOLD}RESUMO:{RESET} {VERDE}{ok} sucesso(s){RESET} | "
          f"{VERMELHO if falhas else CINZA}{falhas} falha(s){RESET} | total {total}")
    linha("═", CIANO)
    for nome, codigo, status in resultados:
        cor = VERDE if codigo in CODIGOS_OK else VERMELHO
        print(f"  {cor}[{codigo:>5}]{RESET} {nome} {CINZA}→ {status}{RESET}")
    if reboot:
        print(f"\n  {AMARELO}>> Reinicie o computador para concluir algumas instalações.{RESET}")
    print(f"\n  {CINZA}Logs detalhados em: {LOG_DIR}{RESET}")

    with open(resumo_path, "w", encoding="utf-8") as f:
        f.write(f"Instalação em {datetime.now():%d/%m/%Y %H:%M:%S}\n\n")
        for nome, codigo, status in resultados:
            f.write(f"[{codigo}] {nome} -> {status}\n")
        f.write(f"\nSucessos: {ok} | Falhas: {falhas}\n")
    _ = cor_res


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
        print(f"   {CIANO}[R]{RESET} Reescanear diretórios")
        print(f"   {CIANO}[0]{RESET} Sair")
        print(f"\n  {CINZA}Dica: para várias pastas use vírgula, ex: 1,3{RESET}\n")
        rodape()
        escolha = input(f"\n{AMARELO}  Opção: {RESET}").strip()

        if escolha == "0":
            return
        if escolha.lower() == "r":
            continue

        selecionados = interpretar_escolha(escolha, dirs)
        if selecionados is None:
            print(f"\n  {VERMELHO}Opção inválida.{RESET}")
            pausar()
            continue

        qtd = sum(len(m) for _, m in selecionados)
        nomes = ", ".join(p.name for p, _ in selecionados)
        print(f"\n  Será instalado: {BRANCO}{nomes}{RESET} {CINZA}({qtd} MSI){RESET}")
        if input(f"  {AMARELO}Confirmar? (S/N): {RESET}").strip().lower() not in ("s", "sim", "y"):
            continue

        instalar_lista(selecionados)
        print()
        rodape()
        pausar()


def main() -> None:
    if os.name != "nt":
        print("Este instalador só funciona no Windows.")
        sys.exit(1)
    if not eh_admin():
        print("Solicitando privilégios de administrador...")
        reexecutar_como_admin()
    habilitar_ansi()
    try:
        tela_apresentacao()
        menu()
    except KeyboardInterrupt:
        print(f"\n\n{AMARELO}Interrompido pelo usuário.{RESET}")
    limpar_tela()
    print(f"\n{CIANO}Obrigado por usar o {TITULO}!{RESET}")
    print(f"{DIM}{CINZA}desenvolvido por {DESENVOLVEDOR}{RESET}\n")


if __name__ == "__main__":
    main()

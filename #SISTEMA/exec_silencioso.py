# -*- coding: utf-8 -*-
"""
Execução 100% silenciosa de instaladores (Windows).

O que este módulo garante:
  1. Nenhum console/janela extra: todo subprocesso nasce oculto (CREATE_NO_WINDOW + SW_HIDE).
  2. ÁRVORE DE PROCESSOS: o instalador roda dentro de um Job Object. Só consideramos "terminou"
     quando o processo e TODOS os filhos terminaram (instaladores que relançam um filho e saem
     com código 0 deixavam o script seguir adiante antes da hora).
  3. Janelas que aparecem são ocultadas na hora e registradas (título/classe) no log.
  4. WATCHDOG de interação: se o instalador mostrou uma janela e ficou parado (sem CPU/disco)
     esperando clique, a árvore é encerrada e o chamador tenta o próximo conjunto de argumentos.
  5. Espera o Windows Installer (mutex Global\\_MSIExecute) ficar livre antes/depois de cada pacote.

Funciona só no Windows; em outros sistemas cai num modo simples (útil para testes).
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import shlex
import subprocess
import time
from collections import deque
from typing import Callable, Optional

NT = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000

# classes de janela que não são "tela para o usuário" (janelas-fantasma de runtime/instalador)
CLASSES_IGNORADAS = {"TApplication", "InnoSetupLdrWindow", "MSCTFIME UI", "IME", "tooltips_class32"}


# ----------------------------------------------------------------------------
# Subprocessos ocultos
# ----------------------------------------------------------------------------
def kwargs_ocultos() -> dict:
    """Parâmetros de subprocess.Popen/run para não abrir nenhuma janela."""
    if not NT:
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": CREATE_NO_WINDOW, "startupinfo": si}


def ambiente_silencioso() -> dict:
    """SEE_MASK_NOZONECHECKS evita o aviso 'Abrir arquivo - Aviso de segurança' (Zone.Identifier)."""
    env = os.environ.copy()
    env["SEE_MASK_NOZONECHECKS"] = "1"
    return env


def rodar_oculto(cmd, **kw) -> subprocess.CompletedProcess:
    """subprocess.run sem janela."""
    kw = {**kwargs_ocultos(), **kw}
    return subprocess.run(cmd, **kw)


# ----------------------------------------------------------------------------
# API do Windows (ctypes) - só é tocada em NT
# ----------------------------------------------------------------------------
if NT:
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _u32 = ctypes.WinDLL("user32", use_last_error=True)

    class _BASIC(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                    ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                    ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

    class _IOC(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_IO(ctypes.Structure):
        _fields_ = [("Basic", _BASIC), ("Io", _IOC)]

    _MAXPIDS = 512

    class _PIDLIST(ctypes.Structure):
        _fields_ = [("NumberOfAssignedProcesses", wintypes.DWORD),
                    ("NumberOfProcessIdsInList", wintypes.DWORD),
                    ("ProcessIdList", ctypes.c_size_t * _MAXPIDS)]

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                               wintypes.DWORD, ctypes.c_void_p]
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.OpenMutexW.restype = wintypes.HANDLE
    _k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    _u32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _u32.IsWindowVisible.argtypes = [wintypes.HWND]
    _u32.IsWindow.argtypes = [wintypes.HWND]
    _u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]


def _criar_job(proc: subprocess.Popen):
    """Cria um Job Object e coloca o processo nele. None se não for possível."""
    if not NT:
        return None
    try:
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            return None
        if not _k32.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined]
            _k32.CloseHandle(job)
            return None
        return job
    except Exception:  # noqa: BLE001
        return None


def _contadores(job) -> Optional[tuple]:
    """(cpu_segundos, bytes_io, processos_ativos) acumulados do job."""
    info = _BASIC_IO()
    if not _k32.QueryInformationJobObject(job, 8, ctypes.byref(info), ctypes.sizeof(info), None):
        return None
    cpu = (info.Basic.TotalUserTime + info.Basic.TotalKernelTime) / 1e7
    io = info.Io.ReadTransferCount + info.Io.WriteTransferCount + info.Io.OtherTransferCount
    return cpu, io, info.Basic.ActiveProcesses


def _pids_do_job(job) -> set:
    lista = _PIDLIST()
    if not _k32.QueryInformationJobObject(job, 3, ctypes.byref(lista), ctypes.sizeof(lista), None):
        return set()
    return {lista.ProcessIdList[i] for i in range(min(lista.NumberOfProcessIdsInList, _MAXPIDS))}


def _janelas_visiveis(pids: set) -> list:
    """[(hwnd, título, classe)] das janelas de topo visíveis que pertencem aos pids."""
    achadas: list = []

    def cb(hwnd, _lp):
        try:
            if not _u32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in pids:
                return True
            if _u32.GetWindowLongW(hwnd, -20) & 0x80:          # WS_EX_TOOLWINDOW
                return True
            cls = ctypes.create_unicode_buffer(128)
            _u32.GetClassNameW(hwnd, cls, 128)
            if cls.value in CLASSES_IGNORADAS:
                return True
            r = wintypes.RECT()
            _u32.GetWindowRect(hwnd, ctypes.byref(r))
            if (r.right - r.left) * (r.bottom - r.top) <= 4:   # janela-fantasma (0x0 / 1x1)
                return True
            titulo = ctypes.create_unicode_buffer(256)
            _u32.GetWindowTextW(hwnd, titulo, 256)
            achadas.append((hwnd, titulo.value, cls.value))
        except Exception:  # noqa: BLE001
            pass
        return True

    _u32.EnumWindows(_WNDENUMPROC(cb), 0)
    return achadas


def msi_ocupado() -> bool:
    """True se o Windows Installer está executando algo (mutex Global\\_MSIExecute retido)."""
    if not NT:
        return False
    h = _k32.OpenMutexW(0x00100000, False, "Global\\_MSIExecute")   # SYNCHRONIZE
    if not h:
        return False
    try:
        r = _k32.WaitForSingleObject(h, 0)
        if r in (0, 0x80):                                          # adquirido/abandonado => livre
            _k32.ReleaseMutex(h)
            return False
        return True
    finally:
        _k32.CloseHandle(h)


def aguardar_msi_livre(max_s: int = 600, tick: Optional[Callable[[int], None]] = None) -> bool:
    """Espera o Windows Installer ficar livre. True se livre; False se estourou o tempo."""
    t0 = time.time()
    while msi_ocupado():
        seg = int(time.time() - t0)
        if seg >= max_s:
            return False
        if tick:
            with contextlib.suppress(Exception):
                tick(seg)
        time.sleep(2)
    return True


# ----------------------------------------------------------------------------
# Execução
# ----------------------------------------------------------------------------
class ResultadoExec:
    """codigo: código de saída do processo raiz | motivo: ok / ui_travada / timeout."""

    def __init__(self) -> None:
        self.codigo: int = 0
        self.motivo: str = "ok"
        self.janelas: list = []          # ["título [classe]", ...] vistas durante a execução
        self.duracao: float = 0.0
        self.deixou_filhos: bool = False


def executar_arvore(linha_cmd: str, cwd: Optional[str], timeout_s: int,
                    tick: Optional[Callable[[int], None]] = None,
                    ocultar: bool = True, vigiar_ui: bool = True,
                    ui_ocioso_s: int = 60, pos_ocioso_s: int = 45, pos_max_s: int = 600,
                    ao_janela: Optional[Callable[[str], None]] = None) -> ResultadoExec:
    """Executa 'linha_cmd' e espera a ÁRVORE inteira. Veja o docstring do módulo.

    ui_ocioso_s : janela visível + árvore sem atividade por este tempo => 'ui_travada' (encerra).
    pos_ocioso_s: depois que o processo raiz sai, espera os filhos até ficarem ociosos por este tempo.
    pos_max_s   : teto de espera pelos filhos depois que o processo raiz saiu.
    """
    res = ResultadoExec()
    t0 = time.time()
    if NT:
        proc = subprocess.Popen(linha_cmd, cwd=cwd, env=ambiente_silencioso(), **kwargs_ocultos())
    else:                                                    # modo de teste fora do Windows
        proc = subprocess.Popen(shlex.split(linha_cmd), cwd=cwd)
    job = _criar_job(proc)

    amostras: deque = deque()        # (t, cpu_s, io_bytes)
    ocultas: set = set()
    vistas: set = set()
    ui_desde: Optional[float] = None
    saiu_em: Optional[float] = None
    ultimo_tick = 0.0

    def atividade(janela_s: float) -> Optional[bool]:
        """True se houve atividade (CPU/disco) na janela; None se ainda não há amostras suficientes."""
        if not amostras:
            return None
        agora, cpu, io = amostras[-1]
        ref = None
        for a in amostras:
            if agora - a[0] <= janela_s:
                ref = a
                break
        if ref is None or agora - ref[0] < janela_s * 0.8:
            return None
        return (cpu - ref[1]) >= 0.5 or (io - ref[2]) >= 262144

    try:
        while True:
            agora = time.time()
            seg = int(agora - t0)
            rc = proc.poll()
            if rc is not None and saiu_em is None:
                saiu_em, res.codigo = agora, rc

            cont = _contadores(job) if job else None
            ativos = cont[2] if cont else (1 if rc is None else 0)
            if rc is not None and ativos == 0:
                break
            if cont:
                amostras.append((agora, cont[0], cont[1]))
                while amostras and agora - amostras[0][0] > max(ui_ocioso_s, pos_ocioso_s) + 10:
                    amostras.popleft()

            # ---- janelas: oculta e registra --------------------------------------------------
            if NT and (ocultar or vigiar_ui):
                pids = _pids_do_job(job) if job else {proc.pid}
                for hwnd, titulo, cls in _janelas_visiveis(pids):
                    if hwnd not in vistas:
                        vistas.add(hwnd)
                        desc = f"{titulo or '(sem título)'} [{cls}]"
                        res.janelas.append(desc)
                        if ao_janela:
                            with contextlib.suppress(Exception):
                                ao_janela(desc)
                    if ui_desde is None:
                        ui_desde = agora
                    if ocultar:
                        _u32.ShowWindowAsync(hwnd, 0)
                        ocultas.add(hwnd)
                # janela oculta por nós que ainda existe continua contando como "tela pendente"
                if ui_desde is not None and not any(_u32.IsWindow(h) for h in ocultas) \
                        and not _janelas_visiveis(pids):
                    ui_desde = None

            # ---- watchdog: tela aberta + árvore parada = esperando clique -----------------------
            if vigiar_ui and rc is None and ui_desde and agora - ui_desde >= ui_ocioso_s:
                if atividade(ui_ocioso_s) is False:
                    res.motivo, res.codigo = "ui_travada", 1602
                    _encerrar(job, proc)
                    break

            # ---- depois que o processo raiz saiu: espera os filhos --------------------------------
            if rc is not None:
                if agora - saiu_em >= pos_max_s or (atividade(pos_ocioso_s) is False):
                    res.deixou_filhos = True
                    break

            if seg > timeout_s:
                res.motivo, res.codigo = "timeout", 1460
                _encerrar(job, proc)
                break

            if tick and agora - ultimo_tick >= 5:
                ultimo_tick = agora
                with contextlib.suppress(Exception):
                    tick(seg)
            time.sleep(0.2)
    finally:
        if job:
            _k32.CloseHandle(job)
        res.duracao = time.time() - t0
    return res


def _encerrar(job, proc: subprocess.Popen) -> None:
    """Mata a árvore inteira (job) ou, sem job, só o processo."""
    with contextlib.suppress(Exception):
        if job:
            _k32.TerminateJobObject(job, 1)
        else:
            proc.kill()
    with contextlib.suppress(Exception):
        proc.wait(timeout=30)

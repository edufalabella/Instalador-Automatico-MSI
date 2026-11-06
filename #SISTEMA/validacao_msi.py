# -*- coding: utf-8 -*-
"""
Validação de pacotes MSI (antes de instalar)
--------------------------------------------
Responde, para CADA .msi, "isto vai instalar ou vai dar erro?" sem executar nada. Cada conferência
devolve OK / AVISO / ERRO e um motivo legível; um pacote com ERRO é BLOQUEADO (não é instalado).

O que é conferido
  Arquivo ........ legível, não vazio, cabeçalho OLE de MSI
  Banco .......... o Windows Installer (msi.dll) consegue abrir; tabelas essenciais existem
  Identidade ..... ProductCode (GUID), ProductVersion, ProductName
  Componentes .... Component/Feature/FeatureComponents e referências entre elas (a falta de Component
                   é o que causava o erro 1603 nos MSI gerados por versões antigas); 64 bits x SO
  Sequência ...... InstallInitialize < ... < InstallFinalize
  Fontes ......... .cab embutido legível por inteiro / .cab externo presente ao lado do .msi
  Payload ........ (MSI gerados por este programa) .exe embutido: tamanho, cabeçalho PE, estrutura PE
                   (detecta truncamento), SHA-256 igual ao gravado na conversão / ao .exe original,
                   Custom Action 'RunInstall' coerente e posicionada dentro da transação
  Lote ........... ProductCode duplicado e UpgradeCode igual com versões diferentes (o 2º pacote seria
                   ignorado com o código 1638, que o instalador conta como "sucesso")

Regra de severidade: ERRO só quando há evidência conclusiva de que a instalação vai falhar. Falha do
próprio validador vira AVISO (nunca bloqueia por engano). Em pacotes de terceiros, inconsistências
"de catálogo" (ICE) são AVISO; em pacotes gerados por este programa, são ERRO.

Este módulo não importa nada específico do Windows ao ser carregado (msi.dll é usada só ao abrir um
banco), por isso pode ser testado em qualquer sistema.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import re
import shutil
import struct
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

VERSAO_VALIDADOR = "1.0"
FABRICANTE_WRAPPER = "Instalador Automatico"     # marca dos MSI gerados por instalador_msi.py
OLE = bytes.fromhex("D0CF11E0A1B11AE1")
SQL_BIN = "SELECT `Data` FROM `Binary` WHERE `Name`='SetupExe'"
LIMITE_HASH_MB = 2048            # acima disso o payload não é lido por inteiro (só cabeçalho/tamanho)
LIMITE_CAB_MB = 800              # .cab embutido de pacote de terceiros: lido por inteiro até este tamanho
GUID = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
VERSAO_PRODUTO = re.compile(r"^\d+\.\d+(\.\d+){0,2}$")
NIVEL_ORDEM = {"ok": 0, "info": 0, "aviso": 1, "erro": 2}


# ----------------------------------------------------------------------------
# Resultado
# ----------------------------------------------------------------------------
@dataclass
class Verificacao:
    nome: str
    nivel: str          # ok | info | aviso | erro
    detalhe: str


@dataclass
class Resultado:
    msi: Path
    verificacoes: list = field(default_factory=list)
    embutido: bool = False          # MSI gerado por este programa (tem o .exe na tabela Binary)
    tamanho: int = 0
    duracao: float = 0.0
    assinatura: tuple = ()          # (tamanho, mtime_ns) quando foi validado
    info: dict = field(default_factory=dict)

    @property
    def nivel(self) -> str:
        pior = max((NIVEL_ORDEM.get(v.nivel, 0) for v in self.verificacoes), default=0)
        return {0: "ok", 1: "aviso", 2: "erro"}[pior]

    @property
    def bloqueado(self) -> bool:
        return self.nivel == "erro"

    @property
    def resumo(self) -> str:
        for alvo in ("erro", "aviso"):
            for v in self.verificacoes:
                if v.nivel == alvo:
                    return f"{v.nome}: {v.detalhe}"
        return "íntegro"

    def adicionar(self, nome: str, nivel: str, detalhe: str) -> None:
        self.verificacoes.append(Verificacao(nome, nivel, detalhe))

    def linhas(self) -> list:
        marca = {"ok": "OK   ", "info": "OK   ", "aviso": "AVISO", "erro": "ERRO "}
        return [f"[{marca.get(v.nivel, '?')}] {v.nome}: {v.detalhe}" for v in self.verificacoes]


def assinatura_arquivo(arq: Path) -> tuple:
    try:
        st = Path(arq).stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return ()


def fmt_mb(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def os_64bits() -> bool:
    arq = (os.environ.get("PROCESSOR_ARCHITEW6432") or platform.machine() or "").lower()
    return arq in ("amd64", "x86_64", "arm64", "aarch64", "ia64")


# ----------------------------------------------------------------------------
# Leitor de banco MSI (msi.dll)
# ----------------------------------------------------------------------------
class ErroMSI(OSError):
    """Código de retorno diferente de zero devolvido pela API do Windows Installer."""


def _api():
    m = ctypes.windll.msi          # type: ignore[attr-defined]
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


class LeitorWindows:
    """Abre o MSI UMA vez (somente leitura) e responde às consultas da validação."""

    def __init__(self, caminho: Path):
        self.api = _api()
        self.hdb = ctypes.c_ulong(0)
        rc = self.api.MsiOpenDatabaseW(str(caminho), None, ctypes.byref(self.hdb))   # None = só leitura
        if rc:
            raise ErroMSI(rc, f"MsiOpenDatabase falhou ({rc})")

    def fechar(self) -> None:
        if self.hdb.value:
            self.api.MsiCloseHandle(self.hdb.value)
            self.hdb = ctypes.c_ulong(0)

    def _abrir_view(self, sql: str):
        hview = ctypes.c_ulong(0)
        rc = self.api.MsiDatabaseOpenViewW(self.hdb.value, sql, ctypes.byref(hview))
        if rc:
            raise ErroMSI(rc, f"consulta inválida ou tabela ausente ({rc})")
        rc = self.api.MsiViewExecute(hview.value, 0)
        if rc:
            self.api.MsiCloseHandle(hview.value)
            raise ErroMSI(rc, f"MsiViewExecute falhou ({rc})")
        return hview

    def _texto(self, hrec: int, coluna: int) -> str:
        tam = 1024
        while True:
            buf = ctypes.create_unicode_buffer(tam)
            n = ctypes.c_ulong(tam)
            rc = self.api.MsiRecordGetStringW(hrec, coluna, buf, ctypes.byref(n))
            if rc == 234:                       # ERROR_MORE_DATA: n = tamanho necessário
                tam = n.value + 1
                continue
            if rc:
                raise ErroMSI(rc, f"MsiRecordGetString falhou ({rc})")
            return buf.value

    def linhas(self, sql: str, colunas: int) -> list:
        """Todas as linhas da consulta, cada uma como tupla de textos (coluna nula = '')."""
        hview = self._abrir_view(sql)
        saida = []
        try:
            while True:
                hrec = ctypes.c_ulong(0)
                rc = self.api.MsiViewFetch(hview.value, ctypes.byref(hrec))
                if rc == 259:                   # ERROR_NO_MORE_ITEMS
                    break
                if rc:
                    raise ErroMSI(rc, f"MsiViewFetch falhou ({rc})")
                try:
                    saida.append(tuple(self._texto(hrec.value, i) for i in range(1, colunas + 1)))
                finally:
                    self.api.MsiCloseHandle(hrec.value)
        finally:
            self.api.MsiCloseHandle(hview.value)
        return saida

    def tabelas(self) -> set:
        return {r[0] for r in self.linhas("SELECT `Name` FROM `_Tables`", 1)}

    def tamanho_stream(self, sql: str) -> int:
        """Tamanho do fluxo binário da 1ª coluna da 1ª linha; 0 se não houver linha."""
        hview = self._abrir_view(sql)
        try:
            hrec = ctypes.c_ulong(0)
            if self.api.MsiViewFetch(hview.value, ctypes.byref(hrec)) != 0:
                return 0
            try:
                return int(self.api.MsiRecordDataSize(hrec.value, 1))
            finally:
                self.api.MsiCloseHandle(hrec.value)
        finally:
            self.api.MsiCloseHandle(hview.value)

    def ler_stream(self, sql: str, bloco: int = 1 << 20) -> Iterator[bytes]:
        """Entrega o fluxo binário da 1ª coluna da 1ª linha, em blocos (sem gravar em disco)."""
        hview = self._abrir_view(sql)
        try:
            hrec = ctypes.c_ulong(0)
            if self.api.MsiViewFetch(hview.value, ctypes.byref(hrec)) != 0:
                return
            try:
                buf = ctypes.create_string_buffer(bloco)
                while True:
                    n = ctypes.c_ulong(bloco)
                    rc = self.api.MsiRecordReadStream(hrec.value, 1, buf, ctypes.byref(n))
                    if rc:
                        raise ErroMSI(rc, f"MsiRecordReadStream falhou ({rc})")
                    if n.value == 0:
                        break
                    yield buf.raw[:n.value]
            finally:
                self.api.MsiCloseHandle(hrec.value)
        finally:
            self.api.MsiCloseHandle(hview.value)


# ----------------------------------------------------------------------------
# Estrutura do executável (PE)
# ----------------------------------------------------------------------------
def analisar_pe(cab: bytes) -> tuple:
    """(valido, tamanho_minimo_esperado, mensagem). O mínimo vem da tabela de seções (e da assinatura
    digital, se houver): um .exe menor que isso foi truncado. 0 = não deu para calcular."""
    if len(cab) < 64 or cab[:2] != b"MZ":
        return False, 0, "não começa com 'MZ' (não é um executável do Windows)"
    lfanew = struct.unpack_from("<I", cab, 0x3C)[0]
    if lfanew < 64 or lfanew + 24 > len(cab):
        return False, 0, "cabeçalho PE fora do alcance (arquivo corrompido)"
    if cab[lfanew:lfanew + 4] != b"PE\0\0":
        return False, 0, "assinatura 'PE' ausente (arquivo corrompido)"
    nsec = struct.unpack_from("<H", cab, lfanew + 6)[0]
    tam_opt = struct.unpack_from("<H", cab, lfanew + 20)[0]
    opt = lfanew + 24
    sec = opt + tam_opt
    if nsec == 0 or nsec > 96:
        return False, 0, f"número de seções inválido ({nsec})"
    if sec + 40 * nsec > len(cab):
        return True, 0, "tabela de seções fora do trecho lido (estrutura não conferida)"
    minimo = 0
    for i in range(nsec):
        base = sec + 40 * i
        tam_raw, ptr_raw = struct.unpack_from("<II", cab, base + 16)
        if tam_raw:
            minimo = max(minimo, ptr_raw + tam_raw)
    if opt + 2 <= len(cab):
        magico = struct.unpack_from("<H", cab, opt)[0]
        desl_n, desl_dd = (92, 96) if magico == 0x10B else (108, 112)
        if magico in (0x10B, 0x20B) and opt + desl_dd + 40 <= len(cab):
            n_dir = struct.unpack_from("<I", cab, opt + desl_n)[0]
            if n_dir > 4:
                pos, tam = struct.unpack_from("<II", cab, opt + desl_dd + 32)   # diretório 4 = assinatura
                if pos:
                    minimo = max(minimo, pos + tam)
    return True, minimo, "estrutura PE consistente"


# ----------------------------------------------------------------------------
# Validação de um pacote
# ----------------------------------------------------------------------------
def _sha256_arquivo(arq: Path) -> str:
    h = hashlib.sha256()
    with open(arq, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def validar_pacote(msi: Path, exe: Optional[Path] = None, completo: bool = True,
                   progresso: Optional[Callable[[float, str], None]] = None,
                   abrir: Callable = LeitorWindows) -> Resultado:
    """Valida um .msi. 'exe' = .exe original (se ainda existir) para comparação exata;
    'completo=False' pula a leitura integral dos fluxos (só estrutura, tamanhos e cabeçalho PE)."""
    msi = Path(msi)
    r = Resultado(msi=msi)
    t0 = time.time()
    try:
        _validar(r, exe, completo, progresso or (lambda f, t: None), abrir)
    except Exception as exc:  # noqa: BLE001 - falha do validador nunca bloqueia por engano
        r.adicionar("Validador", "aviso", f"falha interna ao validar ({type(exc).__name__}: {exc}); "
                                          "pacote NÃO conferido por completo")
    r.duracao = time.time() - t0
    r.assinatura = assinatura_arquivo(msi)
    return r


def _validar(r: Resultado, exe: Optional[Path], completo: bool, prog: Callable, abrir: Callable) -> None:
    msi = r.msi
    add = r.adicionar

    # 1) arquivo ---------------------------------------------------------------------------------
    try:
        tam_msi = msi.stat().st_size
        with open(msi, "rb") as f:
            cab8 = f.read(8)
    except OSError as exc:
        add("Arquivo", "erro", f"não foi possível ler o arquivo ({exc.strerror or exc})")
        return
    r.tamanho = tam_msi
    if tam_msi == 0:
        add("Arquivo", "erro", "arquivo vazio (0 bytes) - cópia interrompida")
        return
    if cab8 != OLE:
        add("Arquivo", "erro", "o cabeçalho não é de um MSI (arquivo corrompido, incompleto ou de outro formato)")
        return
    add("Arquivo", "ok", f"{fmt_mb(tam_msi)}, legível, cabeçalho MSI válido")

    # 2) banco -----------------------------------------------------------------------------------
    try:
        leitor = abrir(msi)
    except OSError as exc:
        cod = getattr(exc, "args", [None])[0]
        add("Banco MSI", "erro", f"o Windows Installer não consegue abrir o pacote (código {cod}): "
                                 "arquivo corrompido ou cópia incompleta")
        return
    try:
        _checar_banco(r, leitor, exe, completo, prog)
    finally:
        leitor.fechar()


def _checar_banco(r: Resultado, L, exe: Optional[Path], completo: bool, prog: Callable) -> None:
    add, msi = r.adicionar, r.msi
    try:
        tabs = L.tabelas()
    except OSError as exc:
        add("Banco MSI", "erro", f"não foi possível listar as tabelas ({exc})")
        return
    tem = tabs.__contains__

    def consulta(sql: str, n: int) -> list:
        return L.linhas(sql, n)

    # tabelas e propriedades --------------------------------------------------------------------
    if not tem("Property"):
        add("Banco MSI", "erro", "tabela Property ausente - não é um pacote de instalação válido")
        return
    prop = {k: v for k, v in consulta("SELECT `Property`,`Value` FROM `Property`", 2)}
    binarios = {x[0] for x in consulta("SELECT `Name` FROM `Binary`", 1)} if tem("Binary") else set()
    emb = prop.get("Manufacturer") == FABRICANTE_WRAPPER and "SetupExe" in binarios
    r.embutido = emb
    sev = "erro" if emb else "aviso"        # inconsistências de catálogo: erro só nos MSI deste programa

    faltam_graves = [t for t in ("InstallExecuteSequence",) if not tem(t)]
    if emb:
        faltam_graves += [t for t in ("Binary", "CustomAction", "Component", "Feature",
                                      "FeatureComponents", "Directory") if not tem(t)]
    faltam_leves = [] if emb else [t for t in ("Component", "Feature", "FeatureComponents", "Directory")
                                   if not tem(t)]
    if faltam_graves:
        add("Tabelas", "erro", "tabelas obrigatórias ausentes: " + ", ".join(faltam_graves)
            + (" (sem Component o Windows Installer aborta com o erro 1603)" if "Component" in faltam_graves else ""))
    elif faltam_leves:
        add("Tabelas", "aviso", "tabelas ausentes: " + ", ".join(faltam_leves))
    else:
        add("Tabelas", "ok", f"{len(tabs)} tabelas; essenciais presentes")

    # identidade ---------------------------------------------------------------------------------
    pc, uc = prop.get("ProductCode", ""), prop.get("UpgradeCode", "")
    ver, nome = prop.get("ProductVersion", ""), prop.get("ProductName", "")
    r.info.update(nome=nome, versao=ver, product_code=pc.upper(), upgrade_code=uc.upper())
    if not GUID.match(pc):
        add("Identidade", "erro", f"ProductCode ausente ou inválido ({pc or 'vazio'})")
    elif not ver or not VERSAO_PRODUTO.match(ver):
        add("Identidade", "erro" if not ver else "aviso", f"ProductVersion {'ausente' if not ver else 'fora do padrão: ' + ver}")
    else:
        partes = [int(p) for p in ver.split(".")]
        if partes[0] > 255 or partes[1] > 255 or (len(partes) > 2 and partes[2] > 65535):
            add("Identidade", "aviso", f"ProductVersion {ver} excede os limites do Windows Installer (255.255.65535)")
        elif not nome:
            add("Identidade", "aviso", f"sem ProductName (versão {ver})")
        else:
            add("Identidade", "ok", f"{nome} {ver}")
    if emb and not GUID.match(uc):
        add("Identidade", "aviso", "UpgradeCode ausente")

    # componentes ---------------------------------------------------------------------------------
    if tem("Component") and tem("FeatureComponents") and tem("Feature"):
        comps = consulta("SELECT `Component`,`Directory_`,`Attributes` FROM `Component`", 3)
        feats = {x[0] for x in consulta("SELECT `Feature` FROM `Feature`", 1)}
        fc = consulta("SELECT `Feature_`,`Component_` FROM `FeatureComponents`", 2)
        dirs = {x[0] for x in consulta("SELECT `Directory` FROM `Directory`", 1)} if tem("Directory") else set()
        ids = {c[0] for c in comps}
        problemas = []
        nivel = "ok"
        if not comps:
            problemas.append("nenhum Component (a instalação aborta com o erro 1603)")
        if not feats:
            problemas.append("nenhuma Feature")
        if comps and feats and not fc:
            problemas.append("nenhuma Feature liga componentes (a instalação aborta com o erro 1603)")
        sem_comp = sorted({c for _, c in fc if c not in ids})
        sem_feat = sorted({f for f, _ in fc if f not in feats})
        sem_dir = sorted({d for _, d, _ in comps if d and tem("Directory") and d not in dirs})
        if sem_comp:
            problemas.append(f"FeatureComponents aponta para Component inexistente ({sem_comp[0]}"
                             f"{' +' + str(len(sem_comp) - 1) if len(sem_comp) > 1 else ''})")
        if sem_feat:
            problemas.append(f"FeatureComponents aponta para Feature inexistente ({sem_feat[0]})")
        if sem_dir:
            problemas.append(f"Component aponta para Directory inexistente ({sem_dir[0]}"
                             f"{' +' + str(len(sem_dir) - 1) if len(sem_dir) > 1 else ''})")
        if problemas:
            add("Componentes", sev, "; ".join(problemas))
        else:
            add("Componentes", "ok", f"{len(comps)} componente(s), {len(feats)} feature(s), referências consistentes")
        if any((int(a or 0) & 256) for _, _, a in comps) and not os_64bits():
            add("Plataforma", "erro", "o pacote contém componentes de 64 bits e este Windows é de 32 bits (erro 1633)")

    # sequência de instalação ----------------------------------------------------------------------
    seq: dict = {}
    if tem("InstallExecuteSequence"):
        for acao, num, _cond in consulta("SELECT `Action`,`Sequence`,`Condition` FROM `InstallExecuteSequence`", 3):
            if num.lstrip("-").isdigit():
                seq[acao] = int(num)
        ini, fim = seq.get("InstallInitialize"), seq.get("InstallFinalize")
        if ini is None or fim is None:
            add("Sequência", "erro", "InstallExecuteSequence sem InstallInitialize/InstallFinalize")
        elif ini >= fim:
            add("Sequência", "erro", "InstallInitialize vem depois de InstallFinalize")
        else:
            add("Sequência", "ok", f"{len(seq)} ações; InstallInitialize ({ini}) < InstallFinalize ({fim})")

    # fontes (.cab) --------------------------------------------------------------------------------
    if tem("Media") and tem("File") and consulta("SELECT `File` FROM `File`", 1):
        cabs = sorted({c[0] for c in consulta("SELECT `Cabinet` FROM `Media`", 1) if c[0]})
        _checar_cabs(r, L, cabs, completo, prog)

    # payload (MSI gerado por este programa) -------------------------------------------------------
    if emb:
        _checar_payload(r, L, prop, seq, exe, completo, prog, sev)
    else:
        add("Origem", "info", "pacote MSI de terceiros (conferência de estrutura; não há .exe embutido)")


def _checar_cabs(r: Resultado, L, cabs: list, completo: bool, prog: Callable) -> None:
    add = r.adicionar
    if not cabs:
        add("Fontes", "info", "pacote sem .cab (arquivos descompactados ao lado do .msi não são conferidos um a um)")
        return
    problemas, lidos = [], 0
    for cab in cabs:
        if cab.startswith("#"):
            nome = cab[1:]
            sql = "SELECT `Data` FROM `_Streams` WHERE `Name`='%s'" % nome.replace("'", "''")
            try:
                tam = L.tamanho_stream(sql)
                if tam == 0:
                    problemas.append(f"cabinet embutido '{nome}' ausente ou vazio")
                    continue
                if completo and tam <= LIMITE_CAB_MB << 20:
                    total = 0
                    for bloco in L.ler_stream(sql):
                        total += len(bloco)
                        prog(min(total / tam, 1.0), f"lendo {nome}")
                    if total != tam:
                        problemas.append(f"cabinet '{nome}' truncado (lidos {fmt_mb(total)} de {fmt_mb(tam)})")
                        continue
                    lidos += 1
            except ErroMSI as exc:
                problemas.append(f"cabinet '{nome}' ilegível (código {exc.args[0]}): cópia corrompida")
        else:
            if not (r.msi.parent / cab).is_file():
                problemas.append(f"cabinet externo '{cab}' não está ao lado do .msi")
    if problemas:
        add("Fontes", "erro", "; ".join(problemas))
    else:
        add("Fontes", "ok", f"{len(cabs)} cabinet(s) presentes" + (f", {lidos} lido(s) por inteiro" if lidos else ""))


def _checar_payload(r: Resultado, L, prop: dict, seq: dict, exe: Optional[Path], completo: bool,
                    prog: Callable, sev: str) -> None:
    add = r.adicionar
    try:
        tam = L.tamanho_stream(SQL_BIN)
    except OSError as exc:
        add("Payload", "erro", f"não foi possível consultar o .exe embutido ({exc})")
        return
    if tam <= 0:
        add("Payload", "erro", "o .exe embutido (Binary.SetupExe) está vazio")
        return
    r.info["payload"] = tam
    if r.tamanho < tam:
        add("Payload", "erro", f"o .msi ({fmt_mb(r.tamanho)}) é menor que o .exe embutido ({fmt_mb(tam)}): arquivo truncado")
        return

    ler_tudo = completo and tam <= LIMITE_HASH_MB << 20
    h, cab, total = hashlib.sha256(), b"", 0
    try:
        for bloco in L.ler_stream(SQL_BIN):
            if len(cab) < 8192:
                cab += bloco[:8192 - len(cab)]
            if ler_tudo:
                h.update(bloco)
                total += len(bloco)
                prog(min(total / tam, 1.0), "conferindo o .exe embutido")
            else:
                break
    except ErroMSI as exc:
        add("Payload", "erro", f"o .exe embutido não pôde ser lido até o fim (código {exc.args[0]}): MSI corrompido")
        return
    if ler_tudo and total != tam:
        add("Payload", "erro", f"leitura incompleta do .exe embutido ({fmt_mb(total)} de {fmt_mb(tam)})")
        return
    sha = h.hexdigest() if ler_tudo else None

    # tamanho declarado / original
    esperado = prop.get("ExeBytes", "")
    if esperado.isdigit() and int(esperado) != tam:
        add("Payload", "erro", f"o .exe embutido tem {tam} bytes mas a conversão gravou {esperado}")
        return
    if exe is not None and Path(exe).is_file() and Path(exe).stat().st_size != tam:
        add("Payload", "erro", f"o .exe embutido ({tam} bytes) difere do .exe original ({Path(exe).stat().st_size} bytes)")
        return

    # hash
    ref, origem = prop.get("ExeSha256", "").lower(), "gravado na conversão"
    if sha and exe is not None and Path(exe).is_file():      # o .exe original é a prova mais forte
        ref, origem = _sha256_arquivo(Path(exe)), "do .exe original"
    if sha and ref:
        if sha == ref:
            add("Integridade", "ok", f"SHA-256 do .exe embutido idêntico ao {origem}")
        else:
            add("Integridade", "erro", f"SHA-256 do .exe embutido DIFERE do {origem}: conteúdo corrompido")
            return

    # estrutura PE
    ok_pe, minimo, msg = analisar_pe(cab)
    if not ok_pe:
        add("Executável", "erro", f"o conteúdo embutido {msg}")
        return
    if minimo and tam < minimo:
        nivel = "info" if (sha and ref and sha == ref) else "aviso"   # hash igual => já era assim no original
        add("Executável", nivel, f"o .exe termina antes do esperado pela sua tabela de seções "
                                 f"({tam} < {minimo} bytes): possível truncamento")
    else:
        add("Executável", "ok", f"cabeçalho e {msg.replace('estrutura PE consistente', 'seções consistentes')}")
    if not (sha and ref):
        add("Integridade", "info", ("sem hash de referência (MSI gerado por versão anterior); " if not ref else "")
            + ("conteúdo não lido por inteiro (validação rápida); " if not ler_tudo else "")
            + "conferidos tamanho e estrutura PE")

    # Custom Action + posição na transação
    try:
        ca = L.linhas("SELECT `Action`,`Type`,`Source`,`Target` FROM `CustomAction` WHERE `Action`='RunInstall'", 4)
    except OSError as exc:
        add("Custom Action", "erro", f"não foi possível ler CustomAction ({exc})")
        return
    if not ca:
        add("Custom Action", "erro", "ação 'RunInstall' ausente: o pacote não executaria o instalador")
        return
    _, tipo, fonte, args = ca[0]
    problemas = []
    if fonte != "SetupExe":
        problemas.append(f"origem '{fonte}' em vez de SetupExe")
    if not tipo.isdigit() or (int(tipo) & 0x3F) != 2:
        problemas.append(f"tipo {tipo} não é 'EXE da tabela Binary'")
    if not args.strip():
        problemas.append("sem argumentos silenciosos (o instalador abriria telas)")
    n_run, ini, fim = seq.get("RunInstall"), seq.get("InstallInitialize"), seq.get("InstallFinalize")
    if n_run is None:
        problemas.append("RunInstall não está na InstallExecuteSequence")
    elif ini is not None and fim is not None and not (ini < n_run < fim):
        problemas.append(f"RunInstall ({n_run}) fora da transação ({ini}..{fim})")
    if problemas:
        add("Custom Action", "erro", "; ".join(problemas))
    else:
        add("Custom Action", "ok", f"RunInstall executa o .exe embutido (argumentos: {args}) na posição {n_run}")

    # espaço para extrair (modo direto)
    try:
        livre = shutil.disk_usage(tempfile.gettempdir()).free
        if livre < tam * 1.15 + (200 << 20):
            add("Espaço", "aviso", f"pouco espaço em %TEMP% ({fmt_mb(livre)} livres) para extrair {fmt_mb(tam)}")
    except OSError:
        pass


# ----------------------------------------------------------------------------
# Conferência entre pacotes (lote)
# ----------------------------------------------------------------------------
def limpar_lote(r: Resultado) -> None:
    """Remove avisos de colisão de uma conferência anterior (resultados em cache são reaproveitados)."""
    r.verificacoes = [x for x in r.verificacoes if x.nome not in ("Duplicado", "Conflito")]


def checar_lote(resultados: list) -> None:
    """Acrescenta AVISOS aos resultados que colidem entre si (não altera pacotes com ERRO)."""
    por_pc: dict = {}
    por_uc: dict = {}
    for r in resultados:
        pc, uc = r.info.get("product_code"), r.info.get("upgrade_code")
        if pc:
            por_pc.setdefault(pc, []).append(r)
        if uc and r.embutido:
            por_uc.setdefault(uc, []).append(r)
    for pc, grupo in por_pc.items():
        if len(grupo) > 1:
            for r in grupo:
                outros = ", ".join(o.msi.name for o in grupo if o is not r)
                r.adicionar("Duplicado", "aviso", f"mesmo ProductCode de {outros}: o segundo a instalar é ignorado (código 1638)")
    for uc, grupo in por_uc.items():
        versoes = {r.info.get("versao") for r in grupo}
        if len(grupo) > 1 and len(versoes) > 1:
            for r in grupo:
                outros = ", ".join(o.msi.name for o in grupo if o is not r)
                r.adicionar("Conflito", "aviso", f"mesmo UpgradeCode de {outros} com versões diferentes (nomes de .exe iguais?): "
                                                 "o mais antigo pode ser ignorado (código 1638)")

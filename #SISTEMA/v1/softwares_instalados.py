# -*- coding: utf-8 -*-
"""
Softwares instalados no computador
----------------------------------
* listar()      -> lista (nome, versão, fabricante, origem) lida do registro do Windows (HKLM 64/32 bits,
                   HKCU e HKU dos outros usuários) em paralelo, mais os apps da Microsoft Store (opcional).
* ja_instalado() -> diz se um pacote (nome do arquivo) já parece estar instalado.
* exportar()    -> grava a lista em .txt/.csv.

Só o registro é lido (rápido: ~0,2 s); nada é executado.
"""
from __future__ import annotations

import csv
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import winreg  # type: ignore
except ImportError:  # fora do Windows (testes)
    winreg = None

_CHAVE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_FONTES = []
if winreg:
    _FONTES = [
        (winreg.HKEY_LOCAL_MACHINE, _CHAVE, winreg.KEY_WOW64_64KEY, "64 bits"),
        (winreg.HKEY_LOCAL_MACHINE, _CHAVE, winreg.KEY_WOW64_32KEY, "32 bits"),
        (winreg.HKEY_CURRENT_USER, _CHAVE, 0, "usuário"),
    ]


def _valor(chave, nome: str) -> str:
    try:
        v, _ = winreg.QueryValueEx(chave, nome)
        return str(v).strip()
    except OSError:
        return ""


def _ler_fonte(fonte) -> list:
    raiz, caminho, acesso, origem = fonte
    itens = []
    try:
        with winreg.OpenKey(raiz, caminho, 0, winreg.KEY_READ | acesso) as k:
            n = winreg.QueryInfoKey(k)[0]
            subs = [winreg.EnumKey(k, i) for i in range(n)]
    except OSError:
        return itens
    for sub in subs:
        try:
            with winreg.OpenKey(raiz, f"{caminho}\\{sub}", 0, winreg.KEY_READ | acesso) as s:
                nome = _valor(s, "DisplayName")
                if not nome or _valor(s, "SystemComponent") == "1" or _valor(s, "ParentKeyName"):
                    continue
                itens.append({"nome": nome, "versao": _valor(s, "DisplayVersion"),
                              "fabricante": _valor(s, "Publisher"), "origem": origem,
                              "codigo": sub, "local": _valor(s, "InstallLocation")})
        except OSError:
            continue
    return itens


def _apps_store() -> list:
    """Apps da Microsoft Store (opcional, mais lento: roda em paralelo com a leitura do registro)."""
    import subprocess
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-AppxPackage -AllUsers | Where-Object {$_.IsFramework -eq $false -and $_.SignatureKind -eq 'Store'} "
             "| ForEach-Object { $_.Name + '|' + $_.Version }"],
            capture_output=True, text=True, timeout=40, creationflags=0x08000000)
        out = []
        for ln in r.stdout.splitlines():
            if "|" in ln:
                n, v = ln.strip().split("|", 1)
                out.append({"nome": n, "versao": v, "fabricante": "Microsoft Store", "origem": "Store",
                            "codigo": "", "local": ""})
        return out
    except Exception:  # noqa: BLE001
        return []


def listar(incluir_store: bool = False) -> list:
    """Lista ordenada e sem duplicados (nome+versão) de tudo que está instalado."""
    if winreg is None:
        return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_ler_fonte, f) for f in _FONTES]
        fstore = pool.submit(_apps_store) if incluir_store else None
        itens = [i for f in futs for i in f.result()]
        if fstore:
            itens += fstore.result()
    vistos, unicos = set(), []
    for i in itens:
        k = (i["nome"].lower(), i["versao"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(i)
    return sorted(unicos, key=lambda i: i["nome"].lower())


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


_RUIDO = {"setup", "installer", "install", "win", "win64", "windows", "x64", "x86", "amd64", "64bit", "32bit",
          "english", "en", "us", "exe", "msi", "bit", "br", "ptbr", "demo", "portable", "portatil", "l10n"}


def _tokens(t: str) -> set:
    """Palavras (só letras) do nome, sem ruído de arquivo (setup, x64, versões...)."""
    return {w for w in re.findall(r"[a-z]+", _norm(t)) if w not in _RUIDO and len(w) >= 3}


def ja_instalado(nome_pacote: str, instalados: list) -> str:
    """Devolve o nome do programa instalado que corresponde ao pacote, ou ''.
    Regra conservadora: TODAS as palavras do pacote (>=3 letras, sem ruído) precisam aparecer no nome
    instalado (palavra inteira; palavras >=5 letras também valem coladas, ex.: 'foxitpdfreader')."""
    tp = _tokens(Path(nome_pacote).stem)
    if not tp:
        return ""
    for i in instalados:
        ti = _tokens(i["nome"])
        if not ti:
            continue
        colado = "".join(sorted(ti)) + "".join(w for w in _norm(i["nome"]).split())
        if all(w in ti or (len(w) >= 5 and w in colado) for w in tp):
            return i["nome"]
    return ""


def exportar(itens: list, caminho: Path) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.suffix.lower() == ".csv":
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Nome", "Versão", "Fabricante", "Origem"])
            for i in itens:
                w.writerow([i["nome"], i["versao"], i["fabricante"], i["origem"]])
    else:
        with open(caminho, "w", encoding="utf-8") as f:
            for i in itens:
                f.write(f"{i['nome']}\t{i['versao']}\t{i['fabricante']}\n")
    return caminho

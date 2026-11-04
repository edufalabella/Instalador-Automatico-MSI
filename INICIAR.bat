@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Iniciador - Instalador MSI
cd /d "%~dp0"

REM ---------------------------------------------------------------
REM 1) Garante privilegios de administrador
REM ---------------------------------------------------------------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Solicitando privilegios de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM ---------------------------------------------------------------
REM 2) Procura o Python; se nao achar, instala a partir da raiz
REM ---------------------------------------------------------------
set "PY="
call :achar_python
if defined PY goto :rodar

echo [INFO] Python nao encontrado neste computador.

set "PYINST="
for %%F in ("%~dp0python-*.exe") do set "PYINST=%%~fF"

if not defined PYINST (
    echo.
    echo [ERRO] Instalador do Python nao encontrado na pasta:
    echo        %~dp0
    echo        Coloque o arquivo python-3.x.x-amd64.exe ao lado deste .bat.
    echo.
    pause
    exit /b 1
)

echo [INFO] Instalando Python a partir de: %PYINST%
echo        Aguarde, isso pode levar alguns minutos...
"%PYINST%" /quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0 Include_doc=0
set "RC=%errorlevel%"

if %RC% neq 0 if %RC% neq 3010 (
    echo.
    echo [ERRO] Falha ao instalar o Python (codigo %RC%).
    pause
    exit /b %RC%
)

REM O PATH desta janela nao foi atualizado, entao procuramos o python.exe direto
call :achar_python
if not defined PY (
    echo.
    echo [ERRO] Python foi instalado, mas nao foi possivel localiza-lo.
    echo        Feche esta janela e execute o INICIAR.bat novamente.
    pause
    exit /b 1
)
echo [OK] Python instalado com sucesso.
echo.

REM ---------------------------------------------------------------
REM 3) Executa o instalador de MSIs
REM ---------------------------------------------------------------
:rodar
set "PYTHONUTF8=1"
"%PY%" "%~dp0instalador_msi.py"
set "RC=%errorlevel%"
if %RC% neq 0 (
    echo.
    echo [AVISO] O instalador terminou com codigo %RC%.
    pause
)
exit /b %RC%


REM ===============================================================
REM Sub-rotina: define a variavel PY com o caminho do python.exe
REM ===============================================================
:achar_python
set "PY="

REM a) Python Launcher (py.exe)
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)"') do set "PY=%%P"
    if defined PY exit /b 0
)

REM b) python no PATH (o atalho da Microsoft Store retorna erro e e ignorado)
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PY=python"
    exit /b 0
)

REM c) Pastas padrao de instalacao
for /d %%D in ("%ProgramFiles%\Python3*" "%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%~D\python.exe" set "PY=%%~D\python.exe"
)
exit /b 0

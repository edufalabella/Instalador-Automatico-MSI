@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Iniciador - Instalador MSI
REM pushd (e nao "cd /d"): funciona tambem quando a pasta esta na rede (caminho \\servidor\...)
pushd "%~dp0"

REM --lancador  : (interno) indica que veio do INSTALAR.bat
REM --auto      : instalacao sem menu/perguntas (console visivel)
REM --sem-pausa : nao espera tecla no final (OBRIGATORIO em tarefa agendada/GPO/SCCM)
REM Modo GRAFICO (padrao): a unica janela visivel e a tela Python; o console fica oculto.
set "SEE_MASK_NOZONECHECKS=1"
set "AUTO="
set "NOPAUSE="
echo %* | "%SystemRoot%\System32\find.exe" /i "--auto" >nul && set "AUTO=1"
echo %* | "%SystemRoot%\System32\find.exe" /i "--sem-pausa" >nul && set "NOPAUSE=1"
set "GUI=1"
for %%A in (--auto --console --listar --menu --sem-pausa --pastas) do (
    echo %* | "%SystemRoot%\System32\find.exe" /i "%%A" >nul && set "GUI="
)

REM ---------------------------------------------------------------
REM Protecao: este arquivo so roda quando chamado pelo INSTALAR.bat da raiz
REM ---------------------------------------------------------------
echo %* | "%SystemRoot%\System32\find.exe" /i "--lancador" >nul
if errorlevel 1 (
    echo.
    echo Este arquivo nao deve ser executado diretamente.
    echo Use o INSTALAR.bat que fica na pasta raiz.
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0logs" mkdir "%~dp0logs" >nul 2>&1
REM rastro de cada execucao: se a janela "abrir e fechar", logs\iniciar.log mostra ate onde chegou
>>"%~dp0logs\iniciar.log" echo.
>>"%~dp0logs\iniciar.log" echo [%date% %time%] inicio - argumentos: %*

REM ---------------------------------------------------------------
REM 1) Garante privilegios de administrador (a unica janela do Windows que ainda pode aparecer: o UAC)
REM ---------------------------------------------------------------
REM CORRECAO: "net session" depende do servico "Servidor" (LanmanServer). Se ele estiver
REM desativado (comum em PC corporativo), o teste falha MESMO como administrador: a janela
REM elevada achava que nao era admin, pedia elevacao de novo e fechava - em loop.
REM "fltmc" so funciona como administrador e nao depende de servico nenhum.
"%SystemRoot%\System32\fltmc.exe" >nul 2>&1
if %errorlevel% equ 0 goto :admin_ok
echo %* | "%SystemRoot%\System32\find.exe" /i "--elevado" >nul
if not errorlevel 1 (
    >>"%~dp0logs\iniciar.log" echo [%date% %time%] ERRO: janela elevada sem privilegio de administrador
    echo.
    echo   [ERRO] A janela foi aberta como administrador, mas o Windows nao concedeu o privilegio.
    echo          Clique com o botao direito no INSTALAR.bat e use "Executar como administrador".
    echo.
    pause
    exit /b 1
)

REM Antes de elevar: anota o Python DESTE usuario. A janela elevada pode rodar com OUTRA conta
REM (ex.: usuario comum + senha do TI) que nao enxerga o Python instalado so para este usuario.
call :achar_python
if defined PY (
    for /f "delims=" %%P in ('call "%PY%" -c "import sys;print(sys.executable)" 2^>nul') do set "PYUSR=%%P"
)
if defined PYUSR >"%~dp0logs\python_usuario.txt" echo !PYUSR!
>>"%~dp0logs\iniciar.log" echo [%date% %time%] sem admin; python deste usuario: "!PYUSR!" - pedindo elevacao

REM CORRECAO do "abre e fecha": a janela elevada agora e um cmd que PAUSA se o .bat nao rodar ate o fim
REM (pasta inacessivel para a conta de administrador, unidade de rede mapeada, erro de sintaxe...).
REM Unidade mapeada (ex.: D: = \\servidor\pasta) nao existe na sessao elevada: trocamos pelo caminho de rede.
set "IM_BAT=%~f0"
set "IM_ARGS=%* --elevado"
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$b = $env:IM_BAT; $l = $b.Substring(0,1); $d = Get-PSDrive -Name $l -ErrorAction SilentlyContinue; if ($d -and $d.DisplayRoot) { $b = $d.DisplayRoot.TrimEnd([char]92) + $b.Substring(2) }; $q = [string][char]34; $c = '/c call ' + $q + $b + $q + ' ' + $env:IM_ARGS + ' || (echo. & echo [ERRO] O instalador parou. Veja a mensagem acima. & pause)'; try { Start-Process -FilePath $env:ComSpec -ArgumentList $c -Verb RunAs -WindowStyle Normal -ErrorAction Stop } catch { exit 1 }"
if errorlevel 1 (
    >>"%~dp0logs\iniciar.log" echo [%date% %time%] elevacao negada ou falhou
    call :falha "A permissao de administrador foi negada. O instalador precisa dela para funcionar."
)
exit /b

:admin_ok
>>"%~dp0logs\iniciar.log" echo [%date% %time%] rodando como administrador em "%CD%"

REM Remove a marca de "arquivo baixado da internet" (evita avisos de seguranca e bloqueio das DLLs do WiX)
powershell -NoProfile -WindowStyle Hidden -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1

REM ---------------------------------------------------------------
REM 2) Procura o Python; se nao achar, instala a partir da pasta #SISTEMA (com progresso visivel)
REM ---------------------------------------------------------------
call :banner
echo   [1/3] Permissao de administrador ...... OK
echo   [2/3] Verificando o Python
set "PY="
call :achar_python
if defined PY goto :py_achado

echo         Python nao encontrado neste computador.
set "PYINST="
for %%F in ("%~dp0python-*.exe") do set "PYINST=%%~fF"
if not defined PYINST (
    call :falha "Instalador do Python nao encontrado. Coloque o arquivo python-3.x.x-amd64.exe dentro da pasta #SISTEMA."
    exit /b 1
)
echo         Instalador: %PYINST%
echo         Instalando o Python. NAO feche esta janela.
echo.
REM O script e carregado como TEXTO (ScriptBlock): assim a politica de execucao de .ps1 (GPO) nao o bloqueia
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create([IO.File]::ReadAllText('%~dp0instalar_python.ps1'))) -Instalador '%PYINST%' -Log '%~dp0logs\python_instalacao.log'"
set "RC=!errorlevel!"
echo.

REM O PATH desta janela nao foi atualizado, entao procuramos o python.exe direto
call :achar_python
if defined PY goto :py_instalou

echo         A instalacao com progresso nao concluiu, codigo !RC!. Tentando o modo direto.
echo         Aguarde, isso pode levar alguns minutos. NAO feche esta janela.
start "" /wait "%PYINST%" /quiet /norestart InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_tcltk=1 Include_test=0 Include_doc=0 /log "%~dp0logs\python_instalacao_direto.log"
set "RC=!errorlevel!"
call :achar_python
if not defined PY (
    call :falha "O Python nao pode ser instalado ou localizado, codigo !RC!. Veja logs\python_instalacao.log."
    exit /b 1
)

:py_instalou
echo         [OK] Python instalado com sucesso.
goto :py_pronto

:py_achado
echo         [OK] Python ja instalado neste computador.

:py_pronto
set "PYVER="
REM CORRECAO: "call" na frente evita que o cmd remova as aspas de caminhos com espaco (C:\Program Files\...)
for /f "delims=" %%V in ('call "%PY%" --version 2^>^&1') do set "PYVER=%%V"
if defined PYVER echo         %PYVER%
>>"%~dp0logs\iniciar.log" echo [%date% %time%] python: %PY% - %PYVER%
echo.

REM ---------------------------------------------------------------
REM 3) Executa o instalador de MSIs
REM ---------------------------------------------------------------
:rodar
echo   [3/3] Iniciando a conversao e a validacao dos pacotes
set "PYTHONUTF8=1"
set "PYEXE="
for /f "delims=" %%P in ('call "%PY%" -c "import sys;print(sys.executable)"') do set "PYEXE=%%P"
if not defined PYEXE set "PYEXE=%PY%"
for %%I in ("%PYEXE%") do set "PYDIR=%%~dpI"
set "PYW=%PYDIR%pythonw.exe"
>>"%~dp0logs\iniciar.log" echo [%date% %time%] python.exe: %PYEXE% / pythonw.exe: %PYW%

REM Auto-teste: se o Python nao conseguir CARREGAR o programa, o erro aparece aqui (com pythonw seria invisivel)
"%PYEXE%" -c "import sys; sys.path.insert(0, r'%~dp0.'); import instalador_msi, tela_instalacao, validacao_msi" > "%~dp0logs\inicializacao.log" 2>&1
if errorlevel 1 (
    echo.
    echo   [ERRO] O Python nao conseguiu carregar o instalador. Detalhes:
    echo.
    type "%~dp0logs\inicializacao.log"
    echo.
    echo   Esse texto tambem esta em logs\inicializacao.log - envie-o para suporte.
    pause
    exit /b 1
)
if not defined GUI goto :modo_texto

REM ---------------------------------------------------------------
REM Tela grafica (pythonw.exe + tkinter). CORRECAO do "o prompt abre, fecha e nada acontece":
REM antes o pythonw era disparado com START e esta janela fechava NA HORA, sem conferir nada.
REM Se o pythonw morresse ao iniciar, ninguem via o erro. Agora esta janela so fecha depois que
REM a tela grafica avisa que abriu (logs\tela_aberta.flag); se o pythonw morrer, o erro aparece aqui.
REM ---------------------------------------------------------------
if not exist "%PYW%" (
    echo         [AVISO] pythonw.exe nao encontrado em "%PYW%" - usando o modo texto.
    >>"%~dp0logs\iniciar.log" echo [%date% %time%] pythonw.exe ausente: "%PYW%"
    goto :modo_console
)
"%PYEXE%" -c "import tkinter; tkinter.Tk().destroy()" >"%~dp0logs\tkinter.log" 2>&1
if errorlevel 1 (
    echo         [AVISO] O tkinter deste Python nao funciona - usando o modo texto.
    type "%~dp0logs\tkinter.log"
    >>"%~dp0logs\iniciar.log" echo [%date% %time%] tkinter falhou, ver logs\tkinter.log
    goto :modo_console
)

echo         Abrindo a tela do instalador. Aguarde...
set "IM_PYW=%PYW%"
set "IM_SCRIPT=%~dp0instalador_msi.py"
set "IM_ARGS=%*"
set "IM_FLAG=%~dp0logs\tela_aberta.flag"
del /q "%IM_FLAG%" >nul 2>&1
>>"%~dp0logs\iniciar.log" echo [%date% %time%] abrindo a tela grafica: %PYW%
powershell -NoProfile -ExecutionPolicy Bypass -Command "$q = [string][char]34; $a = $q + $env:IM_SCRIPT + $q + ' ' + $env:IM_ARGS; try { $p = Start-Process -FilePath $env:IM_PYW -ArgumentList $a -PassThru -ErrorAction Stop } catch { Write-Host $_.Exception.Message; exit 4 }; for ($i = 0; $i -lt 90; $i++) { if (Test-Path -LiteralPath $env:IM_FLAG) { exit 0 }; if ($p.HasExited) { exit 2 }; Start-Sleep -Milliseconds 500 }; exit 3"
set "GUIRC=%errorlevel%"
>>"%~dp0logs\iniciar.log" echo [%date% %time%] resultado da abertura: %GUIRC% (0=abriu 2=morreu 3=sem janela 4=nao iniciou)
if "%GUIRC%"=="0" exit /b 0

echo.
if "%GUIRC%"=="3" (
    echo   [AVISO] O programa esta rodando, mas a janela nao apareceu em 45 segundos.
    echo           Procure a janela na barra de tarefas. Se nao houver nenhuma, veja os logs abaixo.
) else (
    echo   [ERRO] A tela grafica fechou logo ao abrir, codigo %GUIRC%.
)
echo.
echo   ---- ultimas linhas de logs\console.log ----
powershell -NoProfile -Command "if (Test-Path -LiteralPath $env:IM_FLAG.Replace('tela_aberta.flag','console.log')) { Get-Content -LiteralPath $env:IM_FLAG.Replace('tela_aberta.flag','console.log') -Tail 25 }"
if exist "%~dp0logs\erro_fatal.txt" (
    echo   ---- logs\erro_fatal.txt ----
    powershell -NoProfile -Command "Get-Content -LiteralPath $env:IM_FLAG.Replace('tela_aberta.flag','erro_fatal.txt') -Tail 25"
)
if exist "%~dp0logs\falha_nativa.txt" (
    echo   ---- logs\falha_nativa.txt ----
    powershell -NoProfile -Command "Get-Content -LiteralPath $env:IM_FLAG.Replace('tela_aberta.flag','falha_nativa.txt') -Tail 25"
)
echo.
if "%GUIRC%"=="3" (
    pause
    exit /b 0
)
echo   Envie a pasta logs para o suporte. Agora o instalador vai abrir no MODO TEXTO nesta janela.
pause

:modo_console
"%PYEXE%" "%~dp0instalador_msi.py" %* --console
set "RC=%errorlevel%"
echo.
echo [FIM] Modo texto encerrado, codigo %RC%.
pause
exit /b %RC%

:modo_texto
"%PYEXE%" "%~dp0instalador_msi.py" %*
set "RC=%errorlevel%"
echo.
if %RC% equ 0 (
    echo [FIM] Concluido com sucesso.
) else if %RC% equ 3010 (
    echo [FIM] Concluido. REINICIE o computador para finalizar algumas instalacoes.
) else (
    echo [AVISO] O instalador terminou com codigo %RC%. Veja a pasta logs.
)
if defined AUTO if not defined NOPAUSE pause
exit /b %RC%


REM ===============================================================
REM Sub-rotina: cabecalho do prompt de comando
REM ===============================================================
:banner
cls
echo.
echo   ============================================================
echo     INSTALADOR AUTOMATICO MSI
echo     Python  ^>  Conversao EXE-MSI  ^>  Validacao  ^>  Instalacao
echo   ============================================================
echo.
exit /b 0


REM ===============================================================
REM Sub-rotina: mostra um erro (janela de mensagem no modo grafico; texto + pausa nos demais)
REM ===============================================================
:falha
echo.
echo [ERRO] %~1
>>"%~dp0logs\inicio.txt" echo [%date% %time%] %~1
if defined GUI (
    powershell -NoProfile -WindowStyle Hidden -Command "Add-Type -AssemblyName PresentationFramework; [void][System.Windows.MessageBox]::Show('%~1','Instalador MSI','OK','Error')"
) else (
    if not defined NOPAUSE pause
)
exit /b 1


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
if defined PY exit /b 0

REM d) Python anotado pela janela NAO elevada (instalacao "so para este usuario")
if exist "%~dp0logs\python_usuario.txt" (
    set /p "PYTMP=" <"%~dp0logs\python_usuario.txt"
    if exist "!PYTMP!" set "PY=!PYTMP!"
)
exit /b 0

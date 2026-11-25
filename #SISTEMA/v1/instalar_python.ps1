# ===============================================================
#  instalar_python.ps1  -  instala o Python MOSTRANDO O PROGRESSO no prompt de comando
#  Chamado pelo INICIAR.bat. Devolve o codigo de saida do instalador do Python.
#  (somente ASCII de proposito: o PowerShell 5 le .ps1 sem BOM como ANSI)
# ===============================================================
param(
    [Parameter(Mandatory = $true)][string]$Instalador,
    [Parameter(Mandatory = $true)][string]$Log
)
$ErrorActionPreference = 'Stop'
$argumentos = @('/quiet', '/norestart', 'InstallAllUsers=1', 'PrependPath=1', 'Include_launcher=1',
                'Include_tcltk=1', 'Include_test=0', 'Include_doc=0', '/log', ('"' + $Log + '"'))   # aspas: o caminho pode ter espacos

function Etapa-Atual([string]$arquivo) {
    # le o fim do log do instalador (Burn) e traduz a etapa em texto curto
    try {
        $linhas = Get-Content -LiteralPath $arquivo -Tail 60 -ErrorAction Stop
        for ($i = $linhas.Count - 1; $i -ge 0; $i--) {
            if ($linhas[$i] -match 'execute package: ([A-Za-z0-9_]+)') { return 'componente ' + $Matches[1] }
            if ($linhas[$i] -match 'Registering|Registration') { return 'registrando no Windows' }
            if ($linhas[$i] -match 'Planning|Plan complete') { return 'planejando a instalacao' }
        }
    } catch { }
    return 'iniciando'
}

function Escrever([string]$texto) {
    $largura = 78
    try { $largura = [Math]::Max(70, $Host.UI.RawUI.WindowSize.Width - 4) } catch { }
    if ($texto.Length -gt $largura) { $texto = $texto.Substring(0, $largura) }
    Write-Host ("`r" + $texto.PadRight($largura)) -NoNewline
}

$giro = '|', '/', '-', '\'
$rc = 1
for ($tentativa = 1; $tentativa -le 5; $tentativa++) {
    $proc = Start-Process -FilePath $Instalador -ArgumentList $argumentos -PassThru
    $relogio = [Diagnostics.Stopwatch]::StartNew()
    $n = 0
    while (-not $proc.HasExited) {
        $t = $relogio.Elapsed
        Escrever ("        [{0}] Instalando o Python   {1:00}:{2:00}   {3}" -f $giro[$n % 4], [int][Math]::Floor($t.TotalMinutes), $t.Seconds, (Etapa-Atual $Log))
        Start-Sleep -Milliseconds 400
        $n++
    }
    $proc.WaitForExit()
    $rc = $proc.ExitCode
    Escrever ("        [*] Instalador do Python terminou (codigo {0}) em {1:00}:{2:00}" -f $rc, [int][Math]::Floor($relogio.Elapsed.TotalMinutes), $relogio.Elapsed.Seconds)
    Write-Host ''
    # 1618 = outra instalacao em andamento (Windows Update etc.). 0x80070652 e o mesmo erro em HRESULT.
    if ($rc -eq 1618 -or $rc -eq -2147023278) {
        if ($tentativa -ge 5) { break }
        for ($s = 30; $s -ge 1; $s--) {
            Escrever ("        [!] Outra instalacao em andamento no Windows. Nova tentativa {0}/5 em {1}s" -f ($tentativa + 1), $s)
            Start-Sleep -Seconds 1
        }
        Write-Host ''
        continue
    }
    break
}
exit $rc

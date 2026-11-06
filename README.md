# 🛠️ Instalador Automático MSI

Ferramenta de linha de comando para **instalar pacotes `.msi` em lote** no Windows, com menu interativo, instalação silenciosa, logs detalhados e instalação automática do Python caso ele não exista na máquina.

> Desenvolvido por **Eduardo Falabella**

---

## 📑 Índice

1. [Visão geral](#-visão-geral)
2. [Funcionalidades](#-funcionalidades)
3. [Requisitos](#-requisitos)
4. [Estrutura de pastas](#-estrutura-de-pastas)
5. [Passo a passo de uso](#-passo-a-passo-de-uso)
6. [Usando o menu](#-usando-o-menu)
7. [Como funciona por dentro](#-como-funciona-por-dentro)
8. [Códigos de retorno](#-códigos-de-retorno)
9. [Logs](#-logs)
10. [Configurações](#-configurações)
11. [Controlando a ordem de instalação](#-controlando-a-ordem-de-instalação)
12. [Gerar um .exe (opcional)](#-gerar-um-exe-opcional)
13. [Solução de problemas](#-solução-de-problemas)
14. [Limitações conhecidas](#-limitações-conhecidas)

---

## 📌 Visão geral

Em vez de abrir cada instalador manualmente, você organiza os arquivos `.msi` em **subpastas** ao lado do programa. Ao executar, o software:

1. Garante que está rodando como **administrador**;
2. Verifica se o **Python** está instalado e, se não estiver, instala a partir do instalador que você deixou na pasta;
3. Exibe uma **tela de apresentação** e escaneia as subpastas;
4. Monta um **menu** com cada pasta encontrada;
5. Instala os MSIs da pasta escolhida (ou **todos**) de forma silenciosa, mostrando progresso e um resumo final.

Ideal para **preparação de computadores**, formatações, suporte técnico e padronização de softwares em empresas.

---

## ✨ Funcionalidades

| Recurso | Descrição |
|---|---|
| 📂 Menu dinâmico | Cada subpasta com `.msi` vira uma opção automaticamente |
| ⚡ Instalar tudo | Uma opção para instalar todos os MSIs de todas as pastas |
| 🔢 Seleção múltipla | Escolha várias pastas de uma vez, ex.: `1,3` |
| 🤫 Instalação silenciosa | Usa `msiexec /qn /norestart` (sem janelas e sem reiniciar o PC) |
| 🐍 Bootstrap do Python | Instala o Python sozinho se ele não existir na máquina |
| 🛡️ Auto-elevação | Pede permissão de administrador (UAC) automaticamente |
| 📊 Progresso visual | Barra de progresso geral e indicador de atividade por pacote |
| 🧾 Logs completos | Um log detalhado por MSI e um resumo por execução |
| 🔁 Reescanear | Adicione pastas e atualize o menu sem fechar o programa |
| 🎨 Interface colorida | Tela de apresentação, cores e rodapé com o nome do desenvolvedor |

---

## 💻 Requisitos

- **Windows 10 ou 11** (as cores ANSI do console precisam dessas versões)
- **Permissão de administrador** na máquina
- **Instalador do Python 3.9 ou superior** (64-bit) na pasta do projeto, caso o Python ainda não esteja instalado
- Arquivos **`.msi`** a serem instalados

> O software usa apenas a biblioteca padrão do Python. Não é necessário instalar nenhum pacote via `pip`.

---

## 📁 Estrutura de pastas

Recomendado (v1.2): todo o sistema dentro de uma pasta cujo nome começa com `#`, e as pastas de MSI na raiz, ao lado dela.

```
Raiz\                            ← pasta compartilhada / pendrive
│
├── INSTALAR.bat                 ← ÚNICO arquivo para executar
│
├── #SISTEMA\                    ← interno: ninguém precisa abrir
│   ├── INICIAR.bat              ← só roda se chamado pelo INSTALAR.bat
│   ├── VER_STATUS.bat           ← acompanha o progresso
│   ├── instalador_msi.py
│   ├── python-3.x.x-amd64.exe   ← instalador do Python
│   ├── wix3\                    ← candle.exe/light.exe (conversão EXE → MSI)
│   ├── README.md
│   └── logs\                    ← criada automaticamente
│
├── TECNICO-ELETRICA\            ← pastas de instaladores (cada uma vira uma opção)
│   └── *.msi / *.exe
├── TI-APT\
└── ...
```

- Se o programa estiver numa pasta com nome iniciado por `#`, os MSI são procurados na **pasta pai**. Em qualquer outra pasta, ao lado do programa (como antes).
- Pastas que começam com `#` ou `.` nunca entram no menu; `logs`, `build`, `dist` e `__pycache__` também são ignoradas.
- Para apontar outra pasta de MSI: `INSTALAR.bat --raiz D:\Instaladores`.
- O **nome das subpastas** é o que aparece no menu; só aparecem as que **contêm pelo menos um `.msi`**.

---

## 🚀 Passo a passo de uso

### 1. Prepare a pasta

1. Copie a pasta `InstaladorMSI` para o computador (ou para um pendrive/rede).
2. Baixe o instalador do Python em <https://www.python.org/downloads/windows/> (*Windows installer 64-bit*, versão 3.9+) e coloque-o dentro da **`#SISTEMA`**, ao lado do `INICIAR.bat`. Qualquer nome no formato `python-*.exe` funciona.
3. Crie subpastas e coloque os `.msi` dentro delas.

### 2. Execute

Dê um duplo clique em **`INSTALAR.bat`** (na raiz) e aceite a solicitação de administrador.

- Se o Python **já está instalado** → o menu abre direto.
- Se **não está** → o instalador da raiz é executado em modo silencioso e, ao terminar, o programa continua sozinho (não precisa reabrir nem reiniciar).

### 3. Escolha o que instalar

Veja a seção [Usando o menu](#-usando-o-menu).

### 4. Confira o resultado

Ao final é exibido um resumo com sucessos, falhas e aviso de reinicialização, se necessário.

---

## 🎛️ Usando o menu

Após a tela de apresentação (pressione **ENTER** para continuar), o menu exibe algo assim:

```
 Selecione o que deseja instalar:

  [1] Drivers                        (1 MSI)
  [2] Office                         (2 MSI)
  [3] Utilitarios                    (2 MSI)

  [A] INSTALAR TUDO                  (5 MSI)
  [R] Reescanear diretórios
  [0] Sair
```

| Entrada | Ação |
|---|---|
| `1`, `2`, `3`… | Instala todos os MSIs da pasta correspondente |
| `1,3` | Instala as pastas 1 e 3 (separadas por vírgula) |
| `A` | Instala **todos** os MSIs de **todas** as pastas |
| `R` | Reescaneia as pastas (útil depois de adicionar arquivos) |
| `0` | Sai do programa |

Antes de iniciar, o programa mostra o que será instalado e pede confirmação (`S/N`).

---

## ⚙️ Como funciona por dentro

### Fluxo geral

```
INICIAR.bat
   │
   ├─ É administrador?  ── não ──► relança com UAC
   │
   ├─ Python instalado? ── não ──► executa python-*.exe /quiet ...
   │                               e localiza o python.exe recém-instalado
   │
   └─► python instalador_msi.py
          │
          ├─ Tela de apresentação
          ├─ Escaneia subpastas e conta MSIs
          ├─ Menu (escolha do usuário)
          └─ Para cada MSI:  msiexec /i "arquivo.msi" /qn /norestart /L*v "log"
                             └─ lê o código de retorno → sucesso/falha → resumo
```

### Detecção do Python (INICIAR.bat)

O `.bat` procura o Python nesta ordem:

1. `py -3` (Python Launcher);
2. `python` no `PATH` (o atalho falso da Microsoft Store é ignorado);
3. Pastas padrão: `C:\Program Files\Python3*` e `%LocalAppData%\Programs\Python\Python3*`.

### Instalação do Python (quando necessário)

```
python-x.y.z-amd64.exe /quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0 Include_doc=0
```

Instala para todos os usuários, adiciona ao `PATH` e dispensa testes e documentação. Como o `PATH` da janela atual não é atualizado na hora, o `.bat` localiza o `python.exe` direto na pasta de instalação e segue com a execução.

### Comando de instalação dos MSIs

```
msiexec /i "caminho\arquivo.msi" /qn /norestart /L*v "logs\Pasta_Arquivo_AAAAMMDD_HHMMSS.log"
```

| Parâmetro | Função |
|---|---|
| `/i` | Instalar o pacote |
| `/qn` | Sem interface (silencioso) |
| `/norestart` | Nunca reinicia o computador automaticamente |
| `/L*v` | Log verboso completo |

---

## 🔢 Códigos de retorno

O `msiexec` devolve um código ao terminar. O programa interpreta assim:

### Considerados sucesso

| Código | Significado |
|:---:|---|
| `0` | Instalado com sucesso |
| `1641` | Instalado; reinicialização iniciada |
| `3010` | Instalado; **reinicialização necessária** |
| `1638` | Já existe outra versão instalada |

### Falhas comuns

| Código | Significado provável |
|:---:|---|
| `1602` | Instalação cancelada |
| `1603` | Erro fatal durante a instalação (veja o log) |
| `1618` | Outra instalação já está em andamento (ex.: Windows Update) |
| `1619` | Não foi possível abrir o pacote (arquivo corrompido ou caminho inválido) |
| `1620` | Pacote MSI inválido |
| `1625` | Instalação bloqueada por política do sistema |
| `1`, `2`, `3` | Erros de caminho/arquivo não encontrado |

Qualquer código fora da lista de sucesso é exibido como **FALHA (código N)** em vermelho.

---

## 🧾 Logs

Tudo fica na pasta `logs\`, criada automaticamente ao lado do programa:

| Arquivo | Conteúdo |
|---|---|
| `Pasta_Arquivo_AAAAMMDD_HHMMSS.log` | Log verboso do `msiexec` para **cada** MSI |
| `resumo_AAAAMMDD_HHMMSS.txt` | Lista de pacotes com código e status de **cada execução** |

Em caso de falha, abra o log do pacote e procure por `Return value 3` ou `error` para encontrar a causa.

---

## 🔧 Configurações

No topo do arquivo `instalador_msi.py`:

| Variável | Padrão | Descrição |
|---|:---:|---|
| `TITULO` | `"INSTALADOR AUTOMÁTICO MSI"` | Título exibido no cabeçalho |
| `VERSAO` | `"1.0"` | Versão exibida |
| `DESENVOLVEDOR` | `"Eduardo Falabella"` | Nome exibido no rodapé |
| `PASTAS_IGNORADAS` | `{"logs", "build", ...}` | Pastas que não aparecem no menu |
| `BUSCA_RECURSIVA` | `True` | Procura MSIs também em subpastas das subpastas |
| `MODO_SILENCIOSO` | `True` | `True` = `/qn` (sem interface); `False` = `/qb` (barra de progresso do Windows Installer) |
| `ANIMACAO` | `True` | `False` pula as animações da tela inicial |
| `CODIGOS_OK` | ver código | Códigos de retorno tratados como sucesso |

---

## 📶 Controlando a ordem de instalação

- Os MSIs de uma pasta são instalados em **ordem alfabética**.
- No modo **Instalar tudo**, as pastas seguem a ordem exibida no menu (também alfabética).

Para forçar uma ordem, use prefixos numéricos:

```
01_Runtimes\
02_Drivers\
03_Aplicativos\
```

ou, dentro de uma pasta: `01_vcredist.msi`, `02_app.msi`.

---

## 📦 Gerar um .exe (opcional)

Se quiser distribuir sem depender do Python na máquina:

```cmd
pip install pyinstaller
pyinstaller --onefile --uac-admin instalador_msi.py
```

O executável será criado em `dist\instalador_msi.exe`. Coloque-o na pasta raiz, junto às pastas dos MSIs. Ele detecta o próprio diretório automaticamente e **dispensa o `INICIAR.bat` e o instalador do Python**.

---

## 🩺 Solução de problemas

**O Python não foi encontrado e o instalador acusa erro**
Verifique se o arquivo `python-*.exe` está na **mesma pasta** do `INICIAR.bat`.

**O console mostra caracteres estranhos ou códigos como `←[38;5;45m`**
Você provavelmente está em um Windows antigo (anterior ao 10). Use o Windows 10/11 ou o Windows Terminal.

**Uma pasta não aparece no menu**
Confirme que há ao menos um arquivo `.msi` dentro dela (ou em subpastas, se `BUSCA_RECURSIVA = True`) e que o nome da pasta não está em `PASTAS_IGNORADAS`. Use `R` para reescanear.

**Erro `1618`**
Outra instalação está em curso (frequentemente o Windows Update). Aguarde terminar e tente novamente.

**Erro `1603`**
Falha genérica do pacote. Abra o log correspondente em `logs\` para ver o motivo (permissão, dependência ausente, conflito de versão).
Se o log mostrar `Adding REMOVE property. Its value is 'ALL'` e `InstallInitialize. Return value 3` logo no começo, é o defeito dos MSI gerados pelas versões **≤ 1.4** (Feature sem Component). Na v1.5 isso é corrigido e reparado automaticamente (veja *Reparo automático* abaixo).

**Windows SmartScreen bloqueia o `.bat`**
Clique em *Mais informações → Executar assim mesmo*, ou desbloqueie o arquivo em *Propriedades → Desbloquear*.

**Preciso passar parâmetros ao MSI (ex.: `INSTALLDIR`, chave de licença, `.mst`)**
O programa usa os parâmetros padrão. Para casos específicos, edite a função `instalar_msi()` em `instalador_msi.py` e acrescente as propriedades na lista `cmd`.

---

## ⚠️ Limitações conhecidas

- Instala arquivos **`.msi`**; arquivos `.exe` são convertidos antes para MSI (veja *Conversão EXE → MSI*). `.msix` e `.msu` não são suportados.
- Não aplica parâmetros personalizados por pacote (veja a dica acima).
- Não há desinstalação nem reparo de pacotes.
- Funciona apenas no **Windows**.
- Se um pacote falhar, o programa **continua** com os próximos e registra a falha no resumo.

---

<p align="center"><sub>Desenvolvido por <b>Eduardo Falabella</b></sub></p>

---

## 🤖 Modo automático (v1.1)

Instala **sem menu, sem ENTER e sem confirmação**, mostrando o progresso e gravando um status ao vivo.

### Como usar

| Quero... | Faça |
|---|---|
| Instalar tudo | Duplo clique em `INSTALAR.bat` |
| Abrir o menu interativo | `INSTALAR.bat --menu` |
| Só conferir (simula as conversões, não altera nada) | `INSTALAR.bat --listar` |
| Instalar só algumas pastas | `INSTALAR.bat --pastas Office,Drivers` (sem aspas; nomes de pasta sem espaços) |
| Rodar em tarefa agendada / GPO / SCCM | `INSTALAR.bat --sem-pausa` |
| Acompanhar de outra janela/PC | `INSTALAR.bat --status` (atualiza a cada 3 s) |

> **Importante:** sem `--sem-pausa` o `.bat` espera uma tecla no final (para você ler o resultado). Em execução sem ninguém logado isso travaria — **use sempre `--sem-pausa` em automações**.

Ao abrir sem ser administrador, o `.bat` pede UAC e **abre uma nova janela** — é nela que o progresso aparece.

### Parâmetros do `instalador_msi.py`

| Parâmetro | Função |
|---|---|
| `--auto` | Modo automático (sem interação nem animação) |
| `--pastas A,B` | Instala apenas as pastas indicadas (padrão: todas) |
| `--listar` | Lista pastas/MSIs encontrados e sai |
| `--raiz CAMINHO` | Pasta que contém as subpastas de MSI (padrão: pasta pai de `#SISTEMA`) |
| `--sem-converter` | Não converte `.exe` (só instala os `.msi` existentes) |
| `--manter-exe` | Converte, mas **não apaga** os `.exe` |
| `--sem-pausa` | Usado pelo `.bat`: não espera tecla no final |
| `--sem-cores` | Remove códigos ANSI (automático se a saída for redirecionada) |

### Status ao vivo

Durante a execução o programa mostra, com hora em cada linha:

```
20:49:02 [1/3] Office › app.msi
        20:49:17 ... ainda instalando (15s) | etapa: InstallFiles
        20:49:19 [ OK ] Instalado com sucesso (17s)
```

e mantém `logs\status.txt` atualizado (estado, progresso, pacote atual, etapa do MSI, concluídos). Veja com `INSTALAR.bat --status` ou abra o arquivo.

### Códigos de saída

| Código | Significado |
|:---:|---|
| `0` | Tudo instalado |
| `3010` | Tudo instalado, **reinício necessário** |
| `1` | Pelo menos um MSI falhou (veja `logs\`) |
| `2` | Pasta informada em `--pastas` não existe / sem MSI |
| `4` | Nenhum MSI encontrado |
| `6` | Instalou, mas ficou algum `.exe` sem converter (veja `status.txt`) |
| `5` | Sem administrador (no modo automático o `.py` não usa UAC; o `.bat` sim) |

### Erro 1618

Se o `msiexec` devolver `1618` (outra instalação em andamento, como o Windows Update), o programa espera 30 s e tenta de novo, até 5 vezes (`TENTATIVAS_1618` / `ESPERA_1618` no topo do `.py`).

### Tarefa agendada (sem ninguém logado)

Conta `SYSTEM`, *Executar com privilégios mais altos*, ação:

```
cmd.exe /c ""C:\Caminho\Raiz\INSTALAR.bat" --sem-pausa > "C:\Caminho\Raiz\#SISTEMA\logs\auto.txt" 2>&1"
```

---

## ✅ Validação dos pacotes (v2.2)

O fluxo agora tem **três etapas visíveis** (indicador no topo da tela): **① Conversão › ② Validação › ③ Instalação**.

1. **Prompt de comando visível** – o `INICIAR.bat` mostra `[1/3] administrador`, `[2/3] Python` e `[3/3] iniciando`. Se o Python não estiver instalado, `instalar_python.ps1` instala com cronômetro e a etapa atual do instalador ao vivo; quando termina, a tela abre e a janela fecha sozinha.
2. **Conversão na tela** – cada `.exe` convertido é conferido contra o original (tamanho + SHA-256) antes de o `.exe` ser apagado. Qualquer dúvida (erro **ou** aviso) mantém o `.exe`.
3. **Validação de TODOS os `.msi`** – um por um, com resultado ao vivo. Nada é instalado antes de terminar.
4. **Seleção** – cada pacote mostra `✓ VÁLIDO`, `⚠ AVISO` ou `✕ BLOQUEADO` com o **motivo**. Bloqueados não têm caixa de seleção; os válidos já vêm marcados (`PRESELECIONAR_VALIDOS`).
5. **Instalação** – confere de novo na hora (se o arquivo mudou desde a validação) e **nunca executa um pacote reprovado** (registrado como código 1620 + motivo).

### O que é conferido

| Conferência | Reprova (ERRO) quando… |
|---|---|
| Arquivo | vazio, ilegível ou sem cabeçalho de MSI (cópia interrompida) |
| Banco MSI | o Windows Installer não consegue abrir (arquivo corrompido/truncado) |
| Tabelas | faltam Property, InstallExecuteSequence (e, nos MSI gerados aqui, Component/Feature/FeatureComponents/Directory/Binary/CustomAction) |
| Identidade | ProductCode ausente/inválido, ProductVersion ausente |
| Componentes | nenhum Component ou Feature sem componentes (**causa do erro 1603**), referências quebradas, componente 64 bits em Windows 32 bits |
| Sequência | InstallInitialize/InstallFinalize ausentes ou fora de ordem |
| Fontes (.cab) | `.cab` externo não está ao lado do `.msi`; `.cab` embutido ausente ou truncado |
| Payload (MSI gerados aqui) | `.exe` embutido vazio, sem cabeçalho PE, **SHA-256 diferente** do gravado na conversão/do `.exe` original, tamanho divergente |
| Custom Action | `RunInstall` ausente, sem argumentos silenciosos ou fora da transação |
| Entre pacotes | (AVISO) mesmo ProductCode ou mesmo UpgradeCode com versões diferentes – o 2º seria ignorado com código 1638, que conta como "sucesso" |

Em **pacotes de terceiros**, inconsistências de catálogo viram **AVISO** (não bloqueiam); só há bloqueio com evidência de que vai falhar. Falha do próprio validador também vira AVISO – nunca bloqueia por engano.

### Parâmetros e configurações

| Parâmetro | Efeito |
|---|---|
| `--validacao-rapida` | só estrutura e tamanhos (não lê cada instalador por inteiro) |
| `--sem-validar` | pula a validação (não recomendado) |
| `--ignorar-bloqueio` | valida e mostra o relatório, mas instala mesmo os reprovados (emergência) |

Constantes em `instalador_msi.py`: `VALIDAR`, `VALIDACAO_COMPLETA`, `BLOQUEAR_INVALIDOS`, `PRESELECIONAR_VALIDOS`. Relatório completo em `logs\validacao_*.txt` e seção "Validação dos pacotes" no `status.txt`.

**Tempo:** a validação completa lê cada `.msi` uma vez; em pen drive, é proporcional ao tamanho total dos instaladores.
**Limitações:** arquivos soltos de MSI não comprimido não são verificados um a um; condições de lançamento (LaunchCondition) não são avaliadas; MSI gerados por versões anteriores não têm hash gravado (confere-se tamanho e estrutura PE).

## 🔄 Conversão EXE → MSI (v1.3)

A cada execução, **antes de instalar**, o programa varre as pastas de instaladores (nunca a `#SISTEMA` nem pastas `#`/`.`), converte cada `.exe` em um `.msi` de mesmo nome na mesma pasta, **verifica** o resultado e então **apaga o `.exe`**. Em seguida instala tudo, inclusive os MSI novos.

### O que é a "conversão"

Não existe conversão real de EXE para MSI. O programa cria um MSI que **contém o .exe** e o executa em modo silencioso na instalação (WiX 3: `candle` + `light`, na pasta `wix3`, sem precisar de .NET SDK nem de internet). O MSI **não conhece os arquivos** que o .exe instala, então não desinstala o programa.

### Como ele descobre os argumentos silenciosos

1. Se existir `nome.exe.args` ao lado do .exe, usa a **1ª linha** desse arquivo (ex.: `/silent /noreboot`). Escrever `IGNORAR` faz o programa pular esse .exe.
2. Senão, detecta o tipo pelo conteúdo do arquivo:

| Tipo detectado | Argumentos usados |
|---|---|
| Inno Setup | `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-` |
| NSIS | `/S` |
| WiX Burn (vários redistribuíveis Microsoft) | `/quiet /norestart` |
| Advanced Installer | `/exenoui /qn /norestart` |
| InstallShield | `/s /v"/qn REBOOT=ReallySuppress"` |

3. Tipo desconhecido: **(v2.1)** converte com argumentos genéricos e **mantém o `.exe`**; na instalação a escada de argumentos + vigia de tela tentam achar o que funciona (veja a seção v2.1).

### Quando o .exe é apagado

Somente se o MSI foi gerado **e** passou na verificação (arquivo MSI válido, tamanho coerente, tabela `Binary` contendo o .exe **e ao menos um `Component` ligado à Feature**, tudo conferido pelo Windows Installer). Qualquer falha mantém o .exe e remove o MSI incompleto. Use `--manter-exe` para nunca apagar.

### O que é pulado (e o .exe fica intacto)

- Desinstaladores (`unins*.exe`, `uninstall*.exe`);
- .exe cujo tipo é desconhecido e sem `.args`;
- Pasta com arquivos `.cab` (parece bootstrapper de um MSI já existente — converter duplicaria a instalação);
- Já existe um `.msi` com o mesmo nome do `.exe`.

### Cuidados

- **Teste antes:** `INSTALAR.bat --listar` mostra o que seria convertido, com tipo e argumentos, sem alterar nada. Teste um instalador de cada tipo antes de rodar em tudo — se os argumentos estiverem errados, o MSI é gerado, o `.exe` é apagado e a instalação silenciosa falha ou trava.
- **Mantenha uma cópia dos .exe originais** fora desta pasta.
- Códigos de retorno do .exe diferentes de 0 (inclusive 3010) fazem o MSI falhar com erro 1603.
- Arquivos muito grandes (acima de ~2 GB) não cabem em um MSI.
- Se o Windows bloquear os arquivos de `wix3` (extraídos de um zip baixado), rode no PowerShell: `Get-ChildItem "#SISTEMA\wix3" | Unblock-File`.
- Cada MSI criado aparece como um programa extra em *Aplicativos instalados*, com o nome do .exe.
- Logs de cada conversão: `logs\conv_<nome>_<data>.log`; o andamento aparece em `status.txt` na seção *Conversões EXE → MSI*.

---

## 🩹 Correção do erro 1603 e reparo automático (v1.5)

**Causa:** até a v1.4 o `.wxs` gerado tinha uma `<Feature>` sem nenhum `<Component>`. O Windows Installer trata esse pacote como vazio, injeta `REMOVE=ALL` e aborta em `InstallInitialize` (erro 1603). O aviso `LGHT1079 ... media1.cab does not contain any files` no log de conversão já apontava isso. Além disso, a verificação só olhava a tabela `Binary`, então aprovava o MSI defeituoso e **apagava o .exe**.

**O que mudou:**
- o MSI agora inclui um `Component` (apenas uma chave de registro em `HKLM\SOFTWARE\InstaladorAutomaticoMSI\<UpgradeCode>`) ligado à Feature `Main`;
- `verificar_msi` passou a exigir `Component` + `FeatureComponents`; sem isso o .exe **não** é apagado.

**Reparo automático:** ao iniciar, o programa procura MSIs gerados por ele mesmo (Fabricante `Instalador Automatico`, com `Binary\SetupExe`) que não tenham `Component`. Para cada um: extrai o .exe de dentro do MSI, reconstrói o pacote, verifica e só então substitui o MSI antigo (se algo falhar, o antigo é mantido). Logs: `logs\reparo_<nome>_<data>.log`. Use `--sem-converter` para pular. Os argumentos silenciosos vêm de, em ordem: `<nome>.exe.args` ao lado do MSI → os já gravados no MSI → detecção automática.

**Desinstalação:** desinstalar o MSI gerado remove só a chave de registro marcadora, **não** o programa instalado pelo .exe; desinstale pelo próprio programa.

---

## 🔒 Um único arquivo para executar (v1.4)

Na raiz fica só o **`INSTALAR.bat`**; tudo o mais está em `#SISTEMA`.

- O `INICIAR.bat` **recusa execução direta** (mostra um aviso e sai); ele só roda quando chamado pelo `INSTALAR.bat`.
- `INSTALAR.bat` sem parâmetros = modo automático. Outros modos: `--menu`, `--listar`, `--status`, `--pastas`, `--sem-pausa`, `--manter-exe`.
- Para esconder a pasta de quem navega pela raiz (opcional): `attrib +h +s "#SISTEMA"` (para desfazer: `attrib -h -s "#SISTEMA"`). É só visual: quem digitar o caminho ainda acessa.
- Para impedir de verdade, use permissões NTFS/compartilhamento: usuários comuns só com **leitura e execução** na raiz, e **modificação** apenas para a equipe de TI.


---

## 🛡️ v2.1 — Instalação 100% silenciosa e à prova de telas

**Objetivo:** a única janela que o técnico vê é a tela gráfica do programa. Nenhum assistente de instalador, console, PowerShell ou aviso de segurança deve aparecer nem exigir clique.

### O que causava as telas e os erros (e o que mudou)

| Causa | Correção na v2.1 |
|---|---|
| Argumento silencioso errado/desconhecido → o instalador abria o assistente e ficava esperando clique | **Escada de argumentos**: se uma tentativa abre tela e trava (ou rejeita o argumento), ela é encerrada e o próximo argumento é tentado (até `MAX_TENTATIVAS_ARGS`). Há escada por tipo (Inno, NSIS, Burn, Advanced Installer, InstallShield, Qt IFW) e uma lista genérica para tipo desconhecido |
| Instalador que relança um processo filho e sai com código 0 → o programa achava que terminou e seguia (colisão, 1618, telas) | O instalador roda dentro de um **Job Object**: só termina quando o processo **e todos os filhos** terminam. Entre um pacote e outro espera o Windows Installer ficar livre (mutex `_MSIExecute`) |
| Janela que o instalador criava mesmo em modo silencioso | Toda janela criada pela árvore do instalador é **ocultada na hora** e registrada (título/classe) no log e na tela |
| Instalador parado numa tela esperando clique (travava horas) | **Vigia**: tela aberta + zero atividade de CPU/disco por `UI_OCIOSO_S` (60 s) → encerra a árvore, registra a janela e tenta o próximo argumento. Se todas falharem: `FALHA (código 1602 - abriu tela e esperou interação)` com o título da janela no log |
| Tipo desconhecido era **descartado** na conversão | Agora converte com argumentos genéricos e **mantém o `.exe`** (nunca apaga um tipo desconhecido) |
| Console/PowerShell piscando (`taskkill`, `candle`, `light`, `powershell`) | Todo subprocesso nasce oculto; a verificação do MSI não usa mais PowerShell (lê direto via `msi.dll`) |
| Console preto do `.bat` aberto durante tudo | No modo gráfico o `.bat` fica oculto e abre a tela com `pythonw.exe`. Se faltar `pythonw`/`tkinter`, cai no console visível |
| Conversão rodava **antes** de a tela abrir (sem nada na tela) | A tela abre na hora e mostra "Preparando os pacotes…" com o andamento da conversão |
| "Abrir arquivo – Aviso de segurança" em arquivos baixados | `Unblock-File` em `#SISTEMA` + `SEE_MASK_NOZONECHECKS=1` nos processos filhos |
| Python não instalava por 1618 (Windows Update) | `INICIAR.bat` espera 30 s e tenta de novo (até 5×); log em `logs\python_instalacao.log` |
| Verificação do MSI só olhava a estrutura | Agora também confere **tamanho exato** e **SHA‑256** do `.exe` embutido (até `VERIFICAR_HASH_ATE_MB`) antes de apagar o original; avisa se o `.exe` passa de ~2 GB |

> Única janela do Windows que ainda pode aparecer: o **UAC** (pedido de administrador). Para eliminá‑lo, execute o `INSTALAR.bat` já como administrador / tarefa agendada com privilégios mais altos.

### Arquivo `.args` agora aceita VÁRIAS linhas

```
nome_do_instalador.exe.args
-------------------------------
# comentário (linhas com # ou ; são ignoradas)
/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
/SILENT /SUPPRESSMSGBOXES /NORESTART /SP-
```

Cada linha é **uma tentativa**, na ordem. Se o arquivo existir, **só** as linhas dele são usadas (você assume o controle). `IGNORAR` pula o `.exe`. O `.args` agora **não é mais apagado** após a conversão (a instalação lê as tentativas dele).

Para MSI de verdade (não gerados pelo programa): `<nome>.mst` ao lado do MSI vira `TRANSFORMS=`, e `<nome>.msi.args` (1ª linha) acrescenta propriedades, ex.: `ACCEPTEULA=1`.

### Como descobrir qual instalador abre tela

1. Rode `INSTALAR.bat --ver-janelas`: **não** oculta nem encerra nada, só registra no log o **título e a classe** de cada janela que o instalador abrir.
2. Abra `logs\<Pasta>_<nome>_<data>.log` — procure `Janela detectada` e `Tentativa n/N` (mostra o comando exato usado e o código de saída).
3. Descobriu o argumento certo? Grave em `<nome>.exe.args`.

### Novas configurações (topo do `instalador_msi.py`)

| Variável | Padrão | Função |
|---|:---:|---|
| `OCULTAR_JANELAS` | `True` | Oculta qualquer janela criada pelo instalador |
| `VIGIAR_UI` | `True` | Encerra e tenta o próximo argumento se a tela travar |
| `UI_OCIOSO_S` | `60` | Segundos de "tela aberta sem atividade" para considerar travado (aumente para instaladores web que baixam muito com pouca CPU/disco) |
| `MAX_TENTATIVAS_ARGS` | `5` | Tentativas de argumentos por instalador |
| `POS_OCIOSO_S` / `POS_MAX_S` | `45` / `600` | Espera pelos processos filhos depois que o principal sai |
| `ESPERA_MSI_LIVRE_S` | `900` | Espera máxima pelo Windows Installer entre pacotes |
| `VERIFICAR_HASH_ATE_MB` | `300` | Confere SHA‑256 do `.exe` dentro do MSI até este tamanho |

### Limites que continuam valendo

- Se o instalador **não tem** modo silencioso (ou exige chave/aceite próprio), nenhuma escada resolve: use `.args`/`.mst` específicos ou deixe o pacote fora do lote.
- Se o instalador mostra uma tela **de verdade ocupada** (CPU/disco ativos), ela é apenas ocultada, não encerrada.
- Erros fatais da tela gráfica (sem console) aparecem numa caixa de mensagem e ficam em `logs\erro_fatal.txt`; a saída de texto vai para `logs\console.log`.
- `INSTALAR.bat` continua abrindo um console por uma fração de segundo antes do UAC (limitação de qualquer `.bat`; para evitar, use um atalho com "Executar: Minimizado" ou um `.exe` lançador).

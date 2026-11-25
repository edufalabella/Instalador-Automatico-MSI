# 🛠️ Instalador Automático (MSI e EXE)

Ferramenta para **instalar pacotes `.msi` e `.exe` em lote** no Windows, com **tela gráfica de seleção** (v2.0; menu de texto com `--console`), instalação silenciosa, logs detalhados e instalação automática do Python caso ele não exista na máquina.

> Desenvolvido por **Eduardo Falabella**

> **v3.1 — portáteis, mídias e validação rápida.** Veja [Novidades da v3.1](#-novidades-da-v31).
>
> **v3.0 — sem conversão EXE → MSI.** Os `.exe` agora são instalados **diretamente**, em modo
> silencioso (sem cliques). Se o instalador não aceitar nenhum argumento silencioso, ele é aberto
> normalmente para você **concluir com cliques**. A pasta `wix3` não é mais necessária. Veja a seção
> [Instalação direta de .exe (v3.0)](#-instalação-direta-de-exe-v30).

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
15. [Instalação direta de .exe (v3.0)](#-instalação-direta-de-exe-v30)

---

## 📌 Visão geral

Em vez de abrir cada instalador manualmente, você organiza os arquivos `.msi` e `.exe` em **subpastas** ao lado do programa. Ao executar, o software:

1. Garante que está rodando como **administrador**;
2. Verifica se o **Python** está instalado e, se não estiver, instala a partir do instalador que você deixou na pasta;
3. Exibe uma **tela de apresentação** e escaneia as subpastas;
4. Monta um **menu** com cada pasta encontrada;
5. Instala os pacotes da pasta escolhida (ou **todos**) de forma silenciosa (`.msi` via `msiexec`, `.exe` executado direto), mostrando progresso e um resumo final.

Ideal para **preparação de computadores**, formatações, suporte técnico e padronização de softwares em empresas.

---

## ✨ Funcionalidades

| Recurso | Descrição |
|---|---|
| 📂 Menu dinâmico | Cada subpasta com `.msi` ou `.exe` vira uma opção automaticamente |
| ⚡ Instalar tudo | Uma opção para instalar todos os pacotes de todas as pastas |
| 🔢 Seleção múltipla | Escolha várias pastas de uma vez, ex.: `1,3` |
| 🤫 Instalação silenciosa | `.msi`: `msiexec /qn /norestart`; `.exe`: argumentos silenciosos detectados pelo tipo do instalador |
| 🖱️ Plano B com cliques | Se o `.exe` não instalar em silêncio, abre o instalador normal para você concluir |
| 🐍 Bootstrap do Python | Instala o Python sozinho se ele não existir na máquina |
| 🛡️ Auto-elevação | Pede permissão de administrador (UAC) automaticamente |
| 📊 Progresso visual | Barra de progresso geral e indicador de atividade por pacote |
| 🧾 Logs completos | Um log detalhado por pacote e um resumo por execução |
| 🔁 Reescanear | Adicione pastas e atualize o menu sem fechar o programa |
| 🎨 Interface colorida | Tela de apresentação, cores e rodapé com o nome do desenvolvedor |

---

## 💻 Requisitos

- **Windows 10 ou 11** (as cores ANSI do console precisam dessas versões)
- **Permissão de administrador** na máquina
- **Instalador do Python 3.9 ou superior** (64-bit) na pasta do projeto, caso o Python ainda não esteja instalado
- Arquivos **`.msi`** e/ou **`.exe`** a serem instalados

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
- O **nome das subpastas** é o que aparece no menu; só aparecem as que **contêm pelo menos um `.msi` ou `.exe`**.

---

## 🚀 Passo a passo de uso

### 1. Prepare a pasta

1. Copie a pasta `InstaladorMSI` para o computador (ou para um pendrive/rede).
2. Baixe o instalador do Python em <https://www.python.org/downloads/windows/> (*Windows installer 64-bit*, versão 3.9+) e coloque-o dentro da **`#SISTEMA`**, ao lado do `INICIAR.bat`. Qualquer nome no formato `python-*.exe` funciona.
3. Crie subpastas e coloque os `.msi` e `.exe` dentro delas.

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
| `S` | Abre a lista de **softwares um a um** (numeração única; aceita `1,3` e intervalos `2-5`) |
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
          ├─ Escaneia subpastas (.msi e .exe) e valida cada pacote
          ├─ Tela de seleção (escolha do usuário)
          ├─ Para cada .msi:  msiexec /i "arquivo.msi" /qn /norestart /L*v "log"
          ├─ Para cada .exe:  "arquivo.exe" <argumentos silenciosos>  (escada de tentativas)
          │                   └─ nada funcionou? abre o instalador normal (com cliques)
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

- Instala arquivos **`.msi`** e **`.exe`** (o `.exe` roda direto, sem conversão). `.msix` e `.msu` não são suportados.
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
| Só conferir (lista os pacotes e os argumentos silenciosos de cada `.exe`, não instala nada) | `INSTALAR.bat --listar` |
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
| `--sem-exe` | Não instala `.exe` (só os `.msi`) |
| `--interativo` | No modo automático: se o silencioso de um `.exe` falhar, abre o instalador para clicar |
| `--sem-interativo` | Nunca abre a janela do instalador (falha se o silencioso não funcionar) |
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
| `5` | Sem administrador (no modo automático o `.py` não usa UAC; o `.bat` sim) |

### Erro 1618

Se o `msiexec` devolver `1618` (outra instalação em andamento, como o Windows Update), o programa espera 30 s e tenta de novo, até 5 vezes (`TENTATIVAS_1618` / `ESPERA_1618` no topo do `.py`).

### Tarefa agendada (sem ninguém logado)

Conta `SYSTEM`, *Executar com privilégios mais altos*, ação:

```
cmd.exe /c ""C:\Caminho\Raiz\INSTALAR.bat" --sem-pausa > "C:\Caminho\Raiz\#SISTEMA\logs\auto.txt" 2>&1"
```

---

## 🔒 Um único arquivo para executar (v1.4)

Na raiz fica só o **`INSTALAR.bat`**; tudo o mais está em `#SISTEMA`.

- O `INICIAR.bat` **recusa execução direta** (mostra um aviso e sai); ele só roda quando chamado pelo `INSTALAR.bat`.
- `INSTALAR.bat` sem parâmetros = **modo interativo**: valida os pacotes e, em seguida, abre a **tela de seleção** (pastas ou software por software). O modo automático (sem perguntas) exige `--auto` e também é ativado por `--sem-pausa`, `--pastas` ou `--listar` — **tarefas agendadas/GPO/SCCM que chamavam `INSTALAR.bat` sem parâmetros devem passar a usar `--auto --sem-pausa`**. Outros modos: `--listar`, `--status`.
- Para esconder a pasta de quem navega pela raiz (opcional): `attrib +h +s "#SISTEMA"` (para desfazer: `attrib -h -s "#SISTEMA"`). É só visual: quem digitar o caminho ainda acessa.
- Para impedir de verdade, use permissões NTFS/compartilhamento: usuários comuns só com **leitura e execução** na raiz, e **modificação** apenas para a equipe de TI.


---

## 🛡️ v2.1 — Instalação 100% silenciosa e à prova de telas

**Objetivo:** a única janela que o técnico vê é a tela gráfica do programa (exceto no plano B com cliques da v3.0). Nenhum assistente de instalador, console, PowerShell ou aviso de segurança deve aparecer nem exigir clique.

### O que causava as telas e os erros (e o que mudou)

| Causa | Correção na v2.1 |
|---|---|
| Argumento silencioso errado/desconhecido → o instalador abria o assistente e ficava esperando clique | **Escada de argumentos**: se uma tentativa abre tela e trava (ou rejeita o argumento), ela é encerrada e o próximo argumento é tentado (até `MAX_TENTATIVAS_ARGS`). Há escada por tipo (Inno, NSIS, Burn, Advanced Installer, InstallShield, Qt IFW) e uma lista genérica para tipo desconhecido |
| Instalador que relança um processo filho e sai com código 0 → o programa achava que terminou e seguia (colisão, 1618, telas) | O instalador roda dentro de um **Job Object**: só termina quando o processo **e todos os filhos** terminam. Entre um pacote e outro espera o Windows Installer ficar livre (mutex `_MSIExecute`) |
| Janela que o instalador criava mesmo em modo silencioso | Toda janela criada pela árvore do instalador é **ocultada na hora** e registrada (título/classe) no log e na tela |
| Instalador parado numa tela esperando clique (travava horas) | **Vigia**: tela aberta + zero atividade de CPU/disco por `UI_OCIOSO_S` (60 s) → encerra a árvore, registra a janela e tenta o próximo argumento. Se todas falharem: `FALHA (código 1602 - abriu tela e esperou interação)` com o título da janela no log |
| Console/PowerShell piscando (`taskkill`, `powershell`) | Todo subprocesso nasce oculto; a verificação do MSI não usa mais PowerShell (lê direto via `msi.dll`) |
| Console preto do `.bat` aberto durante tudo | No modo gráfico o `.bat` fica oculto e abre a tela com `pythonw.exe`. Se faltar `pythonw`/`tkinter`, cai no console visível |
| "Abrir arquivo – Aviso de segurança" em arquivos baixados | `Unblock-File` em `#SISTEMA` + `SEE_MASK_NOZONECHECKS=1` nos processos filhos |
| Python não instalava por 1618 (Windows Update) | `INICIAR.bat` espera 30 s e tenta de novo (até 5×); log em `logs\python_instalacao.log` |

> Única janela do Windows que ainda pode aparecer: o **UAC** (pedido de administrador). Para eliminá‑lo, execute o `INSTALAR.bat` já como administrador / tarefa agendada com privilégios mais altos.

### Arquivo `.args` agora aceita VÁRIAS linhas

```
nome_do_instalador.exe.args
-------------------------------
# comentário (linhas com # ou ; são ignoradas)
/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
/SILENT /SUPPRESSMSGBOXES /NORESTART /SP-
```

Cada linha é **uma tentativa**, na ordem. Se o arquivo existir, **só** as linhas dele são usadas (você assume o controle). `IGNORAR` esconde o `.exe` da lista. `INTERATIVO` abre o instalador normal (com cliques) — sozinha, ou como última linha depois das tentativas silenciosas.

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

### Limites que continuam valendo

- Se o instalador **não tem** modo silencioso (ou exige chave/aceite próprio), nenhuma escada resolve: use `.args`/`.mst` específicos ou deixe o pacote fora do lote.
- Se o instalador mostra uma tela **de verdade ocupada** (CPU/disco ativos), ela é apenas ocultada, não encerrada.
- Erros fatais da tela gráfica (sem console) aparecem numa caixa de mensagem e ficam em `logs\erro_fatal.txt`; a saída de texto vai para `logs\console.log`.
- `INSTALAR.bat` continua abrindo um console por uma fração de segundo antes do UAC (limitação de qualquer `.bat`; para evitar, use um atalho com "Executar: Minimizado" ou um `.exe` lançador).

## 🧯 Se a tela não abrir (v2.2.1)

O `INICIAR.bat` agora testa se o Python consegue carregar o programa **antes** de abrir a tela. Se não conseguir, o erro aparece no prompt de comando e fica salvo em `logs\inicializacao.log` (envie esse arquivo para suporte). Se o Python não puder ser instalado com a barra de progresso (política de execução de scripts, por exemplo), o `.bat` tenta automaticamente o modo direto. Logs: `logs\python_instalacao.log` e `logs\python_instalacao_direto.log`.

---

## 🚀 Instalação direta de .exe (v3.0)

A conversão EXE → MSI (WiX) foi **removida**: dava erro com frequência (1603, 1618, telas presas) porque
um instalador que usa o Windows Installer não pode rodar dentro de outro `msiexec`. Agora:

| Pacote | Como é instalado |
|---|---|
| `.msi` | `msiexec /i ... /qn /norestart` (igual antes) |
| `.exe` | executado **direto**, na pasta dele, como o administrador atual, oculto e com vigia de tela |
| `.msi` antigo gerado pela conversão (v2.2 ou anterior) | o `.exe` de dentro é extraído e executado direto (continua funcionando) |

Fluxo na tela: **① Validação › ② Instalação**. Nada é convertido, nada é apagado.

### Sem cliques (padrão)
1. O tipo do instalador é detectado pelo conteúdo do `.exe` (Inno Setup, NSIS, WiX Burn, Advanced Installer,
   InstallShield) e o argumento silencioso certo é usado. A validação mostra o tipo e o argumento de cada `.exe`.
2. Se o instalador recusar ou abrir uma tela e ficar parado, o próximo argumento é tentado (até `MAX_TENTATIVAS_ARGS`).

### Com cliques (plano B)
Se **nenhum** argumento silencioso funcionar, o instalador é aberto **normalmente** e o programa espera você
concluir (a tela mostra "Conclua na janela do instalador"). Isso é controlado pela caixa
*"Se um .exe não instalar em silêncio, abrir o instalador para eu concluir com cliques"* (marcada por padrão).
No modo `--auto` fica desligado (não há ninguém para clicar), a menos que se use `--interativo`.

Para forçar um `.exe` a abrir sempre com cliques, crie `nome.exe.args` com a linha `INTERATIVO`.

### O que aparece na lista
- todos os `.msi` e `.exe` das pastas (inclusive subpastas);
- **não** aparecem: desinstaladores (`unins*.exe`, `uninstall*.exe`), `.exe` com `IGNORAR` no `.args`,
  `.exe` com um `.msi` de mesmo nome ao lado, e `.exe` em pasta com arquivos `.cab` (é o `setup.exe` de um
  `.msi` — instalaria duas vezes). Para incluir um desses, crie `nome.exe.args` com os argumentos.
- Se uma pasta tem vários `.exe` auxiliares (redistribuíveis, ferramentas), marque só o principal na tela,
  ou crie `auxiliar.exe.args` com `IGNORAR`.

### Validação do .exe
Antes de instalar, cada `.exe` é conferido: legível, não vazio, executável do Windows (MZ/PE) e **não truncado**
(cópia incompleta do pen drive/rede). `.exe` reprovado aparece como **BLOQUEADO** com o motivo e não é executado.

### Parâmetros novos/alterados
| Parâmetro | Efeito |
|---|---|
| `--sem-exe` | só instala `.msi` |
| `--interativo` | no `--auto`, permite o plano B com cliques |
| `--sem-interativo` | nunca abre a janela do instalador |
| `--sem-converter`, `--manter-exe` | aceitos por compatibilidade, **não fazem nada** |

Constantes no topo de `instalador_msi.py`: `INSTALAR_EXE`, `FALLBACK_INTERATIVO`, `PULAR_EXE_COM_CAB`,
`EXE_IGNORAR_PREFIXOS`.

### Atualizando de uma versão anterior
- Apague a pasta `#SISTEMA\wix3` (não é mais usada).
- Os `.msi` que a conversão antiga criou continuam funcionando. Se o `.exe` original estiver ao lado,
  o `.exe` é usado e o `.msi` antigo é escondido da lista (você pode apagá-lo).
- Tarefas agendadas com `--sem-converter`/`--manter-exe` continuam rodando sem alteração.

---

## ⚡ Novidades da v3.1

Correções feitas a partir dos logs de uso real (526 pacotes em `APT TI`, `TECNICO ELETRICA`, `TECNICO MECANICA`).

### 1. Programas PORTÁTEIS são identificados (nada é executado)
Cada `.exe` é analisado **sem executar**: cabeçalho PE, dados anexados ao final, informações de versão,
manifesto e assinaturas de ~15 tipos de instalador (WiX Burn, Inno Setup, NSIS, InstallShield, Advanced
Installer, InstallAware, Wise, Setup Factory, Squirrel, Qt IFW, IExpress, .NET Framework, SFX do WinRAR/7-Zip).

| Selo na tela | O que é | O que o programa faz |
|---|---|---|
| `EXE` | instalador | instala em silêncio (argumento certo para o tipo detectado) |
| `PORTÁTIL` | o próprio programa (ex.: ZoomIt, CADe_SIMU, PC_SIMU) | **copia** a pasta para `C:\Portateis\<pasta>` e cria atalho na Área de Trabalho pública e no Menu Iniciar › Portáteis |
| `MENU` | menu de CD/pen drive (autorun.exe) | abre a janela para você clicar (não vem marcado) |

- Ferramentas de linha de comando portáteis (`7za.exe`, `ffmpeg.exe`, `createdump.exe`) e desinstaladores
  (`unins*.exe`, `Unwise.exe`) **não aparecem** na lista.
- Se um portátil escapar da detecção e for executado, o vigia de **processo parado** o encerra em
  `PARADO_S` (180 s) sem janela e sem atividade. Antes ele travava a instalação por até 2 horas (caso do ZoomIt).
- Para não copiar portáteis: `PORTATEIS_ACAO = "ignorar"`. Pasta de destino: `PASTA_PORTATEIS`.
- Errou a classificação? `nome.exe.args` com os argumentos (ou `INTERATIVO`) força tratar como instalador.

### 2. Mídias de instalação mostram só o Setup
Uma subpasta com `Setup.exe`, `Install.exe`, `Installer.exe` ou `Start.exe` (AutoCAD, Inventor, DWG TrueView,
TIA Portal, FluidSim, MotoSim...) mostra **só esse lançador**; os componentes internos (`3rdParty`, `VC_redist`,
`.msi` das partes, `senddmp.exe`, `KillProcess.exe`...) ficam escondidos, porque quem os instala é o próprio Setup, na
ordem certa. A lista caiu de centenas de itens para os programas de verdade. Para ver tudo: `--mostrar-componentes`.

### 3. Validação muito mais rápida
- **Rápida por padrão**: estrutura, tamanho esperado (detecta cópia truncada), início e fim do arquivo. Antes lia
  ~45 GB inteiros. Leitura completa: `--validacao-completa`.
- **Em paralelo** em todos os núcleos (`TRABALHADORES` = 2 × núcleos, até 32).
- **Cache** em `logs\cache_pacotes.json`: arquivo que não mudou (mesmo tamanho e data) não é validado de novo.
  Da segunda vez em diante a validação é praticamente instantânea. Ignorar o cache: `--sem-cache`.

### 4. Correções na instalação
| Problema nos logs | Correção |
|---|---|
| `autorun.exe` (menu) gastou 5 min em 5 tentativas | reconhecido como MENU; e se a **mesma tela** voltar com outro argumento, as tentativas param |
| Wacom: código 2 = "arquivo não encontrado" (errado) e nada de plano B | em NSIS, 2 = **abortado pelo instalador**; qualquer falha agora abre o modo com cliques (exceto reinício pendente/outro MSI rodando) |
| SEB: `FALHA (8595)` sem explicação | lê o log do Burn e mostra **qual pacote interno falhou**, com dica. No SEB foi o **WebView2_Bootstrapper**, que precisa de internet. Conecte o PC ou instale antes o `MicrosoftEdgeWebView2RuntimeInstallerX64.exe` |
| Duas cópias do programa abertas ao mesmo tempo (clique duplo) | **instância única**: a segunda só traz a primeira para a frente |

### Parâmetros novos
| Parâmetro | Efeito |
|---|---|
| `--validacao-completa` | lê cada pacote por inteiro |
| `--sem-cache` | valida tudo de novo, ignorando o cache |
| `--mostrar-componentes` | lista também os componentes internos das mídias |


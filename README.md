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

```
InstaladorMSI\
│
├── INICIAR.bat                  ← ponto de entrada (execute este)
├── instalador_msi.py            ← programa principal
├── python-3.12.x-amd64.exe      ← instalador do Python (você adiciona)
├── README.md
│
├── Office\                      ← sua pasta de instaladores
│   ├── Office_Setup.msi
│   └── Teams.msi
├── Drivers\
│   └── Driver_Video.msi
├── Utilitarios\
│   ├── 7zip.msi
│   └── VLC.msi
│
└── logs\                        ← criada automaticamente
```

- O **nome das subpastas** é o que aparece no menu.
- Só aparecem no menu as pastas que **contêm pelo menos um `.msi`**.
- As pastas `logs`, `build`, `dist`, `__pycache__` e pastas iniciadas por `.` são ignoradas.

---

## 🚀 Passo a passo de uso

### 1. Prepare a pasta

1. Copie a pasta `InstaladorMSI` para o computador (ou para um pendrive/rede).
2. Baixe o instalador do Python em <https://www.python.org/downloads/windows/> (*Windows installer 64-bit*, versão 3.9+) e coloque-o **na raiz**, ao lado do `INICIAR.bat`. Qualquer nome no formato `python-*.exe` funciona.
3. Crie subpastas e coloque os `.msi` dentro delas.

### 2. Execute

Dê um duplo clique em **`INICIAR.bat`** e aceite a solicitação de administrador.

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

**Windows SmartScreen bloqueia o `.bat`**
Clique em *Mais informações → Executar assim mesmo*, ou desbloqueie o arquivo em *Propriedades → Desbloquear*.

**Preciso passar parâmetros ao MSI (ex.: `INSTALLDIR`, chave de licença, `.mst`)**
O programa usa os parâmetros padrão. Para casos específicos, edite a função `instalar_msi()` em `instalador_msi.py` e acrescente as propriedades na lista `cmd`.

---

## ⚠️ Limitações conhecidas

- Instala apenas arquivos **`.msi`** (não executa `.exe`, `.msix` ou `.msu`).
- Não aplica parâmetros personalizados por pacote (veja a dica acima).
- Não há desinstalação nem reparo de pacotes.
- Funciona apenas no **Windows**.
- Se um pacote falhar, o programa **continua** com os próximos e registra a falha no resumo.

---

<p align="center"><sub>Desenvolvido por <b>Eduardo Falabella</b></sub></p>

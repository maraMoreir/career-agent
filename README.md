# Career Agent

Agente de carreira integrado ao Claude Desktop via MCP. Encontra vagas,
calcula compatibilidade com o seu perfil, personaliza seu curriculo de forma
legitima, gera mensagens e respostas, e mantem o historico de candidaturas.

**A acao externa final e sempre sua.** O agente prepara; voce clica.

---

## Indice

1. [Arquitetura](#1-arquitetura)
2. [Pre-requisitos](#2-pre-requisitos)
3. [Instalacao](#3-instalacao)
4. [Configuracao](#4-configuracao)
5. [Configuracao do Claude Desktop](#5-configuracao-do-claude-desktop)
6. [Como iniciar](#6-como-iniciar)
7. [Como testar](#7-como-testar)
8. [Como adicionar uma nova fonte de vagas](#8-como-adicionar-uma-nova-fonte-de-vagas)
9. [Como adicionar um novo curriculo](#9-como-adicionar-um-novo-curriculo)
10. [Como registrar uma candidatura](#10-como-registrar-uma-candidatura)
11. [Exemplos de comandos no Claude Desktop](#11-exemplos-de-comandos-no-claude-desktop)
12. [Limitacoes atuais](#12-limitacoes-atuais)
13. [Proximos passos](#13-proximos-passos)

---

## 1. Arquitetura

### Visao geral

```
                        Claude Desktop
                              |
              +---------------+---------------+
              |               |               |
        career-agent     job-search     career-files
         (MCP stdio)     (MCP stdio)     (MCP stdio)
              |               |               |
              +---------------+---------------+
                              |
                        career_core
              (dominio puro - nao conhece MCP)
                              |
         +--------+-----------+-----------+--------+
         |        |           |           |        |
      profile  scoring   applications  resume  job_sources
       (.md)   (7 dim.)  (SQLite+JSON) (tailor) (IJobSource)
```

### Decisoes arquiteturais

**Dominio separado dos adapters.** Toda a regra de negocio vive em
`src/career_core/`, que nao importa nada de MCP. Os tres `server.py` sao
adapters finos: traduzem argumentos, chamam o dominio, formatam a resposta.
Isso permite testar 100% da logica sem subir servidor nenhum.

**SQLite como fonte de verdade, JSON como espelho.** SQLite da escrita
transacional (o historico nao corrompe se o processo morrer no meio) e
consultas de duplicidade baratas, com zero configuracao — ao contrario do
PostgreSQL, que exigiria servidor e credenciais sem ganho nenhum na escala de
uma pessoa. O `applications.json` continua existindo, reescrito de forma
atomica a cada mudanca, para inspecao a olho nu e versionamento no Git. Ele e
**somente escrita**: nunca e lido de volta, entao nao existe risco de duas
fontes divergirem.

**Score como dimensoes plugaveis.** Cada uma das 7 dimensoes e uma classe que
implementa `IScoreDimension` e sabe pontuar *e explicar* um unico aspecto. O
`JobScorer` so soma e classifica. Adicionar uma dimensao nova nao altera o
somador (Open/Closed).

**Fontes de vagas atras de uma interface.** `IJobSource` tem quatro
implementacoes: `MockJobSource` (offline), `RemotiveJobSource` e
`ArbeitnowJobSource` (APIs publicas reais, sem autenticacao) e
`UnavailableJobSource` (LinkedIn/Indeed/Gupy — declaradas, porem em modo
manual). Adicionar uma fonte e escrever uma classe e registra-la; nada mais
muda.

**Composition root unico.** `CareerServices` monta o grafo de objetos. Os
servidores nao instanciam dependencias a mao, e os testes injetam dublês.

### Estrutura de diretorios

```
career-agent/
├── pyproject.toml            # deps + config do pytest (fonte unica)
├── .env.example              # modelo de configuracao (versionado)
├── .env                      # sua configuracao real (NAO versionado)
│
├── src/career_core/          # DOMINIO - nao conhece MCP
│   ├── config.py             # Settings por ambiente
│   ├── models.py             # Job, CandidateProfile, Application, JobScore
│   ├── text.py               # normalizacao (aliases de stack, URL, empresa)
│   ├── security.py           # politica + maquina de estados (ApprovalGate)
│   ├── paths.py              # SandboxedFileSystem (jail em data/)
│   ├── errors.py             # hierarquia de erros de dominio
│   ├── logging_setup.py      # logging para stderr + arquivo
│   ├── services.py           # composition root
│   ├── job_input.py          # vaga colada -> Job normalizado
│   ├── profile/repository.py # perfil .md -> CandidateProfile
│   ├── scoring/              # dimensions.py (7 dimensoes) + scorer.py
│   ├── applications/         # repository.py, dedupe.py, builder.py
│   ├── resume/tailor.py      # personalizacao + FactGuard
│   └── job_sources/          # base.py, mock.py, http_sources.py,
│                             # unavailable.py, registry.py
│
├── mcp-career/               # MCP 1 - logica de carreira
├── mcp-job-search/           # MCP 2 - obtencao de vagas
├── mcp-career-files/         # MCP 3 - leitura de arquivos (sandbox)
│
├── data/                     # UNICO diretorio visivel ao career-files
│   ├── profile/              # profile.md, skills.md, preferences.md
│   ├── resumes/              # curriculo-principal.md (+ variantes)
│   └── applications/         # applications.db (verdade) + .json (espelho)
│
├── agent/career-agent.md     # instrucoes de comportamento do agente
├── scripts/                  # install.ps1, start.ps1, test.ps1, configure-*
├── tests/                    # pytest
└── docs/                     # SECURITY.md, SCORING.md, ARCHITECTURE.md
```

---

## 2. Pre-requisitos

| Requisito | Versao | Observacao |
|---|---|---|
| Windows | 10/11 | testado no Windows 11 |
| Python | >= 3.11 | `python --version` |
| uv | qualquer | o `install.ps1` instala se faltar |
| Claude Desktop | atual | necessario para usar os MCPs |
| Git | opcional | para versionar o projeto |

---

## 3. Instalacao

```powershell
cd C:\career-agent
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

O script verifica Python, instala `uv` se faltar, cria o `.venv`, instala as
dependencias, cria a arvore de `data/`, gera o `.env` a partir do
`.env.example` e valida que os tres MCPs sobem.

Para tambem gravar a configuracao do Claude Desktop no mesmo passo:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -ConfigureClaude
```

---

## 4. Configuracao

### 4.1 Preencha seu perfil

Estes arquivos sao a **fonte de verdade**. O agente nunca afirma nada que nao
esteja neles.

| Arquivo | O que colocar |
|---|---|
| `data/profile/profile.md` | nome, contatos, resumo, formacao, empresas bloqueadas |
| `data/profile/skills.md` | tecnologias, arquitetura, dominios |
| `data/profile/preferences.md` | cargos-alvo, senioridade, modalidade, cidades, salario |
| `data/resumes/curriculo-principal.md` | seu curriculo completo |

Procure por `[PREENCHER]` — sao os campos que o agente nao pode inventar.

Dois deles mudam o score na hora:

- **`Anos de experiencia`** em `profile.md`: enquanto estiver
  `nao informado`, a parte de "anos" da dimensao Experiencia fica neutra. O
  agente **nao** deduz esse numero.
- **`Minimo` / `Alvo`** em `preferences.md`: enquanto estiverem
  `[PREENCHER]`, a dimensao Salario fica neutra para vagas com faixa
  divulgada.

### 4.2 Ajuste o `.env`

```ini
CAREER_DATA_ROOT=C:\career-agent\data
CAREER_MIN_SCORE=70

JOB_SEARCH_ENABLE_NETWORK=false      # true = habilita APIs publicas reais
JOB_SEARCH_SOURCES=mock              # mock,remotive,arbeitnow
JOB_SEARCH_USER_AGENT=career-agent/1.0 (personal job search; contact: SEU-EMAIL)
```

A V1 sai de fabrica **offline** (`mock`), para voce validar o fluxo inteiro
sem depender de terceiros. Quando quiser vagas reais, ligue a rede e ponha seu
e-mail no User-Agent — identificar-se e a forma educada de consumir uma API
publica.

Nao existe variavel de credencial do LinkedIn neste projeto. Isso e
deliberado.

---

## 5. Configuracao do Claude Desktop

### Automatico (recomendado)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\configure-claude-desktop.ps1
```

O script faz backup do arquivo existente (`.backup-AAAAMMDD-HHMMSS`), preserva
todas as suas configuracoes e MCPs atuais, e **so** adiciona/atualiza as tres
entradas do Career Agent.

### Manual

Arquivo: `%APPDATA%\Claude\claude_desktop_config.json`
(no seu caso: `C:\Users\Roger\AppData\Roaming\Claude\claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "career-agent": {
      "command": "C:\\career-agent\\.venv\\Scripts\\python.exe",
      "args": ["C:\\career-agent\\mcp-career\\server.py"]
    },
    "job-search": {
      "command": "C:\\career-agent\\.venv\\Scripts\\python.exe",
      "args": ["C:\\career-agent\\mcp-job-search\\server.py"]
    },
    "career-files": {
      "command": "C:\\career-agent\\.venv\\Scripts\\python.exe",
      "args": ["C:\\career-agent\\mcp-career-files\\server.py"]
    }
  }
}
```

> **Caminhos absolutos.** Se voce instalou o projeto em outro lugar, troque
> `C:\\career-agent` pelo seu caminho real, em todas as ocorrencias. As barras
> invertidas precisam ser duplicadas — e JSON.

> **Por que o python do `.venv` e nao o `uv`?** O Claude Desktop inicia os
> servidores sem carregar seu PATH de usuario. Apontar direto para o
> interpretador do ambiente virtual elimina a dependencia de PATH e torna a
> inicializacao mais rapida e previsivel. O `uv` continua sendo a ferramenta
> de instalacao e de execucao dos testes.

Depois de salvar: **feche o Claude Desktop completamente** (inclusive o icone
na bandeja do sistema, ao lado do relogio — fechar a janela nao encerra o
processo) e abra de novo.

Para confirmar, pergunte no chat: *"Quais ferramentas de career voce tem?"*

---

## 6. Como iniciar

Os servidores sao iniciados pelo proprio Claude Desktop — voce nao precisa
deixar nada rodando.

Para verificar manualmente que os tres sobem:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

Logs: `C:\career-agent\logs\` (`mcp-career.log`, `mcp-job-search.log`,
`mcp-career-files.log`).

---

## 7. Como testar

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

O script roda a suite pytest e, em seguida, uma validacao ponta a ponta:
importacao dos modulos, inicializacao dos tres MCPs, leitura do perfil,
calculo de score, registro de candidatura, consulta de historico e deteccao de
duplicidade.

Apenas os testes unitarios:

```powershell
C:\career-agent\.venv\Scripts\python.exe -m pytest tests -v
```

---

## 8. Como adicionar uma nova fonte de vagas

**Antes de tudo:** verifique se a fonte tem API publica documentada. Se exigir
login, cookie ou scraping, ela nao entra — use `UnavailableJobSource` e o modo
manual.

1. Crie a classe em `src/career_core/job_sources/`:

```python
from .base import IJobSource, JobQuery, SourceResult, detect_seniority

class MinhaFonteJobSource(IJobSource):
    name = "minhafonte"
    provenance = "API JSON publica de X, sem autenticacao."
    usable = True

    def search(self, query: JobQuery) -> SourceResult:
        # ... chamar a API e converter cada item em `Job`
        return SourceResult(source=self.name, jobs=jobs, ok=True, message="...")
```

2. Registre em `src/career_core/job_sources/registry.py`:

```python
_FACTORIES = {
    ...,
    "minhafonte": (lambda s: MinhaFonteJobSource(...), True),  # True = precisa de rede
}
```

3. Ative no `.env`: `JOB_SEARCH_SOURCES=mock,minhafonte`

4. Adicione um teste em `tests/test_job_sources.py`.

Nenhum outro arquivo do sistema muda. Score, deduplicacao e candidatura
funcionam automaticamente porque a fonte devolve `Job` normalizado.

---

## 9. Como adicionar um novo curriculo

Coloque um `.md` em `C:\career-agent\data\resumes\`. O nome do arquivo importa:
o agente escolhe automaticamente o curriculo cujo nome tem mais palavras em
comum com a vaga.

```
data/resumes/
├── curriculo-principal.md      # padrao / fallback
├── curriculo-backend-dotnet.md # vence em vagas .NET/backend
├── curriculo-fullstack.md      # vence em vagas fullstack/React
└── curriculo-sap.md            # vence em vagas SAP
```

Para forcar um especifico: *"Prepare a candidatura usando curriculo-sap.md"*.

---

## 10. Como registrar uma candidatura

Ciclo de vida:

```
   generate_application          register_application
   (mostra o pacote)      -->    (grava o historico)
                                        |
                                        v
                                pending_approval
                                        |
                          voce aprova   |
                                        v
                                    approved
                                        |
                    VOCE se candidata no site
                                        v
                                     applied
                                        |
              +-------------+-----------+-----------+
              v             v           v           v
          interview  technical_test   offer     rejected
```

`rejected` e `withdrawn` sao estados finais.

**Nao existe caminho de `pending_approval` direto para `applied`.** A tentativa
e recusada pela maquina de estados. Essa e a garantia, em codigo, de que nada
avanca sem voce ter visto.

---

## 11. Exemplos de comandos no Claude Desktop

**Buscar**
```
Procure vagas Backend .NET compativeis com meu perfil.
Priorize remoto e hibrido em Goiania.
Mostre somente vagas com score >= 80.
```

**Analisar uma vaga colada**
```
Analise esta vaga:
[cole aqui a URL e a descricao completa]
```

**Preparar candidatura**
```
Prepare minha candidatura para a vaga da Nexatech.
```

**Acompanhar**
```
Mostre minhas candidaturas pendentes.
Quais candidaturas estao aguardando minha aprovacao?
Atualize a candidatura app-xxxx para entrevista.
```

**Aprovar**
```
Aprovo a candidatura app-xxxx.
```

**Diagnostico**
```
Esta tudo configurado no Career Agent?
De onde vem as vagas que voce busca?
Voce consegue se candidatar por mim no LinkedIn?
```

---

## 12. Limitacoes atuais

- **LinkedIn, Indeed e Gupy funcionam em modo manual.** Nenhum deles oferece
  API publica de busca para candidatos. Voce copia a vaga; o agente faz o
  resto. Isso e uma escolha de seguranca, nao uma pendencia.
- **A fonte padrao e `mock`** (catalogo ficticio, offline). Vagas reais exigem
  ligar `JOB_SEARCH_ENABLE_NETWORK=true`.
- **A busca automatica praticamente nao serve para vagas .NET no Brasil.**
  Isso foi medido, nao estimado (agosto/2026):
  - **Remotive**: o endpoint publico gratuito devolve um feed de **amostra de
    14 vagas** e **ignora o parametro `search`** — a mesma resposta volta para
    `.net`, `python` ou uma consulta sem sentido. Nenhuma vaga de engenharia
    .NET. O projeto passou a filtrar do lado do cliente e a avisar disso.
  - **Arbeitnow**: 175 vagas no feed, concentradas em Londres, Berlim e
    Munique, presenciais. **Zero** com .NET/C#.
  - **LinkedIn, Indeed e Gupy** — onde as vagas brasileiras de fato estao —
    nao tem API publica de busca para candidatos.

  Na pratica: **use o modo manual.** Voce busca no portal pelo navegador,
  cola a vaga aqui, e o agente faz score, gaps, curriculo, mensagem e
  historico. A busca automatica e a parte fraca do sistema; a analise e a
  parte forte.
- **A extracao de requisitos e heuristica.** Funciona bem com descricoes em
  bullets; com texto corrido, os requisitos saem menos estruturados.
- **A deteccao de senioridade e por palavra-chave** no titulo e na descricao.
  Titulos ambiguos podem sair como `nao_informado` — informe manualmente
  quando importar.
- **Salario so e comparado quando a vaga divulga a faixa.** A maioria das
  vagas brasileiras nao divulga; nesse caso a dimensao fica neutra.
- **O curriculo personalizado sai em Markdown.** Nao ha exportacao para PDF
  ou DOCX na V1.
- **Instalacao mono-usuario, local.** Sem multi-perfil, sem sincronizacao.

---

## 13. Proximos passos

Ordenados por relacao valor/esforco:

1. **Exportar curriculo para PDF/DOCX** — hoje o material sai em Markdown e
   voce converte a mao.
2. **Ler descricao de vaga a partir de uma URL publica** (paginas de carreira
   abertas, sem login), reduzindo o copiar-e-colar.
3. **Fontes brasileiras** — mapear ATSs que expoem endpoint publico de vagas
   por empresa e implementar como `IJobSource`.
4. **Lembretes de follow-up** — sinalizar candidaturas paradas em `applied` ha
   mais de N dias.
5. **Metricas do funil** — taxa de resposta por score, por stack e por
   modalidade, para calibrar os pesos com dados reais.
6. **Calibracao dos pesos** — hoje sao os pesos definidos na especificacao;
   com historico suficiente, ajustar com base no que realmente converte.
7. **Deteccao de duplicidade semantica** — hoje e por similaridade textual;
   embeddings pegariam "Dev Backend .NET" vs "Engenheiro de Software C#".

---

## Seguranca

Resumo do que este projeto **nao faz**, por design:

| Nao faz | Por que |
|---|---|
| Login automatico no LinkedIn | viola os ToS; risco de bloqueio da conta |
| Guardar senha/cookie/token | superficie de ataque desnecessaria |
| Automatizar cliques | viola os ToS |
| Enviar candidatura sozinho | a decisao final e sua |
| Enviar mensagem sozinho | a decisao final e sua |
| Burlar anti-bot / CAPTCHA | ilegitimo |
| Scraping agressivo | ilegitimo e desrespeitoso |
| Inventar experiencia | mentira em curriculo prejudica voce |

Detalhes em [docs/SECURITY.md](docs/SECURITY.md).

O acesso a arquivos do Claude fica restrito a `C:\career-agent\data`. Ele nao
enxerga `C:\`, nem sua pasta de usuario, nem o codigo do proprio projeto.

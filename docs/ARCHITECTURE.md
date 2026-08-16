# Arquitetura

## Principio central

O dominio nao conhece MCP.

Tudo que decide alguma coisa — score, duplicidade, personalizacao de
curriculo, maquina de estados — vive em `src/career_core/` e nao importa nada
do SDK MCP. Os tres `server.py` sao adapters: traduzem argumentos, chamam o
dominio, formatam texto.

Consequencias praticas:

- 100% da logica e testavel sem subir servidor nenhum.
- Trocar MCP por uma CLI, uma API HTTP ou um bot exigiria escrever um adapter
  novo, sem tocar em regra de negocio.
- Quando o SDK MCP mudou de `FastMCP` para `MCPServer`, a correcao foi um
  unico arquivo (`mcp_compat.py`).

```
                        Claude Desktop
                              |
              +---------------+---------------+
              |               |               |
        career-agent     job-search     career-files
              |               |               |
              +---------------+---------------+
                              |
                        career_core
                              |
    +--------+--------+-------+-------+--------+--------+
    |        |        |       |       |        |        |
 profile  scoring  applications resume job_sources security paths
```

---

## Modulos

| Modulo | Responsabilidade |
|---|---|
| `config.py` | `Settings` imutavel a partir do ambiente / `.env` |
| `models.py` | `Job`, `CandidateProfile`, `Application`, `JobScore` (pydantic) |
| `text.py` | Normalizacao: aliases de stack, URL, empresa, titulo, similaridade |
| `security.py` | Politica de capacidades + `ApprovalGate` (maquina de estados) |
| `paths.py` | `SandboxedFileSystem` — jail em `data/` |
| `errors.py` | Hierarquia de erros de dominio |
| `logging_setup.py` | Logging para stderr + arquivo rotativo |
| `services.py` | Composition root |
| `job_input.py` | Vaga colada → `Job` normalizado |
| `mcp_compat.py` | Isola a diferenca entre SDK MCP 1.x e 2.x |
| `profile/` | Markdown → `CandidateProfile` |
| `scoring/` | 7 dimensoes plugaveis + somador |
| `applications/` | Repositorio, deduplicacao, montagem do pacote |
| `resume/` | Personalizacao + `FactGuard` |
| `job_sources/` | `IJobSource` e implementacoes |

---

## Decisoes

### SQLite como fonte de verdade, JSON como espelho

**Alternativas:** PostgreSQL, JSON puro, SQLite.

**Escolha:** SQLite, com espelho JSON derivado.

PostgreSQL exigiria servidor, credenciais e manutencao — custo real, ganho
zero na escala de uma pessoa com dezenas ou centenas de candidaturas.

JSON puro parece mais simples, mas escrita concorrente ou processo morto no
meio do `write` corrompe o historico inteiro. E cada consulta de duplicidade
viraria uma varredura completa do arquivo.

SQLite da transacao, indices e zero configuracao. O `applications.json`
continua existindo — reescrito de forma atomica (tmpfile + `os.replace`) apos
cada mutacao — para inspecao a olho nu e diff no Git.

O espelho e **somente escrita**. Nunca e lido de volta, entao nao ha como as
duas fontes divergirem. Falha ao escrever o espelho e logada, mas nao derruba
a operacao: o SQLite ja commitou.

### Dimensoes de score como classes

**Alternativa:** uma funcao grande com `if`s.

**Escolha:** uma classe por dimensao, implementando `IScoreDimension`.

Cada dimensao sabe pontuar **e explicar** um unico aspecto (Single
Responsibility). O `JobScorer` recebe a lista por injecao e so soma
(Open/Closed: adicionar dimensao nao altera o somador). Uma dimensao que
lanca excecao pontua 0 e e logada — nao derruba o score inteiro.

### Perfil em Markdown, nao em banco

**Escolha:** a usuaria edita `data/profile/*.md` e o sistema le a cada
chamada.

Sem duplicacao de estado, sem tela de cadastro, sem migracao. Ela abre o
arquivo, adiciona uma tecnologia, e o score de todas as vagas muda na proxima
pergunta. O custo (parser de Markdown) e pequeno perto do ganho.

### Fontes de vagas atras de interface

`IJobSource` com quatro implementacoes, incluindo `UnavailableJobSource` para
portais sem API publica. Declarar a fonte como indisponivel — em vez de
omiti-la — deixa explicito **por que** o LinkedIn nao aparece, e mantem o
ponto de extensao pronto caso uma API oficial surja.

### Rede desligada por padrao

A V1 sai com `mock`. O fluxo inteiro pode ser validado offline, os testes sao
deterministicos, e nada sai para a internet sem a usuaria ter ligado
explicitamente.

### `python.exe` do venv no config, nao `uv`

O Claude Desktop inicia os servidores sem carregar o PATH completo do usuario.
Apontar direto para o interpretador do `.venv` elimina a dependencia de PATH e
torna a inicializacao mais rapida e previsivel. O `uv` continua sendo a
ferramenta de instalacao e de execucao dos testes.

### Logging nunca em stdout

Um servidor MCP em stdio usa **stdout** para o protocolo JSON-RPC. Um
`print()` perdido corrompe a sessao. Todo log vai para stderr (visivel nos
logs do Claude Desktop) e para arquivo rotativo em `logs/`.

---

## Fluxo de uma requisicao

```
"Procure vagas Backend .NET com score >= 80"
        |
        v
job-search.search_jobs(keywords=..., min_score=80)
        |
        +-> CareerServices.job_search  (AggregatedJobSearch)
        |       +-> JobSourceRegistry.enabled_names()  -> ["mock"]
        |       +-> MockJobSource.search(JobQuery)     -> list[Job]
        |       +-> deduplicate_jobs(...)              -> sem repetidos
        |
        +-> CareerServices.profile()   (le os .md do disco)
        |
        +-> JobScorer.score(job, profile) por vaga
        |       +-> 7 dimensoes -> DimensionScore
        |       +-> eliminacao automatica
        |       +-> classificacao
        |
        v
   texto ordenado por score, com gaps e links
```

---

## Testes

| Arquivo | Cobre |
|---|---|
| `test_scoring.py` | Pesos, faixas, dimensoes, eliminacao, resiliencia |
| `test_security.py` | Capacidades proibidas, maquina de estados, dependencias |
| `test_sandbox.py` | Jail de arquivos, travessia, extensoes |
| `test_dedupe.py` | Normalizacao e deteccao de duplicidade |
| `test_profile_and_resume.py` | Parser de perfil, `FactGuard`, personalizacao |
| `test_applications.py` | Persistencia, historico, espelho JSON, pacote |
| `test_job_sources.py` | Fontes, deteccao, registry, modo manual |
| `test_end_to_end.py` | Fluxo completo do dominio |
| `scripts/validate_mcp.py` | Fluxo completo **atraves da camada MCP** |

Os testes rodam contra um `data_root` temporario. A validacao MCP copia o
perfil real para uma pasta temporaria — o historico real nunca e tocado.

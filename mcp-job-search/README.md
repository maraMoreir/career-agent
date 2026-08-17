# MCP `job-search`

Obtencao e normalizacao de vagas, atras da interface `IJobSource`.

## Ferramentas

| Ferramenta | Para que serve |
|---|---|
| `search_jobs` | Busca nas fontes ativas, deduplica, pontua e ordena. |
| `list_job_sources` | Mostra todas as fontes, quais estao ativas e por que. |
| `get_manual_search_guide` | Passo a passo do modo manual para portais sem API. |

## Fontes

| Fonte | Estado | Como e acessada |
|---|---|---|
| `ats` | **padrao** | Quadros publicos de empresas em Greenhouse, Lever e Ashby. **Melhor cobertura de vagas .NET no Brasil.** |
| `mock` | disponivel | Catalogo local ficticio. Offline, deterministico. Para demonstracao e testes. |
| `remotive` | disponivel | `GET https://remotive.com/api/remote-jobs` — feed de amostra de 14 vagas que **ignora o parametro de busca**. Pouco util. |
| `arbeitnow` | disponivel | `GET https://www.arbeitnow.com/api/job-board-api` — 175 vagas, quase todas europeias e presenciais. Pouco util. |
| `linkedin` | modo manual | Sem API publica de busca. Exigiria sessao autenticada. |
| `indeed` | modo manual | Acesso publico da antiga Publisher API encerrado. |
| `gupy` | modo manual | Sem API aberta para candidatos (as APIs sao para clientes ATS). |

Todos os endpoints foram verificados contra a resposta real antes de escrever
o parser. Nenhum endpoint foi inventado.

### A fonte `ats` — a que realmente funciona

Greenhouse, Lever e Ashby publicam a lista de vagas de cada empresa num
endpoint JSON publico e sem autenticacao. E a mesma resposta que alimenta a
pagina de carreiras que qualquer pessoa abre no navegador.

```
Greenhouse : GET boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Lever      : GET api.lever.co/v0/postings/{slug}?mode=json
Ashby      : GET api.ashbyhq.com/posting-api/job-board/{slug}
```

Configure as empresas em `JOB_SEARCH_ATS_COMPANIES`:

```ini
JOB_SEARCH_ENABLE_NETWORK=true
JOB_SEARCH_SOURCES=ats
JOB_SEARCH_ATS_COMPANIES=greenhouse:stone,ashby:nubank,lever:neon
```

Para descobrir o slug, abra a pagina de carreiras da empresa e olhe a URL:
`job-boards.greenhouse.io/X` → `greenhouse:X`, `jobs.lever.co/X` → `lever:X`,
`jobs.ashbyhq.com/X` → `ashby:X`.

Notas de implementacao:

- Os quadros sao buscados em paralelo (4 threads), com timeout por requisicao.
  Um quadro fora do ar nao derruba os outros — ele e reportado na mensagem.
- O HTML do Greenhouse vem com entidades escapadas duas vezes; e limpo antes
  de virar descricao.
- `department`/`team` **nao** entram em `tech_tags`: eles alimentariam a
  dimensao Stack como tecnologia exigida, e "Engenharia & Tecnologia" viraria
  um gap inventado.
- A pre-ordenacao por relevancia (termo no titulo pesa 3x) acontece **antes**
  do corte por `max_results`, senao as vagas mais aderentes seriam descartadas.

## Comportamento em rede

- Timeout por requisicao (`JOB_SEARCH_TIMEOUT`).
- Intervalo minimo entre chamadas a uma mesma fonte (`JOB_SEARCH_MIN_INTERVAL`).
- Teto de resultados por fonte (`JOB_SEARCH_MAX_RESULTS`).
- User-Agent identificado.
- Sem cookies, sem sessao, sem credencial, sem retry agressivo.

## O que este servidor nao faz

Nao faz login, nao usa cookie ou token de sessao, nao automatiza cliques, nao
faz scraping e nao tenta burlar anti-bot. Portais sem API publica caem no modo
manual: a usuaria copia a vaga, e o agente faz score, gaps, curriculo,
mensagem e historico.

## Adicionar uma fonte

1. Implemente `IJobSource` em `src/career_core/job_sources/`.
2. Registre em `registry.py` (`_FACTORIES`).
3. Ative no `.env`.
4. Teste em `tests/test_job_sources.py`.

Nenhum outro arquivo muda — a fonte devolve `Job` normalizado e o resto do
sistema segue funcionando.

## Execucao

```powershell
.\scripts\start.ps1 -Server job-search
```

Logs em `logs\mcp-job-search.log`.

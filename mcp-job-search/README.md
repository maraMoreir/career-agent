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
| `mock` | ativa por padrao | Catalogo local ficticio. Offline, deterministico. |
| `remotive` | opcional | `GET https://remotive.com/api/remote-jobs` — JSON publico, sem auth. Só vagas remotas. |
| `arbeitnow` | opcional | `GET https://www.arbeitnow.com/api/job-board-api` — JSON publico, sem auth. Base majoritariamente europeia. |
| `linkedin` | modo manual | Sem API publica de busca. Exigiria sessao autenticada. |
| `indeed` | modo manual | Acesso publico da antiga Publisher API encerrado. |
| `gupy` | modo manual | Sem API aberta para candidatos (as APIs sao para clientes ATS). |

Os dois endpoints HTTP foram verificados contra a resposta real antes de
escrever o parser. Nenhum endpoint foi inventado.

### Por que `mock` e o padrao

A V1 sai offline para que o fluxo inteiro possa ser validado sem depender de
terceiros, e para que os testes sejam deterministicos. Para ligar as fontes
reais, no `.env`:

```ini
JOB_SEARCH_ENABLE_NETWORK=true
JOB_SEARCH_SOURCES=mock,remotive,arbeitnow
JOB_SEARCH_USER_AGENT=career-agent/1.0 (personal job search; contact: seu-email)
```

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

# Fontes de vagas — disponibilidade real

Levantamento feito contra as APIs reais em **17 de agosto de 2026**. Cada
linha foi testada, não estimada.

## Resumo

| Fonte | Auth | Cobertura BR | Situação |
|---|---|---|---|
| **Greenhouse** | nenhuma | boa (por empresa) | ✅ implementada |
| **Lever** | nenhuma | média (por empresa) | ✅ implementada |
| **Ashby** | nenhuma | média (por empresa) | ✅ implementada |
| **Workable** | nenhuma | por empresa | ✅ implementada |
| **SmartRecruiters** | nenhuma | por empresa | ✅ implementada |
| **Adzuna** | chave grátis | **índice nacional `br`** | ✅ implementada, aguarda sua chave |
| **Remotive** | nenhuma | ~nenhuma | ⚠️ implementada, pouco útil |
| **Arbeitnow** | nenhuma | ~nenhuma | ⚠️ implementada, pouco útil |
| **Jooble** | chave | boa | ❌ bloqueado por Cloudflare |
| **LinkedIn** | sessão | ótima | ❌ sem API pública |
| **Indeed** | parceiro | boa | ❌ API pública encerrada |
| **Gupy** | token da empresa | ótima | ❌ API só para empregadores |

---

## Implementadas

### Quadros de ATS (fonte `ats`) — a melhor cobertura brasileira

Greenhouse, Lever, Ashby, Workable e SmartRecruiters publicam as vagas de
cada empresa num endpoint JSON público e sem autenticação. É a mesma resposta
que alimenta a página de carreiras que qualquer pessoa abre no navegador.

```
Greenhouse      GET boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Lever           GET api.lever.co/v0/postings/{slug}?mode=json
Ashby           GET api.ashbyhq.com/posting-api/job-board/{slug}
Workable        GET apply.workable.com/api/v1/widget/accounts/{slug}?details=true
SmartRecruiters GET api.smartrecruiters.com/v1/companies/{slug}/postings
```

**Configuração:** `JOB_SEARCH_ATS_COMPANIES=greenhouse:stone,ashby:nubank,...`

**Descobrir o slug:** abra a página de carreiras da empresa e leia a URL.
`job-boards.greenhouse.io/X` → `greenhouse:X`.

**Medido:** 10 empresas brasileiras configuradas, ~1.160 vagas varridas por
execução, vagas .NET reais encontradas (Stone, VTEX).

**Armadilhas encontradas ao implementar:**

- O Workable devolve `city`/`state`/`country` no **topo do item**, não
  aninhados num objeto `location` como os outros quatro. Assumir o formato
  aninhado zerava a localização.
- O Greenhouse devolve o `content` com entidades HTML escapadas **duas
  vezes**. Um `html.unescape` só não basta.
- O SmartRecruiters expõe `fullLocation` legível e flags `remote`/`hybrid`
  próprias — melhor do que montar a string e adivinhar a modalidade.
- Nenhum deles deve ter `department`/`team` copiados para `tech_tags`:
  isso transforma "Engenharia & Tecnologia" num gap técnico inventado.
- O Workable aplica rate limit agressivo (429). A camada HTTP com backoff é
  necessária, não decorativa.

### Adzuna (fonte `adzuna`) — único índice nacional

```
GET https://api.adzuna.com/v1/api/jobs/br/search/1
    ?app_id=...&app_key=...&what=...&where=...
```

Exige `app_id` e `app_key` gratuitos, emitidos em
[developer.adzuna.com](https://developer.adzuna.com/). É uma **credencial de
desenvolvedor emitida para você**, não uma senha de portal: não há login de
candidato, cookie ou conta envolvida.

```ini
ADZUNA_APP_ID=seu_app_id
ADZUNA_APP_KEY=sua_app_key
```

Sem a chave, a fonte não falha em silêncio — ela explica onde obtê-la.

### Remotive e Arbeitnow — implementadas, mas quase inúteis aqui

- **Remotive**: o endpoint gratuito devolve um feed de **amostra de 14 vagas**
  e **ignora o parâmetro `search`**. A mesma resposta volta para `.net`,
  `python` ou uma consulta sem sentido. Zero vagas de engenharia .NET. Por
  isso o filtro por palavra-chave é feito do lado do cliente, e a mensagem
  avisa quando o feed é uma amostra.
- **Arbeitnow**: 175 vagas, concentradas em Londres, Berlim e Munique,
  presenciais. **Zero** com .NET ou C#.

---

## Não implementadas, e por quê

### Jooble — bloqueado por anti-bot

A API exige chave **e** o endpoint responde `403` do Cloudflare
("Just a moment...") **antes mesmo da autenticação** — verificado em
`jooble.org` e `br.jooble.org`. Fazer a requisição passar exigiria contornar
proteção anti-bot, exatamente o que a especificação deste projeto proíbe.

A fonte fica **declarada e desligada**, com o motivo. Se o Jooble liberar
acesso programático estável, basta implementar `search` — nada mais no sistema
muda.

### LinkedIn, Indeed e Gupy — sem API pública para candidatos

- **LinkedIn**: a busca de vagas exige sessão autenticada. A API oficial é
  restrita a parceiros corporativos.
- **Indeed**: o acesso público da antiga Publisher API foi encerrado.
- **Gupy**: a API oficial (`api.gupy.io/api/v1`) usa Bearer token **gerado no
  painel da empresa contratante** e serve para o empregador gerenciar as
  próprias vagas. Não existe busca pública para candidatos.

Os três operam em **modo manual**: você busca no navegador, copia URL e
descrição, e usa `save_job` ou `analyze_job`. O agente faz score, gaps,
currículo, mensagem e histórico igual.

---

## Adicionar uma fonte nova

### Se for um ATS já suportado

Basta adicionar a empresa em `JOB_SEARCH_ATS_COMPANIES`. Nenhum código muda.

### Se for um ATS novo

1. Implemente `IAtsBoard` em `src/career_core/job_sources/ats_boards.py`:

```python
class MeuAtsBoard(IAtsBoard):
    provider = "meuats"

    def endpoint(self, company: str) -> tuple[str, dict]:
        return f"https://api.meuats.com/boards/{company}/jobs", {}

    def parse(self, company: str, payload) -> list[Job]:
        ...  # devolva Job normalizado
```

2. Registre em `BOARDS`. Pronto.

### Se for um agregador com API própria

1. Implemente `IJobSource` (veja `aggregators.py` como modelo).
2. Registre em `_FACTORIES` no `registry.py`, indicando se exige rede.
3. Ative em `JOB_SEARCH_SOURCES`.
4. Escreva o teste com uma fixture da resposta **real** — capture antes de
   escrever o parser. Foi assim que os cinco bugs acima apareceram.

Score, deduplicação, catálogo e candidatura funcionam automaticamente, porque
a fonte devolve `Job` normalizado.

### Antes de implementar qualquer fonte

Verifique se ela pode ser consumida de forma legítima:

- Tem API pública documentada? → pode.
- Exige chave de desenvolvedor emitida para você? → pode.
- Exige login de usuário, cookie ou sessão? → **não**.
- Está atrás de anti-bot? → **não**.
- Precisaria de scraping de HTML? → **não**.

Nesses últimos três casos, use `UnavailableJobSource` e o modo manual.

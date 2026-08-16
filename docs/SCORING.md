# Sistema de Score

Score de 0 a 100, sempre acompanhado da justificativa de cada dimensao. Um
numero sem explicacao nao ajuda a decidir nada.

## Pesos

| Dimensao | Peso | O que mede |
|---|---:|---|
| Stack tecnica | 30 | Tecnologias exigidas vs. tecnologias do perfil |
| Senioridade | 20 | Nivel da vaga vs. nivel desejado |
| Salario | 15 | Faixa oferecida vs. minimo e alvo |
| Modalidade | 10 | Remoto / hibrido / presencial vs. ordem de preferencia |
| Localizacao | 10 | Compatibilidade geografica (remoto neutraliza distancia) |
| Experiencia | 10 | Arquitetura e dominio exigidos vs. declarados |
| Empresa | 5 | Listas de preferencia/bloqueio e sinais na descricao |

## Classificacao

```
90-100  PRIORIDADE ALTA
80-89   PRIORIDADE
70-79   ANALISAR
 0-69   DESCARTAR
```

## Eliminacao automatica

Independente da pontuacao, a vaga vira `DESCARTAR` (com o total limitado a 69)
quando:

- a senioridade esta na lista `Evitar` do perfil (estagio / trainee / junior);
- a empresa esta na lista de bloqueio.

O detalhamento continua visivel — voce ve o que ela teria pontuado e por que
foi eliminada.

---

## Como cada dimensao pontua

### Stack tecnica (30)

Extrai as tecnologias da vaga (titulo, descricao e tags) usando um vocabulario
de mercado + tudo que esta no seu perfil, com resolucao de aliases
(`dotnet`/`.NET Core`/`.net 8` → `.net`; `csharp` → `c#`; `EF Core` → `entity
framework core`).

```
cobertura  = tecnologias_que_voce_tem / tecnologias_exigidas
core_ratio = quanto do core (.NET, C#, ASP.NET Core, EF Core) a vaga pede e voce tem

pontos = 30 * (0.7 * cobertura + 0.3 * core_ratio)
```

Se a vaga **nao** menciona .NET/C#, o teto cai para 60% — e uma vaga fora do
seu foco, mesmo que outras tecnologias batam.

Vaga sem tecnologia reconhecivel: 50% (neutro) + aviso para colar a descricao
completa.

### Senioridade (20)

| Situacao | Pontos |
|---|---:|
| Nivel exatamente no alvo (pleno/senior) | 20 |
| Especialista / lead | 16 |
| Nao informado | 12 |
| Outro nivel | 6 |
| Nivel na lista `Evitar` | 0 + eliminacao |

### Salario (15)

| Situacao | Pontos |
|---|---:|
| Oferta >= alvo | 15 |
| Entre minimo e alvo | 10.5 a 15 (linear) |
| Nao divulgado | 9 (neutro) + gap registrado |
| Perfil sem minimo definido | 9 (neutro) |
| Abaixo do minimo | 0 a 7.5 + gap registrado |

Salario nao divulgado recebe nota **neutra**, nao zero. A maioria das vagas
brasileiras nao publica faixa; penalizar distorceria todo o ranking.

### Modalidade (10)

Segue a ordem em `preferences.md`:

| Posicao | Pontos |
|---|---:|
| 1a opcao (remoto) | 10 |
| 2a opcao (hibrido) | 7 |
| 3a opcao (presencial) | 3 |
| Nao informada | 5 |

### Localizacao (10)

| Situacao | Pontos |
|---|---:|
| Remoto sem restricao incompativel | 10 |
| Remoto com restricao de regiao | 5 + gap |
| Nao-remoto em cidade preferida | 10 |
| Nao-remoto, Brasil, outra cidade | 3-4 + gap |
| Nao-remoto fora do Brasil | 0 + gap |

### Experiencia (10)

```
pontos = 10 * (0.65 * cobertura_de_dominio + 0.35 * proporcao_de_anos)
```

**Dominio** = arquitetura (Clean Architecture, SOLID, DDD, hexagonal,
microsservicos...) e area de negocio (SAP, fiscal, SEFAZ...). Linguagens e
ferramentas **nao** entram aqui — ja sao pontuadas em Stack; conta-las duas
vezes inflaria o score.

**Anos**: se o perfil nao declara anos de experiencia, essa metade fica neutra
(60%). O sistema **nunca** deduz seu tempo de carreira. Para ativar a
comparacao, preencha `Anos de experiencia` em `profile.md`.

### Empresa (5)

| Situacao | Pontos |
|---|---:|
| Na lista de preferidas | 5 |
| Sem historico, base | 3 |
| +0.5 por beneficio citado (PLR, plano de saude, home office...) | ate 5 |
| -1 por sinal de alerta (sobreaviso 24x7, viagens constantes...) | — |
| Na lista de bloqueio | 0 + eliminacao |

---

## Exemplo real

```
Score: 90/100

Stack tecnica: 28.38/30
Senioridade: 20/20
Salario: 9/15
Modalidade: 10/10
Localizacao: 10/10
Experiencia: 8.6/10
Empresa: 4/5

Detalhamento:
  - Stack tecnica: 12/13 tecnologias exigidas estao no perfil (92% de
    cobertura); core .NET/C# presente.
  - Senioridade: Nivel 'senior' e exatamente o alvo.
  - Salario: Vaga informa R$ 16.000 a R$ 18.000, mas o perfil nao define
    salario minimo; nota neutra.
  - Modalidade: 'remoto' e a 1a opcao na sua ordem de preferencia.
  - Localizacao: Remoto sem restricao geografica incompativel.
  - Experiencia: 4/4 areas de experiencia exigidas presentes no perfil;
    sem exigencia explicita de anos.
  - Empresa: sem historico nas suas listas: beneficios citados (2).

Gaps:
  - azure

Recomendacao:
PRIORIDADE ALTA
```

Note os dois pontos onde o score se penaliza por **falta de dado seu**, nao da
vaga: Salario (9/15, porque o minimo nao esta preenchido) e Experiencia
(8.6/10, parte pela ausencia de anos declarados). Preencher
`preferences.md` e `profile.md` sobe o score de todas as vagas boas e melhora
a separacao entre elas.

---

## Ajustar os pesos

Os pesos vivem em `max_points` de cada classe em
`src/career_core/scoring/dimensions.py`. Precisam somar 100 — ha um teste que
verifica isso, e o `JobScorer` avisa em log se nao somarem.

## Adicionar uma dimensao

```python
class CulturaDimension(IScoreDimension):
    key = "cultura"
    label = "Cultura"
    max_points = 5.0

    def score(self, job, profile) -> DimensionScore:
        return self._result(3.0, "justificativa clara aqui")
```

Registre em `default_dimensions()` e reduza o peso de outra dimensao para
manter o total em 100. O `JobScorer` nao muda — ele so soma.

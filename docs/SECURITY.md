# Seguranca

Este documento descreve o que o Career Agent **nao faz**, por que, e como
essas garantias sao aplicadas em codigo — nao apenas prometidas em texto.

---

## 1. Automacao de portais de vagas

### Nao implementado, por design

| Capacidade | Motivo |
|---|---|
| Login automatico no LinkedIn | Viola os Termos de Servico. Contas automatizadas sao detectadas e bloqueadas. Perder a conta custa mais do que qualquer ganho de velocidade. |
| Armazenamento de senha | Uma senha guardada em disco e uma superficie de ataque que nao precisa existir. |
| Armazenamento de cookie / token de sessao | Um cookie de sessao roubado da acesso total a conta, sem senha e sem MFA. |
| Captura de sessao do navegador | Mesmo problema, com o agravante de tocar em dados de outros sites. |
| Automacao de cliques | Viola os ToS e quebra a cada mudanca de layout. |
| Envio automatico de candidatura | A decisao final e da usuaria. Uma candidatura enviada por engano nao volta atras. |
| Envio automatico de mensagem | Mensagem enviada em nome dela, sem ela ler, e um risco reputacional. |
| Evasao de anti-bot / CAPTCHA | Ilegitimo. Se um site sinaliza que nao quer trafego automatizado, a resposta e respeitar. |
| Scraping agressivo | Ilegitimo e desrespeitoso com a infraestrutura alheia. |

### Como isso e garantido

**`career_core/security.py`** declara `FORBIDDEN_CAPABILITIES` e
`assert_capability_not_forbidden()`, que levanta `ForbiddenActionError`. Uma
extensao futura que tente habilitar qualquer uma dessas capacidades falha de
forma explicita.

**`tests/test_security.py`** verifica cada item da lista, inclusive variacoes
de escrita, e falha o build se o `pyproject.toml` ganhar dependencia de
`selenium`, `playwright` ou similar.

**`tests/test_job_sources.py`** garante que nenhum endpoint HTTP aponte para
LinkedIn, Indeed ou Gupy.

**Nao existe variavel de credencial no `.env.example`**, e um teste verifica
isso.

### O que existe no lugar: modo manual

Para portais sem API publica, `get_manual_search_guide` devolve o passo a
passo: a usuaria busca no navegador, copia URL e descricao, e o agente faz
score, gaps, curriculo, mensagem e historico. Ela mantem o clique final —
que e exatamente o ponto.

---

## 2. Human-in-the-loop

Toda candidatura nasce em `pending_approval`.

```
pending_approval --> approved --> applied --> interview / technical_test --> offer
                 \                        \
                  --> rejected             --> rejected / withdrawn
                  --> withdrawn
```

**Nao existe transicao de `pending_approval` para `applied`.** A tentativa e
recusada por `ApprovalGate.validate()` com uma mensagem que explica o caminho
correto. A validacao acontece **antes** de qualquer escrita no banco.

Isso significa, em termos praticos: nenhuma candidatura pode ser marcada como
enviada sem que a usuaria tenha, em algum momento, aprovado explicitamente.

Coberto por `tests/test_security.py` e pelo fluxo real em
`tests/test_end_to_end.py`.

---

## 3. Acesso a arquivos

O MCP `career-files` so enxerga `CAREER_DATA_ROOT` (padrao
`C:\career-agent\data`).

`SandboxedFileSystem` resolve o caminho real — seguindo symlinks e junctions —
**antes** de comparar com a raiz. Bloqueia travessia (`..`), caminhos
absolutos externos, caminhos UNC, nomes de dispositivo reservados do Windows,
bytes nulos e arquivos acima do limite de tamanho.

Só `.md`, `.markdown`, `.json` e `.txt` sao legiveis. Binarios, `.exe`,
`.pem` e `.env` sao recusados e nem aparecem nas listagens.

O servidor **nao escreve e nao apaga** nada.

Coberto por `tests/test_sandbox.py`.

---

## 4. Honestidade factual

O perfil e a unica fonte de verdade sobre a experiencia da candidata.

`FactGuard` audita **todo** texto gerado (resumo adaptado, mensagem ao
recrutador, respostas sugeridas, curriculo personalizado). Ele:

1. Identifica as tecnologias exigidas pela vaga que **nao** estao no perfil.
2. Detecta se o texto **afirma** experiencia nelas ("experiencia com X",
   "trabalhei com X", "dominio de X", "certificada em X", "X: 5 anos").
3. Aceita quando o termo esta explicitamente marcado como **gap** ("nao
   possuo experiencia com X", "interesse em aprender X").
4. Reprova qualquer mencao nao qualificada.

A personalizacao do curriculo so pode **reordenar**, **destacar** e **adaptar
palavras-chave** para itens que ja existem no perfil. O curriculo base nunca e
modificado — um teste verifica isso byte a byte.

Se o perfil nao declara anos de experiencia, o sistema mantem `None` e a
dimensao Experiencia usa nota neutra. **Nunca** deduz um numero.

Coberto por `tests/test_profile_and_resume.py` e `tests/test_applications.py`.

---

## 5. Rede

- Somente APIs publicas, documentadas e sem autenticacao.
- Desabilitada por padrao (`JOB_SEARCH_ENABLE_NETWORK=false`).
- Timeout, teto de resultados e intervalo minimo entre requisicoes.
- User-Agent identificado — pratica correta ao consumir API publica alheia.
- Sem cookies, sem sessao, sem retry agressivo.

---

## 6. Segredos

- Configuracao vem de variaveis de ambiente / `.env`.
- `.env` esta no `.gitignore`.
- Nenhum segredo no codigo.
- O projeto nao precisa de nenhuma credencial para funcionar — nao ha o que
  vazar.

---

## Resumo

| Camada | Garantia | Onde e testada |
|---|---|---|
| Politica | Capacidades proibidas rejeitadas | `test_security.py` |
| Fluxo | Nada avanca sem aprovacao humana | `test_security.py`, `test_end_to_end.py` |
| Arquivos | Jail em `data/`, somente leitura | `test_sandbox.py` |
| Conteudo | Nenhum fato inventado | `test_profile_and_resume.py` |
| Rede | So API publica, com rate limit | `test_job_sources.py` |
| Dependencias | Sem automacao de navegador | `test_security.py` |

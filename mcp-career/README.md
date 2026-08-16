# MCP `career-agent`

Logica de carreira: perfil, score, personalizacao de curriculo, geracao de
candidatura e historico.

Adapter fino sobre `career_core`. Nenhuma regra de negocio mora aqui — as
ferramentas traduzem argumentos, chamam o dominio e formatam a resposta.

## Ferramentas

| Ferramenta | Para que serve |
|---|---|
| `get_candidate_profile` | Le o perfil estruturado. Chame antes de qualquer analise. |
| `analyze_job` | Normaliza + pontua + checa historico, tudo de uma vez. |
| `calculate_job_match` | So o score 0-100, explicado por dimensao. |
| `check_duplicate_application` | Verifica duplicidade por URL, empresa, cargo e similaridade. |
| `generate_application` | Monta o pacote completo para revisao. Nao registra nada. |
| `register_application` | Grava no historico em `pending_approval`. |
| `list_applications` | Lista com filtros de status, empresa e score. |
| `get_application` | Detalhe completo com historico. |
| `update_application_status` | Muda status respeitando a maquina de estados. |
| `get_safety_policy` | O que o agente nao faz, e por que. |
| `get_system_status` | Diagnostico: caminhos, perfil, curriculos, historico. |

## Garantias

- **Nada e enviado para fora.** Este servidor escreve em disco local e nada mais.
- **Nenhuma candidatura avanca sozinha.** `pending_approval` -> `approved`
  exige acao explicita da usuaria; `applied` so e alcancavel via `approved`.
- **Nenhum fato e inventado.** Todo texto gerado passa pelo `FactGuard`, que
  reprova afirmacao de experiencia em tecnologia ausente do perfil.

## Dependencias

Ver `requirements.txt`. Na pratica sao instaladas pelo `pyproject.toml` da
raiz — este arquivo existe para documentar o que este servidor usa.

## Execucao

Iniciado pelo Claude Desktop via stdio. Para depurar em primeiro plano:

```powershell
.\scripts\start.ps1 -Server career-agent
```

Logs em `logs\mcp-career.log` (e em stderr — nunca em stdout, que pertence ao
protocolo JSON-RPC).

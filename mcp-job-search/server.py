"""MCP `job-search` - obtencao e normalizacao de vagas.

Consulta apenas fontes que podem ser usadas de forma compativel com seus
termos: APIs publicas, documentadas e sem autenticacao. Fontes sem API
publica (LinkedIn, Indeed, Gupy) existem na abstracao, mas se declaram
indisponiveis e orientam o modo manual.

Este servidor NAO faz login, NAO usa cookies, NAO usa token de sessao, NAO
automatiza cliques e NAO faz scraping. Requisicoes HTTP saem com User-Agent
identificado e intervalo minimo entre chamadas.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from career_core.config import get_settings  # noqa: E402
from career_core.errors import CareerAgentError  # noqa: E402
from career_core.job_sources.base import JobQuery  # noqa: E402
from career_core.logging_setup import configure_logging  # noqa: E402
from career_core.mcp_compat import build_server  # noqa: E402
from career_core.models import Job  # noqa: E402
from career_core.services import CareerServices  # noqa: E402

SETTINGS = get_settings()
logger = configure_logging("mcp-job-search", SETTINGS.log_dir, SETTINGS.log_level)
services = CareerServices(SETTINGS)

mcp = build_server(
    "job-search",
    instructions=(
        "Busca e normalizacao de vagas em APIs publicas e documentadas. "
        "Nao faz login, nao usa cookies e nao automatiza portais. "
        "LinkedIn, Indeed e Gupy operam em modo manual."
    ),
)


def _guard(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except CareerAgentError as exc:
            logger.warning("%s: %s", func.__name__, exc)
            return f"ERRO: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha inesperada em %s", func.__name__)
            return f"ERRO INTERNO em {func.__name__}: {exc}"

    return wrapper


def _no_results_guidance() -> str:
    """Orientacao honesta quando as fontes automaticas nao entregam nada.

    Existe porque a limitacao e estrutural, nao um acaso da busca: nao ha API
    publica de vagas com boa cobertura do mercado brasileiro de .NET.
    """
    return (
        "SOBRE O MERCADO BRASILEIRO - leia antes de tentar de novo\n"
        "\n"
        "As fontes automaticas deste projeto tem cobertura fraca para vagas\n"
        ".NET no Brasil, e isso nao se resolve mudando os termos de busca:\n"
        "\n"
        "  - Remotive: o endpoint publico gratuito devolve um feed de amostra\n"
        "    (~14 vagas) e ignora o parametro de pesquisa.\n"
        "  - Arbeitnow: base quase toda europeia e presencial.\n"
        "  - LinkedIn, Indeed e Gupy - onde as vagas brasileiras realmente\n"
        "    estao - nao tem API publica de busca, e este projeto nao\n"
        "    automatiza login, cookies nem cliques.\n"
        "\n"
        "O CAMINHO QUE FUNCIONA (modo manual):\n"
        "  1. Busque no LinkedIn ou na Gupy pelo navegador, normalmente.\n"
        "  2. Copie a URL da vaga e o texto da descricao.\n"
        "  3. Cole aqui: 'Analise esta vaga: <URL>' + a descricao.\n"
        "\n"
        "A partir dai o agente faz tudo: score explicado por dimensao, gaps,\n"
        "curriculo personalizado, mensagem para o recrutador, respostas do\n"
        "formulario e registro no historico sem duplicata. E ai que esta o\n"
        "valor do sistema - a busca automatica e o pedaco fraco, a analise\n"
        "e o pedaco forte."
    )


def _format_job(job: Job, index: int, score_line: str = "") -> str:
    lines = [
        f"{index}. {job.title}",
        f"   Empresa......: {job.company or 'nao informada'}",
        f"   Senioridade..: {job.seniority.value}",
        f"   Modalidade...: {job.work_mode.value}",
        f"   Localizacao..: {job.location or 'nao informada'}",
        f"   Salario......: {job.salary_text or 'nao divulgado'}",
        f"   Fonte........: {job.source}",
    ]
    if score_line:
        lines.append(f"   {score_line}")
    if job.tech_tags:
        lines.append(f"   Tags.........: {', '.join(job.tech_tags[:12])}")
    if job.url:
        lines.append(f"   Link.........: {job.url}")
    return "\n".join(lines)


@mcp.tool()
@_guard
def search_jobs(
    keywords: str = "",
    location: str = "",
    work_modes: str = "",
    min_score: float = 0.0,
    limit: int = 20,
    sources: str = "",
) -> str:
    """Busca vagas nas fontes habilitadas e ja pontua cada uma contra o perfil.

    Use quando a usuaria pedir "procure vagas ...". Faz tudo de uma vez: busca
    nas fontes, normaliza o formato, remove duplicatas entre fontes, calcula o
    score de compatibilidade e ordena do maior para o menor.

    Por padrao a V1 usa a fonte `mock` (catalogo local ficticio, offline). Para
    vagas reais, habilite `JOB_SEARCH_ENABLE_NETWORK=true` no `.env` e inclua
    `remotive` e/ou `arbeitnow` em `JOB_SEARCH_SOURCES`.

    LinkedIn, Indeed e Gupy nao tem API publica de busca - pedi-las devolve
    instrucoes de modo manual, nao uma automacao proibida.

    Args:
        keywords: termos de busca, ex.: "backend .net c#".
        location: cidade/estado/pais, ex.: "Goiania" ou "Brasil".
        work_modes: filtro de modalidade separado por virgula:
            "remoto,hibrido".
        min_score: mostra apenas vagas com score maior ou igual a este valor.
        limit: maximo de vagas retornadas.
        sources: fontes especificas separadas por virgula. Vazio = as
            habilitadas no .env.
    """
    query = JobQuery(
        keywords=keywords,
        location=location,
        work_modes=tuple(m.strip() for m in work_modes.split(",") if m.strip()),
        limit=max(1, min(limit, 100)),
    )
    source_names = [s.strip().lower() for s in sources.split(",") if s.strip()] or None

    jobs, results = services.job_search.search(query, source_names)
    profile = services.profile()

    scored = [(job, services.scorer.score(job, profile)) for job in jobs]
    scored.sort(key=lambda pair: pair[1].total, reverse=True)

    threshold = min_score if min_score > 0 else 0.0
    visible = [(job, score) for job, score in scored if score.total >= threshold]

    lines = [
        "BUSCA DE VAGAS",
        "=" * 60,
        f"Termos.....: {keywords or '(todos)'}",
        f"Local......: {location or '(qualquer)'}",
        f"Modalidade.: {work_modes or '(qualquer)'}",
        f"Score min..: {threshold:g}",
        "",
        "Fontes consultadas:",
    ]
    for result in results:
        marker = "OK " if result.ok else "!! "
        lines.append(f"  {marker}{result.source}: {result.message}")

    lines.extend(["", "-" * 60, ""])

    if not visible:
        lines.append(
            f"Nenhuma vaga com score >= {threshold:g}."
            + (
                f" ({len(scored)} vaga(s) encontrada(s), todas abaixo do corte.)"
                if scored
                else ""
            )
        )
        if scored:
            best_job, best_score = scored[0]
            lines.extend(
                [
                    "",
                    f"Melhor resultado foi {best_score.total:g}/100:",
                    _format_job(best_job, 1),
                ]
            )
        lines.extend(["", "-" * 60, _no_results_guidance()])
        return "\n".join(lines)

    lines.append(f"{len(visible)} vaga(s) com score >= {threshold:g}, ordenadas:")
    lines.append("")

    for index, (job, score) in enumerate(visible, start=1):
        lines.append(
            _format_job(
                job,
                index,
                f"SCORE........: {score.total:g}/100 - {score.recommendation.value}",
            )
        )
        if score.gaps:
            lines.append(f"   Gaps.........: {', '.join(score.gaps[:6])}")
        lines.append("")

    lines.extend(
        [
            "-" * 60,
            "Para detalhar uma vaga: `analyze_job` (servidor career-agent).",
            "Para montar a candidatura: `generate_application`.",
            "Nada foi enviado a lugar nenhum - so leitura de vagas publicas.",
        ]
    )
    return "\n".join(lines)


@mcp.tool()
@_guard
def list_job_sources() -> str:
    """Lista todas as fontes de vagas, quais estao ativas e por que.

    Use quando a usuaria perguntar de onde vem as vagas, por que o LinkedIn
    nao aparece, ou como habilitar busca real.
    """
    registry = services.job_sources
    enabled = registry.enabled_names()

    lines = [
        "FONTES DE VAGAS",
        "=" * 60,
        f"Rede habilitada......: "
        f"{'sim' if SETTINGS.enable_network else 'nao (JOB_SEARCH_ENABLE_NETWORK=false)'}",
        f"Configuradas no .env.: {', '.join(SETTINGS.sources)}",
        f"Ativas agora.........: {', '.join(enabled)}",
        "",
    ]

    for info in registry.describe_all():
        status = "ATIVA" if info["name"] in enabled else (
            "disponivel" if info["usable"] else "INDISPONIVEL (modo manual)"
        )
        lines.extend(
            [
                f"[{status}] {info['name']}",
                f"   Requer rede: {'sim' if info['requires_network'] else 'nao'}",
                f"   {info['provenance']}",
                "",
            ]
        )

    lines.extend(
        [
            "-" * 60,
            "Para habilitar busca real, edite C:\\career-agent\\.env:",
            "   JOB_SEARCH_ENABLE_NETWORK=true",
            "   JOB_SEARCH_SOURCES=mock,remotive,arbeitnow",
            "e reinicie o Claude Desktop.",
            "",
            "LinkedIn, Indeed e Gupy continuam em modo manual - nao existe API",
            "publica de busca para candidatos, e este projeto nao automatiza",
            "login, cookies nem cliques nesses portais.",
        ]
    )
    return "\n".join(lines)


@mcp.tool()
@_guard
def get_manual_search_guide(portal: str = "linkedin", keywords: str = "") -> str:
    """Explica como trazer vagas de portais sem API publica (modo manual).

    Use quando a usuaria pedir vagas do LinkedIn, Indeed ou Gupy. Devolve o
    passo a passo: ela busca no navegador, copia URL e descricao, e o agente
    faz score, gaps, curriculo, mensagem e historico.

    Args:
        portal: linkedin | indeed | gupy.
        keywords: termos que ela quer buscar, usados no exemplo.
    """
    source = services.job_sources.get(portal.strip().lower())
    if source is None:
        return (
            f"Portal '{portal}' desconhecido. Disponiveis: "
            f"{', '.join(services.job_sources.available_names())}."
        )
    return source.search(JobQuery(keywords=keywords)).message


if __name__ == "__main__":
    logger.info(
        "Iniciando MCP job-search (rede=%s, fontes=%s)",
        SETTINGS.enable_network,
        SETTINGS.sources,
    )
    mcp.run()

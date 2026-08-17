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

from career_core.catalog.models import JobStatus  # noqa: E402
from career_core.catalog.repository import technology_links, to_catalog_job  # noqa: E402
from career_core.config import get_settings  # noqa: E402
from career_core.errors import CareerAgentError  # noqa: E402
from career_core.job_input import build_job_from_input  # noqa: E402
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


def _no_results_guidance(active_sources: list[str]) -> str:
    """Orientacao quando a busca nao devolve nada util.

    O conselho depende de quais fontes estao ligadas: com `ats` ativa existe
    caminho automatico de verdade; sem ela, so o modo manual resolve.
    """
    if "ats" not in active_sources:
        return (
            "COMO MELHORAR ESTA BUSCA\n"
            "\n"
            "A fonte com melhor cobertura de vagas .NET no Brasil ('ats') NAO\n"
            "esta ligada. Ela consulta os quadros de vagas publicos das proprias\n"
            "empresas (Greenhouse, Lever, Ashby) - sem login, sem scraping.\n"
            "\n"
            "Para ligar, edite C:\\career-agent\\.env:\n"
            "  JOB_SEARCH_ENABLE_NETWORK=true\n"
            "  JOB_SEARCH_SOURCES=mock,ats\n"
            "e reinicie o Claude Desktop.\n"
            "\n"
            "Remotive e Arbeitnow existem, mas nao ajudam: a Remotive devolve um\n"
            "feed de amostra que ignora a busca, e o Arbeitnow e quase todo\n"
            "europeu e presencial."
        )

    return (
        "COMO AMPLIAR A BUSCA\n"
        "\n"
        "A fonte 'ats' varre os quadros publicos das empresas configuradas. Se\n"
        "nao veio nada util, tente nesta ordem:\n"
        "\n"
        "  1. Palavras-chave mais amplas: 'backend', 'software engineer',\n"
        "     'desenvolvedor' - em vez de '.net c#'.\n"
        "  2. Baixe o score minimo para 60 e veja o que aparece.\n"
        "  3. Adicione empresas em JOB_SEARCH_ATS_COMPANIES no .env, no\n"
        "     formato 'greenhouse:empresa'. Descubra o slug abrindo a pagina de\n"
        "     carreiras da empresa: se a URL for job-boards.greenhouse.io/X,\n"
        "     jobs.lever.co/X ou jobs.ashbyhq.com/X, use 'greenhouse:X',\n"
        "     'lever:X' ou 'ashby:X'.\n"
        "\n"
        "E sempre vale o MODO MANUAL para LinkedIn e Gupy: copie a URL e a\n"
        "descricao da vaga e mande 'Analise esta vaga: <URL>'. O agente faz\n"
        "score, gaps, curriculo, mensagem e historico do mesmo jeito."
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
        lines.extend(["", "-" * 60, _no_results_guidance([r.source for r in results])])
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
def search_jobs_by_source(source: str, keywords: str = "", location: str = "", limit: int = 20) -> str:
    """Busca vagas em UMA fonte especifica, ignorando as demais.

    Use para diagnosticar ("a Stone tem vaga?" -> source=ats) ou quando a
    usuaria quiser resultados de uma origem so. Fontes: ats, mock, adzuna,
    remotive, arbeitnow. Para linkedin/indeed/gupy/jooble, devolve o guia do
    modo manual em vez de tentar automatizar.
    """
    return search_jobs(
        keywords=keywords, location=location, limit=limit, sources=source
    )


@mcp.tool()
@_guard
def run_job_search(
    keywords: str = "backend .net c#",
    location: str = "",
    min_score: float = 0.0,
    sources: str = "",
) -> str:
    """Executa o pipeline completo e SALVA as vagas no catalogo.

    Diferente de `search_jobs`, que so mostra: aqui as vagas sao persistidas,
    deduplicadas contra o que ja foi coletado antes, pontuadas e classificadas.
    A execucao fica registrada no historico de buscas.

    Use quando a usuaria pedir para "rodar a busca", "atualizar as vagas" ou
    quando quiser que os resultados fiquem disponiveis depois em
    `list_matching_jobs` e no dashboard.
    """
    profile = services.profile()
    threshold = min_score if min_score > 0 else float(SETTINGS.min_score)

    query = JobQuery(
        keywords=keywords,
        location=location,
        limit=SETTINGS.max_results,
    )
    source_names = [s.strip().lower() for s in sources.split(",") if s.strip()] or None

    result = services.pipeline.run(profile, query, source_names, minimum_score=threshold)

    lines = ["PIPELINE DE BUSCA", "=" * 60, result.summary(), ""]

    if result.relevant:
        lines.append(f"VAGAS RELEVANTES (score >= {threshold:g}):")
        lines.append("")
        for index, job in enumerate(result.relevant[:15], start=1):
            lines.append(
                f"{index}. [{job.id}] {job.title}\n"
                f"   {job.company} | {job.match_score:g}/100 | "
                f"{job.work_model.value} | {job.location or 'n/d'}\n"
                f"   {job.url}"
            )
            if job.gaps:
                lines.append(f"   Gaps: {', '.join(job.gaps[:5])}")
        lines.append("")
        lines.append(
            "Para detalhar: `get_job` com o ID. Para preparar candidatura: "
            "`generate_application` (servidor career-agent)."
        )
    else:
        lines.append(f"Nenhuma vaga nova com score >= {threshold:g}.")
        lines.append("")
        lines.append(_no_results_guidance([r for r in result.execution.sources]))

    return "\n".join(lines)


@mcp.tool()
@_guard
def list_matching_jobs(
    min_score: float = 0.0, status: str = "", source: str = "", limit: int = 20
) -> str:
    """Lista as vagas JA COLETADAS no catalogo, ordenadas por compatibilidade.

    Nao vai a rede - le o que o pipeline ja salvou. Use para "quais as
    melhores vagas que voce achou", "mostre as vagas com score acima de 80",
    "quais vagas estao marcadas como interessantes".

    Args:
        min_score: score minimo (0 = todas).
        status: Found | Analyzed | Interested | Applied | Interview |
            Rejected | Discarded. Vazio = todos menos descartadas.
        source: filtra pela fonte de origem.
        limit: maximo de resultados.
    """
    parsed_status = None
    if status.strip():
        try:
            parsed_status = JobStatus(status.strip().capitalize())
        except ValueError:
            valid = ", ".join(s.value for s in JobStatus)
            return f"ERRO: status '{status}' invalido. Validos: {valid}."

    jobs = services.catalog.list_jobs(
        status=parsed_status,
        min_score=min_score if min_score > 0 else None,
        source=source or None,
        limit=limit,
    )
    if not parsed_status:
        jobs = [j for j in jobs if j.status is not JobStatus.DISCARDED]

    if not jobs:
        total = services.catalog.count()
        if total == 0:
            return (
                "O catalogo esta vazio. Rode `run_job_search` para coletar vagas."
            )
        return (
            f"Nenhuma vaga bate com os filtros ({total} no catalogo). "
            f"Tente baixar o `min_score` ou limpar o filtro de status."
        )

    lines = [f"{len(jobs)} vaga(s) no catalogo", "=" * 60, ""]
    for index, job in enumerate(jobs, start=1):
        lines.append(
            f"{index}. [{job.id}] {job.title}\n"
            f"   Empresa....: {job.company or 'n/d'}\n"
            f"   Score......: {job.match_score:g}/100 ({job.recommendation.value})\n"
            f"   Status.....: {job.status.value}\n"
            f"   Modalidade.: {job.work_model.value} | {job.location or 'n/d'}\n"
            f"   Fonte......: {job.source} | coletada em {job.collected_at[:10]}\n"
            f"   Link.......: {job.url}"
        )
        if job.gaps:
            lines.append(f"   Gaps.......: {', '.join(job.gaps[:5])}")
        lines.append("")

    counts = services.catalog.count_by_status()
    lines.append("-" * 60)
    lines.append("Catalogo por status: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return "\n".join(lines)


@mcp.tool()
@_guard
def get_job(job_id: str) -> str:
    """Mostra uma vaga do catalogo em detalhe, com o score explicado.

    Use quando a usuaria pedir detalhes de uma vaga listada por
    `list_matching_jobs` ou `run_job_search`.
    """
    job = services.catalog.get_job(job_id.strip())
    lines = [
        f"VAGA [{job.id}]",
        "=" * 60,
        f"Cargo........: {job.title}",
        f"Empresa......: {job.company or 'nao informada'}",
        f"Senioridade..: {job.seniority.value}",
        f"Modalidade...: {job.work_model.value}",
        f"Localizacao..: {job.location or 'nao informada'}",
        f"Salario......: {job.salary or 'nao divulgado'}",
        f"Fonte........: {job.source}",
        f"Publicada em.: {job.published_at[:10] or 'n/d'}",
        f"Coletada em..: {job.collected_at[:19]}",
        f"Status.......: {job.status.value}",
        f"Link.........: {job.url}",
        "",
        job.score_explanation or f"Score: {job.match_score:g}/100",
    ]
    if job.application_id:
        lines.extend(["", f"Candidatura vinculada: {job.application_id}"])
    if job.description:
        lines.extend(["", "-" * 60, "DESCRICAO:", job.description[:3000]])
        if len(job.description) > 3000:
            lines.append(f"... (+{len(job.description) - 3000} caracteres)")
    return "\n".join(lines)


@mcp.tool()
@_guard
def save_job(
    title: str,
    company: str = "",
    url: str = "",
    description: str = "",
    location: str = "",
    work_mode: str = "",
    seniority: str = "",
    salary_text: str = "",
    status: str = "Interested",
) -> str:
    """Salva no catalogo uma vaga que a usuaria encontrou manualmente.

    Use quando ela colar uma vaga do LinkedIn, Gupy ou Indeed e quiser
    guarda-la. A vaga e pontuada e deduplicada contra o catalogo, igual as
    coletadas automaticamente.

    Args:
        status: Found | Analyzed | Interested | Discarded. Padrao Interested,
            porque salvar manualmente ja indica interesse.
    """
    profile = services.profile()
    job = build_job_from_input(
        title=title, description=description, company=company, url=url,
        location=location, work_mode=work_mode or None,
        seniority=seniority or None, salary_text=salary_text, source="manual",
    )
    score = services.scorer.score(job, profile)
    catalog_job = to_catalog_job(job, score)

    try:
        catalog_job.status = JobStatus(status.strip().capitalize())
    except ValueError:
        catalog_job.status = JobStatus.INTERESTED

    saved, is_new = services.catalog.upsert_job(catalog_job)
    services.catalog.record_technologies(saved.id, technology_links(saved.id, score))

    prefix = "VAGA SALVA" if is_new else "VAGA JA EXISTIA (atualizada)"
    return "\n".join(
        [
            prefix,
            "=" * 60,
            f"ID.......: {saved.id}",
            f"Cargo....: {saved.title}",
            f"Empresa..: {saved.company or 'n/d'}",
            f"Score....: {saved.match_score:g}/100 ({saved.recommendation.value})",
            f"Status...: {saved.status.value}",
            "",
            "" if is_new else "O status e a candidatura vinculada foram preservados.",
            score.explanation,
        ]
    )


@mcp.tool()
@_guard
def update_job_status(job_id: str, status: str) -> str:
    """Muda o status de uma vaga do catalogo.

    Found | Analyzed | Interested | Applied | Interview | Rejected | Discarded.

    ATENCAO: marcar como `Applied` significa que VOCE ja se candidatou no site.
    O agente nunca se candidata sozinho - ele apenas registra o que voce fez.
    """
    try:
        target = JobStatus(status.strip().capitalize())
    except ValueError:
        valid = ", ".join(s.value for s in JobStatus)
        return f"ERRO: status '{status}' invalido. Validos: {valid}."

    job = services.catalog.update_status(job_id.strip(), target)
    extra = ""
    if target is JobStatus.APPLIED:
        extra = (
            "\n\nRegistrado que VOCE se candidatou. Se ainda nao preparou o "
            "material, use `generate_application` antes de enviar."
        )
    return f"[{job.id}] {job.company} - {job.title}\nStatus => {job.status.value}{extra}"


@mcp.tool()
@_guard
def search_companies(name: str = "", limit: int = 30) -> str:
    """Lista as empresas presentes no catalogo, com quantas vagas cada uma teve.

    Use para "quais empresas voce ja encontrou", "a Stone tem vaga?" ou para
    descobrir onde vale adicionar um quadro de ATS.
    """
    companies = services.catalog.list_companies(search=name, limit=limit)
    if not companies:
        return (
            f"Nenhuma empresa encontrada{f' para {name!r}' if name else ''}. "
            f"Rode `run_job_search` para popular o catalogo."
        )

    lines = [f"{len(companies)} empresa(s)", "=" * 60, ""]
    for company in companies:
        lines.append(f"  {company.jobs_count:4d} vaga(s)  {company.name}")
    return "\n".join(lines)


@mcp.tool()
@_guard
def get_search_history(limit: int = 10) -> str:
    """Mostra o historico de execucoes do pipeline de busca.

    Use para "quando foi a ultima busca", "o que a busca de hoje encontrou"
    ou para diagnosticar por que uma fonte parou de trazer vagas.
    """
    executions = services.catalog.list_executions(limit=limit)
    if not executions:
        return "Nenhuma busca executada ainda. Rode `run_job_search`."

    lines = [f"{len(executions)} execucao(oes)", "=" * 60, ""]
    for execution in executions:
        duration = execution.duration_seconds()
        lines.append(
            f"[{execution.id}] {execution.started_at[:19]} - {execution.status}\n"
            f"   Termos...: {execution.query or '(todos)'}\n"
            f"   Fontes...: {', '.join(execution.sources) or 'n/d'}\n"
            f"   Coletadas: {execution.jobs_found} "
            f"({execution.jobs_new} novas, {execution.jobs_duplicated} ja conhecidas)\n"
            f"   Relevantes: {execution.jobs_above_threshold} "
            f"(score >= {execution.minimum_score:g}) | melhor: {execution.best_score:g}"
            + (f"\n   Duracao..: {duration:g}s" if duration is not None else "")
        )
        for error in execution.errors[:3]:
            lines.append(f"   ! {error[:120]}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
@_guard
def get_catalog_statistics() -> str:
    """Estatisticas do catalogo: vagas por status, tecnologias mais exigidas
    e desempenho das fontes.

    Use para "como esta minha busca", "quais tecnologias aparecem mais nas
    vagas" ou para decidir o que estudar em seguida.
    """
    counts = services.catalog.count_by_status()
    total = services.catalog.count()

    lines = ["ESTATISTICAS DO CATALOGO", "=" * 60, f"Total de vagas: {total}", ""]
    if counts:
        lines.append("Por status:")
        for status_name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {status_name:12s} {count:4d}")

    technologies = services.catalog.top_technologies(15)
    if technologies:
        lines.extend(["", "Tecnologias mais exigidas:"])
        for name, required, matched in technologies:
            marker = "voce tem" if matched else "GAP"
            lines.append(f"  {name:24s} {required:3d} vaga(s)   [{marker}]")
        gaps = [t for t in technologies if not t[2]]
        if gaps:
            lines.extend(
                [
                    "",
                    "Maiores gaps do mercado em relacao ao seu perfil: "
                    + ", ".join(t[0] for t in gaps[:6]),
                    "(sao candidatos naturais para o proximo estudo)",
                ]
            )

    sources = services.catalog.list_sources()
    if sources:
        lines.extend(["", "Fontes:"])
        for source in sources:
            lines.append(
                f"  {source.name:16s} {source.jobs_collected:5d} vaga(s) coletadas"
                + (f" | ultimo erro: {source.last_error[:60]}" if source.last_error else "")
            )
    return "\n".join(lines)


@mcp.tool()
@_guard
def get_scoring_config() -> str:
    """Mostra os pesos e as faixas de score em vigor, e onde edita-los.

    Use quando a usuaria perguntar como o score e calculado ou quiser
    ajustar a importancia de algum criterio.
    """
    config = services.scoring_config
    path = SETTINGS.data_root / "config" / "scoring.json"
    return "\n".join(
        [
            "CONFIGURACAO DO SCORE",
            "=" * 60,
            config.as_text(),
            "",
            f"Arquivo: {path}",
            "Edite os pesos, salve e reinicie o Claude Desktop. Eles devem somar "
            "100 - se nao somarem, o score e normalizado automaticamente.",
        ]
    )


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

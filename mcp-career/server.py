"""MCP `career-agent` - logica de carreira.

Adapter fino sobre `career_core`. Cada ferramenta traduz argumentos, chama o
dominio e devolve texto legivel para o Claude. Nenhuma regra de negocio mora
aqui.

Nenhuma ferramenta deste servidor envia nada para fora. Ele prepara material
e registra historico; a acao externa e sempre da usuaria.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Bootstrap: torna `career_core` importavel sem instalacao previa.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from career_core.applications.repository import SqliteApplicationRepository  # noqa: E402
from career_core.config import get_settings  # noqa: E402
from career_core.errors import CareerAgentError  # noqa: E402
from career_core.job_input import build_job_from_input  # noqa: E402
from career_core.logging_setup import configure_logging  # noqa: E402
from career_core.mcp_compat import build_server  # noqa: E402
from career_core.models import Application, ApplicationStatus, DuplicateVerdict  # noqa: E402
from career_core.security import SAFETY_POLICY  # noqa: E402
from career_core.services import CareerServices  # noqa: E402

SETTINGS = get_settings()
logger = configure_logging("mcp-career", SETTINGS.log_dir, SETTINGS.log_level)
services = CareerServices(SETTINGS)

mcp = build_server(
    "career-agent",
    instructions=(
        "Logica de carreira: perfil, score de compatibilidade, personalizacao "
        "legitima de curriculo, geracao de candidatura e historico. "
        "Nunca afirme experiencia que nao esteja no perfil. "
        "Nunca envie nada para fora - toda acao externa depende de aprovacao "
        "humana explicita."
    ),
)


# ---------------------------------------------------------------------------
# Helpers de apresentacao
# ---------------------------------------------------------------------------


def _guard(func):
    """Converte erros de dominio em mensagens uteis; loga bugs de verdade."""
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
            return (
                f"ERRO INTERNO em {func.__name__}: {exc}\n"
                f"Detalhes em {SETTINGS.log_dir / 'mcp-career.log'}."
            )

    return wrapper


def _format_application(app: Application, detailed: bool = False) -> str:
    lines = [
        f"[{app.id}] {app.company} - {app.role}",
        f"  Status.......: {app.status.value}",
        f"  Score........: {app.score:g}/100 ({app.recommendation.value})",
        f"  Modalidade...: {app.work_mode.value}",
        f"  Localizacao..: {app.location or 'nao informada'}",
        f"  Salario......: {app.salary_text or 'nao divulgado'}",
        f"  Criada em....: {app.created_at[:19]}",
    ]
    if app.job_url:
        lines.append(f"  Link.........: {app.job_url}")

    if not detailed:
        return "\n".join(lines)

    lines.append("")
    lines.append("  Detalhamento do score:")
    for dimension in app.score_breakdown:
        lines.append(
            f"    {dimension.label}: {dimension.points:g}/{dimension.max_points:g}"
            f"  - {dimension.rationale}"
        )

    if app.matched_technologies:
        lines.extend(["", "  Tecnologias compativeis:", f"    {', '.join(app.matched_technologies)}"])
    if app.gaps:
        lines.extend(["", "  Gaps:"] + [f"    - {gap}" for gap in app.gaps])
    if app.key_requirements:
        lines.extend(["", "  Principais requisitos da vaga:"])
        lines.extend(f"    - {req}" for req in app.key_requirements)

    lines.extend(["", f"  Curriculo recomendado: {app.recommended_resume}"])
    lines.extend(["", "  Resumo personalizado:", f"    {app.tailored_summary}"])
    lines.extend(["", "  Mensagem para o recrutador (RASCUNHO):"])
    lines.extend(f"    {line}" for line in app.recruiter_message.splitlines())

    if app.suggested_answers:
        lines.extend(["", "  Respostas sugeridas (RASCUNHO):"])
        for answer in app.suggested_answers:
            lines.append(f"    P: {answer.question}")
            lines.append(f"    R: {answer.answer}")
            lines.append("")

    if app.notes:
        lines.extend(["  Notas internas:"])
        lines.extend(f"    {line}" for line in app.notes.splitlines())

    if app.history:
        lines.extend(["", "  Historico:"])
        for event in app.history:
            note = f" - {event.note}" if event.note else ""
            lines.append(f"    {event.at[:19]} -> {event.status.value}{note}")

    lines.append("")
    lines.append(
        f"  Proximos status validos: "
        f"{', '.join(services.approval_gate.next_states(app.status)) or '(nenhum - estado final)'}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------


@mcp.tool()
@_guard
def get_candidate_profile() -> str:
    """Le o perfil profissional completo da candidata.

    Use SEMPRE antes de analisar vagas, calcular score, personalizar curriculo
    ou escrever mensagens. O perfil e a unica fonte de verdade sobre o que a
    candidata sabe e quer: nada fora dele pode ser afirmado como experiencia
    dela. Retorna stack, arquitetura, dominios, cargos-alvo, senioridade
    desejada, senioridades a evitar, modalidade, localizacao e faixa salarial.
    """
    profile = services.profile()
    lines = [
        "PERFIL DA CANDIDATA",
        "=" * 60,
        f"Nome................: {profile.full_name or '(nao preenchido)'}",
        f"Titulo..............: {profile.headline or '(nao preenchido)'}",
        f"Anos de experiencia.: "
        f"{profile.years_experience if profile.years_experience is not None else 'nao declarado (nao infira)'}",
        "",
        "Resumo profissional:",
        profile.summary or "(nao preenchido)",
        "",
        f"Tecnologias ({len(profile.skills)}):",
        "  " + (", ".join(profile.skills) or "(vazio)"),
        "",
        f"Arquitetura ({len(profile.architecture)}):",
        "  " + (", ".join(profile.architecture) or "(vazio)"),
        "",
        f"Dominios ({len(profile.domains)}):",
        "  " + (", ".join(profile.domains) or "(vazio)"),
        "",
        "PREFERENCIAS",
        "-" * 60,
        f"Cargos-alvo.........: {', '.join(profile.target_roles) or '(vazio)'}",
        f"Senioridade desejada: {', '.join(profile.preferred_seniorities) or '(vazio)'}",
        f"Senioridade a EVITAR: {', '.join(profile.avoid_seniorities) or '(vazio)'}",
        f"Modalidade (ordem)..: {' > '.join(profile.work_mode_priority) or '(vazio)'}",
        f"Paises..............: {', '.join(profile.countries) or '(vazio)'}",
        f"Cidades.............: {', '.join(profile.preferred_cities) or '(vazio)'}",
        f"Salario minimo......: "
        f"{f'R$ {profile.min_salary_brl:,.0f}'.replace(',', '.') if profile.min_salary_brl else 'nao definido'}",
        f"Salario alvo........: "
        f"{f'R$ {profile.target_salary_brl:,.0f}'.replace(',', '.') if profile.target_salary_brl else 'nao definido'}",
        f"Empresas preferidas.: {', '.join(profile.preferred_companies) or '(vazio)'}",
        f"Empresas bloqueadas.: {', '.join(profile.blocked_companies) or '(vazio)'}",
        "",
        "REGRA: nao afirme experiencia em nada que nao esteja acima. "
        "Tecnologia exigida pela vaga e ausente daqui e GAP, nunca experiencia.",
    ]
    return "\n".join(lines)


@mcp.tool()
@_guard
def analyze_job(
    title: str,
    description: str = "",
    company: str = "",
    url: str = "",
    location: str = "",
    work_mode: str = "",
    seniority: str = "",
    salary_text: str = "",
) -> str:
    """Analisa uma vaga: normaliza, pontua, aponta gaps e checa duplicidade.

    Use quando a usuaria colar uma vaga ou pedir "analise a vaga X". Funciona
    com qualquer origem (LinkedIn, Gupy, Indeed, e-mail de recrutador) - basta
    colar o texto. Faz tudo de uma vez: detecta senioridade e modalidade,
    calcula o score 0-100 explicado por dimensao, lista tecnologias compativeis
    e gaps, e avisa se ja existe candidatura semelhante no historico.

    Args:
        title: cargo da vaga. Obrigatorio.
        description: texto completo da descricao. Quanto mais completo, melhor
            o score. Aceita HTML - e limpo automaticamente.
        company: nome da empresa.
        url: link da vaga (usado para detectar duplicidade).
        location: cidade/estado/pais da vaga.
        work_mode: remoto | hibrido | presencial. Se vazio, e detectado do texto.
        seniority: estagio | trainee | junior | pleno | senior | especialista |
            lead. Se vazio, e detectado do texto.
        salary_text: faixa salarial, ex.: "R$ 12.000 a R$ 15.000".
    """
    profile = services.profile()
    job = build_job_from_input(
        title=title,
        description=description,
        company=company,
        url=url,
        location=location,
        work_mode=work_mode or None,
        seniority=seniority or None,
        salary_text=salary_text,
    )
    score = services.scorer.score(job, profile)
    duplicate = services.duplicates.check(job.company, job.title, job.url)

    lines = [
        f"ANALISE DA VAGA",
        "=" * 60,
        f"Cargo........: {job.title}",
        f"Empresa......: {job.company or 'nao informada'}",
        f"Senioridade..: {job.seniority.value}"
        + ("  (detectada do texto)" if not seniority else "  (informada)"),
        f"Modalidade...: {job.work_mode.value}"
        + ("  (detectada do texto)" if not work_mode else "  (informada)"),
        f"Localizacao..: {job.location or 'nao informada'}",
        f"Salario......: {job.salary_text or 'nao divulgado'}",
        "",
        score.explanation,
        "",
        "-" * 60,
        "HISTORICO / DUPLICIDADE",
        duplicate.message,
    ]

    if score.recommendation.value != "DESCARTAR" and not duplicate.is_blocking:
        lines.extend(
            [
                "",
                "-" * 60,
                "PROXIMO PASSO: se a usuaria aprovar, chame `generate_application` "
                "com os mesmos dados para montar o pacote completo (curriculo "
                "personalizado, mensagem e respostas).",
            ]
        )
    return "\n".join(lines)


@mcp.tool()
@_guard
def calculate_job_match(
    title: str,
    description: str = "",
    company: str = "",
    location: str = "",
    work_mode: str = "",
    seniority: str = "",
    salary_text: str = "",
) -> str:
    """Calcula SOMENTE o score de compatibilidade 0-100 de uma vaga.

    Use para comparar varias vagas rapidamente ou quando a usuaria pedir
    "qual o score dessa vaga". Nao consulta historico nem gera material -
    para isso use `analyze_job`.

    Pesos: Stack 30 | Senioridade 20 | Salario 15 | Modalidade 10 |
    Localizacao 10 | Experiencia 10 | Empresa 5.
    Classificacao: 90-100 PRIORIDADE ALTA | 80-89 PRIORIDADE |
    70-79 ANALISAR | 0-69 DESCARTAR.

    Vagas com senioridade na lista de exclusao do perfil (estagio/trainee/
    junior) ou de empresa bloqueada sao eliminadas automaticamente.
    """
    profile = services.profile()
    job = build_job_from_input(
        title=title,
        description=description,
        company=company,
        location=location,
        work_mode=work_mode or None,
        seniority=seniority or None,
        salary_text=salary_text,
    )
    return services.scorer.score(job, profile).explanation


@mcp.tool()
@_guard
def check_duplicate_application(company: str, role: str, job_url: str = "") -> str:
    """Verifica se ja existe candidatura igual ou parecida no historico.

    Use ANTES de recomendar ou registrar qualquer vaga. Compara, nesta ordem:
    URL normalizada (ignora parametros de tracking), empresa normalizada
    (ignora Ltda/S.A.), cargo normalizado (ignora senioridade e modalidade),
    similaridade textual do cargo, e candidaturas recentes na mesma empresa.

    Veredictos: `duplicate` (nao registrar de novo), `similar` (revisar, nao
    bloqueia), `none` (livre).
    """
    result = services.duplicates.check(company, role, job_url)
    return f"Veredicto: {result.verdict.value}\n\n{result.message}"


@mcp.tool()
@_guard
def generate_application(
    title: str,
    description: str = "",
    company: str = "",
    url: str = "",
    location: str = "",
    work_mode: str = "",
    seniority: str = "",
    salary_text: str = "",
    resume: str = "",
    extra_questions: str = "",
) -> str:
    """Monta o pacote completo de candidatura para revisao da usuaria.

    Gera: score detalhado, principais requisitos, tecnologias compativeis,
    gaps, curriculo recomendado, resumo profissional adaptado, mensagem para
    o recrutador e respostas sugeridas para o formulario.

    A personalizacao do curriculo e LEGITIMA: apenas reordena, destaca e
    adapta palavras-chave para itens que JA constam no perfil. Uma auditoria
    automatica (FactGuard) reprova qualquer texto que afirme experiencia em
    tecnologia ausente do perfil.

    Este comando NAO registra nada e NAO envia nada. Apresente o resultado a
    usuaria; se ela aprovar, chame `register_application`.

    Args:
        resume: nome do curriculo a personalizar. Vazio = escolha automatica.
        extra_questions: perguntas do formulario da vaga, uma por linha.
    """
    profile = services.profile()
    job = build_job_from_input(
        title=title,
        description=description,
        company=company,
        url=url,
        location=location,
        work_mode=work_mode or None,
        seniority=seniority or None,
        salary_text=salary_text,
    )
    score = services.scorer.score(job, profile)
    questions = [q.strip() for q in (extra_questions or "").splitlines() if q.strip()]

    builder = services.application_builder(profile)
    application, tailored = builder.build(
        job, score, resume_filename=resume or None, extra_questions=questions
    )
    duplicate = services.duplicates.check(job.company, job.title, job.url)

    lines = [
        "PACOTE DE CANDIDATURA (rascunho - NAO registrado ainda)",
        "=" * 60,
        _format_application(application, detailed=True),
        "",
        "-" * 60,
        "HISTORICO / DUPLICIDADE",
        duplicate.message,
        "",
        "-" * 60,
        "AUDITORIA FACTUAL",
        tailored.guard.as_text(),
    ]
    if tailored.gaps_not_claimed:
        lines.append(
            f"Gaps tratados como gap (nunca como experiencia): "
            f"{', '.join(tailored.gaps_not_claimed)}"
        )

    lines.extend(
        [
            "",
            "=" * 60,
            "AGUARDANDO APROVACAO DA USUARIA.",
            "Mostre este pacote a ela. Se ela aprovar, chame "
            "`register_application` com estes mesmos dados - a candidatura "
            "sera criada em `pending_approval`.",
            "Nada foi enviado a lugar nenhum. O clique final e sempre dela.",
        ]
    )
    return "\n".join(lines)


@mcp.tool()
@_guard
def register_application(
    title: str,
    description: str = "",
    company: str = "",
    url: str = "",
    location: str = "",
    work_mode: str = "",
    seniority: str = "",
    salary_text: str = "",
    resume: str = "",
    extra_questions: str = "",
    allow_duplicate: bool = False,
) -> str:
    """Registra a candidatura no historico com status `pending_approval`.

    Chame apenas DEPOIS de mostrar o pacote (`generate_application`) e a
    usuaria confirmar que quer registrar. A candidatura NAO fica aprovada:
    ela nasce em `pending_approval` e so vai para `approved` quando a usuaria
    pedir explicitamente via `update_application_status`.

    Se houver duplicidade, o registro e RECUSADO. Para forcar, chame de novo
    com `allow_duplicate=true` - mas so depois de avisar a usuaria.
    """
    profile = services.profile()
    job = build_job_from_input(
        title=title,
        description=description,
        company=company,
        url=url,
        location=location,
        work_mode=work_mode or None,
        seniority=seniority or None,
        salary_text=salary_text,
    )

    duplicate = services.duplicates.check(job.company, job.title, job.url)
    if duplicate.is_blocking and not allow_duplicate:
        return (
            "REGISTRO RECUSADO - candidatura duplicada.\n\n"
            f"{duplicate.message}\n\n"
            "Avise a usuaria. Se ela quiser registrar mesmo assim, chame de "
            "novo com allow_duplicate=true."
        )

    score = services.scorer.score(job, profile)
    questions = [q.strip() for q in (extra_questions or "").splitlines() if q.strip()]

    builder = services.application_builder(profile)
    application, _ = builder.build(
        job, score, resume_filename=resume or None, extra_questions=questions
    )
    if duplicate.verdict is not DuplicateVerdict.NONE:
        application.notes += f"\n[duplicidade: {duplicate.verdict.value}]"

    saved = services.applications.add(application)

    return "\n".join(
        [
            "CANDIDATURA REGISTRADA",
            "=" * 60,
            _format_application(saved),
            "",
            f"Status inicial: {saved.status.value}",
            "",
            "A candidatura esta AGUARDANDO SUA APROVACAO. Ela nao avanca "
            "sozinha. Quando voce aprovar, eu mudo para `approved`; depois que "
            "VOCE se candidatar no site, mude para `applied`.",
            "",
            f"ID para os proximos comandos: {saved.id}",
        ]
    )


@mcp.tool()
@_guard
def list_applications(
    status: str = "", company: str = "", min_score: float = 0.0, limit: int = 50
) -> str:
    """Lista candidaturas do historico, com filtros opcionais.

    Use para "mostre minhas candidaturas", "quais estao aguardando aprovacao"
    (status=pending_approval), "quais estao em entrevista" (status=interview).

    Args:
        status: pending_approval | approved | applied | interview |
            technical_test | offer | rejected | withdrawn. Vazio = todas.
        company: filtra por empresa.
        min_score: score minimo.
        limit: maximo de resultados (padrao 50).
    """
    parsed_status = None
    if status.strip():
        try:
            parsed_status = ApplicationStatus(status.strip().lower())
        except ValueError:
            valid = ", ".join(s.value for s in ApplicationStatus)
            return f"ERRO: status '{status}' invalido. Validos: {valid}."

    applications = services.applications.list(
        status=parsed_status,
        company=company or None,
        min_score=min_score if min_score > 0 else None,
        limit=limit,
    )

    if not applications:
        filters = []
        if parsed_status:
            filters.append(f"status={parsed_status.value}")
        if company:
            filters.append(f"empresa={company}")
        if min_score > 0:
            filters.append(f"score>={min_score:g}")
        suffix = f" com {', '.join(filters)}" if filters else ""
        return f"Nenhuma candidatura encontrada{suffix}."

    header = f"{len(applications)} candidatura(s)"
    if parsed_status:
        header += f" com status '{parsed_status.value}'"

    blocks = [header, "=" * 60, ""]
    for application in applications:
        blocks.append(_format_application(application))
        blocks.append("")

    counts: dict[str, int] = {}
    for application in services.applications.all():
        counts[application.status.value] = counts.get(application.status.value, 0) + 1
    blocks.append("-" * 60)
    blocks.append(
        "Total por status: "
        + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    )
    return "\n".join(blocks)


@mcp.tool()
@_guard
def get_application(application_id: str) -> str:
    """Mostra uma candidatura completa: score detalhado, gaps, curriculo
    recomendado, resumo adaptado, mensagem para o recrutador, respostas
    sugeridas e todo o historico de status.

    Use quando a usuaria pedir detalhes de uma candidatura especifica ou
    quando precisar recuperar a mensagem/respostas ja geradas.
    """
    application = services.applications.get(application_id.strip())
    return _format_application(application, detailed=True)


@mcp.tool()
@_guard
def update_application_status(
    application_id: str, status: str, note: str = ""
) -> str:
    """Altera o status de uma candidatura, respeitando a maquina de estados.

    Fluxo: pending_approval -> approved -> applied -> interview /
    technical_test -> offer. `rejected` e `withdrawn` sao finais.

    GARANTIA DE SEGURANCA: nao existe caminho de `pending_approval` direto para
    `applied`. Toda candidatura precisa passar por `approved`, que so acontece
    quando a usuaria pede. Se ela disser "aprove a candidatura X", use
    status=approved.

    Args:
        application_id: ID da candidatura (formato `app-xxxxxxxxxx`).
        status: novo status.
        note: observacao livre, guardada no historico.
    """
    try:
        target = ApplicationStatus(status.strip().lower())
    except ValueError:
        valid = ", ".join(s.value for s in ApplicationStatus)
        return f"ERRO: status '{status}' invalido. Validos: {valid}."

    application = services.applications.update_status(
        application_id.strip(), target, note
    )
    lines = [
        f"Status atualizado: {application.company} - {application.role}",
        f"  {application.id} => {application.status.value}",
    ]
    if note:
        lines.append(f"  Nota: {note}")
    if target is ApplicationStatus.APPROVED:
        lines.extend(
            [
                "",
                "Aprovada. Agora VOCE se candidata no site da vaga usando o "
                "material gerado (`get_application` mostra tudo).",
                "Depois de se candidatar, me avise para eu marcar como `applied`.",
            ]
        )
    lines.append("")
    lines.append(
        f"Proximos status validos: "
        f"{', '.join(services.approval_gate.next_states(application.status)) or '(estado final)'}"
    )
    return "\n".join(lines)


@mcp.tool()
@_guard
def get_safety_policy() -> str:
    """Mostra a politica de seguranca do Career Agent.

    Use se a usuaria perguntar se o agente pode se candidatar sozinho, fazer
    login, enviar mensagem no LinkedIn ou automatizar cliques. A resposta e
    nao - e este documento explica o que e feito no lugar disso.
    """
    return SAFETY_POLICY


@mcp.tool()
@_guard
def get_system_status() -> str:
    """Diagnostico do Career Agent: caminhos, perfil, curriculos e historico.

    Use quando algo parecer errado (perfil vazio, curriculo nao encontrado) ou
    quando a usuaria perguntar se esta tudo configurado.
    """
    lines = [
        "STATUS DO CAREER AGENT",
        "=" * 60,
        f"Raiz de dados....: {SETTINGS.data_root}",
        f"Banco............: {SETTINGS.database_path}",
        f"Espelho JSON.....: {SETTINGS.json_mirror_path}",
        f"Logs.............: {SETTINGS.log_dir}",
        f"Score minimo.....: {SETTINGS.min_score}",
        "",
    ]

    try:
        profile = services.profile()
        pending = [
            name
            for name, value in (
                ("nome", profile.full_name),
                ("salario minimo", profile.min_salary_brl),
            )
            if not value or "[PREENCHER]" in str(value)
        ]
        lines.append(
            f"Perfil...........: OK ({len(profile.skills)} tecnologias, "
            f"{len(profile.architecture)} itens de arquitetura, "
            f"{len(profile.domains)} dominios)"
        )
        if pending:
            lines.append(f"  A preencher: {', '.join(pending)}")
    except CareerAgentError as exc:
        lines.append(f"Perfil...........: FALHOU - {exc}")

    try:
        resumes = services.tailor().list_resumes()
        lines.append(f"Curriculos.......: {', '.join(resumes) or '(nenhum)'}")
    except CareerAgentError as exc:
        lines.append(f"Curriculos.......: FALHOU - {exc}")

    repository = services.applications
    total = repository.count() if isinstance(repository, SqliteApplicationRepository) else len(repository.all())
    counts: dict[str, int] = {}
    for application in repository.all():
        counts[application.status.value] = counts.get(application.status.value, 0) + 1

    lines.append(f"Candidaturas.....: {total}")
    for status_name, count in sorted(counts.items()):
        lines.append(f"  {status_name}: {count}")

    lines.extend(
        [
            "",
            "Automacao de portais (login/cliques/envio): DESABILITADA por design.",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    logger.info("Iniciando MCP career-agent (data_root=%s)", SETTINGS.data_root)
    mcp.run()

"""Testes da fonte de quadros publicos de ATS (Greenhouse / Lever / Ashby).

Todos offline: as respostas sao fixtures com o formato REAL de cada API,
copiado da resposta verificada em producao.
"""

from __future__ import annotations

import pytest

from career_core.job_sources.ats_boards import (
    AshbyBoard,
    AtsBoardsJobSource,
    GreenhouseBoard,
    LeverBoard,
    _display_name,
)
from career_core.job_sources.base import JobQuery
from career_core.models import Seniority, WorkMode

# ---------------------------------------------------------------------------
# Fixtures com o formato real das APIs
# ---------------------------------------------------------------------------

GREENHOUSE_PAYLOAD = {
    "jobs": [
        {
            "id": 7822037003,
            "title": "[ENGENHARIA] .NET SENIOR SOFTWARE ENGINEER ",
            "absolute_url": "https://job-boards.greenhouse.io/stone/jobs/7822037003",
            "location": {"name": "Remoto"},
            "company_name": "Stone - Linkedin",
            "first_published": "2026-07-31T10:30:55-04:00",
            "updated_at": "2026-08-14T12:58:36-04:00",
            "departments": [{"id": 1, "name": "Engenharia &amp; Tecnologia"}],
            "content": (
                "&lt;p&gt;Buscamos pessoa desenvolvedora com &lt;strong&gt;C#&lt;/strong&gt; "
                "e &lt;strong&gt;.NET&lt;/strong&gt;.&lt;/p&gt;&lt;ul&gt;"
                "&lt;li&gt;ASP.NET Core&lt;/li&gt;&lt;li&gt;PostgreSQL&lt;/li&gt;"
                "&lt;li&gt;Azure&lt;/li&gt;&lt;/ul&gt;"
            ),
        },
        {
            "id": 7819474003,
            "title": "[ENGENHARIA] SOFTWARE ENGINEER .NET JR",
            "absolute_url": "https://job-boards.greenhouse.io/stone/jobs/7819474003",
            "location": {"name": "Remoto"},
            "departments": [],
            "content": "&lt;p&gt;Vaga junior de .NET.&lt;/p&gt;",
        },
    ]
}

LEVER_PAYLOAD = [
    {
        "id": "abc-123",
        "text": "Staff Software Engineer - Backend",
        "hostedUrl": "https://jobs.lever.co/neon/abc-123",
        "workplaceType": "remote",
        "country": "BR",
        "categories": {"location": "Remoto", "department": "Engenharia", "commitment": "CLT"},
        "descriptionPlain": "Experiencia com C#, .NET e Kubernetes.",
        "additionalPlain": "Diferencial: Kafka.",
        "createdAt": 1750000000000,
    }
]

ASHBY_PAYLOAD = {
    "jobs": [
        {
            "id": "26140397-e042",
            "title": "Senior Software Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/nubank/26140397-e042",
            "location": "São Paulo",
            "isRemote": True,
            "isListed": True,
            "workplaceType": "Hybrid",
            "department": "Engineer",
            "team": "Engineer",
            "descriptionPlain": "Backend com C# e .NET. PostgreSQL e Docker.",
            "publishedAt": "2026-07-20T11:35:01.642+00:00",
        },
        {
            "id": "oculta",
            "title": "Vaga nao listada",
            "jobUrl": "https://jobs.ashbyhq.com/nubank/oculta",
            "location": "São Paulo",
            "isListed": False,
            "descriptionPlain": "nao deve aparecer",
        },
    ]
}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_greenhouse_desescapa_html_duplo():
    jobs = GreenhouseBoard().parse("stone", GREENHOUSE_PAYLOAD)
    description = jobs[0].description
    assert "&lt;" not in description and "&gt;" not in description
    assert "<p>" not in description
    assert "C#" in description and ".NET" in description
    assert "- ASP.NET Core" in description


def test_greenhouse_extrai_campos_corretos():
    job = GreenhouseBoard().parse("stone", GREENHOUSE_PAYLOAD)[0]
    assert job.title == "[ENGENHARIA] .NET SENIOR SOFTWARE ENGINEER"
    assert job.company == "Stone"
    assert job.url == "https://job-boards.greenhouse.io/stone/jobs/7822037003"
    assert job.location == "Remoto"
    assert job.country == "Brasil"
    assert job.seniority is Seniority.SENIOR
    assert job.work_mode is WorkMode.REMOTE
    assert job.source == "ats"
    assert job.id.startswith("greenhouse-stone-")


def test_departamento_nao_vira_tecnologia_exigida():
    """Regressao: 'Engenharia & Tecnologia' aparecia como gap tecnico."""
    for job in GreenhouseBoard().parse("stone", GREENHOUSE_PAYLOAD):
        assert job.tech_tags == []
    assert LeverBoard().parse("neon", LEVER_PAYLOAD)[0].tech_tags == []
    assert AshbyBoard().parse("nubank", ASHBY_PAYLOAD)[0].tech_tags == []


def test_lever_usa_workplace_type_declarado():
    job = LeverBoard().parse("neon", LEVER_PAYLOAD)[0]
    assert job.work_mode is WorkMode.REMOTE
    assert job.seniority is Seniority.LEAD  # "Staff Software Engineer"
    assert "Kafka" in job.description  # additionalPlain foi concatenado
    assert job.url == "https://jobs.lever.co/neon/abc-123"


def test_ashby_ignora_vaga_nao_listada():
    jobs = AshbyBoard().parse("nubank", ASHBY_PAYLOAD)
    assert len(jobs) == 1
    assert jobs[0].title == "Senior Software Engineer"


def test_ashby_workplace_type_vence_is_remote():
    job = AshbyBoard().parse("nubank", ASHBY_PAYLOAD)[0]
    assert job.work_mode is WorkMode.HYBRID


def test_parsers_toleram_payload_vazio_ou_estranho():
    for board, empty in (
        (GreenhouseBoard(), {}),
        (GreenhouseBoard(), {"jobs": []}),
        (LeverBoard(), []),
        (LeverBoard(), [{"text": ""}]),
        (AshbyBoard(), {}),
    ):
        assert board.parse("x", empty) == []


@pytest.mark.parametrize(
    ("slug", "expected"),
    [("stone", "Stone"), ("c6bank", "C6bank"), ("quinto-andar", "Quinto Andar")],
)
def test_nome_de_exibicao(slug, expected):
    assert _display_name(slug) == expected


# ---------------------------------------------------------------------------
# Fonte agregada
# ---------------------------------------------------------------------------


def _source(monkeypatch, boards: dict[str, tuple[list, str]], **kwargs):
    source = AtsBoardsJobSource(companies=tuple(boards), **kwargs)

    def fake(spec):
        jobs, error = boards[spec]
        return spec, jobs, error

    monkeypatch.setattr(source, "_fetch_board", fake)
    return source


def test_agrega_varios_quadros(monkeypatch):
    gh = GreenhouseBoard().parse("stone", GREENHOUSE_PAYLOAD)
    ash = AshbyBoard().parse("nubank", ASHBY_PAYLOAD)
    source = _source(
        monkeypatch,
        {"greenhouse:stone": (gh, ""), "ashby:nubank": (ash, "")},
    )
    result = source.search(JobQuery(keywords=".net"))
    assert result.ok
    assert len(result.jobs) >= 2
    assert "2/2 quadro(s)" in result.message


def test_quadro_indisponivel_nao_derruba_os_outros(monkeypatch):
    gh = GreenhouseBoard().parse("stone", GREENHOUSE_PAYLOAD)
    source = _source(
        monkeypatch,
        {"greenhouse:stone": (gh, ""), "lever:inexistente": ([], "quadro nao encontrado")},
    )
    result = source.search(JobQuery(keywords=".net"))
    assert result.ok
    assert result.jobs
    assert "Indisponiveis" in result.message
    assert "lever:inexistente" in result.message


def test_relevancia_prioriza_titulo(monkeypatch):
    """Regressao: truncar por data descartava a vaga '.NET' mais aderente."""
    from career_core.models import Job

    ruido = [
        Job(source="ats", title=f"Backend Engineer {i}", company="X",
            description="backend generico", posted_at="2026-08-16")
        for i in range(30)
    ]
    alvo = Job(
        source="ats", title=".NET Senior Software Engineer", company="Stone",
        description="C# e .NET", posted_at="2020-01-01",
    )
    source = _source(monkeypatch, {"greenhouse:stone": (ruido + [alvo], "")}, max_results=5)
    result = source.search(JobQuery(keywords=".net", limit=5))
    assert result.jobs[0].title == ".NET Senior Software Engineer"


def test_filtra_por_modalidade(monkeypatch):
    gh = GreenhouseBoard().parse("stone", GREENHOUSE_PAYLOAD)
    source = _source(monkeypatch, {"greenhouse:stone": (gh, "")})
    assert source.search(JobQuery(work_modes=("remoto",))).jobs
    assert not source.search(JobQuery(work_modes=("presencial",))).jobs


def test_sem_empresa_configurada_avisa():
    result = AtsBoardsJobSource(companies=()).search(JobQuery())
    assert result.ok is False
    assert "JOB_SEARCH_ATS_COMPANIES" in result.message


def test_provedor_desconhecido_e_reportado():
    source = AtsBoardsJobSource(companies=("naoexiste:empresa",))
    spec, jobs, error = source._fetch_board("naoexiste:empresa")
    assert jobs == []
    assert "desconhecido" in error


# ---------------------------------------------------------------------------
# Integracao com o registry
# ---------------------------------------------------------------------------


def test_registry_expoe_ats(settings):
    from career_core.job_sources.registry import JobSourceRegistry

    assert "ats" in JobSourceRegistry(settings).available_names()


def test_ats_exige_rede(settings):
    from career_core.job_sources.registry import JobSourceRegistry

    assert JobSourceRegistry(settings).get("ats") is None  # rede desligada


def test_lista_padrao_de_empresas_e_valida():
    from career_core.job_sources.ats_boards import BOARDS, DEFAULT_COMPANIES

    assert DEFAULT_COMPANIES
    for spec in DEFAULT_COMPANIES:
        provider, _, company = spec.partition(":")
        assert provider in BOARDS, f"provedor invalido em '{spec}'"
        assert company, f"empresa ausente em '{spec}'"


def test_nenhum_endpoint_aponta_para_portal_proibido():
    from career_core.job_sources.ats_boards import BOARDS

    for board in BOARDS.values():
        url, _ = board.endpoint("empresa")
        for banned in ("linkedin", "indeed", "gupy"):
            assert banned not in url.lower()

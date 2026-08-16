"""Testes das fontes de vagas e da validacao/normalizacao de vaga."""

from __future__ import annotations

import pytest

from career_core.errors import ValidationError
from career_core.job_input import build_job_from_input
from career_core.job_sources.base import (
    JobQuery,
    detect_seniority,
    detect_work_mode,
    parse_salary_brl,
    strip_html,
)
from career_core.job_sources.mock import MockJobSource
from career_core.job_sources.registry import JobSourceRegistry
from career_core.models import Seniority, WorkMode


# ---------------------------------------------------------------------------
# Validacao de vaga
# ---------------------------------------------------------------------------


def test_vaga_sem_titulo_e_recusada():
    with pytest.raises(ValidationError):
        build_job_from_input(title="")
    with pytest.raises(ValidationError):
        build_job_from_input(title="   ")


def test_vaga_minima_e_valida():
    job = build_job_from_input(title="Dev Backend .NET")
    assert job.title == "Dev Backend .NET"
    assert job.id, "todo Job precisa de um id estavel"


def test_id_e_deterministico():
    args = dict(title="Dev", company="X", url="https://x.dev/1")
    assert build_job_from_input(**args).id == build_job_from_input(**args).id


def test_campo_explicito_vence_a_deteccao():
    job = build_job_from_input(
        title="Desenvolvedor Junior", description="vaga presencial", seniority="senior",
        work_mode="remoto",
    )
    assert job.seniority is Seniority.SENIOR
    assert job.work_mode is WorkMode.REMOTE


def test_html_da_descricao_e_limpo():
    job = build_job_from_input(
        title="Dev", description="<p>Requisitos:</p><ul><li>C#</li><li>.NET</li></ul>"
    )
    assert "<p>" not in job.description
    assert "C#" in job.description


def test_pais_e_inferido_de_cidade_brasileira():
    assert build_job_from_input(title="Dev", location="Goiania, GO").country == "Brasil"


# ---------------------------------------------------------------------------
# Deteccao
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Desenvolvedor Backend Senior", Seniority.SENIOR),
        ("Desenvolvedor Pleno", Seniority.MID),
        ("Desenvolvedor Junior", Seniority.JUNIOR),
        ("Programa de Trainee 2026", Seniority.TRAINEE),
        ("Estagio em Desenvolvimento", Seniority.INTERN),
        ("Tech Lead Backend", Seniority.LEAD),
        ("Especialista em .NET", Seniority.SPECIALIST),
        ("Desenvolvedor Backend", Seniority.UNKNOWN),
    ],
)
def test_detecta_senioridade(text, expected):
    assert detect_seniority(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Vaga 100% remoto", WorkMode.REMOTE),
        ("Home office", WorkMode.REMOTE),
        ("Trabalho hibrido em Goiania", WorkMode.HYBRID),
        ("Vaga presencial", WorkMode.ONSITE),
        ("Vaga de backend", WorkMode.UNKNOWN),
    ],
)
def test_detecta_modalidade(text, expected):
    assert detect_work_mode(text) is expected


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("R$ 12.000 a R$ 15.000", 12000.0, 15000.0),
        ("R$ 12.000,00", 12000.0, None),
        ("R$ 12k", 12000.0, None),
        ("salario a combinar", None, None),
        ("", None, None),
    ],
)
def test_extrai_salario(text, low, high):
    assert parse_salary_brl(text) == (low, high)


def test_strip_html_preserva_bullets():
    assert "- C#" in strip_html("<ul><li>C#</li></ul>")


# ---------------------------------------------------------------------------
# Fonte mock
# ---------------------------------------------------------------------------


def test_mock_e_offline_e_deterministica():
    source = MockJobSource()
    first = source.search(JobQuery(keywords=".net"))
    second = source.search(JobQuery(keywords=".net"))
    assert first.ok
    assert [j.id for j in first.jobs] == [j.id for j in second.jobs]


def test_mock_avisa_que_as_vagas_sao_ficticias():
    assert "MOCK" in MockJobSource().search(JobQuery()).message


def test_mock_filtra_por_palavra_chave():
    assert MockJobSource().search(JobQuery(keywords="sap")).jobs
    assert not MockJobSource().search(JobQuery(keywords="cobol")).jobs


def test_mock_filtra_por_modalidade():
    result = MockJobSource().search(JobQuery(work_modes=("remoto",)))
    assert result.jobs
    assert all(j.work_mode is WorkMode.REMOTE for j in result.jobs)


def test_mock_respeita_o_limite():
    assert len(MockJobSource().search(JobQuery(limit=2)).jobs) <= 2


def test_toda_vaga_do_mock_e_valida():
    for job in MockJobSource().search(JobQuery()).jobs:
        assert job.title and job.id and job.source == "mock"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_lista_a_abstracao_completa(settings):
    names = JobSourceRegistry(settings).available_names()
    for expected in ("mock", "remotive", "arbeitnow", "linkedin", "indeed", "gupy"):
        assert expected in names


def test_rede_desligada_bloqueia_fontes_http(settings):
    registry = JobSourceRegistry(settings)  # enable_network=False
    assert registry.get("remotive") is None
    assert registry.get("arbeitnow") is None
    assert registry.get("mock") is not None


def test_rede_ligada_libera_fontes_http(settings):
    registry = JobSourceRegistry(
        settings.__class__(
            **{
                **{k: getattr(settings, k) for k in (
                    "data_root", "log_dir", "log_level", "min_score", "sources",
                    "http_timeout", "max_results", "min_interval", "user_agent",
                )},
                "enable_network": True,
            }
        )
    )
    assert registry.get("remotive") is not None


def test_fonte_desconhecida_devolve_none(settings):
    assert JobSourceRegistry(settings).get("fonte-inexistente") is None


def test_enabled_names_sempre_tem_fallback(settings):
    assert JobSourceRegistry(settings).enabled_names() == ["mock"]


# ---------------------------------------------------------------------------
# Fontes indisponiveis - modo manual
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("portal", ["linkedin", "indeed", "gupy"])
def test_portal_sem_api_nao_e_automatizado(settings, portal):
    source = JobSourceRegistry(settings).get(portal)
    assert source is not None
    assert source.usable is False

    result = source.search(JobQuery(keywords="backend .net"))
    assert result.ok is False
    assert result.jobs == []
    assert "MODO MANUAL" in result.message


def test_linkedin_explica_por_que_nao_automatiza(settings):
    message = JobSourceRegistry(settings).get("linkedin").search(JobQuery()).message.lower()
    assert "termos de servico" in message
    assert "nao automatiza" in message or "não automatiza" in message


# ---------------------------------------------------------------------------
# Remotive: o feed publico ignora o parametro de busca
# ---------------------------------------------------------------------------


def _fake_remotive(monkeypatch, entries: list[dict], total: int | None = None):
    from career_core.job_sources.http_sources import RemotiveJobSource

    source = RemotiveJobSource(user_agent="tests", min_interval=0.0)
    payload = {"jobs": entries, "total-job-count": total if total is not None else len(entries)}
    monkeypatch.setattr(source, "_fetch", lambda params: payload)
    return source


_REMOTIVE_SAMPLE = [
    {
        "id": 1, "title": "Freelance Copywriter", "company_name": "Acme",
        "url": "https://remotive.com/1", "description": "Write copy.",
        "tags": ["writing"], "candidate_required_location": "Worldwide",
        "salary": "", "publication_date": "",
    },
    {
        "id": 2, "title": "Senior Backend Engineer (.NET)", "company_name": "Contoso",
        "url": "https://remotive.com/2", "description": "C# and ASP.NET Core.",
        "tags": ["c#", ".net"], "candidate_required_location": "Worldwide",
        "salary": "", "publication_date": "",
    },
]


def test_remotive_filtra_do_lado_do_cliente(monkeypatch):
    """A API ignora `search`; o filtro precisa acontecer aqui."""
    source = _fake_remotive(monkeypatch, _REMOTIVE_SAMPLE)
    result = source.search(JobQuery(keywords=".net backend"))
    assert [j.title for j in result.jobs] == ["Senior Backend Engineer (.NET)"]


def test_remotive_avisa_quando_o_feed_e_amostra(monkeypatch):
    source = _fake_remotive(monkeypatch, _REMOTIVE_SAMPLE[:1], total=14)
    result = source.search(JobQuery(keywords="backend .net c#"))
    assert result.jobs == []
    assert result.ok
    message = result.message.lower()
    assert "amostra" in message
    assert "ignora o parametro" in message
    assert "modo manual" in message


def test_remotive_sem_palavra_chave_devolve_o_feed(monkeypatch):
    source = _fake_remotive(monkeypatch, _REMOTIVE_SAMPLE)
    assert len(source.search(JobQuery()).jobs) == 2


def test_remotive_falha_de_rede_nao_quebra_a_busca(monkeypatch):
    from career_core.errors import JobSourceError
    from career_core.job_sources.http_sources import RemotiveJobSource

    source = RemotiveJobSource(user_agent="tests", min_interval=0.0)

    def boom(_params):
        raise JobSourceError("timeout")

    monkeypatch.setattr(source, "_fetch", boom)
    result = source.search(JobQuery(keywords=".net"))
    assert result.ok is False
    assert result.jobs == []


def test_nenhuma_fonte_http_aponta_para_portal_proibido():
    """Guarda-corpo: nenhum endpoint pode apontar para LinkedIn/Indeed/Gupy."""
    from career_core.job_sources.http_sources import ArbeitnowJobSource, RemotiveJobSource

    for source_cls in (RemotiveJobSource, ArbeitnowJobSource):
        endpoint = source_cls.endpoint.lower()
        for banned in ("linkedin", "indeed", "gupy"):
            assert banned not in endpoint


# ---------------------------------------------------------------------------
# Busca agregada
# ---------------------------------------------------------------------------


def test_busca_agregada_pontua_e_ordena(services, profile):
    jobs, results = services.job_search.search(JobQuery(keywords=".net", limit=10))
    assert jobs
    assert any(r.ok for r in results)

    totals = [services.scorer.score(job, profile).total for job in jobs]
    assert max(totals) >= 80

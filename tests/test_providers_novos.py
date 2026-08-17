"""Testes dos providers Workable, SmartRecruiters, Adzuna e Jooble.

Fixtures copiadas da resposta REAL de cada API (capturada em 17/08/2026),
para que o teste falhe se o parser deixar de casar com o formato de verdade.
"""

from __future__ import annotations

import pytest

from career_core.job_sources.aggregators import AdzunaJobSource, jooble_source
from career_core.job_sources.ats_boards import SmartRecruitersBoard, WorkableBoard
from career_core.job_sources.base import JobQuery
from career_core.models import Seniority, WorkMode

# ---------------------------------------------------------------------------
# Workable - formato real (campos de local vem no TOPO do item)
# ---------------------------------------------------------------------------

WORKABLE_PAYLOAD = {
    "name": "Kahoot!",
    "description": None,
    "jobs": [
        {
            "title": "Senior Backend Engineer (.NET)",
            "shortcode": "5EA5DDE797",
            "employment_type": "Full-time",
            "telecommuting": False,
            "department": "Engineering",
            "url": "https://apply.workable.com/j/5EA5DDE797",
            "shortlink": "https://apply.workable.com/j/5EA5DDE797",
            "application_url": "https://apply.workable.com/j/5EA5DDE797/apply",
            "published_on": "2026-03-27",
            "created_at": "2026-03-15",
            "country": "Brazil",
            "city": "São Paulo",
            "state": "SP",
            "education": "Bachelor's Degree",
            "experience": "Mid-Senior level",
            "description": "<p>Trabalhamos com <strong>C#</strong> e .NET.</p>",
            "requirements": "<ul><li>ASP.NET Core</li><li>PostgreSQL</li></ul>",
            "benefits": "<p>Plano de saude.</p>",
            "locations": [],
        },
        {
            "title": "Remote Platform Engineer",
            "shortcode": "AAA111",
            "telecommuting": True,
            "url": "https://apply.workable.com/j/AAA111",
            "published_on": "2026-04-01",
            "country": "",
            "city": "",
            "state": "",
            "description": "Kubernetes e Docker.",
            "locations": [{"country": "Brazil", "city": "Remoto", "region": ""}],
        },
    ],
}


def test_workable_le_local_do_topo_do_item():
    """Regressao: assumir `location:{...}` aninhado zerava a localizacao."""
    job = WorkableBoard().parse("kahoot", WORKABLE_PAYLOAD)[0]
    assert job.location == "São Paulo, SP, Brazil"
    assert job.country == "Brasil"


def test_workable_usa_locations_como_fallback():
    job = WorkableBoard().parse("kahoot", WORKABLE_PAYLOAD)[1]
    assert "Remoto" in job.location


def test_workable_telecommuting_define_remoto():
    jobs = WorkableBoard().parse("kahoot", WORKABLE_PAYLOAD)
    assert jobs[0].work_mode is not WorkMode.REMOTE
    assert jobs[1].work_mode is WorkMode.REMOTE


def test_workable_concatena_descricao_requisitos_e_beneficios():
    job = WorkableBoard().parse("kahoot", WORKABLE_PAYLOAD)[0]
    assert "C#" in job.description
    assert "ASP.NET Core" in job.description
    assert "Plano de saude" in job.description
    assert "<p>" not in job.description


def test_workable_usa_campo_experience_para_senioridade():
    job = WorkableBoard().parse("kahoot", WORKABLE_PAYLOAD)[0]
    assert job.seniority is Seniority.SENIOR


def test_workable_id_e_url_estaveis():
    job = WorkableBoard().parse("kahoot", WORKABLE_PAYLOAD)[0]
    assert job.id == "workable-kahoot-5EA5DDE797"
    assert job.url == "https://apply.workable.com/j/5EA5DDE797"


def test_workable_departamento_nao_vira_tecnologia():
    for job in WorkableBoard().parse("kahoot", WORKABLE_PAYLOAD):
        assert job.tech_tags == []


# ---------------------------------------------------------------------------
# SmartRecruiters - formato real
# ---------------------------------------------------------------------------

SMARTRECRUITERS_PAYLOAD = {
    "totalFound": 2,
    "content": [
        {
            "id": "744000133907678",
            "name": "Senior Software Engineer .NET",
            "company": {"identifier": "Visa", "name": "Visa"},
            "releasedDate": "2026-06-24T10:00:11.853Z",
            "location": {
                "city": "São Paulo",
                "region": "SP",
                "country": "br",
                "remote": False,
                "hybrid": True,
                "fullLocation": "São Paulo, SP, Brazil",
            },
            "department": {"label": "Software Development/Engineering"},
        },
        {
            "id": "744000129971988",
            "name": "Backend Developer",
            "company": {"identifier": "Visa", "name": "Visa"},
            "releasedDate": "2026-05-01T10:00:00.000Z",
            "location": {
                "city": "Remote",
                "country": "br",
                "remote": True,
                "hybrid": False,
                "fullLocation": "Remote, Brazil",
            },
        },
    ],
}


def test_smartrecruiters_prefere_full_location():
    """`country` vem como sigla minuscula; `fullLocation` e legivel."""
    job = SmartRecruitersBoard().parse("Visa", SMARTRECRUITERS_PAYLOAD)[0]
    assert job.location == "São Paulo, SP, Brazil"
    assert "br," not in job.location


def test_smartrecruiters_respeita_hybrid_e_remote_declarados():
    jobs = SmartRecruitersBoard().parse("Visa", SMARTRECRUITERS_PAYLOAD)
    assert jobs[0].work_mode is WorkMode.HYBRID
    assert jobs[1].work_mode is WorkMode.REMOTE


def test_smartrecruiters_usa_nome_real_da_empresa():
    job = SmartRecruitersBoard().parse("Visa", SMARTRECRUITERS_PAYLOAD)[0]
    assert job.company == "Visa"


def test_smartrecruiters_monta_url_da_vaga():
    job = SmartRecruitersBoard().parse("Visa", SMARTRECRUITERS_PAYLOAD)[0]
    assert job.url == "https://jobs.smartrecruiters.com/Visa/744000133907678"


def test_smartrecruiters_detecta_senioridade_do_titulo():
    job = SmartRecruitersBoard().parse("Visa", SMARTRECRUITERS_PAYLOAD)[0]
    assert job.seniority is Seniority.SENIOR


# ---------------------------------------------------------------------------
# Adzuna
# ---------------------------------------------------------------------------

ADZUNA_PAYLOAD = {
    "count": 137,
    "results": [
        {
            "id": "4712345678",
            "title": "Desenvolvedor .NET Sênior",
            "description": "Vaga remota. Requisitos: C#, ASP.NET Core, SQL Server.",
            "redirect_url": "https://www.adzuna.com.br/details/4712345678",
            "created": "2026-08-15T09:00:00Z",
            "company": {"display_name": "Empresa Exemplo"},
            "location": {"display_name": "São Paulo, São Paulo"},
            "salary_min": 12000.0,
            "salary_max": 16000.0,
            "category": {"label": "IT Jobs"},
        }
    ],
}


def test_adzuna_sem_credencial_nao_falha_silenciosamente():
    result = AdzunaJobSource(app_id="", app_key="").search(JobQuery(keywords=".net"))
    assert result.ok is False
    assert result.jobs == []
    assert "developer.adzuna.com" in result.message
    assert "ADZUNA_APP_ID" in result.message


def test_adzuna_configured_reflete_as_credenciais():
    assert AdzunaJobSource(app_id="", app_key="").configured is False
    assert AdzunaJobSource(app_id="a", app_key="").configured is False
    assert AdzunaJobSource(app_id="a", app_key="b").configured is True


def test_adzuna_parseia_resposta_real(monkeypatch):
    source = AdzunaJobSource(app_id="id", app_key="key")
    monkeypatch.setattr(source._http, "get_json", lambda *a, **k: ADZUNA_PAYLOAD)

    result = source.search(JobQuery(keywords=".net", location="Brasil"))
    assert result.ok
    job = result.jobs[0]
    assert job.title == "Desenvolvedor .NET Sênior"
    assert job.company == "Empresa Exemplo"
    assert job.country == "Brasil"
    assert job.salary_min_brl == 12000.0
    assert job.salary_max_brl == 16000.0
    assert "R$" in job.salary_text
    assert job.seniority is Seniority.SENIOR
    assert job.work_mode is WorkMode.REMOTE
    assert job.url.startswith("https://www.adzuna.com.br/")
    assert job.tech_tags == []  # categoria e area, nao tecnologia


def test_adzuna_envia_credenciais_e_indice_br(monkeypatch):
    captured: dict = {}

    def fake(url, params=None, headers=None):
        captured["url"] = url
        captured["params"] = params
        return {"results": [], "count": 0}

    source = AdzunaJobSource(app_id="meu_id", app_key="minha_key")
    monkeypatch.setattr(source._http, "get_json", fake)
    source.search(JobQuery(keywords="backend .net", location="Goiania"))

    assert "/jobs/br/search/1" in captured["url"]
    assert captured["params"]["app_id"] == "meu_id"
    assert captured["params"]["app_key"] == "minha_key"
    assert captured["params"]["what"] == "backend .net"
    assert captured["params"]["where"] == "Goiania"


def test_adzuna_credencial_invalida_da_mensagem_util(monkeypatch):
    from career_core.errors import JobSourceError

    source = AdzunaJobSource(app_id="x", app_key="y")

    def boom(*a, **k):
        raise JobSourceError("GET ... falhou com HTTP 401.")

    monkeypatch.setattr(source._http, "get_json", boom)
    result = source.search(JobQuery(keywords=".net"))
    assert result.ok is False
    assert "ADZUNA_APP_ID" in result.message


# ---------------------------------------------------------------------------
# Jooble - deliberadamente nao implementado
# ---------------------------------------------------------------------------


def test_jooble_e_declarado_mas_nao_automatizado():
    source = jooble_source()
    assert source.usable is False

    result = source.search(JobQuery(keywords=".net"))
    assert result.ok is False
    assert result.jobs == []
    message = result.message.lower()
    assert "cloudflare" in message
    assert "anti-bot" in message
    assert "MODO MANUAL" in result.message


def test_jooble_esta_no_registry(settings):
    from career_core.job_sources.registry import JobSourceRegistry

    assert "jooble" in JobSourceRegistry(settings).available_names()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_novos_provedores_de_ats_registrados():
    from career_core.job_sources.ats_boards import BOARDS

    for provider in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters"):
        assert provider in BOARDS


def test_adzuna_exige_rede(settings):
    from career_core.job_sources.registry import JobSourceRegistry

    assert JobSourceRegistry(settings).get("adzuna") is None


@pytest.mark.parametrize("provider", ["workable", "smartrecruiters"])
def test_endpoints_novos_nao_apontam_para_portal_proibido(provider):
    from career_core.job_sources.ats_boards import BOARDS

    url, _ = BOARDS[provider].endpoint("empresa")
    for banned in ("linkedin", "indeed", "gupy"):
        assert banned not in url.lower()

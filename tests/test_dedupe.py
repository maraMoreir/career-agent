"""Testes de deteccao de duplicidade e do historico."""

from __future__ import annotations

import pytest

from career_core.models import Application, ApplicationStatus, DuplicateVerdict
from career_core.text import normalize_company, normalize_title, normalize_url


def _register(services, company: str, role: str, url: str = "") -> Application:
    return services.applications.add(
        Application(id=f"app-{abs(hash((company, role, url))) % 10**8}", company=company, role=role, job_url=url)
    )


# ---------------------------------------------------------------------------
# Normalizacao
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Nexatech Sistemas Ltda", "Nexatech Sistemas"),
        ("Nexatech S.A.", "NEXATECH"),
        ("Acme Tecnologia LTDA.", "acme"),
    ],
)
def test_empresa_normaliza_sufixo_juridico(left, right):
    assert normalize_company(left) == normalize_company(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Desenvolvedor Backend .NET Senior", "Desenvolvedor Backend .NET Pleno"),
        ("Dev Backend (Remoto)", "Dev Backend"),
        ("Engenheiro de Software Sr", "Engenheiro de Software"),
    ],
)
def test_titulo_ignora_senioridade_e_modalidade(left, right):
    assert normalize_title(left) == normalize_title(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("https://exemplo.dev/vagas/1?utm_source=x", "https://exemplo.dev/vagas/1"),
        ("https://www.exemplo.dev/vagas/1/", "exemplo.dev/vagas/1"),
        (
            "https://www.linkedin.com/jobs/view/123456789/?trk=abc",
            "https://linkedin.com/jobs/search/?currentJobId=123456789",
        ),
    ],
)
def test_url_normalizada_ignora_ruido(left, right):
    assert normalize_url(left) == normalize_url(right)


def test_url_vazia_nao_quebra():
    assert normalize_url("") == ""
    assert normalize_url("   ") == ""


# ---------------------------------------------------------------------------
# Deteccao
# ---------------------------------------------------------------------------


def test_historico_vazio_nao_acusa_duplicidade(services):
    result = services.duplicates.check("Nexatech", "Dev Backend .NET")
    assert result.verdict is DuplicateVerdict.NONE
    assert not result.is_blocking


def test_url_identica_e_duplicidade(services):
    _register(services, "Nexatech", "Dev Backend .NET", "https://exemplo.dev/vagas/1")
    result = services.duplicates.check(
        "Outro Nome", "Outro Cargo", "https://exemplo.dev/vagas/1?utm_source=news"
    )
    assert result.verdict is DuplicateVerdict.DUPLICATE
    assert result.is_blocking


def test_mesma_empresa_e_cargo_equivalente_e_duplicidade(services):
    _register(services, "Nexatech Sistemas Ltda", "Desenvolvedor Backend .NET Senior")
    result = services.duplicates.check("Nexatech Sistemas", "Desenvolvedor Backend .NET Pleno")
    assert result.verdict is DuplicateVerdict.DUPLICATE


def test_mesma_empresa_cargo_parecido_e_apenas_alerta(services):
    _register(services, "Nexatech", "Desenvolvedor Backend .NET")
    result = services.duplicates.check("Nexatech", "Desenvolvedor Backend Java")
    assert result.verdict is DuplicateVerdict.SIMILAR
    assert not result.is_blocking


def test_mesma_empresa_cargo_distinto_e_alerta_por_recencia(services):
    _register(services, "Nexatech", "Desenvolvedor Backend .NET")
    result = services.duplicates.check("Nexatech", "Designer de Produto")
    assert result.verdict is DuplicateVerdict.SIMILAR
    assert not result.is_blocking


def test_empresas_diferentes_nao_colidem(services):
    _register(services, "Nexatech", "Desenvolvedor Backend .NET")
    result = services.duplicates.check("Cerrado Software", "Desenvolvedor Backend .NET")
    assert result.verdict is DuplicateVerdict.NONE


def test_mensagem_lista_a_candidatura_conflitante(services):
    saved = _register(services, "Nexatech", "Dev Backend .NET", "https://exemplo.dev/vagas/1")
    result = services.duplicates.check("Nexatech", "Dev Backend .NET", "https://exemplo.dev/vagas/1")
    assert saved.id in result.message
    assert "allow_duplicate" in result.message


def test_duplicidade_encontra_por_todos_os_criterios(services):
    """URL, empresa, cargo e similaridade - os criterios pedidos."""
    _register(services, "Nexatech Sistemas Ltda", "Desenvolvedor Backend .NET Senior", "https://exemplo.dev/v/1")

    por_url = services.duplicates.check("Zzz", "Zzz", "https://exemplo.dev/v/1")
    por_empresa_cargo = services.duplicates.check("nexatech sistemas", "desenvolvedor backend .net")

    assert por_url.verdict is DuplicateVerdict.DUPLICATE
    assert por_empresa_cargo.verdict is DuplicateVerdict.DUPLICATE


# ---------------------------------------------------------------------------
# Deduplicacao entre fontes
# ---------------------------------------------------------------------------


def test_mesma_vaga_em_duas_fontes_aparece_uma_vez():
    from career_core.job_sources.registry import deduplicate_jobs
    from career_core.models import Job

    jobs = [
        Job(source="a", title="Dev Backend .NET", company="Nexatech", url="https://x.dev/1"),
        Job(source="b", title="Dev Backend .NET", company="Nexatech Ltda", url="https://x.dev/1?utm_source=b"),
        Job(source="c", title="Dev Frontend React", company="Nexatech", url="https://x.dev/2"),
    ]
    assert len(deduplicate_jobs(jobs)) == 2


def test_deduplicacao_sem_url_usa_empresa_e_titulo():
    from career_core.job_sources.registry import deduplicate_jobs
    from career_core.models import Job

    jobs = [
        Job(source="a", title="Desenvolvedor Backend .NET", company="Nexatech"),
        Job(source="b", title="Desenvolvedor Backend .NET", company="Nexatech Sistemas Ltda"),
    ]
    # Empresas normalizam diferente ("nexatech" vs "nexatech"), entao colidem.
    assert len(deduplicate_jobs(jobs)) == 1

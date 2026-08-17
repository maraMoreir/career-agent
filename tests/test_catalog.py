"""Testes do catalogo de vagas e do pipeline de coleta."""

from __future__ import annotations

import pytest

from career_core.catalog.models import CatalogJob, JobStatus, SearchExecution
from career_core.catalog.repository import (
    JobNotFoundError,
    SqliteJobCatalog,
    technology_links,
    to_catalog_job,
)
from career_core.job_sources.base import JobQuery
from career_core.models import Job, Seniority, WorkMode


@pytest.fixture
def catalog(tmp_path) -> SqliteJobCatalog:
    return SqliteJobCatalog(tmp_path / "catalog.db")


def _job(title="Dev Backend .NET", company="Nexatech", url="https://x.dev/1", **kw) -> CatalogJob:
    return CatalogJob(id="", title=title, company=company, url=url, **kw)


# ---------------------------------------------------------------------------
# Gravacao e deduplicacao
# ---------------------------------------------------------------------------


def test_grava_e_recupera(catalog):
    saved, is_new = catalog.upsert_job(_job(match_score=91.0))
    assert is_new
    assert saved.id.startswith("job-")
    assert catalog.get_job(saved.id).match_score == 91.0


def test_vaga_inexistente_da_erro_claro(catalog):
    with pytest.raises(JobNotFoundError) as exc:
        catalog.get_job("job-nao-existe")
    assert "list_matching_jobs" in str(exc.value)


def test_url_identica_e_a_mesma_vaga(catalog):
    first, _ = catalog.upsert_job(_job(url="https://x.dev/1"))
    second, is_new = catalog.upsert_job(
        _job(title="Outro titulo", company="Outra", url="https://x.dev/1?utm_source=a")
    )
    assert not is_new
    assert second.id == first.id
    assert catalog.count() == 1


def test_mesma_empresa_e_titulo_equivalente_e_a_mesma_vaga(catalog):
    first, _ = catalog.upsert_job(_job(title="Desenvolvedor Backend .NET Senior", url=""))
    second, is_new = catalog.upsert_job(
        _job(title="Desenvolvedor Backend .NET Pleno", company="Nexatech Ltda", url="")
    )
    assert not is_new
    assert second.id == first.id


def test_mesmo_titulo_com_urls_distintas_sao_vagas_distintas(catalog):
    """Empresas publicam a mesma funcao em varias cidades - vistos ao vivo
    no Inter e no C6 Bank. Colapsar apagaria oportunidades reais."""
    catalog.upsert_job(_job(title="Desenvolvedor Backend", url="https://x.dev/sp"))
    _, is_new = catalog.upsert_job(_job(title="Desenvolvedor Backend", url="https://x.dev/rj"))
    assert is_new
    assert catalog.count() == 2


def test_vaga_sem_url_ainda_deduplica_por_empresa_e_titulo(catalog):
    catalog.upsert_job(_job(title="Desenvolvedor Backend", url="https://x.dev/sp"))
    _, is_new = catalog.upsert_job(_job(title="Desenvolvedor Backend", url=""))
    assert not is_new


def test_vagas_distintas_convivem(catalog):
    catalog.upsert_job(_job(title="Dev Backend .NET", url="https://x.dev/1"))
    catalog.upsert_job(_job(title="Designer de Produto", url="https://x.dev/2"))
    assert catalog.count() == 2


def test_recoleta_preserva_status_e_candidatura(catalog):
    """O que voce ja decidiu nao pode ser sobrescrito por uma nova coleta."""
    saved, _ = catalog.upsert_job(_job(match_score=80.0))
    catalog.update_status(saved.id, JobStatus.INTERESTED)

    job = catalog.get_job(saved.id)
    job.application_id = "app-123"
    catalog._write(job)

    again, is_new = catalog.upsert_job(_job(match_score=95.0))
    assert not is_new
    assert again.status is JobStatus.INTERESTED, "status foi sobrescrito"
    assert again.application_id == "app-123", "candidatura foi perdida"
    assert again.match_score == 95.0, "score deveria ser atualizado"


def test_dados_sobrevivem_a_nova_conexao(catalog, tmp_path):
    saved, _ = catalog.upsert_job(_job(match_score=88.0))
    fresh = SqliteJobCatalog(tmp_path / "catalog.db")
    assert fresh.get_job(saved.id).match_score == 88.0


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def test_filtra_por_score_e_status(catalog):
    a, _ = catalog.upsert_job(_job(title="Alta", url="https://x.dev/1", match_score=95.0))
    catalog.upsert_job(_job(title="Baixa", url="https://x.dev/2", match_score=40.0))
    catalog.update_status(a.id, JobStatus.INTERESTED)

    assert [j.id for j in catalog.list_jobs(min_score=80)] == [a.id]
    assert [j.id for j in catalog.list_jobs(status=JobStatus.INTERESTED)] == [a.id]


def test_lista_ordenada_por_score(catalog):
    catalog.upsert_job(_job(title="Media", url="https://x.dev/1", match_score=70.0))
    catalog.upsert_job(_job(title="Alta", url="https://x.dev/2", match_score=95.0))
    scores = [j.match_score for j in catalog.list_jobs()]
    assert scores == sorted(scores, reverse=True)


def test_conta_por_status(catalog):
    a, _ = catalog.upsert_job(_job(url="https://x.dev/1"))
    catalog.upsert_job(_job(url="https://x.dev/2"))
    catalog.update_status(a.id, JobStatus.DISCARDED)
    assert catalog.count_by_status() == {"Found": 1, "Discarded": 1}


def test_transicao_de_status_e_registrada(catalog):
    saved, _ = catalog.upsert_job(_job())
    assert saved.status is JobStatus.FOUND
    assert catalog.update_status(saved.id, JobStatus.APPLIED).status is JobStatus.APPLIED


# ---------------------------------------------------------------------------
# Empresas, tecnologias, fontes, execucoes
# ---------------------------------------------------------------------------


def test_empresas_sao_agregadas(catalog):
    catalog.upsert_job(_job(company="Nexatech", url="https://x.dev/1"))
    catalog.upsert_job(_job(company="Cerrado", title="Dev Java", url="https://x.dev/2"))
    names = {c.name for c in catalog.list_companies()}
    assert {"Nexatech", "Cerrado"} <= names


def test_busca_empresa_por_nome(catalog):
    catalog.upsert_job(_job(company="Nexatech Sistemas Ltda"))
    assert catalog.list_companies(search="nexatech")


def test_tecnologias_contabilizam_exigencia_e_cobertura(catalog):
    from career_core.catalog.models import JobTechnology

    saved, _ = catalog.upsert_job(_job())
    catalog.record_technologies(
        saved.id,
        [
            JobTechnology(job_id=saved.id, technology="c#", matched=True),
            JobTechnology(job_id=saved.id, technology="azure", matched=False),
        ],
    )
    top = dict((name, (req, mat)) for name, req, mat in catalog.top_technologies())
    assert top["c#"] == (1, 1)
    assert top["azure"] == (1, 0)


def test_gap_que_nao_e_tecnologia_nao_vira_technology():
    """'faixa salarial nao divulgada' nao pode virar uma Technology."""
    from career_core.models import JobScore

    score = JobScore(
        job_id="j1",
        total=80.0,
        recommendation="ANALISAR",
        dimensions=[],
        matched_technologies=["c#", ".net"],
        gaps=["azure", "faixa salarial nao divulgada", "exige presenca em Curitiba, PR"],
    )
    names = {link.technology for link in technology_links("j1", score)}
    assert "c#" in names and "azure" in names
    assert "faixa salarial nao divulgada" not in names
    assert not any("presenca" in n for n in names)


def test_execucoes_sao_registradas(catalog):
    execution = catalog.start_execution(SearchExecution(query=".net"))
    assert execution.id.startswith("run-")
    execution.jobs_found = 10
    execution.status = "ok"
    catalog.finish_execution(execution)

    stored = catalog.list_executions()[0]
    assert stored.id == execution.id
    assert stored.jobs_found == 10
    assert stored.finished_at


def test_fontes_acumulam_estatistica(catalog):
    catalog.record_source_run("ats", collected=10)
    catalog.record_source_run("ats", collected=5)
    sources = {s.name: s for s in catalog.list_sources()}
    assert sources["ats"].jobs_collected == 15


# ---------------------------------------------------------------------------
# Conversao
# ---------------------------------------------------------------------------


def test_conversao_preserva_os_campos_do_spec(services, profile):
    job = Job(
        source="ats",
        title="Dev Backend .NET",
        company="Nexatech",
        url="https://x.dev/1",
        location="Goiania",
        work_mode=WorkMode.HYBRID,
        seniority=Seniority.SENIOR,
        salary_text="R$ 14.000",
        description="C# e .NET",
        posted_at="2026-08-01",
    )
    score = services.scorer.score(job, profile)
    catalog_job = to_catalog_job(job, score)

    for field in (
        "id", "title", "company", "description", "location", "work_model",
        "salary", "url", "source", "published_at", "collected_at",
        "match_score", "status",
    ):
        assert hasattr(catalog_job, field), f"campo do spec ausente: {field}"

    assert catalog_job.title == job.title
    assert catalog_job.work_model is WorkMode.HYBRID
    assert catalog_job.match_score == score.total
    assert catalog_job.status is JobStatus.ANALYZED


def test_vaga_eliminada_nasce_descartada(services, profile, junior_job):
    score = services.scorer.score(junior_job, profile)
    assert to_catalog_job(junior_job, score).status is JobStatus.DISCARDED


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def test_pipeline_coleta_pontua_e_salva(services):
    result = services.pipeline.run(
        services.profile(), JobQuery(keywords="backend .net", limit=10), minimum_score=70
    )
    assert result.execution.status == "ok"
    assert result.execution.jobs_found > 0
    assert result.execution.jobs_new == result.execution.jobs_found
    assert result.relevant
    assert services.catalog.count() == result.execution.jobs_found


def test_pipeline_deduplica_na_segunda_execucao(services):
    query = JobQuery(keywords="backend .net", limit=10)
    first = services.pipeline.run(services.profile(), query, minimum_score=70)
    second = services.pipeline.run(services.profile(), query, minimum_score=70)

    assert second.execution.jobs_new == 0
    assert second.execution.jobs_duplicated == first.execution.jobs_found
    assert services.catalog.count() == first.execution.jobs_found


def test_pipeline_ordena_relevantes_por_score(services):
    result = services.pipeline.run(
        services.profile(), JobQuery(keywords="backend .net", limit=10), minimum_score=60
    )
    scores = [j.match_score for j in result.relevant]
    assert scores == sorted(scores, reverse=True)


def test_pipeline_nao_marca_descartada_como_relevante(services):
    result = services.pipeline.run(
        services.profile(), JobQuery(keywords="", limit=20), minimum_score=0
    )
    for job in result.relevant:
        assert job.status is not JobStatus.DISCARDED


def test_pipeline_registra_execucao_no_historico(services):
    services.pipeline.run(services.profile(), JobQuery(keywords=".net", limit=5))
    executions = services.catalog.list_executions()
    assert executions
    assert executions[0].finished_at
    assert executions[0].status in {"ok", "partial"}


def test_fonte_que_falha_nao_derruba_a_execucao(services, monkeypatch):
    from career_core.job_sources.base import SourceResult

    original = services.job_search.search

    def partial(query, sources=None):
        jobs, results = original(query, sources)
        results.append(SourceResult(source="quebrada", ok=False, message="boom"))
        return jobs, results

    monkeypatch.setattr(services.job_search, "search", partial)

    result = services.pipeline.run(
        services.profile(), JobQuery(keywords="backend .net", limit=5), minimum_score=70
    )
    assert result.execution.status == "partial"
    assert result.execution.errors
    assert result.relevant, "as fontes boas precisam continuar valendo"


def test_busca_que_explode_e_registrada_como_falha(services, monkeypatch):
    def boom(query, sources=None):
        raise RuntimeError("rede caiu")

    monkeypatch.setattr(services.job_search, "search", boom)
    result = services.pipeline.run(services.profile(), JobQuery(keywords=".net"))

    assert result.execution.status == "failed"
    assert any("rede caiu" in e for e in result.execution.errors)
    assert result.relevant == []

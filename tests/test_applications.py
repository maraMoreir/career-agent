"""Testes de persistencia, historico e geracao de candidatura."""

from __future__ import annotations

import json

import pytest

from career_core.errors import ApplicationNotFoundError, InvalidStatusTransitionError
from career_core.models import Application, ApplicationStatus as S


# ---------------------------------------------------------------------------
# Repositorio
# ---------------------------------------------------------------------------


def test_registra_e_recupera(services):
    saved = services.applications.add(
        Application(id="app-1", company="Nexatech", role="Dev Backend .NET", score=91.0)
    )
    loaded = services.applications.get("app-1")
    assert loaded.company == saved.company
    assert loaded.score == 91.0
    assert loaded.status is S.PENDING_APPROVAL


def test_candidatura_inexistente_da_erro_claro(services):
    with pytest.raises(ApplicationNotFoundError) as exc:
        services.applications.get("app-nao-existe")
    assert "list_applications" in str(exc.value)


def test_find_devolve_none_sem_excecao(services):
    assert services.applications.find("app-nao-existe") is None


def test_historico_registra_criacao(services):
    saved = services.applications.add(Application(id="app-1", company="X", role="Dev"))
    assert len(saved.history) == 1
    assert saved.history[0].status is S.PENDING_APPROVAL


def test_transicao_valida_atualiza_e_registra(services):
    services.applications.add(Application(id="app-1", company="X", role="Dev"))
    updated = services.applications.update_status("app-1", S.APPROVED, "aprovado por mim")
    assert updated.status is S.APPROVED
    assert updated.history[-1].note == "aprovado por mim"
    assert len(updated.history) == 2


def test_transicao_invalida_e_recusada_e_nao_persiste(services):
    services.applications.add(Application(id="app-1", company="X", role="Dev"))
    with pytest.raises(InvalidStatusTransitionError):
        services.applications.update_status("app-1", S.APPLIED)
    assert services.applications.get("app-1").status is S.PENDING_APPROVAL


def test_ciclo_de_vida_completo(services):
    services.applications.add(Application(id="app-1", company="X", role="Dev"))
    for status in (S.APPROVED, S.APPLIED, S.INTERVIEW, S.TECHNICAL_TEST, S.OFFER):
        services.applications.update_status("app-1", status)
    final = services.applications.get("app-1")
    assert final.status is S.OFFER
    assert len(final.history) == 6


def test_filtra_por_status(services):
    services.applications.add(Application(id="app-1", company="A", role="Dev"))
    services.applications.add(Application(id="app-2", company="B", role="Dev"))
    services.applications.update_status("app-2", S.APPROVED)

    pending = services.applications.list(status=S.PENDING_APPROVAL)
    approved = services.applications.list(status=S.APPROVED)
    assert [a.id for a in pending] == ["app-1"]
    assert [a.id for a in approved] == ["app-2"]


def test_filtra_por_score_minimo(services):
    services.applications.add(Application(id="app-1", company="A", role="Dev", score=95.0))
    services.applications.add(Application(id="app-2", company="B", role="Dev", score=60.0))
    assert [a.id for a in services.applications.list(min_score=80)] == ["app-1"]


def test_filtra_por_empresa_ignorando_sufixo(services):
    services.applications.add(
        Application(id="app-1", company="Nexatech Sistemas Ltda", role="Dev")
    )
    assert len(services.applications.find_by_company("nexatech sistemas")) == 1


def test_dados_sobrevivem_a_nova_conexao(services, settings):
    services.applications.add(
        Application(id="app-1", company="Nexatech", role="Dev", score=91.0)
    )
    from career_core.applications.repository import SqliteApplicationRepository

    fresh = SqliteApplicationRepository(settings.database_path, settings.json_mirror_path)
    assert fresh.get("app-1").score == 91.0


# ---------------------------------------------------------------------------
# Espelho JSON
# ---------------------------------------------------------------------------


def test_espelho_json_e_escrito(services, settings):
    services.applications.add(Application(id="app-1", company="Nexatech", role="Dev"))
    document = json.loads(settings.json_mirror_path.read_text(encoding="utf-8"))
    assert document["count"] == 1
    assert document["applications"][0]["id"] == "app-1"


def test_espelho_json_se_mantem_sincronizado(services, settings):
    services.applications.add(Application(id="app-1", company="Nexatech", role="Dev"))
    services.applications.update_status("app-1", S.APPROVED)
    document = json.loads(settings.json_mirror_path.read_text(encoding="utf-8"))
    assert document["applications"][0]["status"] == "approved"


def test_espelho_json_avisa_que_e_derivado(services, settings):
    services.applications.add(Application(id="app-1", company="X", role="Dev"))
    document = json.loads(settings.json_mirror_path.read_text(encoding="utf-8"))
    assert "GERADO AUTOMATICAMENTE" in document["_comment"]


# ---------------------------------------------------------------------------
# Geracao de candidatura
# ---------------------------------------------------------------------------


def test_pacote_traz_todos_os_campos_pedidos(services, profile, perfect_job):
    score = services.scorer.score(perfect_job, profile)
    application, tailored = services.application_builder(profile).build(perfect_job, score)

    assert application.company == "Nexatech Sistemas"
    assert application.role == perfect_job.title
    assert application.score == score.total
    assert application.salary_text
    assert application.work_mode is perfect_job.work_mode
    assert application.location
    assert application.key_requirements
    assert application.matched_technologies
    assert application.recommended_resume
    assert application.tailored_summary
    assert application.recruiter_message
    assert application.suggested_answers
    assert application.job_url == perfect_job.url
    assert application.status is S.PENDING_APPROVAL
    assert tailored.guard.ok


def test_requisitos_sao_extraidos_da_descricao(services, profile, perfect_job):
    score = services.scorer.score(perfect_job, profile)
    application, _ = services.application_builder(profile).build(perfect_job, score)
    joined = " ".join(application.key_requirements).lower()
    assert "c#" in joined or ".net" in joined


def test_mensagem_ao_recrutador_avisa_que_e_rascunho(services, profile, perfect_job):
    score = services.scorer.score(perfect_job, profile)
    application, _ = services.application_builder(profile).build(perfect_job, score)
    assert "RASCUNHO" in application.recruiter_message
    assert "nao envia mensagens" in application.recruiter_message.lower()


def test_pergunta_extra_vira_resposta_para_preencher(services, profile, perfect_job):
    score = services.scorer.score(perfect_job, profile)
    application, _ = services.application_builder(profile).build(
        perfect_job, score, extra_questions=["Voce aceita viajar?"]
    )
    questions = [a.question for a in application.suggested_answers]
    assert "Voce aceita viajar?" in questions


def test_ids_de_candidatura_sao_unicos(services, profile, perfect_job):
    score = services.scorer.score(perfect_job, profile)
    builder = services.application_builder(profile)
    ids = {builder.build(perfect_job, score)[0].id for _ in range(20)}
    assert len(ids) == 20


def test_candidatura_gerada_nao_afirma_gap(services, profile):
    from career_core.models import Job, Seniority, WorkMode

    job = Job(
        source="test",
        title="Dev Backend .NET",
        company="Nexatech",
        seniority=Seniority.SENIOR,
        work_mode=WorkMode.REMOTE,
        location="Brasil",
        tech_tags=["C#", ".NET", "Azure"],
        description="Requisitos:\n- C#\n- .NET\n- Azure",
    )
    score = services.scorer.score(job, profile)
    application, tailored = services.application_builder(profile).build(job, score)

    assert "azure" in [g.lower() for g in tailored.gaps_not_claimed]
    assert tailored.guard.ok, tailored.guard.violations

    full_text = " ".join(
        [application.tailored_summary, application.recruiter_message]
        + [a.answer for a in application.suggested_answers]
    )
    from career_core.resume.tailor import FactGuard

    assert FactGuard(profile).audit(full_text, job).ok

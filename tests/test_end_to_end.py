"""Teste do fluxo real completo.

    perfil -> vaga -> score -> candidatura -> aprovacao -> historico

E o cenario que a usuaria vai viver no Claude Desktop, exercitado inteiro.
"""

from __future__ import annotations

import json

import pytest

from career_core.errors import InvalidStatusTransitionError
from career_core.job_sources.base import JobQuery
from career_core.models import ApplicationStatus as S
from career_core.models import DuplicateVerdict, Recommendation


def test_fluxo_completo(services, settings):
    # 1. PERFIL --------------------------------------------------------
    profile = services.profile()
    assert ".NET" in profile.skills
    assert profile.avoid_seniorities == ["estagio", "trainee", "junior"]

    # 2. VAGA ----------------------------------------------------------
    jobs, source_results = services.job_search.search(
        JobQuery(keywords="backend .net", limit=10)
    )
    assert jobs, "a busca precisa devolver vagas"
    assert all(r.source == "mock" for r in source_results), "V1 roda offline"

    # 3. SCORE ---------------------------------------------------------
    scored = sorted(
        ((job, services.scorer.score(job, profile)) for job in jobs),
        key=lambda pair: pair[1].total,
        reverse=True,
    )
    job, score = scored[0]

    assert score.total >= 80
    assert score.recommendation in (Recommendation.HIGH_PRIORITY, Recommendation.PRIORITY)
    assert len(score.dimensions) == 11
    assert score.explanation.startswith("Score: ")

    # Vagas junior precisam ter sido descartadas.
    for candidate, candidate_score in scored:
        if candidate.seniority.value == "junior":
            assert candidate_score.recommendation is Recommendation.DISCARD

    # 4. DUPLICIDADE (antes de recomendar) -----------------------------
    before = services.duplicates.check(job.company, job.title, job.url)
    assert before.verdict is DuplicateVerdict.NONE

    # 5. CANDIDATURA ---------------------------------------------------
    application, tailored = services.application_builder(profile).build(job, score)

    assert application.status is S.PENDING_APPROVAL
    assert application.recruiter_message and "RASCUNHO" in application.recruiter_message
    assert application.suggested_answers
    assert application.recommended_resume == "curriculo-principal.md"
    assert tailored.guard.ok, tailored.guard.violations

    saved = services.applications.add(application)
    assert saved.status is S.PENDING_APPROVAL

    # 6. DUPLICIDADE (depois de registrar) -----------------------------
    after = services.duplicates.check(job.company, job.title, job.url)
    assert after.verdict is DuplicateVerdict.DUPLICATE
    assert saved.id in after.message

    # 7. APROVACAO -----------------------------------------------------
    # Atalho proibido: nada vai para `applied` sem passar por `approved`.
    with pytest.raises(InvalidStatusTransitionError):
        services.applications.update_status(saved.id, S.APPLIED)
    assert services.applications.get(saved.id).status is S.PENDING_APPROVAL

    approved = services.applications.update_status(
        saved.id, S.APPROVED, "aprovada pela usuaria"
    )
    assert approved.status is S.APPROVED

    applied = services.applications.update_status(
        saved.id, S.APPLIED, "candidatura enviada manualmente no site"
    )
    assert applied.status is S.APPLIED

    interview = services.applications.update_status(saved.id, S.INTERVIEW, "entrevista dia 20")
    assert interview.status is S.INTERVIEW

    # 8. HISTORICO -----------------------------------------------------
    pending = services.applications.list(status=S.PENDING_APPROVAL)
    assert saved.id not in [a.id for a in pending]

    in_interview = services.applications.list(status=S.INTERVIEW)
    assert [a.id for a in in_interview] == [saved.id]

    final = services.applications.get(saved.id)
    assert [event.status for event in final.history] == [
        S.PENDING_APPROVAL,
        S.APPROVED,
        S.APPLIED,
        S.INTERVIEW,
    ]
    assert final.history[-1].note == "entrevista dia 20"

    # Espelho JSON refletindo o estado final.
    mirror = json.loads(settings.json_mirror_path.read_text(encoding="utf-8"))
    assert mirror["count"] == 1
    assert mirror["applications"][0]["status"] == "interview"


def test_fluxo_bloqueia_registro_duplicado(services):
    profile = services.profile()
    jobs, _ = services.job_search.search(JobQuery(keywords="backend .net", limit=5))
    job = jobs[0]
    score = services.scorer.score(job, profile)

    builder = services.application_builder(profile)
    services.applications.add(builder.build(job, score)[0])

    verdict = services.duplicates.check(job.company, job.title, job.url)
    assert verdict.is_blocking, "a segunda tentativa precisa ser barrada"


def test_vaga_eliminada_nao_vira_prioridade(services):
    profile = services.profile()
    jobs, _ = services.job_search.search(JobQuery(keywords="junior", limit=10))
    juniors = [j for j in jobs if j.seniority.value == "junior"]
    assert juniors, "o catalogo mock precisa ter uma vaga junior para este teste"

    for job in juniors:
        score = services.scorer.score(job, profile)
        assert score.eliminated
        assert score.recommendation is Recommendation.DISCARD

"""Testes do sistema de score e da classificacao."""

from __future__ import annotations

import pytest

from career_core.models import Job, Recommendation, Seniority, WorkMode
from career_core.scoring.dimensions import default_dimensions
from career_core.scoring.scorer import JobScorer, classify


# ---------------------------------------------------------------------------
# Pesos e classificacao
# ---------------------------------------------------------------------------


def test_pesos_somam_exatamente_100():
    assert sum(d.max_points for d in default_dimensions()) == pytest.approx(100.0)


def test_pesos_vem_da_configuracao():
    from career_core.scoring.config import DEFAULT_WEIGHTS

    weights = {d.key: d.max_points for d in default_dimensions()}
    assert weights == DEFAULT_WEIGHTS


def test_dimensoes_cobrem_os_fatores_da_especificacao():
    """Tecnologias, senioridade, localizacao, modalidade, salario, .NET,
    SAP, fiscal, arquitetura e backend."""
    keys = {d.key for d in default_dimensions()}
    for required in (
        "stack", "seniority", "location", "work_mode", "salary",
        "dotnet", "sap", "fiscal", "architecture", "backend", "company",
    ):
        assert required in keys, f"dimensao ausente: {required}"


def test_pesos_configurados_sobrescrevem_o_padrao():
    from career_core.scoring.config import ScoringConfig

    config = ScoringConfig(weights={"stack": 50.0, "dotnet": 50.0})
    weights = {d.key: d.max_points for d in default_dimensions(config)}
    assert weights["stack"] == 50.0
    assert weights["dotnet"] == 50.0


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (100.0, "Excelente"),
        (90.0, "Excelente"),
        (89.9, "Muito boa"),
        (75.0, "Muito boa"),
        (74.9, "Boa"),
        (60.0, "Boa"),
        (59.9, "Baixa"),
        (40.0, "Baixa"),
        (39.9, "Nao prioritaria"),
        (0.0, "Nao prioritaria"),
    ],
)
def test_faixas_da_especificacao(total, expected):
    from career_core.scoring.config import ScoringConfig

    assert ScoringConfig().classify(total) == expected


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (100.0, Recommendation.HIGH_PRIORITY),
        (90.0, Recommendation.HIGH_PRIORITY),
        (89.9, Recommendation.PRIORITY),
        (75.0, Recommendation.PRIORITY),
        (74.9, Recommendation.ANALYZE),
        (60.0, Recommendation.ANALYZE),
        (59.9, Recommendation.DISCARD),
        (0.0, Recommendation.DISCARD),
    ],
)
def test_faixas_de_classificacao(total, expected):
    assert classify(total) is expected


def test_faixas_configuradas_sao_respeitadas():
    from career_core.scoring.config import ScoringConfig

    config = ScoringConfig(bands=[(50.0, "Otima"), (0.0, "Ruim")])
    assert config.classify(80.0) == "Otima"
    assert config.classify(20.0) == "Ruim"


# ---------------------------------------------------------------------------
# Comportamento geral
# ---------------------------------------------------------------------------


def test_vaga_ideal_recebe_prioridade_alta(services, profile, perfect_job):
    score = services.scorer.score(perfect_job, profile)
    assert score.total >= 90
    assert score.recommendation is Recommendation.HIGH_PRIORITY
    assert not score.eliminated


def test_score_fica_entre_0_e_100(services, profile, perfect_job, junior_job):
    for job in (perfect_job, junior_job):
        score = services.scorer.score(job, profile)
        assert 0.0 <= score.total <= 100.0


def test_toda_dimensao_traz_justificativa(services, profile, perfect_job):
    score = services.scorer.score(perfect_job, profile)
    assert len(score.dimensions) == len(default_dimensions())
    for dimension in score.dimensions:
        assert dimension.rationale.strip(), f"{dimension.key} sem justificativa"
        assert 0.0 <= dimension.points <= dimension.max_points


def test_explicacao_tem_o_formato_pedido(services, profile, perfect_job):
    text = services.scorer.score(perfect_job, profile).explanation
    assert text.startswith("Score: ")
    for label in (
        "Stack tecnica:",
        "Experiencia .NET:",
        "Senioridade:",
        "Foco backend:",
        "Arquitetura:",
        "Salario:",
        "Modalidade:",
        "Localizacao:",
        "Experiencia SAP:",
        "Experiencia fiscal:",
        "Empresa:",
        "Gaps:",
        "Recomendacao:",
    ):
        assert label in text


# ---------------------------------------------------------------------------
# Eliminacao automatica
# ---------------------------------------------------------------------------


def test_vaga_junior_e_eliminada(services, profile, junior_job):
    score = services.scorer.score(junior_job, profile)
    assert score.eliminated
    assert score.recommendation is Recommendation.DISCARD
    assert score.total <= 69
    assert any("junior" in reason.lower() for reason in score.elimination_reasons)


@pytest.mark.parametrize("level", [Seniority.INTERN, Seniority.TRAINEE, Seniority.JUNIOR])
def test_todas_as_senioridades_evitadas_eliminam(services, profile, perfect_job, level):
    job = perfect_job.model_copy(update={"seniority": level})
    score = services.scorer.score(job, profile)
    assert score.eliminated, f"{level.value} deveria eliminar"
    assert score.recommendation is Recommendation.DISCARD


def test_empresa_bloqueada_elimina(services, profile, perfect_job):
    job = perfect_job.model_copy(update={"company": "Empresa Vetada Ltda"})
    score = services.scorer.score(job, profile)
    assert score.eliminated
    assert score.recommendation is Recommendation.DISCARD


def test_sufixo_juridico_nao_escapa_do_bloqueio(services, profile, perfect_job):
    """'Empresa Vetada' e 'Empresa Vetada S.A.' sao a mesma empresa."""
    job = perfect_job.model_copy(update={"company": "Empresa Vetada S.A."})
    assert services.scorer.score(job, profile).eliminated


# ---------------------------------------------------------------------------
# Dimensoes individuais
# ---------------------------------------------------------------------------


def _points(score, key: str) -> float:
    return next(d.points for d in score.dimensions if d.key == key)


def _max(score, key: str) -> float:
    return next(d.max_points for d in score.dimensions if d.key == key)


def test_senioridade_alvo_recebe_nota_cheia(services, profile, perfect_job):
    score = services.scorer.score(perfect_job, profile)
    assert _points(score, "seniority") == _max(score, "seniority")


def test_senioridade_nao_informada_fica_neutra(services, profile, perfect_job):
    job = perfect_job.model_copy(update={"seniority": Seniority.UNKNOWN})
    score = services.scorer.score(job, profile)
    assert _points(score, "seniority") == pytest.approx(_max(score, "seniority") * 0.6)


def test_remoto_vence_hibrido_que_vence_presencial(services, profile, perfect_job):
    def mode_points(mode: WorkMode) -> float:
        job = perfect_job.model_copy(update={"work_mode": mode})
        return _points(services.scorer.score(job, profile), "work_mode")

    assert mode_points(WorkMode.REMOTE) > mode_points(WorkMode.HYBRID)
    assert mode_points(WorkMode.HYBRID) > mode_points(WorkMode.ONSITE)
    score = services.scorer.score(perfect_job, profile)
    assert mode_points(WorkMode.REMOTE) == _max(score, "work_mode")


def test_salario_acima_do_alvo_recebe_nota_cheia(services, profile, perfect_job):
    score = services.scorer.score(perfect_job, profile)
    assert _points(score, "salary") == _max(score, "salary")


def test_salario_abaixo_do_minimo_penaliza(services, profile, perfect_job):
    job = perfect_job.model_copy(
        update={"salary_min_brl": 6000.0, "salary_max_brl": 6000.0, "salary_text": "R$ 6.000"}
    )
    score = services.scorer.score(job, profile)
    assert _points(score, "salary") < _max(score, "salary") * 0.5
    assert any("minimo" in gap.lower() for gap in score.gaps)


def test_salario_nao_divulgado_fica_neutro_e_vira_gap(services, profile, perfect_job):
    job = perfect_job.model_copy(
        update={"salary_min_brl": None, "salary_max_brl": None, "salary_text": ""}
    )
    score = services.scorer.score(job, profile)
    assert _points(score, "salary") == pytest.approx(_max(score, "salary") * 0.6)
    assert any("salarial" in gap.lower() for gap in score.gaps)


def test_presencial_no_exterior_zera_localizacao(services, profile, perfect_job):
    job = perfect_job.model_copy(
        update={
            "work_mode": WorkMode.ONSITE,
            "location": "Berlin, Germany",
            "country": "Germany",
        }
    )
    assert _points(services.scorer.score(job, profile), "location") == 0.0


def test_hibrido_na_cidade_preferida_pontua_cheio(services, profile, perfect_job):
    job = perfect_job.model_copy(
        update={"work_mode": WorkMode.HYBRID, "location": "Goiania, GO", "country": "Brasil"}
    )
    score = services.scorer.score(job, profile)
    assert _points(score, "location") == _max(score, "location")


def test_stack_fora_do_foco_perde_pontos(services, profile):
    job = Job(
        source="test",
        title="Senior Backend Engineer",
        company="Northwind Labs",
        seniority=Seniority.SENIOR,
        work_mode=WorkMode.REMOTE,
        location="Brasil",
        tech_tags=["Go", "Kafka"],
        description="Requirements:\n- Go\n- Kafka\n- Kubernetes",
    )
    score = services.scorer.score(job, profile)
    assert _points(score, "stack") < _max(score, "stack") * 0.5
    # Sem .NET/C#, a dimensao nuclear quase zera.
    assert _points(score, "dotnet") <= _max(score, "dotnet") * 0.15
    assert score.recommendation is Recommendation.DISCARD


def test_gaps_aparecem_e_nao_viram_compativeis(services, profile, perfect_job):
    job = perfect_job.model_copy(
        update={
            "description": perfect_job.description + "\n- Azure\n- Kafka",
            "tech_tags": [*perfect_job.tech_tags, "Azure", "Kafka"],
        }
    )
    score = services.scorer.score(job, profile)
    assert "azure" in [g.lower() for g in score.gaps]
    assert "kafka" in [g.lower() for g in score.gaps]
    assert "azure" not in [t.lower() for t in score.matched_technologies]


def test_vaga_sem_descricao_nao_quebra(services, profile):
    job = Job(source="test", title="Pessoa Desenvolvedora")
    score = services.scorer.score(job, profile)
    assert 0.0 <= score.total <= 100.0
    assert len(score.dimensions) == len(default_dimensions())


def test_dimensao_que_falha_nao_derruba_o_score(profile, perfect_job):
    class BrokenDimension:
        key = "broken"
        label = "Quebrada"
        max_points = 100.0

        def score(self, job, profile):
            raise RuntimeError("boom")

    score = JobScorer([BrokenDimension()]).score(perfect_job, profile)
    assert score.total == 0.0
    assert score.dimensions[0].points == 0.0

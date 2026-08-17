"""Somador de score e classificacao.

O `JobScorer` nao sabe pontuar nada: ele recebe dimensoes por injecao de
dependencia, soma e classifica. Trocar/adicionar uma dimensao nao exige
alterar esta classe.
"""

from __future__ import annotations

import logging

from ..models import (
    CandidateProfile,
    DimensionScore,
    Job,
    JobScore,
    Recommendation,
    Seniority,
)
from ..text import normalize_company, normalize_text
from .dimensions import IScoreDimension, default_dimensions

logger = logging.getLogger(__name__)

def classify(total: float, config=None) -> Recommendation:
    """Converte um total 0-100 em recomendacao, segundo as faixas configuradas.

    Faixas padrao (especificacao):
        90-100 Excelente | 75-89 Muito boa | 60-74 Boa
        40-59 Baixa      |  0-39 Nao prioritaria
    """
    from .config import ScoringConfig

    return (config or ScoringConfig()).recommendation(total)


class JobScorer:
    """Calcula o score de compatibilidade de uma vaga com o perfil."""

    def __init__(
        self,
        dimensions: list[IScoreDimension] | None = None,
        config: "ScoringConfig | None" = None,
    ) -> None:
        from .config import ScoringConfig

        self._config = config or ScoringConfig()
        self._dimensions = (
            dimensions if dimensions is not None else default_dimensions(self._config)
        )
        total_weight = sum(d.max_points for d in self._dimensions)
        if abs(total_weight - 100.0) > 0.01:
            logger.warning(
                "Pesos das dimensoes somam %.2f, esperado 100. O score sera "
                "normalizado para a escala 0-100.",
                total_weight,
            )
        self._total_weight = total_weight or 100.0

    # -- API ---------------------------------------------------------------

    def score(self, job: Job, profile: CandidateProfile) -> JobScore:
        eliminations = self._hard_eliminations(job, profile)

        results: list[DimensionScore] = []
        for dimension in self._dimensions:
            try:
                results.append(dimension.score(job, profile))
            except Exception:  # uma dimensao quebrada nao pode derrubar o score
                logger.exception("Dimensao '%s' falhou; pontuando 0.", dimension.key)
                results.append(
                    DimensionScore(
                        key=dimension.key,
                        label=dimension.label,
                        points=0.0,
                        max_points=dimension.max_points,
                        rationale="Erro interno ao pontuar esta dimensao.",
                    )
                )

        raw_total = sum(r.points for r in results)
        total = round(raw_total * 100.0 / self._total_weight, 1)

        if eliminations:
            # Elimina sem mascarar o calculo: o detalhamento continua visivel.
            total = min(total, 69.0)

        recommendation = (
            Recommendation.DISCARD
            if eliminations
            else self._config.recommendation(total)
        )

        gaps = _dedupe([g for r in results for g in r.gaps])
        matched = _dedupe([m for r in results for m in r.matched])

        score = JobScore(
            job_id=job.id,
            total=total,
            recommendation=recommendation,
            dimensions=results,
            gaps=gaps,
            matched_technologies=matched,
            eliminated=bool(eliminations),
            elimination_reasons=eliminations,
        )
        score.explanation = render_explanation(job, score, self._config)
        return score

    @property
    def config(self):
        return self._config

    # -- eliminacao --------------------------------------------------------

    def _hard_eliminations(self, job: Job, profile: CandidateProfile) -> list[str]:
        """Regras que descartam a vaga independentemente da pontuacao."""
        reasons: list[str] = []

        avoided = {normalize_text(s) for s in profile.avoid_seniorities}
        if (
            job.seniority is not Seniority.UNKNOWN
            and normalize_text(job.seniority.value) in avoided
        ):
            reasons.append(
                f"Senioridade '{job.seniority.value}' esta na lista de exclusao "
                f"do perfil (estagio/trainee/junior)."
            )

        blocked = {normalize_company(c) for c in profile.blocked_companies}
        company_key = normalize_company(job.company)
        if company_key and company_key in blocked:
            reasons.append(f"Empresa '{job.company}' esta bloqueada no perfil.")

        return reasons


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        marker = normalize_text(value)
        if marker and marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def render_explanation(job: Job, score: JobScore, config=None) -> str:
    """Renderiza o score no formato legivel pedido pela usuaria."""
    band = f" - {config.classify(score.total)}" if config else ""
    lines: list[str] = [f"Score: {score.total:g}/100{band}", ""]

    for dimension in score.dimensions:
        lines.append(f"{dimension.label}: {dimension.points:g}/{dimension.max_points:g}")

    lines.append("")
    lines.append("Detalhamento:")
    for dimension in score.dimensions:
        lines.append(f"  - {dimension.label}: {dimension.rationale}")

    if score.matched_technologies:
        lines.append("")
        lines.append("Tecnologias compativeis:")
        lines.append(f"  {', '.join(score.matched_technologies)}")

    lines.append("")
    if score.gaps:
        lines.append("Gaps:")
        for gap in score.gaps:
            lines.append(f"  - {gap}")
    else:
        lines.append("Gaps:")
        lines.append("  - nenhum identificado")

    if score.eliminated:
        lines.append("")
        lines.append("Eliminacao automatica:")
        for reason in score.elimination_reasons:
            lines.append(f"  - {reason}")

    lines.append("")
    lines.append("Recomendacao:")
    lines.append(f"{score.recommendation.value}")

    if job.url:
        lines.append("")
        lines.append(f"Link: {job.url}")

    return "\n".join(lines)

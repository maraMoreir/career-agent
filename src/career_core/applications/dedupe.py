"""Deteccao de candidatura duplicada.

Ordem de verificacao (da evidencia mais forte para a mais fraca):
    1. URL normalizada identica          -> DUPLICATE
    2. Mesma empresa + titulo muito parecido -> DUPLICATE
    3. Mesma empresa + titulo parecido       -> SIMILAR (alerta)
    4. Mesma empresa candidatada recentemente -> SIMILAR (alerta)

`SIMILAR` nunca bloqueia: informa e deixa a decisao com a humana.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..models import (
    Application,
    DuplicateCheckResult,
    DuplicateMatch,
    DuplicateVerdict,
)
from ..text import normalize_company, normalize_title, normalize_url, similarity
from .repository import IApplicationRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuplicateThresholds:
    duplicate_title_similarity: float = 0.85
    similar_title_similarity: float = 0.60
    recent_company_days: int = 45


class DuplicateDetector:
    """Consulta o historico e classifica o risco de duplicidade."""

    def __init__(
        self,
        repository: IApplicationRepository,
        thresholds: DuplicateThresholds | None = None,
    ) -> None:
        self._repository = repository
        self._thresholds = thresholds or DuplicateThresholds()

    def check(
        self, company: str, role: str, job_url: str = ""
    ) -> DuplicateCheckResult:
        matches: list[DuplicateMatch] = []
        verdict = DuplicateVerdict.NONE

        # --- 1. URL exata --------------------------------------------------
        normalized_url = normalize_url(job_url)
        if normalized_url:
            for existing in self._repository.find_by_normalized_url(job_url):
                matches.append(
                    self._match(
                        existing,
                        1.0,
                        f"URL identica ja registrada ({normalized_url}).",
                    )
                )
                verdict = DuplicateVerdict.DUPLICATE

        # --- 2/3. Empresa + titulo ----------------------------------------
        target_title = normalize_title(role)
        company_key = normalize_company(company)
        seen_ids = {m.application_id for m in matches}

        if company_key:
            for existing in self._repository.find_by_company(company):
                if existing.id in seen_ids:
                    continue

                ratio = similarity(target_title, normalize_title(existing.role))

                if ratio >= self._thresholds.duplicate_title_similarity:
                    matches.append(
                        self._match(
                            existing,
                            ratio,
                            f"Mesma empresa e cargo praticamente identico "
                            f"({ratio:.0%} de similaridade).",
                        )
                    )
                    verdict = DuplicateVerdict.DUPLICATE
                    seen_ids.add(existing.id)

                elif ratio >= self._thresholds.similar_title_similarity:
                    matches.append(
                        self._match(
                            existing,
                            ratio,
                            f"Mesma empresa, cargo parecido "
                            f"({ratio:.0%} de similaridade).",
                        )
                    )
                    if verdict is DuplicateVerdict.NONE:
                        verdict = DuplicateVerdict.SIMILAR
                    seen_ids.add(existing.id)

                elif self._is_recent(existing):
                    matches.append(
                        self._match(
                            existing,
                            ratio,
                            f"Voce se candidatou a outra vaga nessa empresa nos "
                            f"ultimos {self._thresholds.recent_company_days} dias.",
                        )
                    )
                    if verdict is DuplicateVerdict.NONE:
                        verdict = DuplicateVerdict.SIMILAR
                    seen_ids.add(existing.id)

        matches.sort(key=lambda m: m.similarity, reverse=True)
        result = DuplicateCheckResult(
            verdict=verdict, matches=matches, message=self._message(verdict, matches)
        )
        logger.info(
            "Checagem de duplicidade: %s - %s => %s (%d ocorrencia(s))",
            company,
            role,
            verdict.value,
            len(matches),
        )
        return result

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _match(existing: Application, ratio: float, reason: str) -> DuplicateMatch:
        return DuplicateMatch(
            application_id=existing.id,
            company=existing.company,
            role=existing.role,
            status=existing.status,
            created_at=existing.created_at,
            similarity=round(ratio, 3),
            reason=reason,
        )

    def _is_recent(self, application: Application) -> bool:
        try:
            created = datetime.fromisoformat(application.created_at)
        except ValueError:
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=self._thresholds.recent_company_days
        )
        return created >= cutoff

    @staticmethod
    def _message(verdict: DuplicateVerdict, matches: list[DuplicateMatch]) -> str:
        if verdict is DuplicateVerdict.NONE:
            return "Nenhuma candidatura semelhante encontrada no historico."

        lines = [
            "DUPLICADA: ja existe candidatura para essa vaga."
            if verdict is DuplicateVerdict.DUPLICATE
            else "ATENCAO: existe candidatura semelhante no historico.",
            "",
        ]
        for match in matches[:5]:
            lines.append(
                f"  - [{match.application_id}] {match.company} - {match.role} "
                f"(status: {match.status.value}, criada em {match.created_at[:10]})"
            )
            lines.append(f"    {match.reason}")

        if verdict is DuplicateVerdict.DUPLICATE:
            lines.append("")
            lines.append(
                "Recomendacao: nao registrar de novo. Se quiser mesmo assim, "
                "chame `register_application` com `allow_duplicate=true`."
            )
        else:
            lines.append("")
            lines.append(
                "Recomendacao: revise antes de registrar. Nao e bloqueante."
            )
        return "\n".join(lines)

"""Pipeline de coleta de vagas.

    buscar -> normalizar -> deduplicar -> pontuar -> salvar -> classificar

Cada execucao vira um `SearchExecution` no catalogo, com contagens e erros.
Isso torna a automacao auditavel: da para responder "o que a busca das 14h
encontrou, e por que trouxe menos que a das 12h".

Uma fonte que falha NAO derruba a execucao - ela e registrada como erro
parcial e as demais seguem.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .catalog.models import CatalogJob, JobStatus, SearchExecution
from .catalog.repository import IJobCatalog, technology_links, to_catalog_job
from .job_sources.base import JobQuery
from .models import CandidateProfile, utc_now_iso

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Resultado de uma execucao, pronto para virar texto ou JSON."""

    execution: SearchExecution
    new_jobs: list[CatalogJob] = field(default_factory=list)
    updated_jobs: list[CatalogJob] = field(default_factory=list)
    relevant: list[CatalogJob] = field(default_factory=list)

    def summary(self) -> str:
        exec_ = self.execution
        duration = exec_.duration_seconds()
        lines = [
            f"Execucao {exec_.id} - {exec_.status}",
            f"  Termos.........: {exec_.query or '(todos)'}",
            f"  Fontes.........: {', '.join(exec_.sources) or '(nenhuma)'}",
            f"  Vagas coletadas: {exec_.jobs_found}",
            f"  Novas..........: {exec_.jobs_new}",
            f"  Ja conhecidas..: {exec_.jobs_duplicated}",
            f"  Acima do corte.: {exec_.jobs_above_threshold} "
            f"(score >= {exec_.minimum_score:g})",
            f"  Melhor score...: {exec_.best_score:g}/100",
        ]
        if duration is not None:
            lines.append(f"  Duracao........: {duration:g}s")
        if exec_.errors:
            lines.append("  Erros:")
            lines.extend(f"    - {e}" for e in exec_.errors)
        return "\n".join(lines)


class JobSearchPipeline:
    """Orquestra a coleta. Nao sabe pontuar nem buscar - apenas coordena."""

    def __init__(
        self,
        job_search,
        scorer,
        catalog: IJobCatalog,
        minimum_score: float = 75.0,
    ) -> None:
        self._search = job_search
        self._scorer = scorer
        self._catalog = catalog
        self._minimum_score = minimum_score

    def run(
        self,
        profile: CandidateProfile,
        query: JobQuery,
        sources: list[str] | None = None,
        minimum_score: float | None = None,
    ) -> PipelineResult:
        threshold = self._minimum_score if minimum_score is None else minimum_score

        execution = SearchExecution(
            query=query.keywords,
            location=query.location,
            minimum_score=threshold,
        )
        self._catalog.start_execution(execution)
        result = PipelineResult(execution=execution)

        # 1-2. buscar + normalizar (as fontes ja devolvem `Job` normalizado)
        try:
            jobs, source_results = self._search.search(query, sources)
        except Exception as exc:
            logger.exception("Pipeline: busca falhou")
            execution.status = "failed"
            execution.errors.append(f"busca: {type(exc).__name__}: {exc}")
            execution.finished_at = utc_now_iso()
            self._catalog.finish_execution(execution)
            return result

        execution.sources = [r.source for r in source_results]
        execution.jobs_found = len(jobs)

        for source_result in source_results:
            self._record_source(source_result)
            if not source_result.ok:
                execution.errors.append(f"{source_result.source}: {source_result.message[:160]}")

        # 3-6. deduplicar + pontuar + salvar + classificar
        best = 0.0
        for job in jobs:
            try:
                score = self._scorer.score(job, profile)
            except Exception as exc:
                logger.exception("Pipeline: score falhou para '%s'", job.title)
                execution.errors.append(f"score '{job.title[:40]}': {type(exc).__name__}")
                continue

            best = max(best, score.total)
            catalog_job = to_catalog_job(job, score)

            try:
                saved, is_new = self._catalog.upsert_job(catalog_job)
                self._catalog.record_technologies(saved.id, technology_links(saved.id, score))
            except Exception as exc:
                logger.exception("Pipeline: falha ao salvar '%s'", job.title)
                execution.errors.append(f"salvar '{job.title[:40]}': {type(exc).__name__}")
                continue

            if is_new:
                execution.jobs_new += 1
                result.new_jobs.append(saved)
            else:
                execution.jobs_duplicated += 1
                result.updated_jobs.append(saved)

            if saved.match_score >= threshold and saved.status not in (
                JobStatus.DISCARDED,
                JobStatus.REJECTED,
            ):
                result.relevant.append(saved)

        execution.jobs_above_threshold = len(result.relevant)
        execution.best_score = best
        execution.status = "partial" if execution.errors else "ok"
        execution.finished_at = utc_now_iso()
        self._catalog.finish_execution(execution)

        result.relevant.sort(key=lambda j: j.match_score, reverse=True)
        result.new_jobs.sort(key=lambda j: j.match_score, reverse=True)

        logger.info(
            "Pipeline concluido: %d coletadas, %d novas, %d relevantes (>= %.0f)",
            execution.jobs_found, execution.jobs_new,
            execution.jobs_above_threshold, threshold,
        )
        return result

    def _record_source(self, source_result) -> None:
        try:
            self._catalog.record_source_run(
                name=source_result.source,
                collected=len(source_result.jobs),
                error="" if source_result.ok else source_result.message[:200],
            )
        except Exception:
            logger.exception("Pipeline: falha ao registrar a fonte")

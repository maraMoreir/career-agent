"""Fontes que consomem APIs publicas e documentadas.

Ambas as APIs abaixo foram VERIFICADAS contra a resposta real antes de escrever
o parser. Nenhum endpoint foi inventado.

  - Remotive : https://remotive.com/api/remote-jobs
               JSON publico, sem autenticacao. Resposta:
               {"job-count": int, "jobs": [{id, url, title, company_name,
                category, tags, job_type, publication_date,
                candidate_required_location, salary, description}]}

  - Arbeitnow: https://www.arbeitnow.com/api/job-board-api
               JSON publico, sem autenticacao. Resposta:
               {"data": [{slug, company_name, title, description, remote,
                url, tags, job_types, location, created_at}]}

Ambas sao consultadas com rate limit e User-Agent identificado. Sem cookies,
sem sessao, sem credencial. Se a resposta mudar de forma, o parser degrada
para campos vazios em vez de quebrar.
"""

from __future__ import annotations

import logging
from typing import Any

from ..errors import JobSourceError
from ..models import Job, WorkMode
from ..text import normalize_text
from .base import (
    IJobSource,
    JobQuery,
    RateLimiter,
    SourceResult,
    detect_seniority,
    detect_work_mode,
    parse_salary_brl,
    strip_html,
)

logger = logging.getLogger(__name__)


class _HttpJobSource(IJobSource):
    """Base com HTTP educado: timeout, rate limit e User-Agent honesto."""

    endpoint: str = ""

    def __init__(
        self,
        user_agent: str,
        timeout: float = 15.0,
        min_interval: float = 2.0,
        max_results: int = 25,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self._max_results = max_results
        self._limiter = RateLimiter(min_interval)

    def _fetch(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise JobSourceError(
                "httpx nao instalado. Rode scripts/install.ps1."
            ) from exc

        self._limiter.wait()
        headers = {"User-Agent": self._user_agent, "Accept": "application/json"}

        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                response = client.get(self.endpoint, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            raise JobSourceError(
                f"Falha ao consultar {self.name} ({self.endpoint}): {exc}"
            ) from exc

    @staticmethod
    def _matches_location(job: Job, wanted: str) -> bool:
        if not wanted:
            return True
        haystack = normalize_text(f"{job.location} {job.country}")
        needle = normalize_text(wanted)
        if needle in haystack:
            return True
        # Remoto sem restricao geografica serve para qualquer lugar.
        return job.work_mode is WorkMode.REMOTE and (
            not haystack
            or any(w in haystack for w in ("worldwide", "anywhere", "global"))
        )


class RemotiveJobSource(_HttpJobSource):
    """Vagas remotas via API publica da Remotive."""

    name = "remotive"
    endpoint = "https://remotive.com/api/remote-jobs"
    provenance = (
        "API JSON publica e documentada da Remotive (remotive.com/api/remote-jobs). "
        "Sem autenticacao, sem cookies, sem scraping. Somente vagas remotas."
    )
    usable = True

    def search(self, query: JobQuery) -> SourceResult:
        params: dict[str, Any] = {"limit": min(self._max_results, query.limit or 25)}
        if query.keywords:
            params["search"] = query.keywords

        try:
            payload = self._fetch(params)
        except JobSourceError as exc:
            logger.warning("remotive indisponivel: %s", exc)
            return SourceResult(source=self.name, ok=False, message=str(exc))

        jobs: list[Job] = []
        for entry in payload.get("jobs", []) or []:
            try:
                job = self._to_job(entry)
            except Exception:
                logger.exception("remotive: entrada ignorada por erro de parse")
                continue
            if self._matches_location(job, query.location):
                jobs.append(job)
            if len(jobs) >= self._max_results:
                break

        return SourceResult(
            source=self.name,
            jobs=jobs,
            ok=True,
            message=(
                f"{len(jobs)} vaga(s) da Remotive (API publica). "
                f"Somente vagas remotas; confirme se aceitam candidatas no Brasil."
            ),
        )

    def _to_job(self, entry: dict[str, Any]) -> Job:
        description = strip_html(str(entry.get("description") or ""))
        title = str(entry.get("title") or "").strip()
        location = str(entry.get("candidate_required_location") or "").strip()
        salary_text = str(entry.get("salary") or "").strip()
        low, high = parse_salary_brl(salary_text)

        tags = entry.get("tags") or []
        tech_tags = [str(t) for t in tags if isinstance(t, (str, int))]

        return Job(
            id=f"remotive-{entry.get('id', '')}",
            source=self.name,
            title=title or "(sem titulo)",
            company=str(entry.get("company_name") or "").strip(),
            url=str(entry.get("url") or "").strip(),
            description=description,
            tech_tags=tech_tags,
            seniority=detect_seniority(title, description),
            # A Remotive so publica vagas remotas.
            work_mode=WorkMode.REMOTE,
            location=location,
            country=location,
            salary_text=salary_text,
            salary_min_brl=low,
            salary_max_brl=high,
            posted_at=str(entry.get("publication_date") or ""),
            raw=entry,
        )


class ArbeitnowJobSource(_HttpJobSource):
    """Vagas via API publica do quadro de vagas Arbeitnow."""

    name = "arbeitnow"
    endpoint = "https://www.arbeitnow.com/api/job-board-api"
    provenance = (
        "API JSON publica e documentada do Arbeitnow "
        "(arbeitnow.com/api/job-board-api). Sem autenticacao. "
        "Base majoritariamente europeia - util para vagas remotas."
    )
    usable = True

    def search(self, query: JobQuery) -> SourceResult:
        try:
            payload = self._fetch({})
        except JobSourceError as exc:
            logger.warning("arbeitnow indisponivel: %s", exc)
            return SourceResult(source=self.name, ok=False, message=str(exc))

        keywords = [k for k in normalize_text(query.keywords).split() if len(k) > 1]
        jobs: list[Job] = []

        for entry in payload.get("data", []) or []:
            try:
                job = self._to_job(entry)
            except Exception:
                logger.exception("arbeitnow: entrada ignorada por erro de parse")
                continue

            haystack = normalize_text(job.searchable_text())
            if keywords and not any(k in haystack for k in keywords):
                continue
            if not self._matches_location(job, query.location):
                continue

            jobs.append(job)
            if len(jobs) >= min(self._max_results, query.limit or self._max_results):
                break

        return SourceResult(
            source=self.name,
            jobs=jobs,
            ok=True,
            message=(
                f"{len(jobs)} vaga(s) do Arbeitnow (API publica). "
                f"Base majoritariamente europeia - verifique elegibilidade."
            ),
        )

    def _to_job(self, entry: dict[str, Any]) -> Job:
        description = strip_html(str(entry.get("description") or ""))
        title = str(entry.get("title") or "").strip()
        location = str(entry.get("location") or "").strip()

        tags = entry.get("tags") or []
        job_types = entry.get("job_types") or []
        tech_tags = [str(t) for t in list(tags) + list(job_types) if isinstance(t, (str, int))]

        is_remote = bool(entry.get("remote"))
        work_mode = WorkMode.REMOTE if is_remote else detect_work_mode(title, description)

        return Job(
            id=f"arbeitnow-{entry.get('slug', '')}",
            source=self.name,
            title=title or "(sem titulo)",
            company=str(entry.get("company_name") or "").strip(),
            url=str(entry.get("url") or "").strip(),
            description=description,
            tech_tags=tech_tags,
            seniority=detect_seniority(title, description),
            work_mode=work_mode,
            location=location,
            country=location,
            salary_text="",
            posted_at=str(entry.get("created_at") or ""),
            raw=entry,
        )

"""Fonte de vagas: job boards publicos de ATS, por empresa.

ESTE E O CAMINHO QUE FUNCIONA PARA O BRASIL.

Greenhouse, Lever e Ashby publicam a lista de vagas de cada empresa num
endpoint JSON **publico, documentado e sem autenticacao** — e a mesma
resposta que alimenta a pagina de carreiras que qualquer pessoa abre no
navegador. Nao ha login, nao ha cookie, nao ha scraping de HTML e nao ha
anti-bot para contornar.

Endpoints (verificados contra a resposta real antes de escrever o parser):

    Greenhouse : GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
                 -> {"jobs": [{id, title, absolute_url, location:{name},
                     content, updated_at, departments, company_name}]}

    Lever      : GET https://api.lever.co/v0/postings/{slug}?mode=json
                 -> [{id, text, hostedUrl, workplaceType, country,
                     categories:{location, commitment, department},
                     descriptionPlain, additionalPlain, createdAt}]

    Ashby      : GET https://api.ashbyhq.com/posting-api/job-board/{slug}
                 -> {"jobs": [{id, title, jobUrl, location, isRemote,
                     workplaceType, employmentType, descriptionPlain,
                     publishedAt, department}]}

A cobertura depende de quais empresas voce configura em
`JOB_SEARCH_ATS_COMPANIES`. Empresas brasileiras de tecnologia usam muito
esses tres ATSs, entao a lista padrao ja traz vagas .NET reais.
"""

from __future__ import annotations

import concurrent.futures
import html
import logging
from abc import ABC, abstractmethod
from typing import Any

from ..errors import JobSourceError
from ..models import Job, Seniority, WorkMode
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


def _clean_html(raw: str) -> str:
    """Greenhouse devolve HTML com entidades escapadas (as vezes duas vezes)."""
    if not raw:
        return ""
    text = html.unescape(html.unescape(raw))
    return strip_html(text)


def _display_name(slug: str) -> str:
    """`quinto-andar` -> `Quinto Andar`. Estavel e limpo, ao contrario do
    `company_name` do Greenhouse (que vem como 'Stone - Linkedin')."""
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


# ---------------------------------------------------------------------------
# Adapters de ATS
# ---------------------------------------------------------------------------


class IAtsBoard(ABC):
    """Um provedor de ATS que expoe o quadro de vagas de uma empresa."""

    provider: str = ""

    @abstractmethod
    def endpoint(self, company: str) -> tuple[str, dict[str, Any]]:
        """Devolve `(url, params)` para o quadro da empresa."""

    @abstractmethod
    def parse(self, company: str, payload: Any) -> list[Job]:
        """Converte a resposta em `Job` normalizados."""


class GreenhouseBoard(IAtsBoard):
    provider = "greenhouse"

    def endpoint(self, company: str) -> tuple[str, dict[str, Any]]:
        return (
            f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs",
            {"content": "true"},
        )

    def parse(self, company: str, payload: Any) -> list[Job]:
        jobs: list[Job] = []
        for entry in (payload or {}).get("jobs", []) or []:
            title = str(entry.get("title") or "").strip()
            if not title:
                continue
            location = str((entry.get("location") or {}).get("name") or "").strip()
            description = _clean_html(str(entry.get("content") or ""))
            low, high = parse_salary_brl(description)

            jobs.append(
                Job(
                    id=f"greenhouse-{company}-{entry.get('id', '')}",
                    source="ats",
                    title=title,
                    company=_display_name(company),
                    url=str(entry.get("absolute_url") or "").strip(),
                    description=description,
                    # `departments` NAO entra aqui: `tech_tags` alimenta a
                    # dimensao Stack como tecnologia EXIGIDA, e "Engenharia &
                    # Tecnologia" viraria um gap inventado. As tecnologias sao
                    # extraidas da descricao.
                    tech_tags=[],
                    seniority=detect_seniority(title, description),
                    work_mode=detect_work_mode(location, title, description),
                    location=location,
                    country=_infer_country(location, description),
                    salary_min_brl=low,
                    salary_max_brl=high,
                    posted_at=str(entry.get("first_published") or entry.get("updated_at") or ""),
                    raw={"provider": self.provider, "company": company},
                )
            )
        return jobs


class LeverBoard(IAtsBoard):
    provider = "lever"

    _MODES = {
        "remote": WorkMode.REMOTE,
        "hybrid": WorkMode.HYBRID,
        "onsite": WorkMode.ONSITE,
        "on-site": WorkMode.ONSITE,
    }

    def endpoint(self, company: str) -> tuple[str, dict[str, Any]]:
        return f"https://api.lever.co/v0/postings/{company}", {"mode": "json"}

    def parse(self, company: str, payload: Any) -> list[Job]:
        jobs: list[Job] = []
        for entry in payload or []:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("text") or "").strip()
            if not title:
                continue

            categories = entry.get("categories") or {}
            location = str(categories.get("location") or "").strip()
            description = "\n\n".join(
                part
                for part in (
                    str(entry.get("descriptionPlain") or ""),
                    str(entry.get("additionalPlain") or ""),
                )
                if part.strip()
            )
            mode = self._MODES.get(
                normalize_text(str(entry.get("workplaceType") or ""))
            ) or detect_work_mode(location, title, description)
            low, high = parse_salary_brl(description)

            jobs.append(
                Job(
                    id=f"lever-{company}-{entry.get('id', '')}",
                    source="ats",
                    title=title,
                    company=_display_name(company),
                    url=str(entry.get("hostedUrl") or entry.get("applyUrl") or "").strip(),
                    description=description,
                    tech_tags=[],  # department/team nao sao tecnologias
                    seniority=detect_seniority(title, description),
                    work_mode=mode,
                    location=location,
                    country=str(entry.get("country") or "")
                    or _infer_country(location, description),
                    salary_min_brl=low,
                    salary_max_brl=high,
                    posted_at=str(entry.get("createdAt") or ""),
                    raw={"provider": self.provider, "company": company},
                )
            )
        return jobs


class AshbyBoard(IAtsBoard):
    provider = "ashby"

    _MODES = {
        "remote": WorkMode.REMOTE,
        "hybrid": WorkMode.HYBRID,
        "onsite": WorkMode.ONSITE,
    }

    def endpoint(self, company: str) -> tuple[str, dict[str, Any]]:
        return f"https://api.ashbyhq.com/posting-api/job-board/{company}", {}

    def parse(self, company: str, payload: Any) -> list[Job]:
        jobs: list[Job] = []
        for entry in (payload or {}).get("jobs", []) or []:
            if entry.get("isListed") is False:
                continue
            title = str(entry.get("title") or "").strip()
            if not title:
                continue

            location = str(entry.get("location") or "").strip()
            description = str(entry.get("descriptionPlain") or "")
            mode = self._MODES.get(normalize_text(str(entry.get("workplaceType") or "")))
            if mode is None:
                mode = (
                    WorkMode.REMOTE
                    if entry.get("isRemote")
                    else detect_work_mode(location, title, description)
                )
            low, high = parse_salary_brl(description)

            jobs.append(
                Job(
                    id=f"ashby-{company}-{entry.get('id', '')}",
                    source="ats",
                    title=title,
                    company=_display_name(company),
                    url=str(entry.get("jobUrl") or entry.get("applyUrl") or "").strip(),
                    description=description,
                    tech_tags=[],  # department/team nao sao tecnologias
                    seniority=detect_seniority(title, description),
                    work_mode=mode,
                    location=location,
                    country=_infer_country(location, description),
                    salary_min_brl=low,
                    salary_max_brl=high,
                    posted_at=str(entry.get("publishedAt") or ""),
                    raw={"provider": self.provider, "company": company},
                )
            )
        return jobs


_BR_MARKERS = (
    "brasil", "brazil", "sao paulo", "rio de janeiro", "belo horizonte",
    "curitiba", "porto alegre", "goiania", "florianopolis", "recife",
    "campinas", "salvador", "fortaleza", "brasilia", "remoto",
)


def _infer_country(location: str, description: str) -> str:
    haystack = normalize_text(f"{location} {description[:400]}")
    if any(marker in haystack for marker in _BR_MARKERS):
        return "Brasil"
    return location


BOARDS: dict[str, IAtsBoard] = {
    board.provider: board
    for board in (GreenhouseBoard(), LeverBoard(), AshbyBoard())
}


# ---------------------------------------------------------------------------
# Fonte
# ---------------------------------------------------------------------------

#: Empresas verificadas com quadro publico e vagas de engenharia no Brasil.
DEFAULT_COMPANIES: tuple[str, ...] = (
    "greenhouse:stone",
    "greenhouse:c6bank",
    "greenhouse:quintoandar",
    "greenhouse:vtex",
    "greenhouse:gympass",
    "greenhouse:inter",
    "greenhouse:ebanx",
    "greenhouse:rdstation",
    "ashby:nubank",
    "lever:neon",
)


class AtsBoardsJobSource(IJobSource):
    """Consulta os quadros publicos de varias empresas e normaliza tudo."""

    name = "ats"
    provenance = (
        "Job boards publicos de ATS (Greenhouse, Lever, Ashby), consultados por "
        "empresa. Mesma resposta JSON que alimenta a pagina de carreiras publica "
        "de cada companhia: sem autenticacao, sem cookies, sem scraping. "
        "E a fonte com melhor cobertura de vagas .NET no Brasil."
    )
    usable = True

    def __init__(
        self,
        companies: tuple[str, ...] | None = None,
        user_agent: str = "career-agent/1.0",
        timeout: float = 15.0,
        min_interval: float = 0.0,
        max_results: int = 25,
        max_workers: int = 4,
    ) -> None:
        # `is None` e nao `or`: uma tupla vazia significa "nenhuma empresa
        # configurada" e deve gerar aviso, nao cair no padrao silenciosamente.
        self._companies = DEFAULT_COMPANIES if companies is None else tuple(companies)
        self._user_agent = user_agent
        self._timeout = timeout
        self._max_results = max_results
        self._max_workers = max(1, min(max_workers, 6))
        self._limiter = RateLimiter(min_interval)

    # -- infraestrutura ----------------------------------------------------

    def _fetch_board(self, spec: str) -> tuple[str, list[Job], str]:
        """Busca um quadro. Devolve `(spec, vagas, erro)` - nunca levanta."""
        provider, _, company = spec.partition(":")
        provider = provider.strip().lower()
        company = company.strip()

        board = BOARDS.get(provider)
        if board is None or not company:
            return spec, [], f"provedor desconhecido em '{spec}'"

        url, params = board.endpoint(company)
        try:
            import httpx

            self._limiter.wait()
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                response = client.get(
                    url,
                    params=params,
                    headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                )
                if response.status_code == 404:
                    return spec, [], "quadro nao encontrado (slug errado?)"
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("ats: falha em %s: %s", spec, exc)
            return spec, [], f"{type(exc).__name__}"

        try:
            return spec, board.parse(company, payload), ""
        except Exception as exc:
            logger.exception("ats: erro de parse em %s", spec)
            return spec, [], f"parse: {type(exc).__name__}"

    # -- API ---------------------------------------------------------------

    def search(self, query: JobQuery) -> SourceResult:
        if not self._companies:
            return SourceResult(
                source=self.name,
                ok=False,
                message=(
                    "Nenhuma empresa configurada. Defina JOB_SEARCH_ATS_COMPANIES "
                    "no .env, no formato 'greenhouse:stone,ashby:nubank'."
                ),
            )

        collected: list[Job] = []
        failures: list[str] = []
        scanned = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for spec, jobs, error in pool.map(self._fetch_board, self._companies):
                if error:
                    failures.append(f"{spec} ({error})")
                    continue
                scanned += len(jobs)
                collected.extend(jobs)

        matched = [job for job in collected if self._matches(job, query)]

        # Ordena por RELEVANCIA antes de truncar. Cortar por data descartaria
        # justamente as vagas mais aderentes - foi assim que uma vaga
        # ".NET Senior" sumiu atras de uma dezena de "backend" genericos.
        keywords = [k for k in normalize_text(query.keywords).split() if len(k) > 1]
        matched.sort(
            key=lambda j: (self._relevance(j, keywords), j.posted_at), reverse=True
        )

        limited = matched[: max(1, min(self._max_results, query.limit or self._max_results))]

        boards_ok = len(self._companies) - len(failures)
        message = (
            f"{len(limited)} vaga(s) de {boards_ok}/{len(self._companies)} quadro(s) "
            f"publico(s) de ATS ({scanned} vagas varridas). "
            f"Fonte: paginas de carreira das proprias empresas."
        )
        if failures:
            message += f" Indisponiveis: {', '.join(failures[:4])}."
        if not limited and scanned:
            message += (
                " Nenhuma bateu com os filtros - tente palavras-chave mais amplas "
                "('backend', 'software engineer') ou adicione empresas em "
                "JOB_SEARCH_ATS_COMPANIES."
            )

        return SourceResult(source=self.name, jobs=limited, ok=True, message=message)

    # -- relevancia e filtros ---------------------------------------------

    @staticmethod
    def _relevance(job: Job, keywords: list[str]) -> int:
        """Quantos termos da busca a vaga casa, com peso extra para o titulo.

        E uma pre-ordenacao barata para escolher QUAIS vagas passam adiante.
        O ranking final continua sendo o score de compatibilidade completo.
        """
        if not keywords:
            return 0
        title = normalize_text(job.title)
        body = normalize_text(job.searchable_text())
        score = 0
        for keyword in keywords:
            if keyword in title:
                score += 3
            elif keyword in body:
                score += 1
        return score

    def _matches(self, job: Job, query: JobQuery) -> bool:
        keywords = [k for k in normalize_text(query.keywords).split() if len(k) > 1]
        if keywords:
            haystack = normalize_text(job.searchable_text())
            if not any(k in haystack for k in keywords):
                return False

        if query.location:
            needle = normalize_text(query.location)
            haystack = normalize_text(f"{job.location} {job.country}")
            remote_anywhere = job.work_mode is WorkMode.REMOTE
            if needle not in haystack and not remote_anywhere:
                return False

        if query.work_modes:
            wanted = {normalize_text(m) for m in query.work_modes if m}
            if wanted and normalize_text(job.work_mode.value) not in wanted:
                return False

        if query.seniorities:
            wanted = {normalize_text(s) for s in query.seniorities if s}
            if wanted and normalize_text(job.seniority.value) not in wanted:
                return False

        return True

"""Registro e agregacao de fontes de vagas.

Ponto unico de composicao (composition root das fontes). Para adicionar uma
fonte nova: implemente `IJobSource` e registre em `_FACTORIES`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..config import Settings
from ..models import Job
from ..text import normalize_company, normalize_title, normalize_url, similarity
from .base import IJobSource, JobQuery, SourceResult
from .http_sources import ArbeitnowJobSource, RemotiveJobSource
from .mock import MockJobSource
from .unavailable import gupy_source, indeed_source, linkedin_source

logger = logging.getLogger(__name__)

#: nome -> (fabrica, exige_rede)
_FACTORIES: dict[str, tuple[Callable[[Settings], IJobSource], bool]] = {
    "mock": (lambda _s: MockJobSource(), False),
    "remotive": (
        lambda s: RemotiveJobSource(
            user_agent=s.user_agent,
            timeout=s.http_timeout,
            min_interval=s.min_interval,
            max_results=s.max_results,
        ),
        True,
    ),
    "arbeitnow": (
        lambda s: ArbeitnowJobSource(
            user_agent=s.user_agent,
            timeout=s.http_timeout,
            min_interval=s.min_interval,
            max_results=s.max_results,
        ),
        True,
    ),
    "linkedin": (lambda _s: linkedin_source(), False),
    "indeed": (lambda _s: indeed_source(), False),
    "gupy": (lambda _s: gupy_source(), False),
}


class JobSourceRegistry:
    """Resolve nomes de fonte em instancias, respeitando a configuracao."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[str, IJobSource] = {}

    def available_names(self) -> list[str]:
        return sorted(_FACTORIES)

    def enabled_names(self) -> list[str]:
        """Fontes ligadas no `.env`, filtrando as que precisam de rede desligada."""
        enabled: list[str] = []
        for name in self._settings.sources:
            factory = _FACTORIES.get(name)
            if factory is None:
                logger.warning("Fonte desconhecida em JOB_SEARCH_SOURCES: '%s'", name)
                continue
            _, needs_network = factory
            if needs_network and not self._settings.enable_network:
                logger.info("Fonte '%s' ignorada: rede desabilitada.", name)
                continue
            enabled.append(name)
        return enabled or ["mock"]

    def get(self, name: str) -> IJobSource | None:
        key = name.strip().lower()
        if key in self._cache:
            return self._cache[key]
        entry = _FACTORIES.get(key)
        if entry is None:
            return None
        factory, needs_network = entry
        if needs_network and not self._settings.enable_network:
            return None
        source = factory(self._settings)
        self._cache[key] = source
        return source

    def describe_all(self) -> list[dict[str, object]]:
        descriptions: list[dict[str, object]] = []
        for name, (factory, needs_network) in sorted(_FACTORIES.items()):
            source = factory(self._settings)
            info = source.describe()
            info["requires_network"] = needs_network
            info["enabled"] = name in self.enabled_names()
            descriptions.append(info)
        return descriptions


class AggregatedJobSearch:
    """Consulta varias fontes e deduplica o resultado combinado."""

    def __init__(self, registry: JobSourceRegistry) -> None:
        self._registry = registry

    def search(
        self, query: JobQuery, sources: list[str] | None = None
    ) -> tuple[list[Job], list[SourceResult]]:
        names = sources or self._registry.enabled_names()
        results: list[SourceResult] = []
        collected: list[Job] = []

        for name in names:
            source = self._registry.get(name)
            if source is None:
                results.append(
                    SourceResult(
                        source=name,
                        ok=False,
                        message=(
                            f"Fonte '{name}' indisponivel. Ou nao existe, ou exige "
                            f"rede com JOB_SEARCH_ENABLE_NETWORK=false."
                        ),
                    )
                )
                continue

            try:
                result = source.search(query)
            except Exception as exc:
                logger.exception("Fonte '%s' falhou", name)
                result = SourceResult(source=name, ok=False, message=str(exc))

            results.append(result)
            collected.extend(result.jobs)

        return deduplicate_jobs(collected), results


def deduplicate_jobs(jobs: list[Job], threshold: float = 0.9) -> list[Job]:
    """Remove a mesma vaga publicada em mais de uma fonte.

    Chave forte: URL normalizada. Chave fraca: empresa + titulo muito similar.
    """
    unique: list[Job] = []
    seen_urls: set[str] = set()
    seen_pairs: list[tuple[str, str]] = []

    for job in jobs:
        url_key = normalize_url(job.url)
        if url_key and url_key in seen_urls:
            continue

        company_key = normalize_company(job.company)
        title_key = normalize_title(job.title)

        is_duplicate = any(
            company_key
            and company_key == existing_company
            and similarity(title_key, existing_title) >= threshold
            for existing_company, existing_title in seen_pairs
        )
        if is_duplicate:
            continue

        if url_key:
            seen_urls.add(url_key)
        seen_pairs.append((company_key, title_key))
        unique.append(job)

    return unique

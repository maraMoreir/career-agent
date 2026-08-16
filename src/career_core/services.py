"""Composition root.

Um unico lugar constroi o grafo de objetos. Os servidores MCP nao instanciam
dependencias a mao - eles pedem ao container. Isso mantem os adapters MCP
finos e permite injetar dublês em teste.
"""

from __future__ import annotations

import logging
from functools import cached_property

from .applications.builder import ApplicationBuilder
from .applications.dedupe import DuplicateDetector
from .applications.repository import IApplicationRepository, SqliteApplicationRepository
from .config import Settings, get_settings
from .job_sources.registry import AggregatedJobSearch, JobSourceRegistry
from .models import CandidateProfile
from .profile.repository import IProfileRepository, MarkdownProfileRepository
from .paths import SandboxedFileSystem
from .resume.tailor import ResumeTailor
from .scoring.scorer import JobScorer
from .security import ApprovalGate

logger = logging.getLogger(__name__)


class CareerServices:
    """Container de dependencias do Career Agent."""

    def __init__(
        self,
        settings: Settings | None = None,
        profile_repository: IProfileRepository | None = None,
        application_repository: IApplicationRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        self._profile_repository = profile_repository
        self._application_repository = application_repository

    # -- infraestrutura ----------------------------------------------------

    @cached_property
    def approval_gate(self) -> ApprovalGate:
        return ApprovalGate()

    @cached_property
    def profile_repository(self) -> IProfileRepository:
        return self._profile_repository or MarkdownProfileRepository(
            self.settings.profile_dir
        )

    @cached_property
    def applications(self) -> IApplicationRepository:
        return self._application_repository or SqliteApplicationRepository(
            database_path=self.settings.database_path,
            json_mirror_path=self.settings.json_mirror_path,
            approval_gate=self.approval_gate,
        )

    @cached_property
    def filesystem(self) -> SandboxedFileSystem:
        return SandboxedFileSystem(self.settings.data_root)

    # -- dominio -----------------------------------------------------------

    @cached_property
    def scorer(self) -> JobScorer:
        return JobScorer()

    @cached_property
    def duplicates(self) -> DuplicateDetector:
        return DuplicateDetector(self.applications)

    @cached_property
    def job_sources(self) -> JobSourceRegistry:
        return JobSourceRegistry(self.settings)

    @cached_property
    def job_search(self) -> AggregatedJobSearch:
        return AggregatedJobSearch(self.job_sources)

    # -- dependem do perfil (recarregado sob demanda) -----------------------

    def profile(self) -> CandidateProfile:
        """Le o perfil do disco a cada chamada: editar o .md reflete na hora."""
        return self.profile_repository.load()

    def tailor(self, profile: CandidateProfile | None = None) -> ResumeTailor:
        return ResumeTailor(self.settings.resumes_dir, profile or self.profile())

    def application_builder(
        self, profile: CandidateProfile | None = None
    ) -> ApplicationBuilder:
        resolved = profile or self.profile()
        return ApplicationBuilder(resolved, self.tailor(resolved))

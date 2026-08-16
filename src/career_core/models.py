"""Modelos de dominio.

Todos os modelos sao pydantic para validacao automatica na fronteira MCP.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WorkMode(str, Enum):
    REMOTE = "remoto"
    HYBRID = "hibrido"
    ONSITE = "presencial"
    UNKNOWN = "nao_informado"


class Seniority(str, Enum):
    INTERN = "estagio"
    TRAINEE = "trainee"
    JUNIOR = "junior"
    MID = "pleno"
    SENIOR = "senior"
    SPECIALIST = "especialista"
    LEAD = "lead"
    UNKNOWN = "nao_informado"


class Recommendation(str, Enum):
    HIGH_PRIORITY = "PRIORIDADE ALTA"
    PRIORITY = "PRIORIDADE"
    ANALYZE = "ANALISAR"
    DISCARD = "DESCARTAR"


class ApplicationStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    APPLIED = "applied"
    INTERVIEW = "interview"
    TECHNICAL_TEST = "technical_test"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class DuplicateVerdict(str, Enum):
    NONE = "none"
    SIMILAR = "similar"
    DUPLICATE = "duplicate"


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------


class CandidateProfile(BaseModel):
    """Perfil factual da candidata. Fonte unica de verdade sobre o que ela sabe.

    Nada fora deste modelo pode ser afirmado como experiencia dela.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str = ""
    headline: str = ""
    summary: str = ""

    skills: list[str] = Field(default_factory=list)
    architecture: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)

    target_roles: list[str] = Field(default_factory=list)
    preferred_seniorities: list[str] = Field(default_factory=list)
    avoid_seniorities: list[str] = Field(default_factory=list)
    work_mode_priority: list[str] = Field(default_factory=list)

    countries: list[str] = Field(default_factory=list)
    preferred_cities: list[str] = Field(default_factory=list)

    min_salary_brl: float | None = None
    target_salary_brl: float | None = None

    # Deliberadamente opcional: o perfil informado nao declara anos de
    # experiencia. Fica `None` ate a usuaria preencher. Nunca inferimos.
    years_experience: float | None = None

    preferred_companies: list[str] = Field(default_factory=list)
    blocked_companies: list[str] = Field(default_factory=list)

    languages: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)

    def known_terms(self) -> set[str]:
        """Todo termo tecnico/dominio que a candidata declarou possuir."""
        from .text import normalize_term

        terms: set[str] = set()
        for bucket in (self.skills, self.architecture, self.domains):
            for item in bucket:
                terms.add(normalize_term(item))
        terms.discard("")
        return terms


# ---------------------------------------------------------------------------
# Vaga
# ---------------------------------------------------------------------------


class Job(BaseModel):
    """Vaga normalizada, independente da fonte de origem."""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    source: str = "manual"
    title: str
    company: str = ""
    url: str = ""

    description: str = ""
    tech_tags: list[str] = Field(default_factory=list)

    seniority: Seniority = Seniority.UNKNOWN
    work_mode: WorkMode = WorkMode.UNKNOWN

    location: str = ""
    country: str = ""

    salary_text: str = ""
    salary_min_brl: float | None = None
    salary_max_brl: float | None = None

    posted_at: str = ""
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("A vaga precisa de um titulo (cargo).")
        return value.strip()

    def model_post_init(self, _context: Any) -> None:
        if not self.id:
            seed = f"{self.source}|{self.company}|{self.title}|{self.url}".lower()
            object.__setattr__(
                self, "id", hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
            )

    def searchable_text(self) -> str:
        return " ".join(
            [self.title, self.description, " ".join(self.tech_tags), self.company]
        )


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------


class DimensionScore(BaseModel):
    """Pontuacao de uma unica dimensao, com justificativa."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    points: float
    max_points: float
    rationale: str
    matched: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    def as_line(self) -> str:
        return f"{self.label}: {self.points:g}/{self.max_points:g}"


class JobScore(BaseModel):
    """Resultado completo do score, sempre explicavel."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    total: float
    recommendation: Recommendation
    dimensions: list[DimensionScore]
    gaps: list[str] = Field(default_factory=list)
    matched_technologies: list[str] = Field(default_factory=list)
    eliminated: bool = False
    elimination_reasons: list[str] = Field(default_factory=list)
    explanation: str = ""


# ---------------------------------------------------------------------------
# Candidatura
# ---------------------------------------------------------------------------


class SuggestedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    grounded_in: list[str] = Field(default_factory=list)


class StatusEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus
    at: str = Field(default_factory=utc_now_iso)
    note: str = ""


class Application(BaseModel):
    """Registro de candidatura. Nunca sai de `pending_approval` sozinho."""

    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    status: ApplicationStatus = ApplicationStatus.PENDING_APPROVAL

    company: str
    role: str
    job_url: str = ""
    job_source: str = "manual"

    score: float = 0.0
    recommendation: Recommendation = Recommendation.ANALYZE
    score_breakdown: list[DimensionScore] = Field(default_factory=list)

    salary_text: str = ""
    work_mode: WorkMode = WorkMode.UNKNOWN
    location: str = ""

    key_requirements: list[str] = Field(default_factory=list)
    matched_technologies: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    recommended_resume: str = ""
    tailored_summary: str = ""
    recruiter_message: str = ""
    suggested_answers: list[SuggestedAnswer] = Field(default_factory=list)

    notes: str = ""
    history: list[StatusEvent] = Field(default_factory=list)

    def normalized_key(self) -> str:
        from .text import normalize_company, normalize_title

        return f"{normalize_company(self.company)}|{normalize_title(self.role)}"


class DuplicateMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: str
    company: str
    role: str
    status: ApplicationStatus
    created_at: str
    similarity: float
    reason: str


class DuplicateCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: DuplicateVerdict
    matches: list[DuplicateMatch] = Field(default_factory=list)
    message: str = ""

    @property
    def is_blocking(self) -> bool:
        return self.verdict is DuplicateVerdict.DUPLICATE

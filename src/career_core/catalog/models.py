"""Entidades do catalogo de vagas.

Separadas de `career_core.models` de proposito: aquele modulo descreve o que
trafega entre as camadas (Job normalizado, score, candidatura preparada); este
descreve o que fica GUARDADO no banco e evolui com o tempo.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from ..models import Recommendation, Seniority, WorkMode, utc_now_iso


class JobStatus(str, Enum):
    """Ciclo de vida de uma vaga no funil.

    `APPLIED` e os estados seguintes so podem ser alcancados apos aprovacao
    humana explicita da candidatura - ver `career_core.security.ApprovalGate`.
    """

    FOUND = "Found"
    ANALYZED = "Analyzed"
    INTERESTED = "Interested"
    APPLIED = "Applied"
    INTERVIEW = "Interview"
    REJECTED = "Rejected"
    DISCARDED = "Discarded"


#: Estados que implicam contato externo ja feito pela humana.
JOB_EXTERNAL_STATES: frozenset[JobStatus] = frozenset(
    {JobStatus.APPLIED, JobStatus.INTERVIEW}
)


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    name: str
    normalized_name: str = ""
    website: str = ""
    first_seen_at: str = Field(default_factory=utc_now_iso)
    jobs_count: int = 0


class JobSourceRecord(BaseModel):
    """Metadados operacionais de uma fonte, para diagnostico e estatistica."""

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str = ""
    kind: str = "api"  # api | ats | mock | manual | unavailable
    enabled: bool = True
    last_run_at: str = ""
    jobs_collected: int = 0
    last_error: str = ""


class Technology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    name: str
    canonical: str = ""
    category: str = "tech"  # tech | architecture | domain


class JobTechnology(BaseModel):
    """Ligacao vaga <-> tecnologia, com o veredito do matching."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    technology: str
    required: bool = True
    matched: bool = False  # a candidata possui essa tecnologia?


class CatalogJob(BaseModel):
    """Vaga persistida. Contem os campos exigidos pela especificacao."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    company: str = ""
    description: str = ""
    location: str = ""
    work_model: WorkMode = WorkMode.UNKNOWN
    salary: str = ""
    salary_min_brl: float | None = None
    salary_max_brl: float | None = None
    url: str = ""
    source: str = "manual"
    published_at: str = ""
    collected_at: str = Field(default_factory=utc_now_iso)
    match_score: float = 0.0
    recommendation: Recommendation = Recommendation.ANALYZE
    status: JobStatus = JobStatus.FOUND

    seniority: Seniority = Seniority.UNKNOWN
    matched_technologies: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    score_explanation: str = ""
    application_id: str = ""
    notes: str = ""
    updated_at: str = Field(default_factory=utc_now_iso)


class SearchExecution(BaseModel):
    """Registro de uma execucao do pipeline de busca."""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: str = ""
    query: str = ""
    location: str = ""
    sources: list[str] = Field(default_factory=list)
    jobs_found: int = 0
    jobs_new: int = 0
    jobs_duplicated: int = 0
    jobs_above_threshold: int = 0
    best_score: float = 0.0
    minimum_score: float = 0.0
    status: str = "running"  # running | ok | partial | failed
    errors: list[str] = Field(default_factory=list)

    def duration_seconds(self) -> float | None:
        from datetime import datetime

        if not self.finished_at:
            return None
        try:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.finished_at)
        except ValueError:
            return None
        return round((end - start).total_seconds(), 2)

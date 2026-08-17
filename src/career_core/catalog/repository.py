"""Persistencia do catalogo de vagas (SQLite).

Mesma decisao do repositorio de candidaturas: SQLite como fonte de verdade,
por dar transacao e indice sem exigir servidor. Aqui o volume e maior
(milhares de vagas ao longo do tempo), o que reforca a escolha - varrer um
JSON a cada checagem de duplicidade nao escalaria.

O banco e SEPARADO do de candidaturas (`catalog.db` vs `applications.db`):
sao ciclos de vida diferentes. Vagas sao descartaveis e recoletaveis; o
historico de candidaturas e o registro que voce nao pode perder. Poder apagar
`catalog.db` e recomecar a coleta sem risco algum e uma propriedade util.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..errors import CareerAgentError
from ..models import Job, JobScore, utc_now_iso
from ..text import normalize_company, normalize_title, normalize_url, similarity
from .models import (
    CatalogJob,
    Company,
    JobSourceRecord,
    JobStatus,
    JobTechnology,
    SearchExecution,
    Technology,
)

logger = logging.getLogger(__name__)


class JobNotFoundError(CareerAgentError):
    """Vaga inexistente no catalogo."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    website         TEXT NOT NULL DEFAULT '',
    first_seen_at   TEXT NOT NULL,
    jobs_count      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS job_sources (
    name           TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL DEFAULT '',
    kind           TEXT NOT NULL DEFAULT 'api',
    enabled        INTEGER NOT NULL DEFAULT 1,
    last_run_at    TEXT NOT NULL DEFAULT '',
    jobs_collected INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS technologies (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    canonical TEXT NOT NULL UNIQUE,
    category  TEXT NOT NULL DEFAULT 'tech'
);

CREATE TABLE IF NOT EXISTS jobs (
    id                 TEXT PRIMARY KEY,
    title              TEXT NOT NULL,
    company            TEXT NOT NULL DEFAULT '',
    normalized_company TEXT NOT NULL DEFAULT '',
    normalized_title   TEXT NOT NULL DEFAULT '',
    url                TEXT NOT NULL DEFAULT '',
    normalized_url     TEXT NOT NULL DEFAULT '',
    source             TEXT NOT NULL DEFAULT 'manual',
    location           TEXT NOT NULL DEFAULT '',
    work_model         TEXT NOT NULL DEFAULT '',
    match_score        REAL NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'Found',
    published_at       TEXT NOT NULL DEFAULT '',
    collected_at       TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    payload            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_norm_url     ON jobs(normalized_url);
CREATE INDEX IF NOT EXISTS idx_jobs_norm_company ON jobs(normalized_company);
CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score        ON jobs(match_score);
CREATE INDEX IF NOT EXISTS idx_jobs_collected    ON jobs(collected_at);

CREATE TABLE IF NOT EXISTS job_technologies (
    job_id     TEXT NOT NULL,
    technology TEXT NOT NULL,
    required   INTEGER NOT NULL DEFAULT 1,
    matched    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (job_id, technology),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobtech_tech ON job_technologies(technology);

CREATE TABLE IF NOT EXISTS search_executions (
    id                    TEXT PRIMARY KEY,
    started_at            TEXT NOT NULL,
    finished_at           TEXT NOT NULL DEFAULT '',
    query                 TEXT NOT NULL DEFAULT '',
    location              TEXT NOT NULL DEFAULT '',
    sources               TEXT NOT NULL DEFAULT '',
    jobs_found            INTEGER NOT NULL DEFAULT 0,
    jobs_new              INTEGER NOT NULL DEFAULT 0,
    jobs_duplicated       INTEGER NOT NULL DEFAULT 0,
    jobs_above_threshold  INTEGER NOT NULL DEFAULT 0,
    best_score            REAL NOT NULL DEFAULT 0,
    minimum_score         REAL NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'running',
    errors                TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_exec_started ON search_executions(started_at);
"""


class IJobCatalog(ABC):
    """Contrato do catalogo de vagas."""

    @abstractmethod
    def upsert_job(self, job: CatalogJob) -> tuple[CatalogJob, bool]: ...

    @abstractmethod
    def get_job(self, job_id: str) -> CatalogJob: ...

    @abstractmethod
    def find_job(self, job_id: str) -> CatalogJob | None: ...

    @abstractmethod
    def list_jobs(self, **filters) -> list[CatalogJob]: ...

    @abstractmethod
    def find_duplicate(self, job: CatalogJob) -> CatalogJob | None: ...

    @abstractmethod
    def update_status(self, job_id: str, status: JobStatus) -> CatalogJob: ...


class SqliteJobCatalog(IJobCatalog):
    """Catalogo em SQLite, com deduplicacao no momento da gravacao."""

    #: Acima disso, mesma empresa + titulo parecido = mesma vaga.
    DUPLICATE_TITLE_SIMILARITY = 0.88

    def __init__(self, database_path: Path) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- vagas -------------------------------------------------------------

    def upsert_job(self, job: CatalogJob) -> tuple[CatalogJob, bool]:
        """Grava a vaga. Devolve `(vaga, era_nova)`.

        Se ja existir uma equivalente, atualiza os campos volateis (score,
        descricao, salario) e PRESERVA o status e o `application_id` - o que
        voce ja decidiu sobre a vaga nao pode ser sobrescrito por uma recoleta.
        """
        existing = self.find_duplicate(job)
        if existing is not None:
            job.id = existing.id
            job.status = existing.status
            job.application_id = existing.application_id
            job.collected_at = existing.collected_at
            job.notes = existing.notes or job.notes
            job.updated_at = utc_now_iso()
            self._write(job)
            return job, False

        if not job.id:
            job.id = f"job-{uuid.uuid4().hex[:12]}"
        job.updated_at = utc_now_iso()
        self._write(job)
        self._touch_company(job.company)
        return job, True

    def _write(self, job: CatalogJob) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, title, company, normalized_company,
                    normalized_title, url, normalized_url, source, location,
                    work_model, match_score, status, published_at, collected_at,
                    updated_at, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    company=excluded.company,
                    normalized_company=excluded.normalized_company,
                    normalized_title=excluded.normalized_title,
                    url=excluded.url,
                    normalized_url=excluded.normalized_url,
                    source=excluded.source,
                    location=excluded.location,
                    work_model=excluded.work_model,
                    match_score=excluded.match_score,
                    status=excluded.status,
                    published_at=excluded.published_at,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    job.id, job.title, job.company, normalize_company(job.company),
                    normalize_title(job.title), job.url, normalize_url(job.url),
                    job.source, job.location, job.work_model.value, job.match_score,
                    job.status.value, job.published_at, job.collected_at,
                    job.updated_at, job.model_dump_json(),
                ),
            )

    def find_duplicate(self, job: CatalogJob) -> CatalogJob | None:
        """URL identica, ou mesma empresa com titulo praticamente igual."""
        normalized_url = normalize_url(job.url)
        company_key = normalize_company(job.company)
        title_key = normalize_title(job.title)

        with self._connect() as conn:
            if normalized_url:
                row = conn.execute(
                    "SELECT payload FROM jobs WHERE normalized_url = ? LIMIT 1",
                    (normalized_url,),
                ).fetchone()
                if row:
                    return CatalogJob.model_validate_json(row["payload"])

            if not company_key:
                return None

            rows = conn.execute(
                "SELECT payload, normalized_title FROM jobs WHERE normalized_company = ?",
                (company_key,),
            ).fetchall()

        for row in rows:
            if similarity(title_key, row["normalized_title"]) >= self.DUPLICATE_TITLE_SIMILARITY:
                return CatalogJob.model_validate_json(row["payload"])
        return None

    def find_job(self, job_id: str) -> CatalogJob | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return CatalogJob.model_validate_json(row["payload"]) if row else None

    def get_job(self, job_id: str) -> CatalogJob:
        job = self.find_job(job_id)
        if job is None:
            raise JobNotFoundError(
                f"Vaga '{job_id}' nao encontrada no catalogo. "
                f"Use `list_matching_jobs` para ver os IDs disponiveis."
            )
        return job

    def list_jobs(
        self,
        status: JobStatus | None = None,
        min_score: float | None = None,
        source: str | None = None,
        company: str | None = None,
        since: str | None = None,
        limit: int = 50,
        order_by_score: bool = True,
    ) -> list[CatalogJob]:
        query = "SELECT payload FROM jobs WHERE 1=1"
        params: list[object] = []

        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if min_score is not None:
            query += " AND match_score >= ?"
            params.append(min_score)
        if source:
            query += " AND source = ?"
            params.append(source)
        if company:
            query += " AND normalized_company = ?"
            params.append(normalize_company(company))
        if since:
            query += " AND collected_at >= ?"
            params.append(since)

        query += " ORDER BY match_score DESC, collected_at DESC" if order_by_score \
            else " ORDER BY collected_at DESC"
        query += " LIMIT ?"
        params.append(max(1, min(limit, 500)))

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [CatalogJob.model_validate_json(r["payload"]) for r in rows]

    def update_status(self, job_id: str, status: JobStatus) -> CatalogJob:
        job = self.get_job(job_id)
        job.status = status
        job.updated_at = utc_now_iso()
        self._write(job)
        logger.info("Vaga %s -> status %s", job_id, status.value)
        return job

    def count_by_status(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"])

    # -- empresas ----------------------------------------------------------

    def _touch_company(self, name: str) -> None:
        key = normalize_company(name)
        if not key:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO companies (id, name, normalized_name, first_seen_at, jobs_count)
                VALUES (?,?,?,?,1)
                ON CONFLICT(normalized_name) DO UPDATE SET
                    jobs_count = jobs_count + 1
                """,
                (f"co-{uuid.uuid4().hex[:10]}", name, key, utc_now_iso()),
            )

    def list_companies(self, search: str = "", limit: int = 100) -> list[Company]:
        query = "SELECT * FROM companies"
        params: list[object] = []
        if search:
            query += " WHERE normalized_name LIKE ?"
            params.append(f"%{normalize_company(search)}%")
        query += " ORDER BY jobs_count DESC, name ASC LIMIT ?"
        params.append(max(1, min(limit, 500)))

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Company(
                id=r["id"], name=r["name"], normalized_name=r["normalized_name"],
                website=r["website"], first_seen_at=r["first_seen_at"],
                jobs_count=r["jobs_count"],
            )
            for r in rows
        ]

    # -- tecnologias -------------------------------------------------------

    def record_technologies(self, job_id: str, links: list[JobTechnology]) -> None:
        if not links:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM job_technologies WHERE job_id = ?", (job_id,))
            conn.executemany(
                """
                INSERT OR REPLACE INTO job_technologies (job_id, technology, required, matched)
                VALUES (?,?,?,?)
                """,
                [(l.job_id, l.technology, int(l.required), int(l.matched)) for l in links],
            )
            conn.executemany(
                """
                INSERT INTO technologies (id, name, canonical, category)
                VALUES (?,?,?,?)
                ON CONFLICT(canonical) DO NOTHING
                """,
                [
                    (f"tech-{uuid.uuid4().hex[:8]}", l.technology, l.technology, "tech")
                    for l in links
                ],
            )

    def top_technologies(self, limit: int = 20) -> list[tuple[str, int, int]]:
        """`(tecnologia, vezes_exigida, vezes_que_a_candidata_tem)`."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT technology,
                       COUNT(*) AS required_count,
                       SUM(matched) AS matched_count
                  FROM job_technologies
                 WHERE required = 1
                 GROUP BY technology
                 ORDER BY required_count DESC
                 LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [(r["technology"], r["required_count"], r["matched_count"] or 0) for r in rows]

    # -- fontes ------------------------------------------------------------

    def record_source_run(
        self, name: str, collected: int, error: str = "", kind: str = "api"
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_sources (name, display_name, kind, last_run_at,
                                         jobs_collected, last_error)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                    last_run_at = excluded.last_run_at,
                    jobs_collected = job_sources.jobs_collected + excluded.jobs_collected,
                    last_error = excluded.last_error
                """,
                (name, name, kind, utc_now_iso(), collected, error),
            )

    def list_sources(self) -> list[JobSourceRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM job_sources ORDER BY name").fetchall()
        return [
            JobSourceRecord(
                name=r["name"], display_name=r["display_name"], kind=r["kind"],
                enabled=bool(r["enabled"]), last_run_at=r["last_run_at"],
                jobs_collected=r["jobs_collected"], last_error=r["last_error"],
            )
            for r in rows
        ]

    # -- execucoes ---------------------------------------------------------

    def start_execution(self, execution: SearchExecution) -> SearchExecution:
        if not execution.id:
            execution.id = f"run-{uuid.uuid4().hex[:10]}"
        self._write_execution(execution)
        return execution

    def finish_execution(self, execution: SearchExecution) -> SearchExecution:
        execution.finished_at = execution.finished_at or utc_now_iso()
        self._write_execution(execution)
        return execution

    def _write_execution(self, execution: SearchExecution) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO search_executions (id, started_at, finished_at, query,
                    location, sources, jobs_found, jobs_new, jobs_duplicated,
                    jobs_above_threshold, best_score, minimum_score, status, errors)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    finished_at=excluded.finished_at,
                    jobs_found=excluded.jobs_found,
                    jobs_new=excluded.jobs_new,
                    jobs_duplicated=excluded.jobs_duplicated,
                    jobs_above_threshold=excluded.jobs_above_threshold,
                    best_score=excluded.best_score,
                    status=excluded.status,
                    errors=excluded.errors
                """,
                (
                    execution.id, execution.started_at, execution.finished_at,
                    execution.query, execution.location, ",".join(execution.sources),
                    execution.jobs_found, execution.jobs_new, execution.jobs_duplicated,
                    execution.jobs_above_threshold, execution.best_score,
                    execution.minimum_score, execution.status,
                    " | ".join(execution.errors),
                ),
            )

    def list_executions(self, limit: int = 20) -> list[SearchExecution]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM search_executions ORDER BY started_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [
            SearchExecution(
                id=r["id"], started_at=r["started_at"], finished_at=r["finished_at"],
                query=r["query"], location=r["location"],
                sources=[s for s in (r["sources"] or "").split(",") if s],
                jobs_found=r["jobs_found"], jobs_new=r["jobs_new"],
                jobs_duplicated=r["jobs_duplicated"],
                jobs_above_threshold=r["jobs_above_threshold"],
                best_score=r["best_score"], minimum_score=r["minimum_score"],
                status=r["status"],
                errors=[e for e in (r["errors"] or "").split(" | ") if e],
            )
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Conversao
# ---------------------------------------------------------------------------


def to_catalog_job(job: Job, score: JobScore | None = None) -> CatalogJob:
    """Converte um `Job` normalizado (+ score) na entidade persistida."""
    catalog_job = CatalogJob(
        id="",
        title=job.title,
        company=job.company,
        description=job.description,
        location=job.location,
        work_model=job.work_mode,
        salary=job.salary_text,
        salary_min_brl=job.salary_min_brl,
        salary_max_brl=job.salary_max_brl,
        url=job.url,
        source=job.source,
        published_at=job.posted_at,
        seniority=job.seniority,
    )
    if score is not None:
        catalog_job.match_score = score.total
        catalog_job.recommendation = score.recommendation
        catalog_job.matched_technologies = score.matched_technologies
        catalog_job.gaps = score.gaps
        catalog_job.score_explanation = score.explanation
        catalog_job.status = (
            JobStatus.DISCARDED if score.eliminated else JobStatus.ANALYZED
        )
    return catalog_job


#: Gaps que sao observacoes do score, nao tecnologias. Nao viram Technology.
_NON_TECH_GAP_MARKERS = (
    "salarial", "salario", "senioridade", "localizacao", "modalidade",
    "empresa", "exige presenca", "restricao de regiao", "nao informad",
    "nao identificada", "nao divulgada",
)


def _is_technology(gap: str) -> bool:
    """Um gap so vira tecnologia se parecer uma: curto e sem cara de frase."""
    value = gap.strip().lower()
    if not value or len(value) > 40:
        return False
    if any(marker in value for marker in _NON_TECH_GAP_MARKERS):
        return False
    return len(value.split()) <= 4


def technology_links(job_id: str, score: JobScore) -> list[JobTechnology]:
    """Deriva as ligacoes vaga <-> tecnologia a partir do score.

    `matched=True`  -> a vaga exige e a candidata tem.
    `matched=False` -> a vaga exige e a candidata NAO tem (gap real).
    """
    links = [
        JobTechnology(job_id=job_id, technology=tech, required=True, matched=True)
        for tech in score.matched_technologies
        if _is_technology(tech)
    ]
    links.extend(
        JobTechnology(job_id=job_id, technology=gap, required=True, matched=False)
        for gap in score.gaps
        if _is_technology(gap)
    )

    seen: set[str] = set()
    unique: list[JobTechnology] = []
    for link in links:
        key = link.technology.lower()
        if key not in seen:
            seen.add(key)
            unique.append(link)
    return unique

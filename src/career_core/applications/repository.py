"""Persistencia de candidaturas.

DECISAO ARQUITETURAL (V1)
    Fonte de verdade: SQLite (`data/applications/applications.db`).
    Motivo: escrita transacional, sem risco de corromper o historico se o
    processo morrer no meio, e consultas de duplicidade baratas. Zero
    configuracao, zero servidor - ao contrario do PostgreSQL, que exigiria
    instalacao e credenciais para ganho nenhum na escala de uma pessoa.

    Espelho legivel: `data/applications/applications.json`, reescrito de forma
    atomica apos cada mutacao. O espelho e SOMENTE ESCRITA (derivado) - nunca e
    lido de volta. Isso da um arquivo versionavel no Git e inspecionavel a olho
    nu, sem criar duas fontes de verdade que podem divergir.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..errors import ApplicationNotFoundError
from ..models import Application, ApplicationStatus, StatusEvent, utc_now_iso
from ..security import ApprovalGate
from ..text import normalize_company, normalize_title, normalize_url

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    status          TEXT NOT NULL,
    company         TEXT NOT NULL,
    role            TEXT NOT NULL,
    job_url         TEXT NOT NULL DEFAULT '',
    normalized_url  TEXT NOT NULL DEFAULT '',
    normalized_company TEXT NOT NULL DEFAULT '',
    normalized_role TEXT NOT NULL DEFAULT '',
    score           REAL NOT NULL DEFAULT 0,
    payload         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_app_norm_url     ON applications(normalized_url);
CREATE INDEX IF NOT EXISTS idx_app_norm_company ON applications(normalized_company);
CREATE INDEX IF NOT EXISTS idx_app_status       ON applications(status);
"""


class IApplicationRepository(ABC):
    """Contrato de persistencia de candidaturas."""

    @abstractmethod
    def add(self, application: Application) -> Application: ...

    @abstractmethod
    def get(self, application_id: str) -> Application: ...

    @abstractmethod
    def find(self, application_id: str) -> Application | None: ...

    @abstractmethod
    def list(
        self,
        status: ApplicationStatus | None = None,
        company: str | None = None,
        min_score: float | None = None,
        limit: int = 100,
    ) -> list[Application]: ...

    @abstractmethod
    def update_status(
        self, application_id: str, status: ApplicationStatus, note: str = ""
    ) -> Application: ...

    @abstractmethod
    def find_by_normalized_url(self, url: str) -> list[Application]: ...

    @abstractmethod
    def find_by_company(self, company: str) -> list[Application]: ...

    @abstractmethod
    def all(self) -> list[Application]: ...


class SqliteApplicationRepository(IApplicationRepository):
    """Implementacao SQLite com espelho JSON derivado."""

    def __init__(
        self,
        database_path: Path,
        json_mirror_path: Path | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self._db_path = Path(database_path)
        self._mirror_path = Path(json_mirror_path) if json_mirror_path else None
        self._gate = approval_gate or ApprovalGate()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    # -- infraestrutura ----------------------------------------------------

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
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

    @staticmethod
    def _to_row(app: Application) -> tuple:
        return (
            app.id,
            app.created_at,
            app.updated_at,
            app.status.value,
            app.company,
            app.role,
            app.job_url,
            normalize_url(app.job_url),
            normalize_company(app.company),
            normalize_title(app.role),
            app.score,
            app.model_dump_json(),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Application:
        return Application.model_validate_json(row["payload"])

    # -- escrita -----------------------------------------------------------

    def add(self, application: Application) -> Application:
        if not application.history:
            application.history = [
                StatusEvent(status=application.status, note="Candidatura registrada.")
            ]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO applications
                    (id, created_at, updated_at, status, company, role, job_url,
                     normalized_url, normalized_company, normalized_role, score, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                self._to_row(application),
            )
        logger.info(
            "Candidatura registrada: %s | %s - %s (status=%s, score=%.1f)",
            application.id,
            application.company,
            application.role,
            application.status.value,
            application.score,
        )
        self._write_mirror()
        return application

    def update_status(
        self, application_id: str, status: ApplicationStatus, note: str = ""
    ) -> Application:
        application = self.get(application_id)

        # A validacao acontece ANTES de qualquer escrita: o gate e a garantia
        # de human-in-the-loop e nao pode ser contornado por este caminho.
        self._gate.validate(application.status, status)

        previous = application.status
        application.status = status
        application.updated_at = utc_now_iso()
        application.history.append(StatusEvent(status=status, note=note))

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE applications
                   SET status = ?, updated_at = ?, payload = ?
                 WHERE id = ?
                """,
                (status.value, application.updated_at, application.model_dump_json(), application.id),
            )
        logger.info(
            "Status alterado: %s | %s -> %s", application.id, previous.value, status.value
        )
        self._write_mirror()
        return application

    def save(self, application: Application) -> Application:
        """Persiste alteracoes de campos que nao sejam status."""
        application.updated_at = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE applications
                   SET updated_at = ?, score = ?, payload = ?
                 WHERE id = ?
                """,
                (application.updated_at, application.score, application.model_dump_json(), application.id),
            )
            if cursor.rowcount == 0:
                raise ApplicationNotFoundError(
                    f"Candidatura '{application.id}' nao encontrada."
                )
        self._write_mirror()
        return application

    # -- leitura -----------------------------------------------------------

    def find(self, application_id: str) -> Application | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def get(self, application_id: str) -> Application:
        application = self.find(application_id)
        if application is None:
            raise ApplicationNotFoundError(
                f"Candidatura '{application_id}' nao encontrada. "
                f"Use `list_applications` para ver os IDs disponiveis."
            )
        return application

    def list(
        self,
        status: ApplicationStatus | None = None,
        company: str | None = None,
        min_score: float | None = None,
        limit: int = 100,
    ) -> list[Application]:
        query = "SELECT payload FROM applications WHERE 1=1"
        params: list[object] = []

        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if company:
            query += " AND normalized_company = ?"
            params.append(normalize_company(company))
        if min_score is not None:
            query += " AND score >= ?"
            params.append(min_score)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]

    def all(self) -> list[Application]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM applications ORDER BY created_at DESC"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def find_by_normalized_url(self, url: str) -> list[Application]:
        normalized = normalize_url(url)
        if not normalized:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM applications WHERE normalized_url = ?",
                (normalized,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def find_by_company(self, company: str) -> list[Application]:
        normalized = normalize_company(company)
        if not normalized:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM applications WHERE normalized_company = ?",
                (normalized,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def count(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
            )

    # -- espelho JSON ------------------------------------------------------

    def _write_mirror(self) -> None:
        """Reescreve o espelho JSON de forma atomica.

        Falha aqui NUNCA derruba a operacao: o SQLite ja commitou e e a fonte
        de verdade. O espelho e conveniencia.
        """
        if self._mirror_path is None:
            return
        try:
            applications = self.all()
            document = {
                "_comment": (
                    "ARQUIVO GERADO AUTOMATICAMENTE. Fonte de verdade: "
                    "applications.db (SQLite). Editar este JSON nao altera nada; "
                    "ele e sobrescrito a cada mudanca."
                ),
                "generated_at": utc_now_iso(),
                "count": len(applications),
                "applications": [app.model_dump(mode="json") for app in applications],
            }
            self._mirror_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(self._mirror_path, document)
        except Exception:
            logger.exception("Falha ao escrever o espelho JSON (dados estao seguros no SQLite).")


def _atomic_write_json(path: Path, document: dict) -> None:
    """Escreve via arquivo temporario + rename, evitando JSON truncado."""
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".tmp-", suffix=".json"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(document, file, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    except Exception:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise

"""Configuracao por ambiente.

Toda configuracao vem de variaveis de ambiente (opcionalmente carregadas de um
`.env` na raiz do projeto). Nenhum segredo e escrito no codigo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:  # python-dotenv e opcional em runtime; o projeto funciona sem ele.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - caminho de fallback

    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False


PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_SOURCES = ("mock",)


def _default_ats_companies() -> tuple[str, ...]:
    # Import tardio: `config` e importado por todo mundo e nao deve puxar
    # o pacote de fontes junto.
    from .job_sources.ats_boards import DEFAULT_COMPANIES

    return DEFAULT_COMPANIES


def _load_env_file() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    items = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return items or default


@dataclass(frozen=True)
class Settings:
    """Configuracao imutavel da aplicacao."""

    data_root: Path
    log_dir: Path
    log_level: str
    min_score: int

    enable_network: bool
    sources: tuple[str, ...]
    http_timeout: float
    max_results: int
    min_interval: float
    user_agent: str
    #: Quadros de ATS a consultar, no formato `provedor:empresa`.
    ats_companies: tuple[str, ...]

    # Derivados -------------------------------------------------------
    profile_dir: Path = field(init=False)
    resumes_dir: Path = field(init=False)
    applications_dir: Path = field(init=False)
    database_path: Path = field(init=False)
    json_mirror_path: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_dir", self.data_root / "profile")
        object.__setattr__(self, "resumes_dir", self.data_root / "resumes")
        object.__setattr__(self, "applications_dir", self.data_root / "applications")
        object.__setattr__(
            self, "database_path", self.data_root / "applications" / "applications.db"
        )
        object.__setattr__(
            self,
            "json_mirror_path",
            self.data_root / "applications" / "applications.json",
        )

    def ensure_directories(self) -> None:
        """Cria a arvore de diretorios necessaria (idempotente)."""
        for directory in (
            self.data_root,
            self.profile_dir,
            self.resumes_dir,
            self.applications_dir,
            self.log_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def build_settings() -> Settings:
    """Le o ambiente e devolve um `Settings`. Sem cache - util em testes."""
    _load_env_file()

    data_root = Path(
        os.getenv("CAREER_DATA_ROOT") or (PROJECT_ROOT / "data")
    ).resolve()
    log_dir = Path(os.getenv("CAREER_LOG_DIR") or (PROJECT_ROOT / "logs")).resolve()

    return Settings(
        data_root=data_root,
        log_dir=log_dir,
        log_level=(os.getenv("CAREER_LOG_LEVEL") or "INFO").upper(),
        min_score=_get_int("CAREER_MIN_SCORE", 70),
        enable_network=_get_bool("JOB_SEARCH_ENABLE_NETWORK", False),
        sources=_get_csv("JOB_SEARCH_SOURCES", _DEFAULT_SOURCES),
        http_timeout=_get_float("JOB_SEARCH_TIMEOUT", 15.0),
        max_results=_get_int("JOB_SEARCH_MAX_RESULTS", 25),
        min_interval=_get_float("JOB_SEARCH_MIN_INTERVAL", 2.0),
        user_agent=os.getenv("JOB_SEARCH_USER_AGENT")
        or "career-agent/1.0 (personal job search)",
        ats_companies=_get_csv("JOB_SEARCH_ATS_COMPANIES", _default_ats_companies()),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings compartilhado do processo (carregado uma unica vez)."""
    return build_settings()


def reset_settings_cache() -> None:
    """Limpa o cache. Usado por testes que manipulam o ambiente."""
    get_settings.cache_clear()

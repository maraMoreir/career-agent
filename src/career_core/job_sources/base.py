"""Abstracao de fonte de vagas.

    IJobSource
        |- MockJobSource        (offline, deterministica - padrao da V1)
        |- RemotiveJobSource    (API publica documentada, sem auth)
        |- ArbeitnowJobSource   (API publica documentada, sem auth)
        `- UnavailableJobSource (LinkedIn / Indeed / Gupy - modo manual)

Adicionar uma fonte = criar uma classe aqui e registra-la no `registry`.
Nenhum outro modulo do sistema muda.
"""

from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import Job, Seniority, WorkMode
from ..text import normalize_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobQuery:
    """Criterios de busca, independentes de fonte."""

    keywords: str = ""
    location: str = ""
    work_modes: tuple[str, ...] = ()
    seniorities: tuple[str, ...] = ()
    limit: int = 25


@dataclass
class SourceResult:
    """Resultado de uma fonte, incluindo falha parcial."""

    source: str
    jobs: list[Job] = field(default_factory=list)
    ok: bool = True
    message: str = ""


class IJobSource(ABC):
    """Contrato de uma fonte de vagas."""

    name: str = ""
    #: Descricao honesta do que a fonte e e de como ela e acessada.
    provenance: str = ""
    #: `False` quando a fonte nao pode ser usada de forma legitima/automatica.
    usable: bool = True

    @abstractmethod
    def search(self, query: JobQuery) -> SourceResult:
        """Busca vagas e devolve `Job` ja normalizados."""

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "usable": self.usable,
            "provenance": self.provenance,
        }


class RateLimiter:
    """Espacamento minimo entre requisicoes. Evita ser um mau cidadao."""

    def __init__(self, min_interval_seconds: float) -> None:
        self._interval = max(0.0, min_interval_seconds)
        self._last_call = 0.0

    def wait(self) -> None:
        if self._interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last_call = time.monotonic()


# ---------------------------------------------------------------------------
# Normalizacao compartilhada
# ---------------------------------------------------------------------------

_SENIORITY_PATTERNS: tuple[tuple[Seniority, tuple[str, ...]], ...] = (
    (Seniority.INTERN, ("estagio", "estagiario", "estagiaria", "intern ", "internship")),
    (Seniority.TRAINEE, ("trainee",)),
    (Seniority.JUNIOR, ("junior", " jr", "jr.", "entry level", "entry-level", " i ")),
    (
        Seniority.LEAD,
        (
            "tech lead", "team lead", "lider tecnico", "staff engineer",
            "staff software", " staff ", "principal engineer", "principal software",
        ),
    ),
    (Seniority.SPECIALIST, ("especialista", "specialist", "expert")),
    (Seniority.SENIOR, ("senior", " sr", "sr.", "sênior", " iii")),
    (Seniority.MID, ("pleno", " pl ", "mid level", "mid-level", "middle", " ii")),
)

_WORK_MODE_PATTERNS: tuple[tuple[WorkMode, tuple[str, ...]], ...] = (
    (WorkMode.REMOTE, ("remoto", "remote", "home office", "anywhere", "100% remoto", "teletrabalho")),
    (WorkMode.HYBRID, ("hibrido", "hybrid", "semi presencial", "semipresencial")),
    (WorkMode.ONSITE, ("presencial", "on-site", "onsite", "no escritorio", "in office")),
)

_SALARY = re.compile(
    r"(?:r\$|brl)\s*([\d][\d.,]*)\s*(k|mil)?(?:\s*(?:a|ate|-|~)\s*(?:r\$|brl)?\s*([\d][\d.,]*)\s*(k|mil)?)?",
    re.IGNORECASE,
)


def detect_seniority(*texts: str) -> Seniority:
    """Detecta senioridade a partir de titulo/descricao. Titulo tem prioridade."""
    for text in texts:
        haystack = f" {normalize_text(text)} "
        for level, markers in _SENIORITY_PATTERNS:
            if any(marker in haystack for marker in markers):
                return level
    return Seniority.UNKNOWN


def detect_work_mode(*texts: str) -> WorkMode:
    for text in texts:
        haystack = f" {normalize_text(text)} "
        for mode, markers in _WORK_MODE_PATTERNS:
            if any(marker in haystack for marker in markers):
                return mode
    return WorkMode.UNKNOWN


def parse_salary_brl(text: str) -> tuple[float | None, float | None]:
    """Extrai (minimo, maximo) em BRL de texto livre. `(None, None)` se ausente."""
    if not text:
        return None, None
    match = _SALARY.search(normalize_text(text))
    if not match:
        return None, None

    def to_float(raw: str | None, unit: str | None) -> float | None:
        if not raw:
            return None
        value = raw
        if "," in value and "." in value:
            value = value.replace(".", "").replace(",", ".")
        elif "," in value:
            value = value.replace(",", ".")
        elif value.count(".") == 1 and len(value.split(".")[1]) == 3:
            value = value.replace(".", "")
        try:
            amount = float(value)
        except ValueError:
            return None
        if unit:
            amount *= 1000
        return amount

    low = to_float(match.group(1), match.group(2))
    high = to_float(match.group(3), match.group(4))
    if low and high and high < low:
        low, high = high, low
    return low, high


def strip_html(raw: str) -> str:
    """Converte HTML de descricao em texto legivel, preservando bullets."""
    if not raw:
        return ""
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", raw)
    text = re.sub(r"(?i)</\s*(p|div|li|h[1-6]|tr)\s*>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    replacements = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&aacute;": "a", "&ccedil;": "c",
    }
    for entity, char in replacements.items():
        text = text.replace(entity, char)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()

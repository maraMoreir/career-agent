"""Construcao de `Job` a partir de entrada manual.

Usado quando a usuaria cola uma vaga (LinkedIn, Gupy, Indeed, e-mail de
recrutador...). Campos explicitos sempre vencem a deteccao automatica.
"""

from __future__ import annotations

import re

from .errors import ValidationError
from .job_sources.base import detect_seniority, detect_work_mode, parse_salary_brl, strip_html
from .models import Job, Seniority, WorkMode
from .text import normalize_text

_TAG_VOCABULARY_HINT = re.compile(r"[A-Za-z][A-Za-z0-9#+.\- ]{1,28}")


def _coerce_enum(raw: str | None, enum_cls, default):
    if not raw:
        return None
    normalized = normalize_text(str(raw)).replace(" ", "_")
    aliases = {
        "remote": "remoto",
        "hybrid": "hibrido",
        "onsite": "presencial",
        "on_site": "presencial",
        "home_office": "remoto",
        "mid": "pleno",
        "middle": "pleno",
        "sr": "senior",
        "jr": "junior",
        "intern": "estagio",
        "especialist": "especialista",
        "specialist": "especialista",
    }
    normalized = aliases.get(normalized, normalized)
    for member in enum_cls:
        if normalize_text(member.value) == normalized:
            return member
    return None


def build_job_from_input(
    title: str,
    description: str = "",
    company: str = "",
    url: str = "",
    location: str = "",
    country: str = "",
    work_mode: str | None = None,
    seniority: str | None = None,
    salary_text: str = "",
    tech_tags: list[str] | None = None,
    source: str = "manual",
) -> Job:
    """Normaliza entrada livre num `Job`, detectando o que nao foi informado."""
    if not title or not title.strip():
        raise ValidationError(
            "O campo 'title' (cargo) e obrigatorio para analisar uma vaga."
        )

    clean_description = strip_html(description or "")

    resolved_mode = _coerce_enum(work_mode, WorkMode, WorkMode.UNKNOWN) or detect_work_mode(
        title, clean_description, location
    )
    resolved_seniority = _coerce_enum(seniority, Seniority, Seniority.UNKNOWN) or detect_seniority(
        title, clean_description
    )

    low, high = parse_salary_brl(salary_text or clean_description)

    resolved_country = country
    if not resolved_country and location:
        haystack = normalize_text(location)
        if any(marker in haystack for marker in ("brasil", "brazil", " br", "goiania", "sao paulo")):
            resolved_country = "Brasil"

    return Job(
        source=source,
        title=title.strip(),
        company=(company or "").strip(),
        url=(url or "").strip(),
        description=clean_description,
        tech_tags=[t.strip() for t in (tech_tags or []) if t and t.strip()],
        seniority=resolved_seniority,
        work_mode=resolved_mode,
        location=(location or "").strip(),
        country=resolved_country.strip(),
        salary_text=(salary_text or "").strip(),
        salary_min_brl=low,
        salary_max_brl=high,
    )

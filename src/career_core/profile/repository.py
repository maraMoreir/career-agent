"""Leitura do perfil da candidata a partir de arquivos Markdown.

Os arquivos Markdown sao a fonte de verdade: a usuaria edita
`data/profile/*.md` e o sistema inteiro reflete a mudanca. Nao ha banco de
perfil, nao ha duplicacao de estado.

Convencao de formato (simples de propositom e facil de editar a mao):

    ## Nome da secao
    - item
    - item

    ## Outra secao
    chave: valor
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from ..errors import ProfileNotFoundError
from ..models import CandidateProfile
from ..text import normalize_text

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
#: Aceita lista com marcador (`- item`) e lista numerada (`1. item`), porque a
#: ordem de preferencia de modalidade e escrita como lista numerada.
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_KEY_VALUE = re.compile(r"^\s*([A-Za-zÀ-ÿ_ /()]+?)\s*:\s*(.+?)\s*$")
#: Marcador de campo que a usuaria ainda nao preencheu - nunca vira dado.
_PLACEHOLDER = re.compile(r"\[PREENCHER", re.IGNORECASE)


def parse_markdown_sections(content: str) -> dict[str, dict[str, object]]:
    """Converte Markdown em `{secao_normalizada: {"items": [...], "fields": {...}, "text": str}}`."""
    sections: dict[str, dict[str, object]] = {}
    current_key = "_preamble"
    sections[current_key] = {"items": [], "fields": {}, "text": ""}
    text_buffer: dict[str, list[str]] = {current_key: []}

    for line in content.splitlines():
        heading = _HEADING.match(line)
        if heading:
            current_key = normalize_text(heading.group(2))
            sections.setdefault(current_key, {"items": [], "fields": {}, "text": ""})
            text_buffer.setdefault(current_key, [])
            continue

        bullet = _BULLET.match(line)
        if bullet:
            value = bullet.group(1).strip()
            # Um bullet pode carregar um par chave: valor.
            kv = _KEY_VALUE.match(value)
            if kv and not value.startswith("http"):
                key = normalize_text(kv.group(1))
                sections[current_key]["fields"][key] = kv.group(2).strip()  # type: ignore[index]
            value = re.sub(r"^\*\*(.+?)\*\*:?\s*", r"\1: ", value).strip()
            if value:
                sections[current_key]["items"].append(value)  # type: ignore[union-attr]
            text_buffer[current_key].append(value)
            continue

        stripped = line.strip()
        if stripped:
            kv = _KEY_VALUE.match(stripped)
            if kv and not stripped.startswith("http"):
                key = normalize_text(kv.group(1))
                sections[current_key]["fields"][key] = kv.group(2).strip()  # type: ignore[index]
            text_buffer[current_key].append(stripped)

    for key, lines in text_buffer.items():
        sections[key]["text"] = "\n".join(lines).strip()

    return sections


def _clean_items(items: list[str]) -> list[str]:
    """Limpa entradas de lista preservando a ordem e a grafia original.

    Cuidado deliberado: so remove pontuacao no FIM. Remover no inicio
    transformaria `.NET` em `NET`.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = re.sub(r"\s*\((?!.*\bcore\b).*?\)\s*$", "", item).strip()
        value = value.rstrip(" .;,").strip()
        if not value or _PLACEHOLDER.search(value):
            continue
        marker = normalize_text(value)
        if marker in seen:
            continue
        seen.add(marker)
        cleaned.append(value)
    return cleaned


def _matching_sections(
    sections: dict[str, dict[str, object]], *candidates: str
) -> list[dict[str, object]]:
    """Todas as secoes cujo titulo contem algum dos candidatos, em ordem."""
    found: list[dict[str, object]] = []
    for candidate in candidates:
        needle = normalize_text(candidate)
        if not needle:
            continue
        for key, value in sections.items():
            if needle in key and value not in found:
                found.append(value)
    return found


def _first_section(
    sections: dict[str, dict[str, object]], *candidates: str
) -> dict[str, object] | None:
    matches = _matching_sections(sections, *candidates)
    return matches[0] if matches else None


def _items(sections: dict[str, dict[str, object]], *candidates: str) -> list[str]:
    section = _first_section(sections, *candidates)
    if not section:
        return []
    return _clean_items(list(section.get("items", [])))  # type: ignore[arg-type]


def _field(
    sections: dict[str, dict[str, object]], section_names: tuple[str, ...], key: str
) -> str | None:
    """Procura `key` em TODAS as secoes que casam com `section_names`.

    Varrer todas importa: `# Perfil Profissional` casa com "perfil" mas nao
    guarda campo nenhum - os campos estao em `## Identificacao`.
    """
    needle = normalize_text(key)
    for section in _matching_sections(sections, *section_names):
        fields: dict[str, str] = section.get("fields", {})  # type: ignore[assignment]
        for field_key, value in fields.items():
            if needle in field_key:
                return None if _PLACEHOLDER.search(value) else value
    return None


def _parse_money(value: str | None) -> float | None:
    """Extrai um valor monetario BRL de texto livre. Devolve None se ausente."""
    if not value:
        return None
    text = normalize_text(value)
    if text in {"", "nao informado", "a combinar", "n/a", "-"}:
        return None
    match = re.search(r"(\d[\d.,]*)\s*(k|mil)?", text)
    if not match:
        return None
    number = match.group(1)
    # Formato BR: 12.000,00 -> 12000.00
    if "," in number and "." in number:
        number = number.replace(".", "").replace(",", ".")
    elif "," in number:
        number = number.replace(",", ".")
    elif number.count(".") == 1 and len(number.split(".")[1]) == 3:
        number = number.replace(".", "")
    try:
        amount = float(number)
    except ValueError:
        return None
    if match.group(2):  # "12k" / "12 mil"
        amount *= 1000
    return amount


class IProfileRepository(ABC):
    """Contrato de leitura de perfil. Permite trocar Markdown por outra fonte."""

    @abstractmethod
    def load(self) -> CandidateProfile:
        """Devolve o perfil completo da candidata."""

    @abstractmethod
    def raw_documents(self) -> dict[str, str]:
        """Devolve o conteudo bruto dos arquivos de perfil."""


class MarkdownProfileRepository(IProfileRepository):
    """Le `profile.md`, `skills.md` e `preferences.md` de um diretorio."""

    FILES = ("profile.md", "skills.md", "preferences.md")

    def __init__(self, profile_dir: Path) -> None:
        self._dir = Path(profile_dir)

    # -- API --------------------------------------------------------------

    def raw_documents(self) -> dict[str, str]:
        documents: dict[str, str] = {}
        for name in self.FILES:
            path = self._dir / name
            if path.is_file():
                documents[name] = path.read_text(encoding="utf-8", errors="replace")
        if not documents:
            raise ProfileNotFoundError(
                f"Nenhum arquivo de perfil encontrado em {self._dir}. "
                f"Esperados: {', '.join(self.FILES)}. Rode scripts/install.ps1."
            )
        return documents

    def load(self) -> CandidateProfile:
        documents = self.raw_documents()
        merged: dict[str, dict[str, object]] = {}
        for content in documents.values():
            for key, section in parse_markdown_sections(content).items():
                if key in merged:
                    merged[key]["items"] = list(merged[key]["items"]) + list(  # type: ignore[index]
                        section["items"]  # type: ignore[index]
                    )
                    merged[key]["fields"].update(section["fields"])  # type: ignore[union-attr]
                    merged[key]["text"] = (
                        f"{merged[key]['text']}\n{section['text']}".strip()
                    )
                else:
                    merged[key] = dict(section)

        return self._build(merged)

    # -- mapeamento -------------------------------------------------------

    def _build(self, sections: dict[str, dict[str, object]]) -> CandidateProfile:
        summary_section = _first_section(sections, "resumo profissional", "resumo")
        summary = str(summary_section.get("text", "")) if summary_section else ""

        skills = _items(sections, "tecnologias", "stack", "skills", "habilidades")
        architecture = _items(sections, "arquitetura", "architecture")
        domains = _items(sections, "dominio", "dominios", "experiencia de dominio")

        work_mode_priority = [
            normalize_text(re.sub(r"^\d+[\.\)]\s*", "", item))
            for item in _items(sections, "modalidade")
        ]

        min_salary = _parse_money(
            _field(sections, ("remuneracao", "salario", "preferencias"), "minimo")
        )
        target_salary = _parse_money(
            _field(sections, ("remuneracao", "salario", "preferencias"), "alvo")
        )
        years_raw = _field(
            sections, ("perfil", "resumo profissional", "experiencia"), "anos de experiencia"
        )
        years = None
        if years_raw and normalize_text(years_raw) not in {
            "nao informado",
            "nao declarado",
            "-",
        }:
            parsed = _parse_money(years_raw)
            years = parsed if parsed and parsed < 80 else None

        return CandidateProfile(
            full_name=_field(sections, ("perfil", "identificacao"), "nome") or "",
            headline=_field(sections, ("perfil", "identificacao"), "titulo") or "",
            summary=summary,
            skills=skills,
            architecture=architecture,
            domains=domains,
            target_roles=_items(sections, "cargos", "vagas prioritarias", "roles"),
            preferred_seniorities=[
                normalize_text(s) for s in _items(sections, "senioridade desejada", "senioridade")
            ],
            avoid_seniorities=[
                normalize_text(s) for s in _items(sections, "evitar")
            ],
            work_mode_priority=[m for m in work_mode_priority if m],
            countries=_items(sections, "pais", "paises"),
            preferred_cities=_items(sections, "cidade", "cidades"),
            min_salary_brl=min_salary,
            target_salary_brl=target_salary,
            years_experience=years,
            preferred_companies=_items(sections, "empresas preferidas"),
            blocked_companies=_items(sections, "empresas bloqueadas"),
            languages=_items(sections, "idioma", "idiomas"),
            education=_items(sections, "formacao", "educacao"),
        )

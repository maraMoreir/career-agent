"""Dimensoes especializadas no perfil da candidata.

A especificacao pede que o matching considere explicitamente experiencia com
.NET, com SAP, fiscal, arquitetura e backend. Sao dimensoes proprias, e nao
mais peso dentro de "stack", por um motivo pratico: uma vaga generica de
backend e uma vaga de backend .NET com integracao SAP fiscal nao podem
receber a mesma nota so porque ambas citam "C#".

Cada uma pontua a INTENSIDADE do tema na vaga cruzada com o que o perfil
declara - nunca inventa experiencia.
"""

from __future__ import annotations

import re

from ..models import CandidateProfile, DimensionScore, Job
from ..text import extract_terms, normalize_term, normalize_text
from .dimensions import IScoreDimension


class _TopicDimension(IScoreDimension):
    """Base: mede quanto a vaga fala de um tema e quanto o perfil cobre."""

    #: Termos que caracterizam o tema.
    vocabulary: frozenset[str] = frozenset()
    #: Termos cujo aparecimento no TITULO indica que o tema e central.
    title_markers: tuple[str, ...] = ()
    #: Texto quando a vaga nao toca no tema.
    absent_note: str = "a vaga nao menciona o tema"
    #: Fracao da nota quando o tema esta AUSENTE da vaga.
    #:
    #: Diferencia dois casos que nao podem ser tratados igual:
    #:   - tema NUCLEAR (.NET): ausencia e um problema real para este perfil,
    #:     entao a nota cai de verdade;
    #:   - tema DIFERENCIAL (SAP, fiscal): a maioria das boas vagas .NET nao
    #:     menciona, e penalizar seria injusto - nota neutra.
    absent_factor: float = 0.45

    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        known = profile.known_terms()
        text = job.searchable_text()

        mentioned = extract_terms(text, set(self.vocabulary))
        mentioned |= {
            normalize_term(tag) for tag in job.tech_tags
        } & set(self.vocabulary)
        mentioned.discard("")

        if not mentioned:
            note = (
                f"{self.absent_note} - fora do foco principal do perfil."
                if self.absent_factor <= 0.2
                else f"{self.absent_note}; sem impacto no ranking."
            )
            return self._result(self.max_points * self.absent_factor, note)

        covered = sorted(mentioned & known)
        missing = sorted(mentioned - known)
        coverage = len(covered) / len(mentioned)

        # Tema no titulo = central na vaga; amplifica o efeito, para cima e
        # para baixo.
        title = normalize_text(job.title)
        in_title = any(marker in title for marker in self.title_markers)

        if in_title:
            points = self.max_points * (0.15 + 0.85 * coverage)
            emphasis = "central na vaga (aparece no titulo)"
        else:
            points = self.max_points * (0.45 + 0.55 * coverage)
            emphasis = "citada nos requisitos"

        return self._result(
            points,
            f"{len(covered)}/{len(mentioned)} termos do tema no perfil; {emphasis}.",
            matched=covered,
            gaps=missing,
        )


class DotNetExperienceDimension(_TopicDimension):
    """Profundidade em .NET/C# - o nucleo do perfil."""

    key = "dotnet"
    label = "Experiencia .NET"
    max_points = 14.0
    # Nucleo do perfil: uma vaga sem .NET perde quase toda a nota aqui.
    absent_factor = 0.1
    absent_note = "a vaga nao cita .NET/C#"
    title_markers = (".net", "c#", "dotnet", "asp.net")
    vocabulary = frozenset(
        {
            ".net", "c#", "asp.net core", "entity framework core", "linq",
            "dapper", "blazor", "xunit", "nunit", "signalr",
        }
    )


class SapExperienceDimension(_TopicDimension):
    """Integracoes SAP - diferencial raro no mercado."""

    key = "sap"
    label = "Experiencia SAP"
    max_points = 5.0
    absent_note = "a vaga nao envolve SAP"
    title_markers = ("sap", "business one", "b1")
    vocabulary = frozenset(
        {
            "sap hana", "sap business one", "sap di api", "sap ui api",
            "sapbouicom", "integracoes com sap",
        }
    )


class FiscalExperienceDimension(_TopicDimension):
    """Dominio fiscal brasileiro - diferencial ainda mais raro."""

    key = "fiscal"
    label = "Experiencia fiscal"
    max_points = 4.0
    absent_note = "a vaga nao envolve dominio fiscal"
    title_markers = ("fiscal", "nf-e", "nfe", "tributar", "sefaz")
    vocabulary = frozenset(
        {
            "nf-e", "nfs-e", "ct-e", "mdf-e", "df-e", "gnre", "sefaz",
            "sistemas fiscais", "reforma tributaria",
        }
    )


class ArchitectureDimension(_TopicDimension):
    """Praticas de arquitetura exigidas pela vaga."""

    key = "architecture"
    label = "Arquitetura"
    max_points = 8.0
    absent_note = "a vaga nao detalha praticas de arquitetura"
    title_markers = ("arquitet", "architect")
    vocabulary = frozenset(
        {
            "clean architecture", "solid", "ddd", "design patterns",
            "hexagonal architecture", "microsserviços", "monolito",
            "sistemas distribuídos", "apis rest", "cqrs", "event sourcing",
        }
    )


class BackendFocusDimension(IScoreDimension):
    """Quanto a vaga e realmente de backend.

    Existe porque o perfil e Backend/FullStack com forte atuacao backend: uma
    vaga de frontend que cita C# nao serve, e uma vaga fullstack vale menos
    que uma de backend puro.
    """

    key = "backend"
    label = "Foco backend"
    max_points = 8.0

    _BACKEND = re.compile(
        r"back[\s-]?end|api|microservic|microsservic|servidor|server[\s-]?side|"
        r"banco de dados|database|mensageria|fila|worker|integrac",
        re.IGNORECASE,
    )
    _FRONTEND_ONLY = re.compile(
        r"front[\s-]?end|ui/ux|designer|mobile|ios|android|flutter", re.IGNORECASE
    )
    _FULLSTACK = re.compile(r"full[\s-]?stack", re.IGNORECASE)

    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        title = job.title or ""
        text = job.searchable_text()

        backend_hits = len(self._BACKEND.findall(text))
        frontend_in_title = bool(self._FRONTEND_ONLY.search(title))
        backend_in_title = bool(self._BACKEND.search(title))
        fullstack = bool(self._FULLSTACK.search(text))

        if frontend_in_title and not backend_in_title:
            return self._result(
                0.0,
                "Vaga de frontend/mobile pelo titulo - fora do foco backend do perfil.",
                gaps=["vaga nao e de backend"],
            )

        if backend_in_title:
            return self._result(
                self.max_points,
                "Backend explicito no titulo da vaga.",
            )

        if fullstack:
            return self._result(
                self.max_points * 0.75,
                "Vaga fullstack - o perfil atende, com backend como ponto forte.",
            )

        if backend_hits >= 3:
            return self._result(
                self.max_points * 0.8,
                f"Descricao com forte carga de backend ({backend_hits} sinais).",
            )
        if backend_hits >= 1:
            return self._result(
                self.max_points * 0.55,
                f"Backend presente, mas nao dominante ({backend_hits} sinal/sinais).",
            )

        return self._result(
            self.max_points * 0.3,
            "Nao da para confirmar foco backend pela descricao.",
            gaps=["foco backend nao confirmado"],
        )

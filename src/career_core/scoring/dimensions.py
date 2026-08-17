"""Dimensoes de score.

Cada dimensao e uma classe independente que sabe pontuar UM aspecto da vaga e
explicar sua nota. O `JobScorer` apenas soma. Isso mantem Single Responsibility
e permite adicionar/remover dimensoes sem tocar no somador (Open/Closed).

Pesos (total 100):
    Stack tecnica  30 | Senioridade 20 | Salario 15 | Modalidade 10
    Localizacao    10 | Experiencia 10 | Empresa      5
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from ..models import CandidateProfile, DimensionScore, Job, Seniority, WorkMode
from ..text import extract_terms, normalize_company, normalize_text, normalize_term


class IScoreDimension(ABC):
    """Contrato de uma dimensao de score."""

    key: str = ""
    label: str = ""
    max_points: float = 0.0

    @abstractmethod
    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        """Pontua a vaga nesta dimensao e explica o resultado."""

    def _result(
        self,
        points: float,
        rationale: str,
        matched: list[str] | None = None,
        gaps: list[str] | None = None,
    ) -> DimensionScore:
        clamped = max(0.0, min(self.max_points, round(points, 2)))
        return DimensionScore(
            key=self.key,
            label=self.label,
            points=clamped,
            max_points=self.max_points,
            rationale=rationale,
            matched=matched or [],
            gaps=gaps or [],
        )


# ---------------------------------------------------------------------------
# 1. Stack tecnica - 30 pontos
# ---------------------------------------------------------------------------

#: Tecnologias que definem o alvo da candidata. Peso extra quando presentes.
_CORE_STACK = {".net", "c#", "asp.net core", "entity framework core"}

#: Vocabulario de tecnologias reconhecidas em descricoes de vaga, alem do perfil.
_MARKET_VOCABULARY = {
    ".net", "c#", "asp.net core", "entity framework core", "dapper", "linq",
    "typescript", "javascript", "react", "angular", "vue", "node", "blazor",
    "postgresql", "sql server", "mysql", "oracle", "mongodb", "redis",
    "sap hana", "sap business one", "sap di api", "sap ui api",
    "rabbitmq", "kafka", "azure service bus",
    "docker", "kubernetes", "terraform", "gitlab ci/cd", "github actions",
    "jenkins", "azure", "aws", "gcp", "azure devops",
    "jwt", "oauth", "grpc", "graphql", "apis rest", "signalr",
    "clean architecture", "solid", "ddd", "design patterns",
    "hexagonal architecture", "microsserviços", "monolito",
    "sistemas distribuídos", "cqrs", "event sourcing",
    "xunit", "nunit", "tdd", "elasticsearch", "python", "java", "go",
    "nf-e", "nfs-e", "ct-e", "mdf-e", "df-e", "gnre", "sefaz",
}


class StackDimension(IScoreDimension):
    """Compara as tecnologias exigidas pela vaga com as declaradas no perfil."""

    key = "stack"
    label = "Stack tecnica"
    max_points = 30.0

    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        known = profile.known_terms()
        vocabulary = _MARKET_VOCABULARY | known

        required = extract_terms(job.searchable_text(), vocabulary)
        required |= {normalize_term(tag) for tag in job.tech_tags}
        required.discard("")

        if not required:
            return self._result(
                self.max_points * 0.5,
                "A vaga nao lista tecnologias reconheciveis; nota neutra. "
                "Cole a descricao completa para um score preciso.",
            )

        matched = sorted(required & known)
        gaps = sorted(required - known)

        coverage = len(matched) / len(required)

        # Presenca do core (.NET/C#) domina: sem ele a vaga nao e o alvo.
        core_required = required & _CORE_STACK
        core_matched = core_required & known
        core_ratio = (len(core_matched) / len(core_required)) if core_required else None

        if core_ratio is None:
            # Vaga tecnica sem .NET/C#: teto reduzido, e coerente com o alvo.
            points = self.max_points * coverage * 0.6
            rationale = (
                f"{len(matched)}/{len(required)} tecnologias batem com o perfil, "
                f"mas a vaga nao menciona .NET/C# - fora do foco principal."
            )
        else:
            # 70% da nota vem da cobertura geral, 30% da presenca do core.
            points = self.max_points * (0.7 * coverage + 0.3 * core_ratio)
            rationale = (
                f"{len(matched)}/{len(required)} tecnologias exigidas estao no "
                f"perfil ({coverage:.0%} de cobertura); core .NET/C# "
                f"{'presente' if core_ratio >= 1 else 'parcial'}."
            )

        return self._result(points, rationale, matched=matched, gaps=gaps)


# ---------------------------------------------------------------------------
# 2. Senioridade - 20 pontos
# ---------------------------------------------------------------------------


class SeniorityDimension(IScoreDimension):
    """Pontua o nivel da vaga contra o desejado; zera niveis a evitar."""

    key = "seniority"
    label = "Senioridade"
    max_points = 20.0

    #: Niveis proximos do alvo pleno/senior, mas nao exatos.
    _ADJACENT = {Seniority.SPECIALIST, Seniority.LEAD}

    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        level = job.seniority
        preferred = {normalize_text(s) for s in profile.preferred_seniorities}
        avoided = {normalize_text(s) for s in profile.avoid_seniorities}
        level_name = normalize_text(level.value)

        if level is Seniority.UNKNOWN:
            return self._result(
                self.max_points * 0.6,
                "Senioridade nao informada na vaga; nota neutra ate confirmar "
                "com o recrutador.",
            )

        if level_name in avoided:
            return self._result(
                0.0,
                f"Nivel '{level.value}' esta na lista de exclusao do perfil.",
                gaps=[f"senioridade {level.value} (evitar)"],
            )

        if level_name in preferred:
            return self._result(
                self.max_points, f"Nivel '{level.value}' e exatamente o alvo."
            )

        if level in self._ADJACENT:
            return self._result(
                self.max_points * 0.8,
                f"Nivel '{level.value}' esta acima de senior - alcancavel, mas "
                f"pode exigir mais tempo de casa/lideranca formal.",
            )

        return self._result(
            self.max_points * 0.3,
            f"Nivel '{level.value}' nao esta entre os desejados "
            f"({', '.join(sorted(preferred)) or 'nao definidos'}).",
        )


# ---------------------------------------------------------------------------
# 3. Salario - 15 pontos
# ---------------------------------------------------------------------------


class SalaryDimension(IScoreDimension):
    """Pontua a faixa salarial contra o minimo e o alvo do perfil."""

    key = "salary"
    label = "Salario"
    max_points = 15.0

    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        minimum = profile.min_salary_brl
        target = profile.target_salary_brl

        offered = job.salary_max_brl or job.salary_min_brl

        if offered is None:
            # Maioria das vagas BR nao publica salario. Penalizar seria injusto
            # e distorceria o ranking; damos nota neutra e sinalizamos.
            return self._result(
                self.max_points * 0.6,
                "Salario nao divulgado (comum no mercado BR); nota neutra. "
                "Confirme a faixa antes de avancar.",
                gaps=["faixa salarial nao divulgada"],
            )

        if minimum is None:
            return self._result(
                self.max_points * 0.6,
                f"Vaga informa {job.salary_text or offered}, mas o perfil nao "
                f"define salario minimo; nota neutra.",
            )

        if offered < minimum:
            ratio = offered / minimum
            return self._result(
                self.max_points * max(0.0, (ratio - 0.7) / 0.3) * 0.5,
                f"Oferta ({offered:,.0f}) abaixo do minimo do perfil "
                f"({minimum:,.0f}).".replace(",", "."),
                gaps=["salario abaixo do minimo"],
            )

        if target is None or offered >= target:
            return self._result(
                self.max_points,
                f"Oferta ({offered:,.0f}) atinge ou supera o alvo.".replace(",", "."),
            )

        # Entre o minimo e o alvo: interpolacao linear de 70% a 100%.
        span = target - minimum
        ratio = (offered - minimum) / span if span > 0 else 1.0
        return self._result(
            self.max_points * (0.7 + 0.3 * ratio),
            f"Oferta ({offered:,.0f}) acima do minimo, abaixo do alvo "
            f"({target:,.0f}).".replace(",", "."),
        )


# ---------------------------------------------------------------------------
# 4. Modalidade - 10 pontos
# ---------------------------------------------------------------------------


class WorkModeDimension(IScoreDimension):
    """Pontua a modalidade segundo a ordem de preferencia do perfil."""

    key = "work_mode"
    label = "Modalidade"
    max_points = 10.0

    _DEFAULT_ORDER = (WorkMode.REMOTE, WorkMode.HYBRID, WorkMode.ONSITE)

    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        order = self._order_from_profile(profile)

        if job.work_mode is WorkMode.UNKNOWN:
            return self._result(
                self.max_points * 0.5,
                "Modalidade nao informada; nota neutra.",
                gaps=["modalidade nao informada"],
            )

        try:
            rank = order.index(job.work_mode)
        except ValueError:
            return self._result(
                self.max_points * 0.5, f"Modalidade '{job.work_mode.value}' fora da lista."
            )

        # 1o lugar = 100%, 2o = 70%, 3o = 30%.
        factor = (1.0, 0.7, 0.3)[min(rank, 2)]
        return self._result(
            self.max_points * factor,
            f"'{job.work_mode.value}' e a {rank + 1}a opcao na sua ordem de "
            f"preferencia ({' > '.join(m.value for m in order)}).",
        )

    def _order_from_profile(self, profile: CandidateProfile) -> tuple[WorkMode, ...]:
        mapping = {
            "remoto": WorkMode.REMOTE,
            "remote": WorkMode.REMOTE,
            "hibrido": WorkMode.HYBRID,
            "hybrid": WorkMode.HYBRID,
            "presencial": WorkMode.ONSITE,
            "onsite": WorkMode.ONSITE,
        }
        ordered: list[WorkMode] = []
        for raw in profile.work_mode_priority:
            mode = mapping.get(normalize_text(raw))
            if mode and mode not in ordered:
                ordered.append(mode)
        for mode in self._DEFAULT_ORDER:
            if mode not in ordered:
                ordered.append(mode)
        return tuple(ordered)


# ---------------------------------------------------------------------------
# 5. Localizacao - 10 pontos
# ---------------------------------------------------------------------------


class LocationDimension(IScoreDimension):
    """Pontua a localizacao considerando que remoto neutraliza a distancia."""

    key = "location"
    label = "Localizacao"
    max_points = 10.0

    _BR_MARKERS = {"brasil", "brazil", "br", "latam", "america latina", "south america"}

    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        location_text = normalize_text(f"{job.location} {job.country}")
        cities = [normalize_text(c) for c in profile.preferred_cities if c]
        in_preferred_city = any(city and city in location_text for city in cities)
        looks_brazilian = any(marker in location_text for marker in self._BR_MARKERS)
        worldwide = any(
            word in location_text for word in ("worldwide", "anywhere", "global")
        )

        if job.work_mode is WorkMode.REMOTE:
            if not location_text or worldwide or looks_brazilian:
                return self._result(
                    self.max_points,
                    "Remoto sem restricao geografica incompativel - localizacao "
                    "deixa de ser um problema.",
                )
            return self._result(
                self.max_points * 0.5,
                f"Remoto, mas com restricao de regiao ('{job.location}'). "
                f"Confirme se aceita candidatas no Brasil.",
                gaps=[f"restricao de regiao: {job.location}"],
            )

        if not location_text:
            return self._result(
                self.max_points * 0.4, "Localizacao nao informada para vaga nao-remota.",
                gaps=["localizacao nao informada"],
            )

        if in_preferred_city:
            return self._result(
                self.max_points,
                f"Vaga em cidade preferida ('{job.location}').",
            )

        if looks_brazilian:
            factor = 0.4 if job.work_mode is WorkMode.HYBRID else 0.3
            return self._result(
                self.max_points * factor,
                f"No Brasil, mas fora das cidades preferidas ('{job.location}') "
                f"e sem ser remoto - exigiria mudanca ou deslocamento.",
                gaps=[f"exige presenca em {job.location}"],
            )

        return self._result(
            0.0,
            f"Fora do Brasil ('{job.location}') e sem modalidade remota.",
            gaps=[f"localizacao incompativel: {job.location}"],
        )


# ---------------------------------------------------------------------------
# 6. Experiencia - 10 pontos
# ---------------------------------------------------------------------------


class ExperienceDimension(IScoreDimension):
    """Compara exigencias de experiencia (anos e dominio) com o perfil.

    IMPORTANTE: se o perfil nao declara anos de experiencia, a checagem de anos
    e neutra. Nunca inferimos ou inventamos tempo de carreira.
    """

    key = "experience"
    label = "Experiencia"
    max_points = 10.0

    _YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:a|ate|-)?\s*\d{0,2}\s*anos?")
    _YEARS_EN = re.compile(r"(\d{1,2})\s*\+?\s*(?:to|-)?\s*\d{0,2}\s*years?")

    #: Sinais de dominio/arquitetura que a vaga pode exigir.
    _DOMAIN_VOCABULARY = {
        "clean architecture", "solid", "ddd", "design patterns",
        "hexagonal architecture", "apis rest", "sistemas distribuídos",
        "microsserviços", "monolito", "cqrs", "event sourcing",
        "sap business one", "sap hana", "sap di api", "sap ui api",
        "nf-e", "nfs-e", "ct-e", "mdf-e", "df-e", "gnre", "sefaz",
    }

    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        text = job.searchable_text()
        known = profile.known_terms()

        # Escopo desta dimensao: arquitetura e dominio de negocio. Linguagens e
        # ferramentas ja sao pontuadas em `StackDimension` - inclui-las aqui
        # contaria a mesma evidencia duas vezes.
        profile_experience = {
            normalize_term(item)
            for item in profile.architecture + profile.domains
        }
        profile_experience.discard("")
        vocabulary = self._DOMAIN_VOCABULARY | profile_experience

        required_domains = extract_terms(text, vocabulary) & vocabulary
        matched_domains = sorted(required_domains & known)
        missing_domains = sorted(required_domains - known)

        if required_domains:
            domain_ratio = len(matched_domains) / len(required_domains)
            domain_note = (
                f"{len(matched_domains)}/{len(required_domains)} areas de "
                f"experiencia exigidas presentes no perfil"
            )
        else:
            domain_ratio = 0.6
            domain_note = "vaga nao detalha areas de experiencia"

        required_years = self._required_years(normalize_text(text))

        if required_years is None:
            years_ratio = 0.6
            years_note = "sem exigencia explicita de anos"
        elif profile.years_experience is None:
            years_ratio = 0.6
            years_note = (
                f"vaga pede {required_years:g} anos, mas o perfil nao declara "
                f"tempo de experiencia (preencha em data/profile/profile.md)"
            )
        elif profile.years_experience >= required_years:
            years_ratio = 1.0
            years_note = f"perfil atende os {required_years:g} anos pedidos"
        else:
            years_ratio = max(0.0, profile.years_experience / required_years)
            years_note = (
                f"vaga pede {required_years:g} anos; perfil declara "
                f"{profile.years_experience:g}"
            )

        # Dominio pesa mais que contagem de anos.
        points = self.max_points * (0.65 * domain_ratio + 0.35 * years_ratio)

        return self._result(
            points,
            f"{domain_note}; {years_note}.",
            matched=matched_domains,
            gaps=missing_domains,
        )

    def _required_years(self, text: str) -> float | None:
        for pattern in (self._YEARS, self._YEARS_EN):
            match = pattern.search(text)
            if match:
                try:
                    value = float(match.group(1))
                except ValueError:
                    continue
                if 0 < value <= 30:
                    return value
        return None


# ---------------------------------------------------------------------------
# 7. Empresa - 5 pontos
# ---------------------------------------------------------------------------


class CompanyDimension(IScoreDimension):
    """Pontua a empresa: listas de preferencia/bloqueio e sinais na descricao."""

    key = "company"
    label = "Empresa"
    max_points = 5.0

    _POSITIVE_SIGNALS = (
        "plr", "participacao nos lucros", "plano de saude", "vale refeicao",
        "auxilio home office", "horario flexivel", "clt", "day off",
        "budget de estudos", "certificacao", "gympass", "totalpass",
    )
    _NEGATIVE_SIGNALS = (
        "banco de horas obrigatorio", "sobreaviso 24x7", "regime de plantao",
        "disponibilidade total", "viagens constantes",
    )

    def score(self, job: Job, profile: CandidateProfile) -> DimensionScore:
        company_key = normalize_company(job.company)

        if not company_key:
            return self._result(
                self.max_points * 0.4, "Empresa nao identificada na vaga.",
                gaps=["empresa nao identificada"],
            )

        blocked = {normalize_company(c) for c in profile.blocked_companies}
        if company_key in blocked:
            return self._result(
                0.0,
                f"'{job.company}' esta na sua lista de empresas bloqueadas.",
                gaps=["empresa bloqueada"],
            )

        preferred = {normalize_company(c) for c in profile.preferred_companies}
        if company_key in preferred:
            return self._result(
                self.max_points, f"'{job.company}' esta na sua lista de preferidas."
            )

        text = normalize_text(job.description)
        positives = [s for s in self._POSITIVE_SIGNALS if s in text]
        negatives = [s for s in self._NEGATIVE_SIGNALS if s in text]

        points = self.max_points * 0.6
        points += min(0.4 * self.max_points, 0.1 * self.max_points * len(positives))
        points -= 0.2 * self.max_points * len(negatives)

        details = []
        if positives:
            details.append(f"beneficios citados ({len(positives)})")
        if negatives:
            details.append(f"sinais de alerta ({', '.join(negatives)})")
        suffix = f": {'; '.join(details)}" if details else "; sem sinais fortes"

        return self._result(
            points,
            f"Empresa '{job.company}' sem historico nas suas listas{suffix}.",
            gaps=negatives,
        )


# ---------------------------------------------------------------------------


def default_dimensions(config=None) -> list[IScoreDimension]:
    """Conjunto padrao de dimensoes, com os pesos vindos da configuracao.

    `max_points` e atributo de classe; atribuir na instancia o sobrescreve
    apenas para aquele objeto. E o que permite reconfigurar o peso sem
    subclasse e sem estado global.
    """
    from .config import ScoringConfig
    from .specialized import (
        ArchitectureDimension,
        BackendFocusDimension,
        DotNetExperienceDimension,
        FiscalExperienceDimension,
        SapExperienceDimension,
    )

    resolved = config or ScoringConfig()

    dimensions: list[IScoreDimension] = [
        StackDimension(),
        DotNetExperienceDimension(),
        SeniorityDimension(),
        BackendFocusDimension(),
        ArchitectureDimension(),
        SalaryDimension(),
        LocationDimension(),
        WorkModeDimension(),
        SapExperienceDimension(),
        FiscalExperienceDimension(),
        CompanyDimension(),
    ]

    for dimension in dimensions:
        weight = resolved.weights.get(dimension.key)
        if weight is not None:
            dimension.max_points = float(weight)

    return dimensions

"""Personalizacao legitima de curriculo.

O QUE E PERMITIDO (e tudo o que este modulo faz):
    - reordenar informacoes ja existentes;
    - destacar tecnologias relevantes que JA estao no perfil;
    - adaptar o resumo profissional usando apenas fatos do perfil;
    - destacar experiencias relevantes que JA existem;
    - ajustar palavras-chave para o vocabulario da vaga, sem criar fatos.

O QUE E PROIBIDO (bloqueado por `FactGuard`):
    - afirmar experiencia em tecnologia ausente do perfil;
    - inventar cargo, empresa, certificacao, formacao ou tempo de casa;
    - copiar requisitos da vaga para dentro do curriculo como se fossem
      experiencia da candidata.

`FactGuard.audit` roda em TODO texto gerado. Se um termo tecnico exigido pela
vaga aparecer no texto sem estar no perfil, ele e reportado como violacao.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ResumeNotFoundError
from ..models import CandidateProfile, Job
from ..text import extract_terms, normalize_term, normalize_text

logger = logging.getLogger(__name__)

MASTER_RESUME_FILENAME = "curriculo-principal.md"


@dataclass
class FactGuardReport:
    """Resultado da auditoria factual de um texto gerado."""

    ok: bool
    violations: list[str] = field(default_factory=list)
    checked_terms: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        if self.ok:
            return "Auditoria factual: OK - nenhuma tecnologia fora do perfil foi afirmada."
        return "Auditoria factual: FALHOU\n" + "\n".join(
            f"  - {violation}" for violation in self.violations
        )


class FactGuard:
    """Verifica que um texto nao afirma experiencia inexistente."""

    #: Verbos/expressoes que transformam mencao em AFIRMACAO de experiencia.
    _CLAIM_PATTERNS = (
        r"experiencia (?:solida |comprovada |profissional )?(?:em|com)",
        r"atuacao (?:solida )?(?:em|com)",
        r"trabalh(?:ei|o|ou) com",
        r"desenvolv(?:i|o|eu) (?:em|com|usando)",
        r"dominio (?:de|em)",
        r"proficien(?:te|cia) (?:em|com)",
        r"conhecimento (?:solido |avancado )?(?:em|de)",
        r"utiliz(?:ei|o) ",
        r"implement(?:ei|o) ",
        r"anos de experiencia",
        r"certifica(?:da|do|cao)",
    )

    def __init__(self, profile: CandidateProfile) -> None:
        self._profile = profile
        self._known = profile.known_terms()

    def audit(self, text: str, job: Job | None = None) -> FactGuardReport:
        """Audita `text` procurando afirmacoes sobre tecnologias fora do perfil."""
        if not text.strip():
            return FactGuardReport(ok=True)

        normalized = normalize_text(text)
        violations: list[str] = []

        # Vocabulario de risco: o que a vaga exige e o perfil nao tem.
        risky: set[str] = set()
        if job is not None:
            from ..scoring.dimensions import _MARKET_VOCABULARY

            job_terms = extract_terms(job.searchable_text(), _MARKET_VOCABULARY)
            job_terms |= {normalize_term(t) for t in job.tech_tags}
            risky = {t for t in job_terms if t and t not in self._known}

        for term in sorted(risky):
            if not self._mentions(normalized, term):
                continue

            # A checagem de gap vem PRIMEIRO. "Nao possuo experiencia com X"
            # contem o padrao de afirmacao "experiencia com", mas nega. Sem
            # esta ordem, ser honesta sobre um gap seria reprovado.
            if self._is_flagged_as_gap(normalized, term):
                continue

            if self._is_claim(normalized, term):
                violations.append(
                    f"O texto afirma experiencia em '{term}', que NAO consta no "
                    f"perfil. Trate como gap, nunca como experiencia."
                )
            else:
                violations.append(
                    f"'{term}' aparece no texto sem estar no perfil e sem ser "
                    f"marcado como gap/interesse. Reescreva ou remova."
                )

        return FactGuardReport(
            ok=not violations,
            violations=violations,
            checked_terms=sorted(risky),
        )

    # -- heuristicas -------------------------------------------------------

    @staticmethod
    def _mentions(normalized_text: str, term: str) -> bool:
        pattern = r"(?<![a-z0-9])" + re.escape(normalize_text(term)) + r"(?![a-z0-9])"
        return bool(re.search(pattern, normalized_text))

    def _is_claim(self, normalized_text: str, term: str) -> bool:
        escaped = re.escape(normalize_text(term))
        for claim in self._CLAIM_PATTERNS:
            # afirmacao ANTES do termo, dentro de uma janela curta
            if re.search(claim + r"[^.\n]{0,80}?" + escaped, normalized_text):
                return True
            # termo ANTES da afirmacao (ex.: "azure: 5 anos de experiencia")
            if re.search(escaped + r"[^.\n]{0,40}?" + claim, normalized_text):
                return True
        return False

    @staticmethod
    def _is_flagged_as_gap(normalized_text: str, term: str) -> bool:
        """O termo aparece explicitamente rotulado como gap/ausencia?

        A janela e curta e nao atravessa o fim da frase, para que um "nao tenho
        experiencia com X" numa frase nao acabe cobrindo um "tenho experiencia
        com Y" na frase seguinte.
        """
        escaped = re.escape(normalize_text(term))
        markers = (
            r"gaps?\b", r"nao (?:tenho|possuo|consta|ha)", r"sem experiencia",
            r"a estudar", r"interesse em", r"disposicao para aprender",
            r"aprender", r"ausente do perfil", r"nao declarad",
            r"nao afirm", r"nao incluir", r"nao consta",
        )
        window = r"[^.\n;]{0,80}"
        return any(
            re.search(marker + window + escaped, normalized_text)
            or re.search(escaped + window + marker, normalized_text)
            for marker in markers
        )


@dataclass
class TailoredResume:
    """Resultado da personalizacao. Tudo rastreavel ate o perfil."""

    source_resume: str
    highlighted_skills: list[str]
    reordered_skills: list[str]
    tailored_summary: str
    keywords_adopted: list[str]
    gaps_not_claimed: list[str]
    guard: FactGuardReport
    markdown: str


class ResumeTailor:
    """Reorganiza e destaca - nunca cria fatos novos."""

    def __init__(self, resumes_dir: Path, profile: CandidateProfile) -> None:
        self._dir = Path(resumes_dir)
        self._profile = profile
        self._guard = FactGuard(profile)

    # -- curriculos --------------------------------------------------------

    def list_resumes(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        return sorted(
            path.name for path in self._dir.glob("*.md") if path.is_file()
        )

    def read_resume(self, filename: str | None = None) -> tuple[str, str]:
        """Devolve `(nome_do_arquivo, conteudo)`. Sem argumento, usa o principal."""
        name = filename or MASTER_RESUME_FILENAME
        if not name.lower().endswith(".md"):
            name = f"{name}.md"

        path = self._dir / Path(name).name  # descarta qualquer componente de caminho
        if not path.is_file():
            available = ", ".join(self.list_resumes()) or "(nenhum)"
            raise ResumeNotFoundError(
                f"Curriculo '{name}' nao encontrado em {self._dir}. "
                f"Disponiveis: {available}."
            )
        return path.name, path.read_text(encoding="utf-8", errors="replace")

    def recommend_resume(self, job: Job) -> str:
        """Escolhe o curriculo mais adequado entre os disponiveis.

        Heuristica simples e transparente: pontua o nome do arquivo pelos
        termos da vaga. Sem variantes, devolve o principal.
        """
        available = self.list_resumes()
        if not available:
            return MASTER_RESUME_FILENAME

        job_text = normalize_text(job.searchable_text())
        best, best_score = MASTER_RESUME_FILENAME, -1

        for name in available:
            tokens = [t for t in re.split(r"[-_.\s]+", normalize_text(name)) if len(t) > 2]
            score = sum(1 for token in tokens if token in job_text)
            if name == MASTER_RESUME_FILENAME:
                score += 0.5  # desempate a favor do principal
            if score > best_score:
                best, best_score = name, score

        return best

    # -- personalizacao ----------------------------------------------------

    def tailor(self, job: Job, resume_filename: str | None = None) -> TailoredResume:
        name, content = self.read_resume(
            resume_filename or self.recommend_resume(job)
        )

        known = self._profile.known_terms()
        from ..scoring.dimensions import _MARKET_VOCABULARY

        job_terms = extract_terms(job.searchable_text(), _MARKET_VOCABULARY | known)
        job_terms |= {normalize_term(t) for t in job.tech_tags}
        job_terms.discard("")

        highlighted = self._match_profile_labels(job_terms & known)
        gaps = sorted(job_terms - known)

        reordered = self._reorder_skills(highlighted)
        summary = self._build_summary(job, highlighted, gaps)
        keywords = self._adopt_keywords(job_terms & known)

        markdown = self._render(
            name, content, job, summary, reordered, highlighted, gaps
        )

        guard = self._guard.audit(f"{summary}\n{markdown}", job)
        if not guard.ok:
            logger.warning(
                "FactGuard reprovou o curriculo personalizado para '%s': %s",
                job.title,
                guard.violations,
            )

        return TailoredResume(
            source_resume=name,
            highlighted_skills=highlighted,
            reordered_skills=reordered,
            tailored_summary=summary,
            keywords_adopted=keywords,
            gaps_not_claimed=gaps,
            guard=guard,
            markdown=markdown,
        )

    # -- internos ----------------------------------------------------------

    def _match_profile_labels(self, canonical_terms: set[str]) -> list[str]:
        """Converte termos canonicos de volta para o rotulo exato do perfil."""
        labels: list[str] = []
        for item in self._profile.skills + self._profile.architecture + self._profile.domains:
            if normalize_term(item) in canonical_terms:
                labels.append(item)
        return labels

    def _reorder_skills(self, highlighted: list[str]) -> list[str]:
        """Coloca as skills relevantes primeiro, preservando o restante."""
        highlighted_set = {normalize_term(s) for s in highlighted}
        rest = [
            item
            for item in self._profile.skills + self._profile.architecture
            if normalize_term(item) not in highlighted_set
        ]
        return highlighted + rest

    def _build_summary(
        self, job: Job, highlighted: list[str], gaps: list[str]
    ) -> str:
        """Resumo profissional montado SO com fatos do perfil."""
        headline = self._profile.headline or "Desenvolvedora Backend/FullStack"
        focus = ", ".join(highlighted[:6]) if highlighted else ", ".join(
            self._profile.skills[:6]
        )
        architecture = ", ".join(self._profile.architecture[:4])

        parts = [f"{headline}."]
        if focus:
            parts.append(
                f"Atuacao com {focus} - tecnologias que constam no perfil e que "
                f"a vaga de {job.title} solicita."
            )
        if architecture:
            parts.append(f"Trabalha com {architecture}.")
        if self._profile.domains:
            parts.append(
                f"Experiencia de dominio em {', '.join(self._profile.domains[:4])}."
            )
        if gaps:
            parts.append(
                f"(Nota interna, NAO incluir no curriculo enviado: a vaga cita "
                f"{', '.join(gaps[:5])}, que nao consta no perfil. Nao afirme "
                f"experiencia nesses itens.)"
            )
        return " ".join(parts)

    def _adopt_keywords(self, matched: set[str]) -> list[str]:
        """Palavras-chave da vaga que podem ser usadas por ja existirem no perfil."""
        return sorted(matched)

    def _render(
        self,
        source_name: str,
        content: str,
        job: Job,
        summary: str,
        reordered: list[str],
        highlighted: list[str],
        gaps: list[str],
    ) -> str:
        header = [
            f"<!-- Curriculo personalizado a partir de: {source_name} -->",
            f"<!-- Vaga: {job.title} @ {job.company or 'n/d'} -->",
            "<!-- Somente reordenacao/destaque. Nenhum fato foi criado. -->",
            "",
            f"## Resumo profissional (adaptado para {job.title})",
            "",
            summary.split("(Nota interna")[0].strip(),
            "",
            "## Tecnologias em destaque para esta vaga",
            "",
        ]
        header.extend(f"- {skill}" for skill in (highlighted or reordered[:10]))
        header.extend(["", "## Demais tecnologias do perfil", ""])
        highlighted_set = {normalize_term(s) for s in highlighted}
        header.extend(
            f"- {skill}"
            for skill in reordered
            if normalize_term(skill) not in highlighted_set
        )

        if gaps:
            header.extend(
                [
                    "",
                    "<!-- GAPS (uso interno, nao enviar): "
                    + ", ".join(gaps)
                    + " - NAO afirmar experiencia nesses itens. -->",
                ]
            )

        header.extend(["", "---", "", "## Curriculo base (inalterado)", "", content])
        return "\n".join(header)

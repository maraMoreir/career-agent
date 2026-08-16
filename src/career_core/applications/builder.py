"""Montagem do pacote de candidatura.

Reune vaga + perfil + score + curriculo personalizado e produz tudo o que a
usuaria precisa revisar antes de agir: requisitos, gaps, resumo adaptado,
mensagem para o recrutador e respostas sugeridas.

Nada aqui envia nada. O resultado nasce em `pending_approval`.
"""

from __future__ import annotations

import logging
import re
import uuid

from ..models import (
    Application,
    ApplicationStatus,
    CandidateProfile,
    Job,
    JobScore,
    SuggestedAnswer,
)
from ..resume.tailor import ResumeTailor, TailoredResume
from ..text import normalize_text

logger = logging.getLogger(__name__)

_REQUIREMENT_BULLET = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+(.{8,180})$", re.MULTILINE)
_REQUIREMENT_SECTION = re.compile(
    r"(requisitos|qualificac|o que esperamos|voce (?:precisa|tera)|"
    r"requirements|what you.ll need|desejavel|diferenciais)",
    re.IGNORECASE,
)


class ApplicationBuilder:
    """Constroi um `Application` completo em estado `pending_approval`."""

    def __init__(self, profile: CandidateProfile, tailor: ResumeTailor) -> None:
        self._profile = profile
        self._tailor = tailor

    def build(
        self,
        job: Job,
        score: JobScore,
        resume_filename: str | None = None,
        extra_questions: list[str] | None = None,
    ) -> tuple[Application, TailoredResume]:
        tailored = self._tailor.tailor(job, resume_filename)

        application = Application(
            id=self._new_id(),
            status=ApplicationStatus.PENDING_APPROVAL,
            company=job.company or "(empresa nao informada)",
            role=job.title,
            job_url=job.url,
            job_source=job.source,
            score=score.total,
            recommendation=score.recommendation,
            score_breakdown=score.dimensions,
            salary_text=job.salary_text or "nao divulgado",
            work_mode=job.work_mode,
            location=job.location,
            key_requirements=self._extract_requirements(job),
            matched_technologies=score.matched_technologies,
            gaps=score.gaps,
            recommended_resume=tailored.source_resume,
            tailored_summary=tailored.tailored_summary,
            recruiter_message=self._recruiter_message(job, tailored),
            suggested_answers=self._suggested_answers(job, tailored, extra_questions),
            notes=self._notes(score, tailored),
        )

        logger.info(
            "Candidatura preparada: %s - %s (score %.1f, curriculo %s)",
            application.company,
            application.role,
            application.score,
            tailored.source_resume,
        )
        return application, tailored

    # -- partes ------------------------------------------------------------

    @staticmethod
    def _new_id() -> str:
        return f"app-{uuid.uuid4().hex[:10]}"

    @staticmethod
    def _extract_requirements(job: Job, limit: int = 12) -> list[str]:
        """Extrai os bullets de requisito da descricao, sem interpretar."""
        description = job.description or ""
        if not description.strip():
            return []

        bullets = [b.strip() for b in _REQUIREMENT_BULLET.findall(description)]

        # Prioriza bullets que aparecem depois de um cabecalho de requisitos.
        match = _REQUIREMENT_SECTION.search(description)
        if match:
            tail = description[match.start():]
            focused = [b.strip() for b in _REQUIREMENT_BULLET.findall(tail)]
            if focused:
                bullets = focused + [b for b in bullets if b not in focused]

        seen: set[str] = set()
        unique: list[str] = []
        for bullet in bullets:
            marker = normalize_text(bullet)[:60]
            if marker and marker not in seen:
                seen.add(marker)
                unique.append(re.sub(r"\s+", " ", bullet))
            if len(unique) >= limit:
                break
        return unique

    def _recruiter_message(self, job: Job, tailored: TailoredResume) -> str:
        """Rascunho de mensagem. Somente fatos do perfil."""
        name = self._profile.full_name or "[seu nome]"
        company = job.company or "a empresa"
        skills = ", ".join(tailored.highlighted_skills[:5]) or ", ".join(
            self._profile.skills[:5]
        )
        architecture = ", ".join(self._profile.architecture[:3])

        lines = [
            f"Ola! Tudo bem?",
            "",
            f"Vi a vaga de {job.title} na {company} e o perfil conversa "
            f"diretamente com o que eu faco.",
            "",
        ]
        if skills:
            lines.append(f"Trabalho com {skills}.")
        if architecture:
            lines.append(f"No dia a dia aplico {architecture}.")
        if self._profile.domains:
            lines.append(
                f"Tambem tenho experiencia em {', '.join(self._profile.domains[:3])}."
            )
        lines.extend(
            [
                "",
                "Fico a disposicao para conversar sobre a oportunidade e mandar "
                "meu curriculo completo.",
                "",
                f"Obrigada!",
                name,
                "",
                "---",
                "RASCUNHO - revise, ajuste o tom e envie voce mesma. "
                "O Career Agent nao envia mensagens.",
            ]
        )
        return "\n".join(lines)

    def _suggested_answers(
        self,
        job: Job,
        tailored: TailoredResume,
        extra_questions: list[str] | None,
    ) -> list[SuggestedAnswer]:
        """Rascunhos ancorados no perfil, com a fonte de cada afirmacao."""
        answers: list[SuggestedAnswer] = []
        skills = ", ".join(tailored.highlighted_skills[:5]) or "minha stack principal"

        answers.append(
            SuggestedAnswer(
                question="Por que voce se interessou por esta vaga?",
                answer=(
                    f"A vaga de {job.title} pede {skills}, que e exatamente o que "
                    f"eu trabalho hoje. "
                    + (
                        f"Alem disso, aplico {', '.join(self._profile.architecture[:3])}, "
                        f"que aparece nos requisitos."
                        if self._profile.architecture
                        else ""
                    )
                ).strip(),
                grounded_in=tailored.highlighted_skills[:5] or self._profile.skills[:5],
            )
        )

        answers.append(
            SuggestedAnswer(
                question="Fale sobre sua experiencia tecnica.",
                answer=(
                    self._profile.summary.strip()
                    or f"Atuo como {self._profile.headline}. Stack: "
                    f"{', '.join(self._profile.skills[:8])}."
                ),
                grounded_in=["data/profile/profile.md"],
            )
        )

        if self._profile.domains:
            answers.append(
                SuggestedAnswer(
                    question="Qual foi um desafio tecnico relevante que voce enfrentou?",
                    answer=(
                        f"Trabalho com {', '.join(self._profile.domains[:3])} - "
                        f"dominio com regras complexas e integracao entre sistemas. "
                        f"PREENCHA AQUI com um caso concreto seu: contexto, o que "
                        f"voce fez e qual foi o resultado. O agente nao inventa "
                        f"exemplos por voce."
                    ),
                    grounded_in=self._profile.domains[:3],
                )
            )

        if tailored.gaps_not_claimed:
            gaps = ", ".join(tailored.gaps_not_claimed[:5])
            answers.append(
                SuggestedAnswer(
                    question=f"Voce tem experiencia com {gaps}?",
                    answer=(
                        f"Nao consta no meu perfil experiencia profissional com "
                        f"{gaps}. Prefiro ser transparente: sao gaps em relacao a "
                        f"esta vaga. Tenho interesse e disposicao para aprender, e "
                        f"minha base em {', '.join(self._profile.skills[:3])} "
                        f"facilita a curva. "
                        f"(Ajuste se voce ja teve contato - mas so afirme o que for "
                        f"verdade.)"
                    ),
                    grounded_in=["gap declarado - nao e afirmacao de experiencia"],
                )
            )

        answers.append(
            SuggestedAnswer(
                question="Qual sua pretensao salarial?",
                answer=(
                    f"Minha pretensao e a partir de R$ "
                    f"{self._profile.min_salary_brl:,.0f}, aberta a conversar "
                    f"conforme o pacote completo.".replace(",", ".")
                    if self._profile.min_salary_brl
                    else "PREENCHA: defina sua faixa em data/profile/preferences.md "
                    "para o agente sugerir esta resposta."
                ),
                grounded_in=["data/profile/preferences.md"],
            )
        )

        for question in extra_questions or []:
            answers.append(
                SuggestedAnswer(
                    question=question,
                    answer=(
                        "PREENCHA: esta pergunta e especifica da vaga. Responda "
                        "usando apenas fatos do seu perfil - o agente nao cria "
                        "experiencia que voce nao tem."
                    ),
                    grounded_in=[],
                )
            )

        return answers

    @staticmethod
    def _notes(score: JobScore, tailored: TailoredResume) -> str:
        notes = [
            f"Recomendacao do score: {score.recommendation.value} "
            f"({score.total:g}/100).",
            tailored.guard.as_text(),
        ]
        if score.eliminated:
            notes.append("ELIMINADA automaticamente: " + "; ".join(score.elimination_reasons))
        if tailored.gaps_not_claimed:
            notes.append(
                "Gaps NAO afirmados no material gerado: "
                + ", ".join(tailored.gaps_not_claimed)
            )
        return "\n".join(notes)

"""Politica de seguranca do Career Agent.

Este modulo e o ponto unico onde as garantias de seguranca sao declaradas e
verificadas. Ele existe por dois motivos:

1. Documentar, em codigo executavel, o que o sistema deliberadamente NAO faz.
2. Garantir, via maquina de estados, que nenhuma candidatura avance para um
   estado de "acao externa" sem aprovacao humana explicita.

Nada aqui automatiza login, cliques, envio de candidatura ou mensagens.
O sistema PREPARA material; a acao externa final e sempre humana.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ForbiddenActionError, InvalidStatusTransitionError
from .models import ApplicationStatus

# ---------------------------------------------------------------------------
# Capacidades deliberadamente NAO implementadas
# ---------------------------------------------------------------------------

FORBIDDEN_CAPABILITIES: tuple[str, ...] = (
    "linkedin_login",
    "linkedin_password_storage",
    "linkedin_cookie_storage",
    "session_capture",
    "linkedin_click_automation",
    "auto_submit_application",
    "auto_send_message",
    "anti_bot_evasion",
    "aggressive_scraping",
    "captcha_solving",
    "credential_storage",
)

SAFETY_POLICY = """\
POLITICA DE SEGURANCA - Career Agent v1

O QUE ESTE SISTEMA FAZ
  - Busca vagas apenas em APIs publicas e documentadas, sem autenticacao.
  - Analisa vagas e calcula um score explicavel.
  - Detecta candidaturas duplicadas.
  - Personaliza o curriculo de forma legitima (reordenar / destacar / adaptar
    resumo e palavras-chave), sem inventar fatos.
  - Gera mensagens e respostas como RASCUNHO, para revisao humana.
  - Registra e acompanha o historico de candidaturas.

O QUE ESTE SISTEMA NAO FAZ (por design, nao por falta de tempo)
  - Nao faz login automatico no LinkedIn nem em qualquer portal.
  - Nao armazena senha, cookie ou token de sessao de nenhum portal.
  - Nao captura sessao de navegador.
  - Nao automatiza cliques em portais de vagas.
  - Nao envia candidatura automaticamente.
  - Nao envia mensagem automaticamente.
  - Nao tenta burlar mecanismos anti-bot nem resolve CAPTCHA.
  - Nao faz scraping agressivo. Fontes sem API publica ficam em modo manual.

APROVACAO HUMANA
  Toda candidatura nasce em `pending_approval`. A transicao para `applied`
  exige passar antes por `approved`, que so acontece por acao explicita da
  usuaria. O sistema nao aprova nada sozinho.

HONESTIDADE FACTUAL
  Nenhuma tecnologia, experiencia ou certificacao pode ser afirmada se nao
  estiver no perfil. Tecnologias exigidas pela vaga e ausentes do perfil sao
  reportadas como GAP - nunca convertidas em experiencia.
"""


def assert_capability_not_forbidden(capability: str) -> None:
    """Levanta `ForbiddenActionError` se a capacidade for proibida por politica.

    Chamado nas fronteiras onde uma extensao futura poderia, por engano,
    tentar habilitar automacao proibida.
    """
    normalized = capability.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in FORBIDDEN_CAPABILITIES:
        raise ForbiddenActionError(
            f"Acao '{capability}' e proibida pela politica de seguranca do "
            f"Career Agent e nao esta implementada. Motivo: automacao de "
            f"portais de vagas / manuseio de credenciais viola os termos de "
            f"uso e coloca sua conta em risco. Consulte docs/SECURITY.md."
        )


# ---------------------------------------------------------------------------
# Maquina de estados da candidatura
# ---------------------------------------------------------------------------

S = ApplicationStatus

ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    S.PENDING_APPROVAL: frozenset({S.APPROVED, S.REJECTED, S.WITHDRAWN}),
    S.APPROVED: frozenset({S.APPLIED, S.WITHDRAWN, S.REJECTED}),
    S.APPLIED: frozenset(
        {S.INTERVIEW, S.TECHNICAL_TEST, S.OFFER, S.REJECTED, S.WITHDRAWN}
    ),
    S.INTERVIEW: frozenset({S.TECHNICAL_TEST, S.OFFER, S.REJECTED, S.WITHDRAWN}),
    S.TECHNICAL_TEST: frozenset({S.INTERVIEW, S.OFFER, S.REJECTED, S.WITHDRAWN}),
    S.OFFER: frozenset({S.REJECTED, S.WITHDRAWN}),
    S.REJECTED: frozenset(),
    S.WITHDRAWN: frozenset(),
}

#: Estados que representam contato externo ja realizado pela humana.
EXTERNAL_ACTION_STATES: frozenset[ApplicationStatus] = frozenset(
    {S.APPLIED, S.INTERVIEW, S.TECHNICAL_TEST, S.OFFER}
)

TERMINAL_STATES: frozenset[ApplicationStatus] = frozenset({S.REJECTED, S.WITHDRAWN})


@dataclass(frozen=True)
class ApprovalGate:
    """Valida transicoes de status, garantindo o human-in-the-loop."""

    def validate(
        self, current: ApplicationStatus, target: ApplicationStatus
    ) -> None:
        if current == target:
            raise InvalidStatusTransitionError(
                f"A candidatura ja esta em '{current.value}'."
            )

        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())

        if target not in allowed:
            if current in TERMINAL_STATES:
                raise InvalidStatusTransitionError(
                    f"'{current.value}' e um estado final. Nao e possivel mudar "
                    f"para '{target.value}'. Registre uma nova candidatura se o "
                    f"processo foi reaberto."
                )
            if (
                current is S.PENDING_APPROVAL
                and target in EXTERNAL_ACTION_STATES
            ):
                raise InvalidStatusTransitionError(
                    f"Nao e possivel ir de 'pending_approval' direto para "
                    f"'{target.value}'. Toda candidatura precisa da sua aprovacao "
                    f"explicita primeiro: mude para 'approved' e so entao para "
                    f"'{target.value}'. Este bloqueio e a garantia de que nada "
                    f"sai daqui sem voce ter visto."
                )
            options = ", ".join(sorted(s.value for s in allowed)) or "(nenhum)"
            raise InvalidStatusTransitionError(
                f"Transicao invalida: '{current.value}' -> '{target.value}'. "
                f"A partir de '{current.value}' os destinos validos sao: {options}."
            )

    def next_states(self, current: ApplicationStatus) -> list[str]:
        return sorted(s.value for s in ALLOWED_TRANSITIONS.get(current, frozenset()))

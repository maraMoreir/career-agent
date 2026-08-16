"""Testes das regras de seguranca.

Estes testes existem para falhar RUIDOSAMENTE se alguem, um dia, tentar
adicionar automacao proibida ou furar o human-in-the-loop.
"""

from __future__ import annotations

import pytest

from career_core.errors import ForbiddenActionError, InvalidStatusTransitionError
from career_core.models import ApplicationStatus as S
from career_core.security import (
    ALLOWED_TRANSITIONS,
    EXTERNAL_ACTION_STATES,
    FORBIDDEN_CAPABILITIES,
    SAFETY_POLICY,
    ApprovalGate,
    assert_capability_not_forbidden,
)


# ---------------------------------------------------------------------------
# Capacidades proibidas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("capability", FORBIDDEN_CAPABILITIES)
def test_capacidade_proibida_e_recusada(capability):
    with pytest.raises(ForbiddenActionError):
        assert_capability_not_forbidden(capability)


@pytest.mark.parametrize(
    "capability",
    [
        "linkedin_login",
        "LinkedIn-Login",
        "LINKEDIN LOGIN",
        "auto_submit_application",
        "auto-send-message",
        "anti bot evasion",
        "aggressive_scraping",
        "linkedin_cookie_storage",
    ],
)
def test_variacoes_de_escrita_tambem_sao_recusadas(capability):
    with pytest.raises(ForbiddenActionError):
        assert_capability_not_forbidden(capability)


def test_capacidade_legitima_passa():
    for capability in ("search_jobs", "calculate_score", "read_profile"):
        assert_capability_not_forbidden(capability)


def test_lista_de_proibicoes_cobre_o_exigido():
    for required in (
        "linkedin_login",
        "linkedin_password_storage",
        "linkedin_cookie_storage",
        "session_capture",
        "linkedin_click_automation",
        "auto_submit_application",
        "auto_send_message",
        "anti_bot_evasion",
        "aggressive_scraping",
    ):
        assert required in FORBIDDEN_CAPABILITIES


def test_politica_declara_o_que_nao_e_feito():
    text = SAFETY_POLICY.lower()
    for marker in ("login automatico", "cookie", "candidatura automaticamente", "scraping"):
        assert marker in text


def test_nao_existe_variavel_de_credencial_no_env_de_exemplo():
    from pathlib import Path

    env = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )
    lowered = env.lower()
    for forbidden in ("linkedin_password", "linkedin_cookie", "li_at", "session_token"):
        assert forbidden not in lowered


# ---------------------------------------------------------------------------
# Maquina de estados / human-in-the-loop
# ---------------------------------------------------------------------------


@pytest.fixture
def gate() -> ApprovalGate:
    return ApprovalGate()


def test_candidatura_nasce_aguardando_aprovacao():
    from career_core.models import Application

    application = Application(id="app-1", company="X", role="Dev")
    assert application.status is S.PENDING_APPROVAL


def test_pending_nao_pula_direto_para_applied(gate):
    """A garantia central: nada avanca sem aprovacao humana explicita."""
    with pytest.raises(InvalidStatusTransitionError) as exc:
        gate.validate(S.PENDING_APPROVAL, S.APPLIED)
    assert "approved" in str(exc.value).lower()


@pytest.mark.parametrize("target", sorted(EXTERNAL_ACTION_STATES, key=lambda s: s.value))
def test_pending_nao_pula_para_nenhum_estado_de_acao_externa(gate, target):
    with pytest.raises(InvalidStatusTransitionError):
        gate.validate(S.PENDING_APPROVAL, target)


def test_fluxo_feliz_completo(gate):
    for current, target in (
        (S.PENDING_APPROVAL, S.APPROVED),
        (S.APPROVED, S.APPLIED),
        (S.APPLIED, S.INTERVIEW),
        (S.INTERVIEW, S.TECHNICAL_TEST),
        (S.TECHNICAL_TEST, S.OFFER),
    ):
        gate.validate(current, target)


@pytest.mark.parametrize("terminal", [S.REJECTED, S.WITHDRAWN])
def test_estados_finais_nao_avancam(gate, terminal):
    with pytest.raises(InvalidStatusTransitionError) as exc:
        gate.validate(terminal, S.INTERVIEW)
    assert "final" in str(exc.value).lower()


def test_nao_transiciona_para_o_mesmo_estado(gate):
    with pytest.raises(InvalidStatusTransitionError):
        gate.validate(S.APPLIED, S.APPLIED)


def test_todo_status_tem_regra_definida():
    for status in S:
        assert status in ALLOWED_TRANSITIONS


def test_desistir_e_sempre_possivel_antes_do_fim(gate):
    for current in (S.PENDING_APPROVAL, S.APPROVED, S.APPLIED, S.INTERVIEW, S.TECHNICAL_TEST):
        gate.validate(current, S.WITHDRAWN)


def test_proximos_estados_sao_uteis(gate):
    assert gate.next_states(S.PENDING_APPROVAL) == ["approved", "rejected", "withdrawn"]
    assert gate.next_states(S.REJECTED) == []


# ---------------------------------------------------------------------------
# Ausencia de automacao proibida no codigo
# ---------------------------------------------------------------------------


def test_projeto_nao_depende_de_automacao_de_navegador():
    """Falha se alguem adicionar selenium/playwright as dependencias."""
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    ).lower()
    for banned in ("selenium", "playwright", "puppeteer", "undetected", "browser-use"):
        assert banned not in pyproject, f"dependencia de automacao proibida: {banned}"

"""Hierarquia de erros do dominio.

Erros de dominio sao esperados e viram mensagens claras para o Claude.
Qualquer outra excecao e um bug e e logada com stack trace.
"""

from __future__ import annotations


class CareerAgentError(Exception):
    """Base de todos os erros de dominio."""


class ConfigurationError(CareerAgentError):
    """Configuracao ausente ou invalida."""


class ProfileNotFoundError(CareerAgentError):
    """Arquivos de perfil ausentes ou ilegiveis."""


class ResumeNotFoundError(CareerAgentError):
    """Curriculo solicitado nao existe."""


class ApplicationNotFoundError(CareerAgentError):
    """Candidatura inexistente."""


class InvalidStatusTransitionError(CareerAgentError):
    """Transicao de status nao permitida pela maquina de estados."""


class PathAccessDeniedError(CareerAgentError):
    """Tentativa de acessar caminho fora da raiz de dados permitida."""


class ForbiddenActionError(CareerAgentError):
    """Acao bloqueada pela politica de seguranca (ex.: automacao no LinkedIn)."""


class JobSourceError(CareerAgentError):
    """Falha ao consultar uma fonte de vagas."""


class JobSourceUnavailableError(JobSourceError):
    """Fonte existe na abstracao mas nao pode ser usada de forma legitima."""


class ValidationError(CareerAgentError):
    """Payload de entrada invalido."""

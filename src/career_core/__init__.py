"""career_core - dominio do Career Agent.

Este pacote nao conhece MCP. Ele contem perfil, score, curriculo,
candidaturas, deduplicacao, fontes de vagas e a politica de seguranca.
Os tres servidores MCP sao apenas adapters finos sobre ele.
"""

from .config import Settings, build_settings, get_settings
from .errors import CareerAgentError
from .models import (
    Application,
    ApplicationStatus,
    CandidateProfile,
    Job,
    JobScore,
    Recommendation,
    Seniority,
    WorkMode,
)
from .services import CareerServices

__version__ = "1.0.0"

__all__ = [
    "Settings",
    "build_settings",
    "get_settings",
    "CareerAgentError",
    "CareerServices",
    "Application",
    "ApplicationStatus",
    "CandidateProfile",
    "Job",
    "JobScore",
    "Recommendation",
    "Seniority",
    "WorkMode",
    "__version__",
]

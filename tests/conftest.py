"""Fixtures compartilhadas.

Todos os testes rodam contra um `data_root` temporario. Nada toca
`C:\\career-agent\\data` real.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from career_core.config import Settings  # noqa: E402
from career_core.models import Job, Seniority, WorkMode  # noqa: E402
from career_core.services import CareerServices  # noqa: E402

PROFILE_MD = """\
# Perfil Profissional

## Identificacao

- Nome: Maria Teste
- Titulo: Desenvolvedora Backend/FullStack | Foco em .NET
- Anos de experiencia: nao informado

## Resumo profissional

Desenvolvedora Backend com foco em .NET.

## Formacao

- MBA em Engenharia de Software com IA (em andamento)

## Empresas bloqueadas

- Empresa Vetada Ltda
"""

SKILLS_MD = """\
# Competencias Tecnicas

## Tecnologias

- C#
- .NET
- ASP.NET Core
- Entity Framework Core
- LINQ
- Dapper
- TypeScript
- React
- PostgreSQL
- SQL Server
- SAP HANA
- RabbitMQ
- Docker
- Kubernetes
- GitLab CI/CD
- JWT

## Arquitetura

- Clean Architecture
- SOLID
- DDD
- Design Patterns
- Hexagonal Architecture
- APIs REST
- Sistemas distribuídos
- Monolito
- Microsserviços

## Dominios

- Integrações com SAP
- SAP Business One
- SAP DI API
- SAP UI API
- Sistemas fiscais
- NF-e
- NFS-e
- CT-e
- MDF-e
- GNRE
- SEFAZ
"""

PREFERENCES_MD = """\
# Preferencias de Vaga

## Cargos prioritarios

- Backend .NET
- Software Engineer

## Senioridade desejada

- Pleno
- Senior

## Evitar

- Estagio
- Trainee
- Junior

## Modalidade

1. Remoto
2. Hibrido
3. Presencial

## Localizacao

### Paises

- Brasil

### Cidades

- Goiania

## Remuneracao

- Minimo: R$ 12.000
- Alvo: R$ 16.000
"""

RESUME_MD = """\
# Maria Teste

Desenvolvedora Backend/FullStack | Foco em .NET

## Resumo profissional

Desenvolvedora Backend com foco em .NET.

## Experiencia profissional

### Desenvolvedora Backend - Empresa Exemplo
2020 - Atual

- Desenvolvimento de APIs REST com ASP.NET Core e Entity Framework Core.
"""


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    (root / "profile").mkdir(parents=True)
    (root / "resumes").mkdir(parents=True)
    (root / "applications").mkdir(parents=True)

    (root / "profile" / "profile.md").write_text(PROFILE_MD, encoding="utf-8")
    (root / "profile" / "skills.md").write_text(SKILLS_MD, encoding="utf-8")
    (root / "profile" / "preferences.md").write_text(PREFERENCES_MD, encoding="utf-8")
    (root / "resumes" / "curriculo-principal.md").write_text(RESUME_MD, encoding="utf-8")
    return root


@pytest.fixture
def settings(data_root: Path, tmp_path: Path) -> Settings:
    return Settings(
        data_root=data_root,
        log_dir=tmp_path / "logs",
        log_level="WARNING",
        min_score=70,
        enable_network=False,
        sources=("mock",),
        http_timeout=5.0,
        max_results=25,
        min_interval=0.0,
        user_agent="career-agent-tests/1.0",
    )


@pytest.fixture
def services(settings: Settings) -> CareerServices:
    return CareerServices(settings)


@pytest.fixture
def profile(services: CareerServices):
    return services.profile()


@pytest.fixture
def perfect_job() -> Job:
    """Vaga desenhada para pontuar muito alto."""
    return Job(
        source="test",
        title="Desenvolvedora Backend .NET Senior",
        company="Nexatech Sistemas",
        url="https://exemplo.dev/vagas/1",
        location="Brasil",
        country="Brasil",
        seniority=Seniority.SENIOR,
        work_mode=WorkMode.REMOTE,
        salary_text="R$ 16.000 a R$ 18.000",
        salary_min_brl=16000.0,
        salary_max_brl=18000.0,
        tech_tags=["C#", ".NET", "ASP.NET Core", "Entity Framework Core"],
        description=(
            "Requisitos:\n"
            "- C# e .NET (ASP.NET Core)\n"
            "- Entity Framework Core e LINQ\n"
            "- PostgreSQL\n"
            "- RabbitMQ\n"
            "- Docker\n"
            "- Clean Architecture, SOLID e DDD\n"
            "- APIs REST\n"
            "Oferecemos CLT, plano de saude e PLR."
        ),
    )


@pytest.fixture
def junior_job() -> Job:
    return Job(
        source="test",
        title="Desenvolvedor .NET Junior",
        company="Primeira Linha",
        url="https://exemplo.dev/vagas/2",
        location="Sao Paulo, SP",
        country="Brasil",
        seniority=Seniority.JUNIOR,
        work_mode=WorkMode.ONSITE,
        tech_tags=["C#", ".NET"],
        description="Requisitos:\n- C# e .NET\n- SQL Server",
    )

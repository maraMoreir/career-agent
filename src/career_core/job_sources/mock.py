"""Fonte mock: deterministica, offline, sem rede.

E a fonte PADRAO da V1. Serve para:
  - validar o fluxo completo sem depender de terceiros;
  - rodar os testes sempre com o mesmo resultado;
  - demonstrar o formato normalizado que qualquer fonte nova deve produzir.

O catalogo cobre casos de propositos: match alto, match medio, senioridade a
evitar (eliminacao), vaga estrangeira presencial e vaga fora da stack.
"""

from __future__ import annotations

import logging

from ..models import Job, Seniority, WorkMode
from ..text import normalize_text
from .base import IJobSource, JobQuery, SourceResult

logger = logging.getLogger(__name__)


_CATALOG: tuple[dict, ...] = (
    {
        "id": "mock-001",
        "title": "Desenvolvedor(a) Backend .NET Senior",
        "company": "Nexatech Sistemas",
        "url": "https://exemplo-vagas.dev/vagas/mock-001",
        "location": "Brasil",
        "country": "Brasil",
        "seniority": Seniority.SENIOR,
        "work_mode": WorkMode.REMOTE,
        "salary_text": "R$ 14.000 a R$ 18.000",
        "salary_min_brl": 14000.0,
        "salary_max_brl": 18000.0,
        "tech_tags": [
            "C#", ".NET", "ASP.NET Core", "Entity Framework Core",
            "PostgreSQL", "Docker", "RabbitMQ", "Clean Architecture",
        ],
        "description": """
Vaga 100% remota para todo o Brasil.

Requisitos:
- Experiencia solida com C# e .NET (ASP.NET Core)
- Entity Framework Core e LINQ
- PostgreSQL
- Mensageria com RabbitMQ
- Docker
- Clean Architecture, SOLID e DDD
- APIs REST
- Autenticacao com JWT

Diferenciais:
- Kubernetes
- Azure

Oferecemos CLT, plano de saude, PLR e auxilio home office.
""",
    },
    {
        "id": "mock-002",
        "title": "Engenheiro(a) de Software Pleno - .NET e React",
        "company": "Cerrado Software",
        "url": "https://exemplo-vagas.dev/vagas/mock-002",
        "location": "Goiania, GO",
        "country": "Brasil",
        "seniority": Seniority.MID,
        "work_mode": WorkMode.HYBRID,
        "salary_text": "R$ 10.000 a R$ 12.000",
        "salary_min_brl": 10000.0,
        "salary_max_brl": 12000.0,
        "tech_tags": [
            "C#", ".NET", "ASP.NET Core", "TypeScript", "React",
            "SQL Server", "Dapper", "GitLab CI/CD",
        ],
        "description": """
Hibrido em Goiania (3x presencial).

Requisitos:
- C# e ASP.NET Core
- Dapper e SQL Server
- TypeScript e React
- GitLab CI/CD
- SOLID e Design Patterns
- APIs REST

Desejavel:
- Integracoes com SAP Business One
- Conhecimento em sistemas fiscais (NF-e)

Beneficios: vale refeicao, plano de saude, horario flexivel.
""",
    },
    {
        "id": "mock-003",
        "title": "Desenvolvedor(a) .NET Junior",
        "company": "Primeira Linha Tecnologia",
        "url": "https://exemplo-vagas.dev/vagas/mock-003",
        "location": "Sao Paulo, SP",
        "country": "Brasil",
        "seniority": Seniority.JUNIOR,
        "work_mode": WorkMode.ONSITE,
        "salary_text": "R$ 4.000",
        "salary_min_brl": 4000.0,
        "salary_max_brl": 4000.0,
        "tech_tags": ["C#", ".NET", "SQL Server"],
        "description": """
Vaga presencial em Sao Paulo.

Requisitos:
- C# e .NET
- SQL Server
- Vontade de aprender
""",
    },
    {
        "id": "mock-004",
        "title": "Senior Backend Engineer (Go / Kubernetes)",
        "company": "Northwind Labs",
        "url": "https://exemplo-vagas.dev/vagas/mock-004",
        "location": "Berlin, Germany",
        "country": "Germany",
        "seniority": Seniority.SENIOR,
        "work_mode": WorkMode.ONSITE,
        "salary_text": "",
        "tech_tags": ["Go", "Kubernetes", "PostgreSQL", "Kafka"],
        "description": """
On-site position in Berlin. Relocation required.

Requirements:
- 5+ years with Go
- Kubernetes
- PostgreSQL
- Kafka
- Distributed systems
""",
    },
    {
        "id": "mock-005",
        "title": "Analista Desenvolvedor(a) SAP Business One - .NET",
        "company": "Integra ERP",
        "url": "https://exemplo-vagas.dev/vagas/mock-005",
        "location": "Brasil",
        "country": "Brasil",
        "seniority": Seniority.SENIOR,
        "work_mode": WorkMode.REMOTE,
        "salary_text": "R$ 13.000 a R$ 16.000",
        "salary_min_brl": 13000.0,
        "salary_max_brl": 16000.0,
        "tech_tags": [
            "C#", ".NET", "SAP Business One", "SAP DI API", "SAP UI API",
            "SAP HANA", "SQL Server", "NF-e",
        ],
        "description": """
Remoto para todo o Brasil.

Requisitos:
- C# e .NET
- SAP Business One (DI API e UI API)
- SAP HANA
- SQL Server
- Sistemas fiscais: NF-e, NFS-e, CT-e, MDF-e
- SEFAZ
- APIs REST

Diferenciais:
- Reforma Tributaria
- GNRE

Beneficios: CLT, plano de saude, PLR, budget de estudos e certificacao.
""",
    },
)


class MockJobSource(IJobSource):
    """Catalogo local para desenvolvimento, testes e demonstracao."""

    name = "mock"
    provenance = (
        "Catalogo local ficticio embutido no projeto. Nenhuma chamada de rede. "
        "As vagas NAO sao reais - servem para validar o fluxo ponta a ponta."
    )
    usable = True

    def search(self, query: JobQuery) -> SourceResult:
        keywords = [k for k in normalize_text(query.keywords).split() if len(k) > 1]
        location = normalize_text(query.location)
        wanted_modes = {normalize_text(m) for m in query.work_modes if m}

        selected: list[Job] = []
        for entry in _CATALOG:
            job = Job(source=self.name, raw=dict(entry), **entry)

            haystack = normalize_text(job.searchable_text())
            if keywords and not any(k in haystack for k in keywords):
                continue

            if location:
                job_location = normalize_text(f"{job.location} {job.country}")
                is_remote_br = job.work_mode is WorkMode.REMOTE and "brasil" in job_location
                if location not in job_location and not is_remote_br:
                    continue

            if wanted_modes and normalize_text(job.work_mode.value) not in wanted_modes:
                continue

            selected.append(job)
            if len(selected) >= max(1, query.limit):
                break

        logger.info("mock: %d vaga(s) para '%s'", len(selected), query.keywords)
        return SourceResult(
            source=self.name,
            jobs=selected,
            ok=True,
            message=(
                f"{len(selected)} vaga(s) do catalogo MOCK (ficticias). "
                f"Para vagas reais, habilite JOB_SEARCH_ENABLE_NETWORK=true e "
                f"inclua 'remotive' ou 'arbeitnow' em JOB_SEARCH_SOURCES."
            ),
        )

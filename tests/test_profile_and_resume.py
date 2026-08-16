"""Testes de leitura de perfil e de personalizacao honesta do curriculo."""

from __future__ import annotations

import pytest

from career_core.errors import ProfileNotFoundError, ResumeNotFoundError
from career_core.models import Job, Seniority, WorkMode
from career_core.profile.repository import MarkdownProfileRepository
from career_core.resume.tailor import FactGuard, ResumeTailor


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------


def test_le_stack_completa(profile):
    for skill in ("C#", ".NET", "ASP.NET Core", "Entity Framework Core", "Dapper"):
        assert skill in profile.skills


def test_ponto_inicial_do_dotnet_e_preservado(profile):
    """Regressao: `.strip('.')` transformava '.NET' em 'NET'."""
    assert ".NET" in profile.skills
    assert "NET" not in profile.skills


def test_le_arquitetura_e_dominios(profile):
    assert "Clean Architecture" in profile.architecture
    assert "SAP Business One" in profile.domains


def test_le_preferencias(profile):
    assert profile.preferred_seniorities == ["pleno", "senior"]
    assert profile.avoid_seniorities == ["estagio", "trainee", "junior"]
    assert profile.countries == ["Brasil"]
    assert profile.preferred_cities == ["Goiania"]


def test_lista_numerada_de_modalidade_e_lida(profile):
    """Regressao: a ordem de modalidade e escrita como `1. Remoto`."""
    assert profile.work_mode_priority == ["remoto", "hibrido", "presencial"]


def test_le_campos_de_secao_aninhada(profile):
    """Regressao: `# Perfil Profissional` casava antes de `## Identificacao`."""
    assert profile.full_name == "Maria Teste"
    assert ".NET" in profile.headline


def test_le_salario_em_formato_brasileiro(profile):
    assert profile.min_salary_brl == 12000.0
    assert profile.target_salary_brl == 16000.0


def test_anos_de_experiencia_nao_e_inventado(profile):
    """'nao informado' precisa continuar None. Nunca inferimos tempo de carreira."""
    assert profile.years_experience is None


def test_placeholder_nao_vira_dado(data_root):
    (data_root / "profile" / "profile.md").write_text(
        "## Identificacao\n\n- Nome: [PREENCHER - seu nome]\n", encoding="utf-8"
    )
    profile = MarkdownProfileRepository(data_root / "profile").load()
    assert profile.full_name == ""


def test_perfil_ausente_da_erro_claro(tmp_path):
    with pytest.raises(ProfileNotFoundError):
        MarkdownProfileRepository(tmp_path / "vazio").load()


def test_known_terms_resolve_aliases(profile):
    terms = profile.known_terms()
    assert ".net" in terms
    assert "c#" in terms
    assert "entity framework core" in terms


# ---------------------------------------------------------------------------
# FactGuard - anti-invencao
# ---------------------------------------------------------------------------


@pytest.fixture
def azure_job() -> Job:
    return Job(
        source="test",
        title="Dev Backend .NET",
        company="Nexatech",
        seniority=Seniority.SENIOR,
        work_mode=WorkMode.REMOTE,
        location="Brasil",
        tech_tags=["C#", ".NET", "Azure", "Kafka"],
        description="Requisitos:\n- C# e .NET\n- Azure\n- Kafka",
    )


def test_guard_reprova_experiencia_inventada(profile, azure_job):
    report = FactGuard(profile).audit(
        "Tenho experiencia solida em Azure e Kafka em producao.", azure_job
    )
    assert not report.ok
    assert any("azure" in v.lower() for v in report.violations)


@pytest.mark.parametrize(
    "text",
    [
        "Experiencia com Azure.",
        "Trabalhei com Kafka por 3 anos.",
        "Dominio de Azure.",
        "Conhecimento solido em Kafka.",
        "Azure: 5 anos de experiencia.",
        "Sou certificada em Azure.",
    ],
)
def test_guard_pega_varias_formas_de_afirmacao(profile, azure_job, text):
    assert not FactGuard(profile).audit(text, azure_job).ok


def test_guard_aprova_gap_declarado_honestamente(profile, azure_job):
    report = FactGuard(profile).audit(
        "Nao possuo experiencia com Azure nem com Kafka - sao gaps para esta "
        "vaga, tenho interesse em aprender.",
        azure_job,
    )
    assert report.ok, report.violations


def test_guard_aprova_texto_so_com_fatos_do_perfil(profile, azure_job):
    report = FactGuard(profile).audit(
        "Atuo com C#, .NET e ASP.NET Core, aplicando Clean Architecture e SOLID.",
        azure_job,
    )
    assert report.ok, report.violations


def test_guard_aceita_texto_vazio(profile):
    assert FactGuard(profile).audit("").ok


# ---------------------------------------------------------------------------
# Personalizacao do curriculo
# ---------------------------------------------------------------------------


@pytest.fixture
def tailor(services, profile) -> ResumeTailor:
    return ResumeTailor(services.settings.resumes_dir, profile)


def test_lista_curriculos(tailor):
    assert "curriculo-principal.md" in tailor.list_resumes()


def test_curriculo_inexistente_da_erro_claro(tailor):
    with pytest.raises(ResumeNotFoundError):
        tailor.read_resume("nao-existe.md")


def test_curriculo_nao_pode_ser_lido_de_fora_da_pasta(tailor):
    with pytest.raises(ResumeNotFoundError):
        tailor.read_resume("../profile/skills.md")


def test_personalizacao_destaca_stack_da_vaga(tailor, perfect_job):
    result = tailor.tailor(perfect_job)
    highlighted = [s.lower() for s in result.highlighted_skills]
    assert "c#" in highlighted
    assert ".net" in highlighted


def test_personalizacao_reordena_sem_perder_nada(tailor, perfect_job, profile):
    result = tailor.tailor(perfect_job)
    assert len(result.reordered_skills) == len(profile.skills) + len(profile.architecture)
    assert set(result.reordered_skills) == set(profile.skills + profile.architecture)


def test_personalizacao_lista_gaps_sem_afirma_los(tailor, azure_job):
    result = tailor.tailor(azure_job)
    assert "azure" in [g.lower() for g in result.gaps_not_claimed]
    assert "azure" not in [s.lower() for s in result.highlighted_skills]


def test_material_gerado_passa_na_auditoria(tailor, azure_job):
    result = tailor.tailor(azure_job)
    assert result.guard.ok, result.guard.violations


def test_curriculo_base_permanece_intacto(tailor, perfect_job):
    _, original = tailor.read_resume("curriculo-principal.md")
    result = tailor.tailor(perfect_job)
    assert original in result.markdown
    _, after = tailor.read_resume("curriculo-principal.md")
    assert after == original, "o curriculo principal nao pode ser modificado"


def test_escolha_automatica_prefere_curriculo_com_nome_afim(tailor, services, perfect_job):
    (services.settings.resumes_dir / "curriculo-backend-dotnet.md").write_text(
        "# Variante backend\n", encoding="utf-8"
    )
    assert tailor.recommend_resume(perfect_job) == "curriculo-backend-dotnet.md"

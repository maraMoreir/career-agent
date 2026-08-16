"""MCP `career-files` - leitura de arquivos, restrita a `data/`.

Acesso SOMENTE LEITURA e SOMENTE dentro de `CAREER_DATA_ROOT`
(padrao: C:\\career-agent\\data).

O Claude NAO tem acesso a C:\\, a sua pasta de usuario, nem a qualquer coisa
fora dessa arvore. Toda resolucao de caminho passa por `SandboxedFileSystem`,
que resolve links e caminhos relativos ANTES de comparar com a raiz - `..`,
caminho absoluto, symlink e junction do Windows sao todos recusados.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from career_core.config import get_settings  # noqa: E402
from career_core.errors import CareerAgentError  # noqa: E402
from career_core.logging_setup import configure_logging  # noqa: E402
from career_core.mcp_compat import build_server  # noqa: E402
from career_core.paths import ALLOWED_SUFFIXES, SandboxedFileSystem, describe_sandbox  # noqa: E402

SETTINGS = get_settings()
SETTINGS.ensure_directories()
logger = configure_logging("mcp-career-files", SETTINGS.log_dir, SETTINGS.log_level)

fs = SandboxedFileSystem(SETTINGS.data_root)
mcp = build_server(
    "career-files",
    instructions=(
        "Leitura somente-leitura de perfil, curriculos e historico, restrita a "
        "C:\\career-agent\\data. Nao acessa C:\\ nem a pasta de usuario."
    ),
)


def _guard(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except CareerAgentError as exc:
            logger.warning("%s: %s", func.__name__, exc)
            return f"ERRO: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha inesperada em %s", func.__name__)
            return f"ERRO INTERNO em {func.__name__}: {exc}"

    return wrapper


@mcp.tool()
@_guard
def read_profile() -> str:
    """Le os arquivos de perfil brutos: profile.md, skills.md e preferences.md.

    Use quando precisar do texto original do perfil (por exemplo, para citar
    um trecho literal). Para a versao estruturada e ja interpretada, prefira
    `get_candidate_profile` do servidor career-agent.
    """
    blocks: list[str] = []
    for name in ("profile.md", "skills.md", "preferences.md"):
        relative = f"profile/{name}"
        if not fs.exists(relative):
            blocks.append(f"### {name}\n\n(arquivo nao encontrado)\n")
            continue
        blocks.append(f"### {name}\n\n{fs.read_text(relative)}\n")
    return "\n---\n\n".join(blocks)


@mcp.tool()
@_guard
def read_preferences() -> str:
    """Le apenas `preferences.md`: cargos-alvo, senioridade desejada e a
    evitar, ordem de modalidade, localizacao e faixa salarial.

    Use quando a usuaria perguntar quais sao suas preferencias atuais ou
    quando precisar conferir os criterios antes de filtrar vagas.
    """
    return fs.read_text("profile/preferences.md")


@mcp.tool()
@_guard
def list_resumes() -> str:
    """Lista os curriculos disponiveis em `data/resumes/`.

    Use antes de escolher qual curriculo personalizar, ou quando a usuaria
    perguntar quais versoes existem.
    """
    files = fs.list_files("resumes", "*.md")
    if not files:
        return (
            "Nenhum curriculo encontrado em data/resumes/. "
            "Crie um arquivo .md nessa pasta (o principal e "
            "`curriculo-principal.md`)."
        )
    lines = [f"{len(files)} curriculo(s) em data/resumes/:", ""]
    for path in files:
        info = fs.stat(path)
        lines.append(
            f"  - {Path(path).name}  ({info['size_bytes']} bytes, "
            f"modificado em {str(info['modified_at'])[:19]})"
        )
    return "\n".join(lines)


@mcp.tool()
@_guard
def read_resume(filename: str = "curriculo-principal.md") -> str:
    """Le o conteudo de um curriculo de `data/resumes/`.

    Use para ver o curriculo base antes de personaliza-lo, ou quando a
    usuaria pedir para revisar o conteudo atual.

    Args:
        filename: nome do arquivo. Padrao: `curriculo-principal.md`.
    """
    safe_name = Path(filename.strip() or "curriculo-principal.md").name
    if not safe_name.lower().endswith((".md", ".markdown", ".txt")):
        safe_name += ".md"
    return fs.read_text(f"resumes/{safe_name}")


@mcp.tool()
@_guard
def read_application_history() -> str:
    """Le o espelho JSON do historico de candidaturas.

    ATENCAO: este arquivo e um espelho gerado automaticamente. A fonte de
    verdade e o SQLite. Para consultar candidaturas, prefira
    `list_applications` / `get_application` do servidor career-agent - sao
    mais rapidos e aceitam filtros. Use esta ferramenta apenas para inspecao
    bruta do arquivo.
    """
    if not fs.exists("applications/applications.json"):
        return "Ainda nao ha historico. Registre a primeira candidatura."
    return fs.read_text("applications/applications.json")


@mcp.tool()
@_guard
def list_data_files(subdirectory: str = "", pattern: str = "*") -> str:
    """Lista os arquivos visiveis dentro da raiz de dados.

    Use para descobrir o que existe antes de ler algo, ou para diagnosticar
    "arquivo nao encontrado".

    Args:
        subdirectory: subpasta relativa (ex.: "profile", "resumes"). Vazio =
            toda a arvore de dados.
        pattern: glob de nome (ex.: "*.md").
    """
    files = fs.list_files(subdirectory, pattern)
    location = subdirectory or "data/ (raiz)"
    if not files:
        return f"Nenhum arquivo em '{location}' com padrao '{pattern}'."
    return f"{len(files)} arquivo(s) em '{location}':\n\n" + "\n".join(
        f"  - {path}" for path in files
    )


@mcp.tool()
@_guard
def get_sandbox_info() -> str:
    """Mostra exatamente o que este servidor pode e nao pode acessar.

    Use se a usuaria perguntar quais arquivos o Claude enxerga, ou se um
    acesso for negado e voce precisar explicar o motivo.
    """
    return (
        "SANDBOX DO career-files\n"
        + "=" * 60
        + "\n"
        + describe_sandbox(fs.root)
        + "\n\n"
        + "Fora do alcance deste servidor (por design):\n"
        + "  - C:\\ e qualquer unidade\n"
        + "  - sua pasta de usuario\n"
        + "  - o codigo-fonte do proprio projeto\n"
        + "  - qualquer caminho fora da raiz acima, inclusive via '..' ou symlink\n\n"
        + f"Extensoes legiveis: {', '.join(sorted(ALLOWED_SUFFIXES))}\n"
        + "Modo: somente leitura. Este servidor nao escreve nem apaga nada."
    )


if __name__ == "__main__":
    logger.info("Iniciando MCP career-files (sandbox=%s)", fs.root)
    mcp.run()

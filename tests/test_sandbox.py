"""Testes do jail de arquivos do MCP career-files.

O requisito e explicito: o Claude NAO pode ver C:\\ nem o diretorio de usuario.
"""

from __future__ import annotations

import pytest

from career_core.errors import PathAccessDeniedError
from career_core.paths import SandboxedFileSystem


@pytest.fixture
def sandbox(data_root) -> SandboxedFileSystem:
    return SandboxedFileSystem(data_root)


# ---------------------------------------------------------------------------
# Acesso permitido
# ---------------------------------------------------------------------------


def test_le_perfil_dentro_da_sandbox(sandbox):
    assert "Competencias" in sandbox.read_text("profile/skills.md")


def test_aceita_barra_invertida_do_windows(sandbox):
    assert sandbox.read_text("profile\\skills.md") == sandbox.read_text("profile/skills.md")


def test_lista_curriculos(sandbox):
    assert "resumes/curriculo-principal.md" in sandbox.list_files("resumes", "*.md")


def test_lista_toda_a_arvore(sandbox):
    files = sandbox.list_files()
    assert any(f.startswith("profile/") for f in files)
    assert any(f.startswith("resumes/") for f in files)


# ---------------------------------------------------------------------------
# Acesso negado - o coracao do requisito
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "escape",
    [
        "../../../Windows/System32/drivers/etc/hosts",
        "..",
        "../",
        "../secret.md",
        "profile/../../escape.md",
        "profile/../../../Users",
        "..\\..\\Windows\\win.ini",
        "C:\\Windows\\win.ini",
        "C:/Users",
        "C:\\career-agent\\mcp-career\\server.py",
        "\\\\servidor\\share\\arquivo.md",
    ],
)
def test_recusa_fuga_da_sandbox(sandbox, escape):
    with pytest.raises(PathAccessDeniedError):
        sandbox.read_text(escape)


def test_mensagem_de_erro_explica_o_limite(sandbox):
    with pytest.raises(PathAccessDeniedError) as exc:
        sandbox.read_text("C:\\Windows\\win.ini")
    message = str(exc.value).lower()
    assert "fora da raiz" in message


def test_recusa_extensao_nao_permitida(sandbox, data_root):
    (data_root / "malicioso.exe").write_bytes(b"MZ")
    with pytest.raises(PathAccessDeniedError) as exc:
        sandbox.read_text("malicioso.exe")
    assert "extensao" in str(exc.value).lower()


def test_lista_ignora_extensoes_nao_permitidas(sandbox, data_root):
    (data_root / "binario.exe").write_bytes(b"MZ")
    (data_root / "chaves.pem").write_text("secret", encoding="utf-8")
    files = sandbox.list_files()
    assert not any(f.endswith((".exe", ".pem")) for f in files)


def test_recusa_nome_de_dispositivo_reservado(sandbox):
    with pytest.raises(PathAccessDeniedError):
        sandbox.read_text("CON.md")


def test_recusa_byte_nulo(sandbox):
    with pytest.raises(PathAccessDeniedError):
        sandbox.read_text("profile/skills.md\x00.txt")


def test_recusa_arquivo_grande(sandbox, data_root):
    (data_root / "grande.md").write_text("x" * 2000, encoding="utf-8")
    with pytest.raises(PathAccessDeniedError):
        sandbox.read_text("grande.md", max_bytes=1000)


def test_recusa_diretorio_como_arquivo(sandbox):
    with pytest.raises(PathAccessDeniedError) as exc:
        sandbox.read_text("profile")
    assert "diretorio" in str(exc.value).lower()


def test_arquivo_inexistente_da_erro_claro(sandbox):
    with pytest.raises(PathAccessDeniedError) as exc:
        sandbox.read_text("profile/inexistente.md")
    assert "nao encontrado" in str(exc.value).lower()


def test_caminho_absoluto_dentro_da_raiz_e_aceito(sandbox, data_root):
    absolute = str(data_root / "profile" / "skills.md")
    assert "Competencias" in sandbox.read_text(absolute)


def test_exists_nao_vaza_excecao(sandbox):
    assert sandbox.exists("profile/skills.md") is True
    assert sandbox.exists("C:\\Windows\\win.ini") is False
    assert sandbox.exists("../fora.md") is False

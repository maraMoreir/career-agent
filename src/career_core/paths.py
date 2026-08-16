"""Resolucao de caminhos com sandbox (jail) na raiz de dados.

Usado pelo MCP `career-files`. Garante que nenhum caminho fornecido pelo
modelo escape de `CAREER_DATA_ROOT`, mesmo via `..`, caminho absoluto,
symlink, junction do Windows ou nome de dispositivo reservado.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import PathAccessDeniedError

#: Somente estes tipos de arquivo podem ser lidos. Sem binarios, sem executaveis.
ALLOWED_SUFFIXES: frozenset[str] = frozenset({".md", ".json", ".txt", ".markdown"})

#: Nomes reservados do Windows que nunca devem ser abertos.
_RESERVED_NAMES: frozenset[str] = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


@dataclass(frozen=True)
class SandboxedFileSystem:
    """Acesso somente-leitura a arquivos, restrito a `root`.

    Toda API publica recebe caminho RELATIVO a raiz. Caminhos absolutos sao
    aceitos apenas se ja estiverem dentro da raiz - qualquer outra coisa e
    recusada com `PathAccessDeniedError`.
    """

    root: Path

    def __post_init__(self) -> None:
        resolved = Path(self.root).resolve()
        object.__setattr__(self, "root", resolved)

    # -- resolucao --------------------------------------------------------

    def resolve(self, relative_path: str) -> Path:
        """Resolve `relative_path` dentro da sandbox ou levanta erro."""
        if relative_path is None:
            raise PathAccessDeniedError("Caminho vazio nao e permitido.")

        candidate_raw = str(relative_path).strip().replace("\\", "/")

        if not candidate_raw or candidate_raw in {".", "./"}:
            return self.root

        if "\x00" in candidate_raw:
            raise PathAccessDeniedError("Caminho contem byte nulo.")

        candidate = Path(candidate_raw)

        # Caminho absoluto so passa se ja estiver dentro da raiz.
        if candidate.is_absolute() or candidate.drive or candidate_raw.startswith("//"):
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()

        self._assert_inside(resolved, relative_path)
        self._assert_name_allowed(resolved, relative_path)
        return resolved

    def _assert_inside(self, resolved: Path, original: str) -> None:
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise PathAccessDeniedError(
                f"Acesso negado: '{original}' fica fora da raiz de dados "
                f"permitida ({self.root}). O Career Agent so enxerga esse "
                f"diretorio - nunca C:\\ nem sua pasta de usuario."
            ) from None

    @staticmethod
    def _assert_name_allowed(resolved: Path, original: str) -> None:
        for part in resolved.parts:
            stem = part.split(".")[0].lower()
            if stem in _RESERVED_NAMES:
                raise PathAccessDeniedError(
                    f"Acesso negado: '{original}' usa um nome de dispositivo "
                    f"reservado do Windows."
                )

    # -- operacoes --------------------------------------------------------

    def read_text(self, relative_path: str, max_bytes: int = 512_000) -> str:
        """Le um arquivo de texto permitido dentro da sandbox."""
        path = self.resolve(relative_path)

        if not path.exists():
            raise PathAccessDeniedError(
                f"Arquivo nao encontrado: '{relative_path}' "
                f"(procurado em {self.root})."
            )
        if path.is_dir():
            raise PathAccessDeniedError(
                f"'{relative_path}' e um diretorio. Use `list_data_files`."
            )
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
            raise PathAccessDeniedError(
                f"Extensao '{path.suffix}' nao permitida. Permitidas: {allowed}."
            )

        size = path.stat().st_size
        if size > max_bytes:
            raise PathAccessDeniedError(
                f"Arquivo grande demais ({size} bytes; limite {max_bytes})."
            )

        return path.read_text(encoding="utf-8", errors="replace")

    def list_files(
        self, relative_dir: str = "", pattern: str = "*", recursive: bool = True
    ) -> list[str]:
        """Lista arquivos permitidos, com caminho relativo a raiz."""
        base = self.resolve(relative_dir)
        if not base.is_dir():
            raise PathAccessDeniedError(f"'{relative_dir}' nao e um diretorio.")

        globber = base.rglob if recursive else base.glob
        results: list[str] = []

        for entry in globber(pattern):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            try:
                self._assert_inside(entry.resolve(), str(entry))
            except PathAccessDeniedError:
                continue  # symlink apontando para fora: ignora silenciosamente
            results.append(entry.relative_to(self.root).as_posix())

        return sorted(results)

    def stat(self, relative_path: str) -> dict[str, object]:
        path = self.resolve(relative_path)
        if not path.exists():
            raise PathAccessDeniedError(f"Nao encontrado: '{relative_path}'.")
        info = path.stat()
        return {
            "path": path.relative_to(self.root).as_posix(),
            "size_bytes": info.st_size,
            "modified_at": _iso(info.st_mtime),
            "is_directory": path.is_dir(),
        }

    def exists(self, relative_path: str) -> bool:
        try:
            return self.resolve(relative_path).exists()
        except PathAccessDeniedError:
            return False


def _iso(timestamp: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(
        timespec="seconds"
    )


def describe_sandbox(root: Path) -> str:
    return (
        f"Raiz de dados: {root}\n"
        f"Extensoes permitidas: {', '.join(sorted(ALLOWED_SUFFIXES))}\n"
        f"Acesso: somente leitura, restrito a essa arvore.\n"
        f"Existe: {'sim' if os.path.isdir(root) else 'NAO - rode scripts/install.ps1'}"
    )

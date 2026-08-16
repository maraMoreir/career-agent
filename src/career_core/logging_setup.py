"""Configuracao de logging para os servidores MCP.

REGRA CRITICA: um servidor MCP em stdio usa **stdout** para o protocolo JSON-RPC.
Escrever qualquer coisa em stdout corrompe a sessao. Todo log vai para stderr
e para arquivo.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED: set[str] = set()

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(server_name: str, log_dir: Path, level: str = "INFO") -> logging.Logger:
    """Configura o logger raiz para um servidor MCP e devolve seu logger.

    Args:
        server_name: identificador curto do servidor (vira o nome do arquivo).
        log_dir: diretorio onde o arquivo rotativo e escrito.
        level: nivel de log textual (DEBUG/INFO/WARNING/ERROR).
    """
    logger = logging.getLogger(f"career.{server_name}")

    if server_name in _CONFIGURED:
        return logger

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)

    formatter = logging.Formatter(_FORMAT)

    # stderr: visivel nos logs do Claude Desktop.
    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    # arquivo rotativo: historico durável.
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / f"{server_name}.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:  # disco cheio / permissao: nao derruba o servidor
        logger.warning("Nao foi possivel abrir o arquivo de log: %s", exc)

    # httpx e barulhento em INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _CONFIGURED.add(server_name)
    logger.info("Logging configurado (nivel=%s, dir=%s)", level, log_dir)
    return logger

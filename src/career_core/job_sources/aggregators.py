"""Agregadores nacionais que exigem credencial de desenvolvedor.

Diferente de uma senha de portal de vagas: aqui a chave e emitida para VOCE,
pelo proprio provedor, para uso programatico documentado. Nao ha login de
usuario, nao ha cookie de sessao, nao ha conta de candidato envolvida.

  Adzuna : GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
           Requer `app_id` e `app_key` gratuitos (developer.adzuna.com).
           Tem indice nacional do Brasil (`br`) - e a unica fonte deste
           projeto com cobertura ampla do mercado brasileiro.

  Jooble : NAO IMPLEMENTADO como fonte ativa. Ver `jooble_source()`.
"""

from __future__ import annotations

import logging
from typing import Any

from ..errors import JobSourceError
from ..http import HostRateLimiter, HttpClient
from ..models import Job, WorkMode
from ..text import normalize_text
from .base import (
    IJobSource,
    JobQuery,
    SourceResult,
    detect_seniority,
    detect_work_mode,
    strip_html,
)
from .unavailable import UnavailableJobSource

logger = logging.getLogger(__name__)


class AdzunaJobSource(IJobSource):
    """Busca no indice nacional da Adzuna (Brasil por padrao).

    Sem credencial a fonte nao falha silenciosamente: ela explica onde obter a
    chave gratuita e segue desabilitada.
    """

    name = "adzuna"
    provenance = (
        "API REST documentada da Adzuna (api.adzuna.com), com indice nacional "
        "do Brasil. Requer app_id/app_key gratuitos emitidos em "
        "developer.adzuna.com - credencial de desenvolvedor, nao login de "
        "portal. Unica fonte deste projeto com cobertura ampla do mercado "
        "brasileiro."
    )
    usable = True

    BASE = "https://api.adzuna.com/v1/api/jobs"

    _CONTRACT_TO_MODE = {
        "permanent": WorkMode.UNKNOWN,
        "contract": WorkMode.UNKNOWN,
    }

    def __init__(
        self,
        app_id: str = "",
        app_key: str = "",
        country: str = "br",
        user_agent: str = "career-agent/1.0",
        timeout: float = 15.0,
        min_interval: float = 1.0,
        max_results: int = 25,
        http_client: HttpClient | None = None,
    ) -> None:
        self._app_id = (app_id or "").strip()
        self._app_key = (app_key or "").strip()
        self._country = (country or "br").strip().lower()
        self._max_results = max_results
        self._http = http_client or HttpClient(
            user_agent=user_agent,
            timeout=timeout,
            limiter=HostRateLimiter(min_interval),
        )

    @property
    def configured(self) -> bool:
        return bool(self._app_id and self._app_key)

    def search(self, query: JobQuery) -> SourceResult:
        if not self.configured:
            return SourceResult(
                source=self.name,
                ok=False,
                message=(
                    "Adzuna nao configurada. E a unica fonte deste projeto com "
                    "indice nacional do Brasil, e vale 2 minutos:\n"
                    "  1. Crie uma conta gratuita em https://developer.adzuna.com/\n"
                    "  2. Copie o Application ID e o Application Key.\n"
                    "  3. Coloque no arquivo C:\\career-agent\\.env:\n"
                    "       ADZUNA_APP_ID=seu_app_id\n"
                    "       ADZUNA_APP_KEY=sua_app_key\n"
                    "  4. Reinicie o Claude Desktop.\n"
                    "A chave e uma credencial de desenvolvedor emitida para voce - "
                    "nao e senha de portal de vagas e nao da acesso a conta nenhuma."
                ),
            )

        params: dict[str, Any] = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "results_per_page": max(1, min(self._max_results, 50)),
            "content-type": "application/json",
        }
        if query.keywords:
            params["what"] = query.keywords
        if query.location:
            params["where"] = query.location

        url = f"{self.BASE}/{self._country}/search/1"

        try:
            payload = self._http.get_json(url, params=params)
        except JobSourceError as exc:
            message = str(exc)
            if "401" in message or "403" in message:
                message = (
                    "Adzuna recusou as credenciais (401/403). Confira "
                    "ADZUNA_APP_ID e ADZUNA_APP_KEY no .env."
                )
            logger.warning("adzuna indisponivel: %s", exc)
            return SourceResult(source=self.name, ok=False, message=message)

        jobs: list[Job] = []
        for entry in (payload or {}).get("results", []) or []:
            try:
                jobs.append(self._to_job(entry))
            except Exception:
                logger.exception("adzuna: entrada ignorada por erro de parse")

        total = (payload or {}).get("count")
        return SourceResult(
            source=self.name,
            jobs=jobs[: self._max_results],
            ok=True,
            message=(
                f"{len(jobs)} vaga(s) da Adzuna "
                f"(indice {self._country.upper()}"
                + (f", {total} no total" if total else "")
                + "). Fonte: Adzuna."
            ),
        )

    def _to_job(self, entry: dict[str, Any]) -> Job:
        title = str(entry.get("title") or "").strip()
        description = strip_html(str(entry.get("description") or ""))
        company = str((entry.get("company") or {}).get("display_name") or "").strip()
        location = str((entry.get("location") or {}).get("display_name") or "").strip()

        low = entry.get("salary_min")
        high = entry.get("salary_max")
        salary_text = ""
        if low or high:
            if low and high and low != high:
                salary_text = f"R$ {float(low):,.0f} a R$ {float(high):,.0f}".replace(",", ".")
            else:
                salary_text = f"R$ {float(low or high):,.0f}".replace(",", ".")

        category = str((entry.get("category") or {}).get("label") or "")

        return Job(
            id=f"adzuna-{entry.get('id', '')}",
            source=self.name,
            title=title or "(sem titulo)",
            company=company,
            url=str(entry.get("redirect_url") or "").strip(),
            description=description,
            tech_tags=[],  # categoria e area, nao tecnologia
            seniority=detect_seniority(title, description),
            work_mode=detect_work_mode(title, description, location),
            location=location,
            country="Brasil" if self._country == "br" else self._country.upper(),
            salary_text=salary_text,
            salary_min_brl=float(low) if low else None,
            salary_max_brl=float(high) if high else None,
            posted_at=str(entry.get("created") or ""),
            raw={"category": category},
        )


def jooble_source() -> UnavailableJobSource:
    """Jooble: declarado, porem NAO consumivel de forma legitima.

    A API do Jooble exige chave E fica atras do Cloudflare, que devolve 403
    ("Just a moment...") antes mesmo da autenticacao - verificado em
    `jooble.org` e `br.jooble.org`. Fazer a requisicao passar exigiria
    contornar a protecao anti-bot, exatamente o que a especificacao deste
    projeto proibe. Entao a fonte fica declarada e desligada, com o motivo.
    """
    return UnavailableJobSource(
        name="jooble",
        display_name="Jooble",
        reason=(
            "A API exige chave e o endpoint responde 403 do Cloudflare "
            "('Just a moment...') antes da autenticacao. Fazer passar exigiria "
            "contornar protecao anti-bot - proibido pela politica deste projeto. "
            "Se o Jooble liberar acesso programatico estavel, a fonte pode ser "
            "implementada sem alterar mais nada do sistema."
        ),
        manual_url="https://br.jooble.org/",
    )

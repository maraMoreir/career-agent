"""Cliente HTTP compartilhado: retry com backoff, rate limiting e cancelamento.

Existe para que toda fonte de vagas se comporte como boa cidada da rede sem
repetir a mesma logica. Regras:

  - Retry apenas para falhas TRANSITORIAS: timeout, erro de conexao, 429 e 5xx.
    Erros 4xx (exceto 429) sao definitivos - repetir e desperdicio e abuso.
  - Backoff exponencial com jitter, para nao sincronizar rajadas.
  - `Retry-After` do servidor SEMPRE vence o nosso calculo. Se o servidor diz
    quanto esperar, esperamos.
  - Rate limiting POR HOST: fontes diferentes nao competem entre si, e varias
    empresas no mesmo host respeitam o mesmo espacamento.
  - Teto de tentativas curto. Insistir contra um 429 repetido e exatamente o
    comportamento que este projeto se recusa a ter.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .errors import JobSourceError

logger = logging.getLogger(__name__)

#: Status que valem uma nova tentativa.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """Politica de repeticao. `max_attempts=1` desliga o retry."""

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.3

    def delay_for(self, attempt: int) -> float:
        """Backoff exponencial com jitter, limitado por `max_delay`."""
        raw = min(self.base_delay * (2 ** max(0, attempt - 1)), self.max_delay)
        return raw * (1 + random.uniform(0, self.jitter))


class HostRateLimiter:
    """Garante um intervalo minimo entre requisicoes ao mesmo host."""

    def __init__(self, min_interval: float = 0.0) -> None:
        self._min_interval = max(0.0, min_interval)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        if self._min_interval <= 0:
            return
        host = (urlparse(url).netloc or "").lower()
        with self._lock:
            elapsed = time.monotonic() - self._last.get(host, 0.0)
            sleep_for = self._min_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last[host] = time.monotonic()


@dataclass
class HttpClient:
    """Cliente JSON com retry, rate limiting e User-Agent identificado."""

    user_agent: str = "career-agent/1.0 (personal job search)"
    timeout: float = 15.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    limiter: HostRateLimiter = field(default_factory=HostRateLimiter)

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return self._request("GET", url, params=params, headers=headers)

    def post_json(
        self,
        url: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return self._request("POST", url, json=payload, headers=headers)

    # -- interno -----------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise JobSourceError(
                "httpx nao instalado. Rode scripts/install.ps1."
            ) from exc

        merged_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        merged_headers.update(kwargs.pop("headers", None) or {})

        last_error: str = "erro desconhecido"

        for attempt in range(1, max(1, self.retry.max_attempts) + 1):
            self.limiter.wait(url)
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    response = client.request(
                        method, url, headers=merged_headers, **kwargs
                    )

                if response.status_code in _RETRYABLE_STATUS:
                    last_error = f"HTTP {response.status_code}"
                    delay = self._delay_from_response(response, attempt)
                    if attempt >= self.retry.max_attempts:
                        break
                    logger.warning(
                        "%s %s -> %s; nova tentativa em %.1fs (%d/%d)",
                        method, url, response.status_code, delay,
                        attempt, self.retry.max_attempts,
                    )
                    time.sleep(delay)
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as exc:
                # 4xx definitivo: nao insistir.
                raise JobSourceError(
                    f"{method} {url} falhou com HTTP {exc.response.status_code}."
                ) from exc

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = type(exc).__name__
                if attempt >= self.retry.max_attempts:
                    break
                delay = self.retry.delay_for(attempt)
                logger.warning(
                    "%s %s -> %s; nova tentativa em %.1fs (%d/%d)",
                    method, url, last_error, delay, attempt, self.retry.max_attempts,
                )
                time.sleep(delay)

            except ValueError as exc:  # JSON invalido
                raise JobSourceError(f"{url} devolveu conteudo nao-JSON.") from exc

        raise JobSourceError(
            f"{method} {url} falhou apos {self.retry.max_attempts} tentativa(s): "
            f"{last_error}."
        )

    def _delay_from_response(self, response: Any, attempt: int) -> float:
        """`Retry-After` do servidor tem prioridade sobre o nosso backoff."""
        header = response.headers.get("Retry-After")
        if header:
            try:
                return max(0.0, min(float(header), 60.0))
            except ValueError:
                pass
        return self.retry.delay_for(attempt)


def build_http_client(settings: Any) -> HttpClient:
    """Cria o cliente a partir do `Settings` da aplicacao."""
    return HttpClient(
        user_agent=settings.user_agent,
        timeout=settings.http_timeout,
        retry=RetryPolicy(max_attempts=getattr(settings, "http_max_attempts", 3)),
        limiter=HostRateLimiter(settings.min_interval),
    )

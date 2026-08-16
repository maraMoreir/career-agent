"""Normalizacao de texto usada por scoring e deduplicacao.

Portugues + ingles, com acentos, aliases de stack e ruido de URL.
Isolado aqui para ser testavel sem tocar em I/O.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlparse

# Aliases de tecnologia -> forma canonica.
# Chave e valor ja normalizados (minusculo, sem acento).
TECH_ALIASES: dict[str, str] = {
    "c sharp": "c#",
    "csharp": "c#",
    "c-sharp": "c#",
    "dotnet": ".net",
    "dot net": ".net",
    "net": ".net",
    ".net core": ".net",
    ".net 6": ".net",
    ".net 7": ".net",
    ".net 8": ".net",
    ".net 9": ".net",
    ".net framework": ".net",
    "netcore": ".net",
    "asp net core": "asp.net core",
    "aspnet core": "asp.net core",
    "asp.net": "asp.net core",
    "aspnet": "asp.net core",
    "ef core": "entity framework core",
    "efcore": "entity framework core",
    "entity framework": "entity framework core",
    "ts": "typescript",
    "reactjs": "react",
    "react js": "react",
    "react.js": "react",
    "postgres": "postgresql",
    "postgre": "postgresql",
    "psql": "postgresql",
    "sqlserver": "sql server",
    "ms sql": "sql server",
    "mssql": "sql server",
    "t-sql": "sql server",
    "tsql": "sql server",
    "hana": "sap hana",
    "rabbit mq": "rabbitmq",
    "k8s": "kubernetes",
    "gitlab ci": "gitlab ci/cd",
    "gitlab-ci": "gitlab ci/cd",
    "ci/cd": "gitlab ci/cd",
    "json web token": "jwt",
    "rest": "apis rest",
    "restful": "apis rest",
    "rest api": "apis rest",
    "api rest": "apis rest",
    "web api": "apis rest",
    "solid principles": "solid",
    "ddd": "ddd",
    "domain driven design": "ddd",
    "domain-driven design": "ddd",
    "clean arch": "clean architecture",
    "arquitetura limpa": "clean architecture",
    "hexagonal": "hexagonal architecture",
    "arquitetura hexagonal": "hexagonal architecture",
    "microservices": "microsserviços",
    "microservicos": "microsserviços",
    "micro servicos": "microsserviços",
    "microsservicos": "microsserviços",
    "design pattern": "design patterns",
    "padroes de projeto": "design patterns",
    "sap b1": "sap business one",
    "business one": "sap business one",
    "di api": "sap di api",
    "ui api": "sap ui api",
    "nfe": "nf-e",
    "nfse": "nfs-e",
    "cte": "ct-e",
    "mdfe": "mdf-e",
    "dfe": "df-e",
    "distributed systems": "sistemas distribuídos",
    "sistemas distribuidos": "sistemas distribuídos",
    "monolith": "monolito",
}

_LEGAL_SUFFIXES = (
    "ltda",
    "ltda.",
    "s.a.",
    "s/a",
    "sa",
    "me",
    "epp",
    "eireli",
    "inc",
    "inc.",
    "llc",
    "corp",
    "corp.",
    "gmbh",
    "bv",
    "b.v.",
    "co",
    "co.",
    "company",
    "tecnologia",
    "technologies",
    "technology",
    "solutions",
    "solucoes",
    "sistemas",
    "group",
    "grupo",
    "holding",
)

# Tokens de senioridade/ruido removidos ao comparar titulos de vaga.
_TITLE_NOISE = (
    "junior",
    "jr",
    "pleno",
    "pl",
    "senior",
    "sr",
    "especialista",
    "specialist",
    "estagio",
    "estagiario",
    "trainee",
    "intern",
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "remoto",
    "remote",
    "hibrido",
    "hybrid",
    "presencial",
    "onsite",
    "vaga",
    "efetivo",
    "clt",
    "pj",
    "afirmativa",
    "pcd",
    "m/f",
    "h/f",
)

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "ref",
    "refid",
    "trk",
    "trackingid",
    "src",
    "source",
    "position",
    "pagenum",
    "origin",
    "eblink",
    "lipi",
}

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9#+./\- ]")


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_text(value: str) -> str:
    """Minusculo, sem acento, espacos colapsados."""
    if not value:
        return ""
    return _WS.sub(" ", strip_accents(value).lower()).strip()


def normalize_term(value: str) -> str:
    """Normaliza um termo tecnico e resolve aliases para a forma canonica."""
    base = normalize_text(value)
    base = _NON_ALNUM.sub(" ", base)
    base = _WS.sub(" ", base).strip(" .-")
    if not base:
        return ""
    return TECH_ALIASES.get(base, base)


def normalize_company(value: str) -> str:
    """Nome de empresa comparavel: sem sufixo juridico, sem pontuacao.

    Os pontos sao REMOVIDOS antes da tokenizacao (nao trocados por espaco),
    senao "S.A." viraria os tokens "s" e "a" e escaparia da lista de sufixos
    juridicos - deixando "Empresa X S.A." diferente de "Empresa X Ltda".
    """
    base = normalize_text(value)
    base = base.replace(".", "")
    base = re.sub(r"[^a-z0-9 ]", " ", base)
    tokens = [t for t in base.split() if t and t not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def normalize_title(value: str) -> str:
    """Titulo de vaga comparavel: sem senioridade, modalidade e ruido."""
    base = normalize_text(value)
    base = re.sub(r"[^a-z0-9#+. ]", " ", base)
    tokens = [t for t in base.split() if t and t not in _TITLE_NOISE]
    return " ".join(tokens)


def normalize_url(value: str) -> str:
    """URL canonica para deteccao de duplicidade.

    Remove esquema, `www.`, parametros de tracking, barra final e fragmento.
    Preserva o identificador real da vaga em portais conhecidos
    (ex.: `currentJobId` do LinkedIn).
    """
    if not value or not value.strip():
        return ""

    raw = value.strip()
    if "://" not in raw:
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
    except ValueError:
        return normalize_text(value)

    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = (parsed.path or "").rstrip("/")

    params = parse_qs(parsed.query, keep_blank_values=False)
    kept = {
        key: values[0]
        for key, values in sorted(params.items())
        if key.lower() not in _TRACKING_PARAMS
    }

    # LinkedIn: /jobs/view/<id> e /jobs/search?currentJobId=<id> sao a mesma vaga.
    if "linkedin.com" in host:
        job_id = kept.pop("currentJobId", None) or kept.pop("currentjobid", None)
        match = re.search(r"/jobs/view/(\d+)", path)
        if match:
            job_id = match.group(1)
        if job_id:
            return f"linkedin.com/jobs/view/{job_id}"

    query = "&".join(f"{k}={v}" for k, v in kept.items())
    canonical = f"{host}{path}"
    return f"{canonical}?{query}" if query else canonical


def similarity(left: str, right: str) -> float:
    """Similaridade 0..1 entre duas strings ja normalizadas."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def extract_terms(text: str, vocabulary: set[str]) -> set[str]:
    """Encontra quais termos do `vocabulary` aparecem em `text`.

    Usa correspondencia por limite de palavra para evitar falsos positivos
    (ex.: "net" dentro de "network"). Considera tambem os aliases.
    """
    if not text or not vocabulary:
        return set()

    haystack = " " + normalize_text(text).replace("/", " / ") + " "
    found: set[str] = set()

    # Mapa reverso: qualquer alias que aponte para um termo do vocabulario.
    candidates: dict[str, str] = {term: term for term in vocabulary}
    for alias, canonical in TECH_ALIASES.items():
        if canonical in vocabulary:
            candidates[alias] = canonical

    for needle, canonical in candidates.items():
        if not needle:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        if re.search(pattern, haystack):
            found.add(canonical)

    return found

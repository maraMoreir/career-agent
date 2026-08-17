"""Configuracao do score: pesos e faixas de classificacao.

Os pesos deixam de estar presos as classes. Voce edita
`data/config/scoring.json` e o ranking muda - sem tocar em codigo.

Se o arquivo nao existir, os defaults abaixo valem. Se existir e estiver
quebrado, o sistema loga e usa os defaults: uma configuracao malformada nao
pode derrubar a busca de vagas.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..models import Recommendation

logger = logging.getLogger(__name__)

#: Pesos padrao, somando 100. Cobrem os fatores pedidos na especificacao:
#: tecnologias, senioridade, localizacao, modalidade, salario, experiencia
#: com .NET, com SAP, fiscal, arquitetura e experiencia backend.
DEFAULT_WEIGHTS: dict[str, float] = {
    "stack": 20.0,        # tecnologias exigidas x perfil
    "dotnet": 14.0,       # profundidade especifica em .NET/C#
    "seniority": 14.0,    # nivel da vaga x nivel desejado
    "backend": 8.0,       # peso de backend na vaga
    "architecture": 8.0,  # Clean Arch, SOLID, DDD, hexagonal, distribuidos
    "salary": 10.0,       # faixa x minimo/alvo
    "location": 7.0,      # compatibilidade geografica
    "work_mode": 7.0,     # remoto > hibrido > presencial
    "sap": 5.0,           # integracoes SAP / Business One / HANA
    "fiscal": 4.0,        # NF-e, CT-e, MDF-e, GNRE, NFS-e, SEFAZ
    "company": 3.0,       # listas de preferencia/bloqueio e sinais
}

#: Faixas de classificacao (limite inferior inclusivo), conforme a spec.
DEFAULT_BANDS: list[tuple[float, str]] = [
    (90.0, "Excelente"),
    (75.0, "Muito boa"),
    (60.0, "Boa"),
    (40.0, "Baixa"),
    (0.0, "Nao prioritaria"),
]

#: Faixa a partir da qual a vaga vale a pena preparar candidatura.
DEFAULT_MINIMUM_SCORE = 75.0


@dataclass(frozen=True)
class ScoringConfig:
    """Pesos e faixas, normalizados para a escala 0-100."""

    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    bands: list[tuple[float, str]] = field(default_factory=lambda: list(DEFAULT_BANDS))
    minimum_score: float = DEFAULT_MINIMUM_SCORE

    def weight_for(self, key: str, fallback: float = 0.0) -> float:
        return float(self.weights.get(key, fallback))

    def total_weight(self) -> float:
        return sum(self.weights.values())

    def classify(self, total: float) -> str:
        for threshold, label in sorted(self.bands, key=lambda b: b[0], reverse=True):
            if total >= threshold:
                return label
        return self.bands[-1][1] if self.bands else "Nao prioritaria"

    def recommendation(self, total: float) -> Recommendation:
        """Mapeia a faixa para o enum interno, preservando compatibilidade."""
        label = self.classify(total)
        return {
            "Excelente": Recommendation.HIGH_PRIORITY,
            "Muito boa": Recommendation.PRIORITY,
            "Boa": Recommendation.ANALYZE,
        }.get(label, Recommendation.DISCARD)

    def as_text(self) -> str:
        lines = ["PESOS (total {:g}):".format(self.total_weight())]
        for key, value in sorted(self.weights.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {key:14s} {value:5.1f}")
        lines.append("")
        lines.append("FAIXAS:")
        ordered = sorted(self.bands, key=lambda b: b[0], reverse=True)
        for index, (threshold, label) in enumerate(ordered):
            upper = 100.0 if index == 0 else ordered[index - 1][0] - 0.1
            lines.append(f"  {threshold:5.0f} - {upper:5.1f}  {label}")
        lines.append("")
        lines.append(f"Score minimo para recomendar: {self.minimum_score:g}")
        return "\n".join(lines)


def default_config_path(data_root: Path) -> Path:
    return Path(data_root) / "config" / "scoring.json"


def load_scoring_config(path: Path | None) -> ScoringConfig:
    """Le a configuracao do disco, caindo nos defaults em qualquer problema."""
    if path is None or not Path(path).is_file():
        return ScoringConfig()

    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("scoring.json invalido (%s); usando os pesos padrao.", exc)
        return ScoringConfig()

    weights = dict(DEFAULT_WEIGHTS)
    raw_weights = document.get("weights")
    if isinstance(raw_weights, dict):
        for key, value in raw_weights.items():
            try:
                weights[str(key)] = float(value)
            except (TypeError, ValueError):
                logger.warning("Peso invalido para '%s'; mantendo o padrao.", key)

    bands = list(DEFAULT_BANDS)
    raw_bands = document.get("bands")
    if isinstance(raw_bands, list) and raw_bands:
        parsed: list[tuple[float, str]] = []
        for item in raw_bands:
            try:
                parsed.append((float(item["min"]), str(item["label"])))
            except (TypeError, ValueError, KeyError):
                logger.warning("Faixa invalida em scoring.json: %r", item)
        if parsed:
            bands = parsed

    try:
        minimum = float(document.get("minimum_score", DEFAULT_MINIMUM_SCORE))
    except (TypeError, ValueError):
        minimum = DEFAULT_MINIMUM_SCORE

    config = ScoringConfig(weights=weights, bands=bands, minimum_score=minimum)
    total = config.total_weight()
    if abs(total - 100.0) > 0.01:
        logger.warning(
            "Os pesos somam %.2f, nao 100. O score sera normalizado para 0-100.",
            total,
        )
    return config


def write_default_config(path: Path) -> Path:
    """Cria o arquivo de configuracao comentado, se ainda nao existir."""
    path = Path(path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "_comment": (
            "Pesos e faixas do score. Os pesos devem somar 100 (se nao somarem, "
            "o score e normalizado). Edite e reinicie o Claude Desktop."
        ),
        "weights": DEFAULT_WEIGHTS,
        "bands": [{"min": m, "label": l} for m, l in DEFAULT_BANDS],
        "minimum_score": DEFAULT_MINIMUM_SCORE,
    }
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path

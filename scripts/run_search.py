"""Executa o pipeline de busca. Ponto de entrada do agendamento.

Roda uma vez e sai - sem processo residente. O agendamento fica a cargo do
Agendador de Tarefas do Windows (ver `scripts/schedule.ps1`), que ja resolve
retomada apos reboot, execucao com a maquina bloqueada e log de falhas.
Reimplementar isso num daemon proprio seria trabalho duplicado e pior.

Uso:
    python scripts/run_search.py
    python scripts/run_search.py --keywords "backend .net" --min-score 80
    python scripts/run_search.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from career_core.config import get_settings  # noqa: E402
from career_core.errors import CareerAgentError  # noqa: E402
from career_core.job_sources.base import JobQuery  # noqa: E402
from career_core.logging_setup import configure_logging  # noqa: E402
from career_core.services import CareerServices  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline de busca de vagas.")
    parser.add_argument("--keywords", default="", help="termos de busca")
    parser.add_argument("--location", default="", help="cidade/estado/pais")
    parser.add_argument("--sources", default="", help="fontes, separadas por virgula")
    parser.add_argument(
        "--min-score", type=float, default=None, help="score minimo para 'relevante'"
    )
    parser.add_argument("--json", action="store_true", help="saida em JSON")
    parser.add_argument("--quiet", action="store_true", help="so o resumo")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    logger = configure_logging("search-runner", settings.log_dir, settings.log_level)

    keywords = args.keywords or " ".join(
        w for w in ("backend", ".net", "c#") if w
    )

    try:
        services = CareerServices(settings)
        profile = services.profile()
    except CareerAgentError as exc:
        logger.error("Perfil indisponivel: %s", exc)
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    query = JobQuery(
        keywords=keywords,
        location=args.location,
        limit=settings.max_results,
    )
    sources = [s.strip() for s in args.sources.split(",") if s.strip()] or None

    result = services.pipeline.run(
        profile, query, sources, minimum_score=args.min_score
    )
    execution = result.execution

    if args.json:
        print(
            json.dumps(
                {
                    "execution_id": execution.id,
                    "status": execution.status,
                    "jobs_found": execution.jobs_found,
                    "jobs_new": execution.jobs_new,
                    "jobs_duplicated": execution.jobs_duplicated,
                    "jobs_above_threshold": execution.jobs_above_threshold,
                    "best_score": execution.best_score,
                    "errors": execution.errors,
                    "relevant": [
                        {
                            "id": job.id,
                            "title": job.title,
                            "company": job.company,
                            "score": job.match_score,
                            "url": job.url,
                            "work_model": job.work_model.value,
                            "location": job.location,
                        }
                        for job in result.relevant
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if execution.status != "failed" else 1

    print(result.summary())

    # Notificacao: vagas NOVAS e relevantes sao o unico motivo de chamar a
    # atencao da usuaria. Vaga ja conhecida nao gera ruido.
    new_relevant = [j for j in result.new_jobs if j in result.relevant]
    if new_relevant and not args.quiet:
        print()
        print(f"*** {len(new_relevant)} VAGA(S) NOVA(S) RELEVANTE(S) ***")
        for job in new_relevant:
            print(f"  {job.match_score:5.1f}  {job.title[:56]}")
            print(f"         {job.company} | {job.work_model.value} | {job.location or 'n/d'}")
            print(f"         {job.url}")
    elif not args.quiet:
        print()
        print("Nenhuma vaga nova relevante nesta execucao.")

    return 0 if execution.status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())

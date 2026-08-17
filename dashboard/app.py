"""Dashboard local do Career Agent.

App FastAPI que le o catalogo e o historico de candidaturas e mostra tudo
numa pagina. SOMENTE LEITURA e SOMENTE em 127.0.0.1 - nao aceita conexao de
fora da maquina e nao altera dado nenhum. As acoes que mudam estado
continuam no Claude Desktop, onde existe a aprovacao humana.

Rode com: .\\scripts\\start-dashboard.ps1
"""

from __future__ import annotations

import html
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

from career_core.catalog.models import JobStatus  # noqa: E402
from career_core.config import get_settings  # noqa: E402
from career_core.errors import CareerAgentError  # noqa: E402
from career_core.models import ApplicationStatus  # noqa: E402
from career_core.services import CareerServices  # noqa: E402

SETTINGS = get_settings()
services = CareerServices(SETTINGS)

app = FastAPI(title="Career Agent", docs_url=None, redoc_url=None)


def e(value: object) -> str:
    return html.escape(str(value or ""))


STYLE = """
:root {
  --paper:#F5F7F9; --surface:#FFF; --surface-2:#EDF0F3; --ink:#171C22;
  --ink-2:#454F5A; --ink-3:#6B7783; --rule:#D6DCE3;
  --accent:#0C6157; --accent-bg:#E2EFEC; --warn:#7A5100; --warn-bg:#F6EEDC;
  --deny:#A32A20; --deny-bg:#F7E7E5;
  --mono:"Cascadia Mono",Consolas,ui-monospace,monospace;
  --body:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
}
@media (prefers-color-scheme: dark) { :root {
  --paper:#0E1216; --surface:#161C22; --surface-2:#1E262E; --ink:#E6EBF0;
  --ink-2:#AFBAC5; --ink-3:#7E8C99; --rule:#2C363F;
  --accent:#58C4B2; --accent-bg:#122B29; --warn:#E0AC55; --warn-bg:#2A2116;
  --deny:#F08A7E; --deny-bg:#2C1A18;
} }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--paper); color:var(--ink); font-family:var(--body);
       font-size:15px; line-height:1.6; padding:0 24px 80px; }
.wrap { max-width:1180px; margin:0 auto; }
header { padding:40px 0 8px; }
h1 { font-size:30px; font-weight:680; letter-spacing:-.02em; }
.sub { color:var(--ink-3); font-family:var(--mono); font-size:12px;
       letter-spacing:.06em; margin-top:6px; }
h2 { font-size:19px; font-weight:650; margin:44px 0 4px;
     padding-bottom:10px; border-bottom:1px solid var(--rule); }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
         gap:1px; background:var(--rule); border:1px solid var(--rule);
         border-radius:5px; overflow:hidden; margin-top:24px; }
.card { background:var(--surface); padding:16px 18px; }
.card .label { font-family:var(--mono); font-size:10px; letter-spacing:.13em;
               text-transform:uppercase; color:var(--ink-3); }
.card .value { font-family:var(--mono); font-size:26px; font-variant-numeric:tabular-nums;
               margin-top:4px; }
.scroller { overflow-x:auto; margin-top:18px; border:1px solid var(--rule);
            border-radius:5px; background:var(--surface); }
table { width:100%; border-collapse:collapse; font-size:14px; }
th { text-align:left; font-family:var(--mono); font-size:10px; font-weight:600;
     letter-spacing:.12em; text-transform:uppercase; color:var(--ink-3);
     padding:11px 14px; border-bottom:1px solid var(--rule); white-space:nowrap; }
td { padding:11px 14px; border-bottom:1px solid var(--rule); color:var(--ink-2);
     vertical-align:top; }
tr:last-child td { border-bottom:none; }
td.score { font-family:var(--mono); font-variant-numeric:tabular-nums;
           text-align:right; white-space:nowrap; color:var(--ink); }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
.pill { display:inline-block; font-family:var(--mono); font-size:10px;
        letter-spacing:.08em; text-transform:uppercase; padding:3px 8px;
        border-radius:3px; background:var(--surface-2); color:var(--ink-2);
        white-space:nowrap; }
.pill.good { background:var(--accent-bg); color:var(--accent); }
.pill.warn { background:var(--warn-bg); color:var(--warn); }
.pill.bad  { background:var(--deny-bg);  color:var(--deny); }
.empty { padding:22px; color:var(--ink-3); font-size:14px; }
.note { color:var(--ink-3); font-size:13px; margin-top:8px; }
footer { margin-top:60px; padding-top:18px; border-top:1px solid var(--rule);
         font-family:var(--mono); font-size:11px; color:var(--ink-3); }
"""

_GOOD = {"Interested", "Applied", "Interview", "approved", "applied", "interview", "offer"}
_BAD = {"Rejected", "Discarded", "rejected", "withdrawn"}


def pill(value: str) -> str:
    css = "good" if value in _GOOD else "bad" if value in _BAD else "warn"
    return f'<span class="pill {css}">{e(value)}</span>'


def score_pill(score: float) -> str:
    css = "good" if score >= 75 else "warn" if score >= 60 else "bad"
    return f'<span class="pill {css}">{score:g}</span>'


def table(headers: list[str], rows: list[str], empty: str) -> str:
    if not rows:
        return f'<div class="scroller"><div class="empty">{e(empty)}</div></div>'
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    return (
        f'<div class="scroller"><table><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    catalog = services.catalog
    counts = catalog.count_by_status()
    total_jobs = catalog.count()

    applications = services.applications.all()
    app_counts = Counter(a.status.value for a in applications)

    best = catalog.list_jobs(min_score=60, limit=25)
    best = [j for j in best if j.status is not JobStatus.DISCARDED]

    recent = catalog.list_jobs(limit=15, order_by_score=False)
    executions = catalog.list_executions(limit=10)
    companies = catalog.list_companies(limit=15)
    technologies = catalog.top_technologies(15)

    parts: list[str] = [
        f"<style>{STYLE}</style>",
        '<div class="wrap">',
        "<header><h1>Career Agent</h1>",
        f'<div class="sub">{e(total_jobs)} vagas no catalogo &middot; '
        f"{len(applications)} candidatura(s) &middot; somente leitura</div></header>",
    ]

    # -- indicadores -------------------------------------------------------
    parts.append('<div class="cards">')
    for label, value in (
        ("Vagas", total_jobs),
        ("Analisadas", counts.get("Analyzed", 0)),
        ("Interessantes", counts.get("Interested", 0)),
        ("Candidaturas", len(applications)),
        ("Entrevistas", app_counts.get("interview", 0) + counts.get("Interview", 0)),
        ("Aguardando voce", app_counts.get("pending_approval", 0)),
    ):
        parts.append(
            f'<div class="card"><div class="label">{e(label)}</div>'
            f'<div class="value">{e(value)}</div></div>'
        )
    parts.append("</div>")

    # -- melhores matches --------------------------------------------------
    parts.append("<h2>Melhores matches</h2>")
    parts.append(
        table(
            ["Score", "Vaga", "Empresa", "Modalidade", "Local", "Status", "Gaps"],
            [
                "<tr>"
                f'<td class="score">{score_pill(j.match_score)}</td>'
                f'<td><a href="{e(j.url)}" target="_blank" rel="noopener">{e(j.title)}</a></td>'
                f"<td>{e(j.company)}</td>"
                f"<td>{e(j.work_model.value)}</td>"
                f"<td>{e(j.location)}</td>"
                f"<td>{pill(j.status.value)}</td>"
                f'<td style="font-size:12.5px">{e(", ".join(j.gaps[:3]))}</td>'
                "</tr>"
                for j in best
            ],
            "Nenhuma vaga com score >= 60. Rode a busca no Claude Desktop "
            "(`run_job_search`) ou pelo agendador.",
        )
    )

    # -- candidaturas ------------------------------------------------------
    parts.append("<h2>Candidaturas</h2>")
    parts.append(
        table(
            ["Status", "Empresa", "Cargo", "Score", "Criada em"],
            [
                "<tr>"
                f"<td>{pill(a.status.value)}</td>"
                f"<td>{e(a.company)}</td>"
                f'<td><a href="{e(a.job_url)}" target="_blank" rel="noopener">{e(a.role)}</a></td>'
                f'<td class="score">{a.score:g}</td>'
                f"<td>{e(a.created_at[:10])}</td>"
                "</tr>"
                for a in applications
            ],
            "Nenhuma candidatura registrada ainda.",
        )
    )

    # -- vagas recentes ----------------------------------------------------
    parts.append("<h2>Coletadas recentemente</h2>")
    parts.append(
        table(
            ["Coletada", "Score", "Vaga", "Empresa", "Fonte"],
            [
                "<tr>"
                f"<td>{e(j.collected_at[:16].replace('T', ' '))}</td>"
                f'<td class="score">{j.match_score:g}</td>'
                f'<td><a href="{e(j.url)}" target="_blank" rel="noopener">{e(j.title)}</a></td>'
                f"<td>{e(j.company)}</td>"
                f"<td>{e(j.source)}</td>"
                "</tr>"
                for j in recent
            ],
            "Catalogo vazio.",
        )
    )

    # -- tecnologias -------------------------------------------------------
    parts.append("<h2>Tecnologias mais exigidas</h2>")
    parts.append(
        table(
            ["Tecnologia", "Vagas", "Voce tem?"],
            [
                "<tr>"
                f"<td>{e(name)}</td>"
                f'<td class="score">{required}</td>'
                f'<td>{pill("sim") if matched else pill("GAP")}</td>'
                "</tr>"
                for name, required, matched in technologies
            ],
            "Sem dados ainda.",
        )
    )
    parts.append(
        '<p class="note">Tecnologias marcadas como GAP aparecem nas vagas mas '
        "nao constam no seu perfil - sao candidatas naturais para o proximo estudo.</p>"
    )

    # -- empresas ----------------------------------------------------------
    parts.append("<h2>Empresas</h2>")
    parts.append(
        table(
            ["Vagas", "Empresa", "Vista pela primeira vez"],
            [
                "<tr>"
                f'<td class="score">{c.jobs_count}</td>'
                f"<td>{e(c.name)}</td>"
                f"<td>{e(c.first_seen_at[:10])}</td>"
                "</tr>"
                for c in companies
            ],
            "Nenhuma empresa no catalogo.",
        )
    )

    # -- historico de buscas -----------------------------------------------
    parts.append("<h2>Historico de buscas</h2>")
    parts.append(
        table(
            ["Quando", "Status", "Termos", "Fontes", "Coletadas", "Novas", "Relevantes", "Melhor"],
            [
                "<tr>"
                f"<td>{e(x.started_at[:16].replace('T', ' '))}</td>"
                f"<td>{pill(x.status)}</td>"
                f"<td>{e(x.query or '(todos)')}</td>"
                f"<td>{e(', '.join(x.sources))}</td>"
                f'<td class="score">{x.jobs_found}</td>'
                f'<td class="score">{x.jobs_new}</td>'
                f'<td class="score">{x.jobs_above_threshold}</td>'
                f'<td class="score">{x.best_score:g}</td>'
                "</tr>"
                for x in executions
            ],
            "Nenhuma busca executada. Rode `run_job_search` no Claude Desktop.",
        )
    )

    parts.append(
        "<footer>Somente leitura &middot; 127.0.0.1 &middot; "
        "acoes que mudam estado ficam no Claude Desktop, onde ha aprovacao humana."
        "</footer></div>"
    )
    return HTMLResponse("".join(parts))


@app.get("/api/stats")
def stats() -> JSONResponse:
    """Mesmos numeros da pagina, em JSON."""
    try:
        catalog = services.catalog
        applications = services.applications.all()
        return JSONResponse(
            {
                "jobs_total": catalog.count(),
                "jobs_by_status": catalog.count_by_status(),
                "applications_total": len(applications),
                "applications_by_status": dict(
                    Counter(a.status.value for a in applications)
                ),
                "top_technologies": [
                    {"name": n, "required": r, "matched": bool(m)}
                    for n, r, m in catalog.top_technologies(20)
                ],
                "last_executions": [
                    x.model_dump(mode="json") for x in catalog.list_executions(5)
                ],
            }
        )
    except CareerAgentError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/jobs")
def jobs(min_score: float = 0.0, limit: int = 50) -> JSONResponse:
    return JSONResponse(
        [
            job.model_dump(mode="json")
            for job in services.catalog.list_jobs(
                min_score=min_score or None, limit=limit
            )
        ]
    )


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "data_root": str(SETTINGS.data_root)})

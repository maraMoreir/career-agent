"""Validacao funcional dos tres servidores MCP.

Importa cada servidor, lista as ferramentas registradas e executa de verdade
um fluxo ponta a ponta atraves da camada MCP (nao so do dominio):

    perfil -> vaga -> score -> candidatura -> aprovacao -> historico

Usado por `scripts/test.ps1`. Sai com codigo != 0 se qualquer etapa falhar.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _isolate_data_root() -> Path:
    """Copia o perfil e os curriculos REAIS para uma raiz temporaria.

    Assim a validacao exercita os arquivos de verdade da usuaria, mas registra
    as candidaturas de teste num banco descartavel - o historico real nunca e
    poluido por uma execucao de `test.ps1`.

    Precisa rodar ANTES de importar os servidores, porque eles leem as
    configuracoes no momento do import.
    """
    real_root = Path(os.getenv("CAREER_DATA_ROOT") or (PROJECT_ROOT / "data"))
    sandbox = Path(tempfile.mkdtemp(prefix="career-agent-validate-"))

    for folder in ("profile", "resumes"):
        source = real_root / folder
        target = sandbox / folder
        target.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            for item in source.glob("*.md"):
                shutil.copy2(item, target / item.name)

    (sandbox / "applications").mkdir(parents=True, exist_ok=True)

    os.environ["CAREER_DATA_ROOT"] = str(sandbox)
    os.environ["CAREER_LOG_DIR"] = str(sandbox / "logs")
    os.environ["JOB_SEARCH_ENABLE_NETWORK"] = "false"
    os.environ["JOB_SEARCH_SOURCES"] = "mock"
    return sandbox


REAL_DATA_ROOT = Path(os.getenv("CAREER_DATA_ROOT") or (PROJECT_ROOT / "data"))
SANDBOX_ROOT = _isolate_data_root()

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  [OK]    {label}")
    else:
        print(f"  [FALHA] {label}" + (f" -> {detail}" if detail else ""))
        FAILURES.append(label)


def section(title: str) -> None:
    print()
    print(title)
    print("-" * 68)


def _load(module_name: str, relative_path: str):
    import importlib.util

    path = PROJECT_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"nao consegui carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


async def _tool_names(server) -> list[str]:
    return [tool.name for tool in await server.list_tools()]


def _extract_text(payload) -> str:
    """Extrai o texto de um retorno de ferramenta, cobrindo as formas do SDK.

    mcp 2.x devolve um objeto com `.content` (lista de blocos) e
    `.structured_content`; mcp 1.x devolve `(content, structured)` ou a lista
    de blocos direto.
    """
    if isinstance(payload, str):
        return payload

    # mcp 2.x: objeto de resultado
    content = getattr(payload, "content", None)
    if content is not None:
        return _extract_text(content)

    if isinstance(payload, tuple):
        return _extract_text(payload[0])

    if isinstance(payload, list):
        return "\n".join(_extract_text(block) for block in payload)

    text = getattr(payload, "text", None)
    return text if text is not None else str(payload)


async def _call(server, name: str, arguments: dict) -> str:
    return _extract_text(await server.call_tool(name, arguments))


async def main() -> int:
    from career_core.config import get_settings
    from career_core.mcp_compat import SDK_FLAVOR

    settings = get_settings()

    print("=" * 68)
    print("VALIDACAO DOS SERVIDORES MCP - Career Agent")
    print("=" * 68)
    print(f"SDK MCP.......: {SDK_FLAVOR}")
    print(f"Python........: {sys.version.split()[0]}")
    print(f"Perfil real...: {REAL_DATA_ROOT} (copiado)")
    print(f"Raiz de teste.: {settings.data_root}")
    print(f"Fontes........: {', '.join(settings.sources)} (rede={settings.enable_network})")
    print()
    print("O historico real NAO e tocado: as candidaturas de teste vao para um")
    print("banco temporario, descartado ao final.")

    # -- 1. Importacao ----------------------------------------------------
    section("1. IMPORTACAO DOS SERVIDORES")
    servers = {}
    for name, path in (
        ("career-agent", "mcp-career/server.py"),
        ("job-search", "mcp-job-search/server.py"),
        ("career-files", "mcp-career-files/server.py"),
    ):
        try:
            module = _load(f"srv_{name.replace('-', '_')}", path)
            servers[name] = module.mcp
            check(f"import {name} ({path})", True)
        except Exception as exc:
            check(f"import {name} ({path})", False, repr(exc))
            traceback.print_exc()

    if len(servers) != 3:
        print("\nImportacao falhou - abortando.")
        return 1

    # -- 2. Ferramentas registradas ---------------------------------------
    section("2. FERRAMENTAS REGISTRADAS")
    expected = {
        "career-agent": [
            "get_candidate_profile", "calculate_job_match", "analyze_job",
            "generate_application", "register_application", "list_applications",
            "get_application", "update_application_status",
            "check_duplicate_application", "get_safety_policy", "get_system_status",
        ],
        "job-search": ["search_jobs", "list_job_sources", "get_manual_search_guide"],
        "career-files": [
            "read_profile", "read_preferences", "list_resumes", "read_resume",
            "read_application_history", "list_data_files", "get_sandbox_info",
        ],
    }
    tools: dict[str, list[str]] = {}
    for name, server in servers.items():
        tools[name] = await _tool_names(server)
        print(f"  {name}: {len(tools[name])} ferramenta(s)")
        for tool_name in expected[name]:
            check(f"  {name}.{tool_name}", tool_name in tools[name])

    section("3. DESCRICOES DAS FERRAMENTAS")
    for name, server in servers.items():
        for tool in await server.list_tools():
            description = (tool.description or "").strip()
            check(
                f"  {name}.{tool.name} tem descricao util",
                len(description) >= 40,
                f"len={len(description)}",
            )

    # -- 4. Fluxo real ----------------------------------------------------
    career = servers["career-agent"]
    search = servers["job-search"]
    files = servers["career-files"]

    section("4. PERFIL")
    profile_text = await _call(career, "get_candidate_profile", {})
    check("le perfil", "PERFIL DA CANDIDATA" in profile_text)
    check("perfil traz a stack .NET", ".NET" in profile_text)
    check("perfil traz senioridade a evitar", "estagio" in profile_text.lower())
    check(
        "nao inventa anos de experiencia",
        "nao declarado" in profile_text.lower() or "years" not in profile_text.lower(),
    )

    files_profile = await _call(files, "read_profile", {})
    check("career-files le o perfil bruto", "Competencias" in files_profile)

    section("5. SANDBOX DE ARQUIVOS")
    sandbox_info = await _call(files, "get_sandbox_info", {})
    check("sandbox reporta a raiz correta", str(settings.data_root) in sandbox_info)
    escape = await _call(files, "read_resume", {"filename": "../../../Windows/win.ini"})
    check("recusa fuga da sandbox", "ERRO" in escape, escape[:120])
    resumes = await _call(files, "list_resumes", {})
    check("lista curriculos", "curriculo-principal.md" in resumes)

    section("6. BUSCA DE VAGAS")
    search_text = await _call(
        search, "search_jobs", {"keywords": "backend .net", "min_score": 80, "limit": 10}
    )
    check("busca retorna vagas", "SCORE" in search_text, search_text[:200])
    check("busca aplica o corte de score", "score >= 80" in search_text)

    sources_text = await _call(search, "list_job_sources", {})
    check("lista fontes", "mock" in sources_text)
    check("declara LinkedIn indisponivel", "linkedin" in sources_text.lower())

    manual = await _call(search, "get_manual_search_guide", {"portal": "linkedin"})
    check("LinkedIn cai em modo manual", "MODO MANUAL" in manual)
    check("LinkedIn nao e automatizado", "nao automatiza" in manual.lower())

    section("7. SCORE")
    job = {
        "title": "Desenvolvedor(a) Backend .NET Senior",
        "company": "Validacao Tech",
        "url": "https://exemplo-validacao.dev/vagas/999",
        "location": "Brasil",
        "work_mode": "remoto",
        "seniority": "senior",
        "salary_text": "R$ 16.000 a R$ 18.000",
        "description": (
            "Requisitos:\n- C# e .NET (ASP.NET Core)\n- Entity Framework Core\n"
            "- PostgreSQL\n- RabbitMQ\n- Docker\n- Clean Architecture, SOLID e DDD\n"
            "- APIs REST\n- JWT\nDiferenciais:\n- Azure\nOferecemos CLT e plano de saude."
        ),
    }
    score_text = await _call(career, "calculate_job_match", job)
    check("score calculado", "Score:" in score_text)
    for label in ("Stack tecnica:", "Senioridade:", "Salario:", "Modalidade:",
                  "Localizacao:", "Experiencia:", "Empresa:", "Recomendacao:"):
        check(f"score detalha '{label}'", label in score_text)
    check("aponta Azure como gap", "azure" in score_text.lower())

    junior = {**job, "title": "Desenvolvedor .NET Junior", "seniority": "junior"}
    junior_text = await _call(career, "calculate_job_match", junior)
    check("vaga junior e descartada", "DESCARTAR" in junior_text)

    section("8. ANALISE E GERACAO DE CANDIDATURA")
    analysis = await _call(career, "analyze_job", job)
    check("analise combina score e historico", "ANALISE DA VAGA" in analysis and "DUPLICIDADE" in analysis)

    package = await _call(career, "generate_application", job)
    for marker in ("PACOTE DE CANDIDATURA", "Curriculo recomendado",
                   "Mensagem para o recrutador", "Respostas sugeridas",
                   "AGUARDANDO APROVACAO", "AUDITORIA FACTUAL"):
        check(f"pacote traz '{marker}'", marker in package)
    check("pacote nao foi registrado ainda", "NAO registrado ainda" in package)
    check("auditoria factual passou", "Auditoria factual: OK" in package)

    section("9. REGISTRO")
    registered = await _call(career, "register_application", job)
    check("candidatura registrada", "CANDIDATURA REGISTRADA" in registered, registered[:200])
    check("status inicial e pending_approval", "pending_approval" in registered)

    import re

    match = re.search(r"\bapp-[0-9a-f]{10}\b", registered)
    application_id = match.group(0) if match else ""
    check("id devolvido", bool(application_id), registered[:200])

    section("10. DUPLICIDADE")
    duplicate = await _call(
        career, "check_duplicate_application",
        {"company": job["company"], "role": job["title"], "job_url": job["url"]},
    )
    check("duplicidade detectada", "duplicate" in duplicate)
    check("aponta a candidatura conflitante", application_id in duplicate)

    re_register = await _call(career, "register_application", job)
    check("registro duplicado e recusado", "RECUSADO" in re_register)

    tracking_url = await _call(
        career, "check_duplicate_application",
        {"company": "Outro Nome", "role": "Outro Cargo",
         "job_url": job["url"] + "?utm_source=newsletter"},
    )
    check("URL com tracking ainda e a mesma vaga", "duplicate" in tracking_url)

    section("11. APROVACAO (human-in-the-loop)")
    shortcut = await _call(
        career, "update_application_status", {"application_id": application_id, "status": "applied"}
    )
    check("pending_approval NAO pula para applied", "ERRO" in shortcut, shortcut[:160])
    check("erro explica que precisa aprovar", "approved" in shortcut.lower())

    approved = await _call(
        career, "update_application_status",
        {"application_id": application_id, "status": "approved", "note": "aprovado na validacao"},
    )
    check("aprovacao aceita", "approved" in approved)

    applied = await _call(
        career, "update_application_status",
        {"application_id": application_id, "status": "applied", "note": "enviado manualmente"},
    )
    check("applied aceito depois de approved", "applied" in applied)

    interview = await _call(
        career, "update_application_status",
        {"application_id": application_id, "status": "interview"},
    )
    check("interview aceito", "interview" in interview)

    section("12. HISTORICO")
    detail = await _call(career, "get_application", {"application_id": application_id})
    check("detalhe traz o historico", "Historico:" in detail)
    for status_name in ("pending_approval", "approved", "applied", "interview"):
        check(f"historico registra '{status_name}'", status_name in detail)

    listing = await _call(career, "list_applications", {"status": "interview"})
    check("filtro por status funciona", application_id in listing)

    pending_listing = await _call(career, "list_applications", {"status": "pending_approval"})
    check("candidatura saiu de pending_approval", application_id not in pending_listing)

    history_file = await _call(files, "read_application_history", {})
    check("espelho JSON atualizado", application_id in history_file)
    check("espelho avisa que e derivado", "GERADO AUTOMATICAMENTE" in history_file)

    section("13. SEGURANCA")
    policy = await _call(career, "get_safety_policy", {})
    for marker in ("Nao faz login automatico", "Nao armazena senha",
                   "Nao envia candidatura automaticamente", "Nao faz scraping agressivo"):
        check(f"politica declara: '{marker}'", marker in policy)

    status_text = await _call(career, "get_system_status", {})
    check("status do sistema responde", "STATUS DO CAREER AGENT" in status_text)
    check("automacao declarada desabilitada", "DESABILITADA" in status_text)

    # -- Resultado --------------------------------------------------------
    print()
    print("=" * 68)
    if FAILURES:
        print(f"RESULTADO: {len(FAILURES)} FALHA(S) de {CHECKS} verificacoes")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print(f"RESULTADO: TODAS as {CHECKS} verificacoes passaram.")
    print("Fluxo validado: perfil -> vaga -> score -> candidatura -> aprovacao -> historico")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    finally:
        shutil.rmtree(SANDBOX_ROOT, ignore_errors=True)
    sys.exit(exit_code)

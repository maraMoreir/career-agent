"""Fontes sem API publica: LinkedIn, Indeed, Gupy.

Estas plataformas NAO oferecem API publica de busca de vagas para uso pessoal.
Obter vagas delas exigiria uma destas coisas, todas proibidas pela politica
deste projeto (ver `career_core.security`):

  - login automatizado / reuso de cookie ou token de sessao;
  - scraping do HTML autenticado;
  - evasao de mecanismos anti-bot.

Em vez de fingir que a integracao existe, a fonte se declara indisponivel e
devolve o **modo manual**: a usuaria abre a vaga no navegador, copia URL e
descricao, e usa `analyze_job` / `prepare_application`. O agente faz todo o
resto - score, gaps, curriculo, mensagem, historico.

A abstracao fica pronta: se qualquer uma dessas plataformas publicar uma API
oficial, basta implementar `search` aqui. Nada mais do sistema muda.
"""

from __future__ import annotations

from .base import IJobSource, JobQuery, SourceResult


class UnavailableJobSource(IJobSource):
    """Fonte declarada, porem nao consumivel de forma legitima e automatica."""

    usable = False

    def __init__(self, name: str, display_name: str, reason: str, manual_url: str) -> None:
        self.name = name
        self._display_name = display_name
        self._reason = reason
        self._manual_url = manual_url
        self.provenance = (
            f"{display_name}: sem API publica de busca. {reason} "
            f"Uso previsto: modo manual (a usuaria copia a vaga; o agente analisa)."
        )

    def search(self, query: JobQuery) -> SourceResult:
        return SourceResult(
            source=self.name,
            jobs=[],
            ok=False,
            message=(
                f"{self._display_name} nao possui API publica de busca de vagas, e "
                f"este projeto NAO automatiza login, cookies, cliques ou scraping "
                f"em portais de vagas.\n\n"
                f"Motivo: {self._reason}\n\n"
                f"MODO MANUAL (funciona muito bem):\n"
                f"  1. Abra {self._manual_url} no seu navegador e busque "
                f"'{query.keywords or 'Backend .NET'}'.\n"
                f"  2. Copie a URL da vaga e o texto da descricao.\n"
                f"  3. Me mande: 'Analise esta vaga: <URL>' e cole a descricao.\n"
                f"  4. Eu calculo o score, aponto os gaps, personalizo o curriculo, "
                f"escrevo a mensagem e registro no historico.\n\n"
                f"Voce continua no controle do clique final - que e exatamente o "
                f"ponto."
            ),
        )


def linkedin_source() -> UnavailableJobSource:
    return UnavailableJobSource(
        name="linkedin",
        display_name="LinkedIn",
        reason=(
            "A busca de vagas do LinkedIn exige sessao autenticada. Automatizar "
            "isso violaria os Termos de Servico da plataforma e colocaria sua "
            "conta em risco de bloqueio. A API oficial de vagas e restrita a "
            "parceiros corporativos."
        ),
        manual_url="https://www.linkedin.com/jobs/",
    )


def indeed_source() -> UnavailableJobSource:
    return UnavailableJobSource(
        name="indeed",
        display_name="Indeed",
        reason=(
            "O Indeed encerrou o acesso publico da antiga Publisher API. O acesso "
            "atual e restrito a parceiros aprovados, com credencial propria."
        ),
        manual_url="https://br.indeed.com/",
    )


def gupy_source() -> UnavailableJobSource:
    return UnavailableJobSource(
        name="gupy",
        display_name="Gupy",
        reason=(
            "A Gupy nao publica uma API aberta de busca de vagas para candidatos. "
            "As APIs existentes sao voltadas a clientes corporativos (ATS), com "
            "credencial da empresa contratante."
        ),
        manual_url="https://portal.gupy.io/",
    )

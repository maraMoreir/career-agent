# MCP `career-files`

Leitura de arquivos, **somente leitura** e **somente dentro de**
`C:\career-agent\data`.

## Ferramentas

| Ferramenta | Para que serve |
|---|---|
| `read_profile` | Le `profile.md`, `skills.md` e `preferences.md` brutos. |
| `read_preferences` | Le so `preferences.md`. |
| `list_resumes` | Lista os curriculos disponiveis. |
| `read_resume` | Le um curriculo especifico. |
| `read_application_history` | Le o espelho JSON do historico. |
| `list_data_files` | Lista os arquivos visiveis na raiz de dados. |
| `get_sandbox_info` | Mostra exatamente o que este servidor pode acessar. |

## O sandbox

O Claude **nao** tem acesso a `C:\`, a sua pasta de usuario, nem ao codigo
deste projeto. Toda resolucao de caminho passa por `SandboxedFileSystem`, que
resolve o caminho real (seguindo links) **antes** de comparar com a raiz.

Bloqueado:

- `..` e travessia de diretorio em qualquer profundidade
- caminhos absolutos fora da raiz (`C:\Windows\win.ini`)
- caminhos UNC (`\\servidor\share`)
- symlinks e junctions do Windows que apontem para fora
- nomes de dispositivo reservados (`CON`, `NUL`, `COM1`...)
- bytes nulos no caminho
- arquivos acima do limite de tamanho

Extensoes legiveis: `.md`, `.markdown`, `.json`, `.txt`. Qualquer outra coisa
— binario, `.exe`, `.pem`, `.env` — e recusada e nem sequer aparece nas
listagens.

**Este servidor nao escreve e nao apaga nada.**

Para mudar a raiz, ajuste `CAREER_DATA_ROOT` no `.env`. Nao aponte para `C:\`
nem para sua pasta de usuario — isso anula todo o proposito.

## Sobre o historico

`read_application_history` le o espelho JSON, que e **gerado
automaticamente**. A fonte de verdade e o SQLite. Para consultar candidaturas,
prefira `list_applications` / `get_application` do servidor `career-agent`:
sao mais rapidos e aceitam filtros.

## Execucao

```powershell
.\scripts\start.ps1 -Server career-files
```

Logs em `logs\mcp-career-files.log`.

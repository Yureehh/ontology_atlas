# Install

The recommended install is a UV tool install. It gives users a global
`ontology-agent` command without activating a project virtualenv.

## macOS And Linux

From a cloned repo:

```bash
cd /path/to/ontology_atlas
uv tool install --force '.[rag]'
ontology-agent --help
```

This installs the complete answer-first product, including Neo4j GraphRAG and the local
portal server. For Parquet datasets, add both extras:

```bash
uv tool install --force '.[rag,parquet]'
```

From a wheel or GitLab artifact:

```bash
uv tool install --force 'company_ontology_agent-0.1.0-py3-none-any.whl[rag]'
ontology-agent --help
```

If UV prints a PATH warning, run:

```bash
uv tool update-shell
```

Then close and reopen the terminal.

Manual shell setup, if needed:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Use `~/.bashrc` instead of `~/.zshrc` if your shell is Bash.

Verify:

```bash
which ontology-agent
ontology-agent --help
```

## Windows PowerShell

From a cloned repo:

```powershell
cd C:\path\to\ontology_atlas
uv tool install --force '.[rag]'
ontology-agent --help
```

From a wheel or GitLab artifact:

```powershell
uv tool install --force '.\company_ontology_agent-0.1.0-py3-none-any.whl[rag]'
ontology-agent --help
```

If UV prints a PATH warning, run:

```powershell
uv tool update-shell
```

Then close and reopen PowerShell.

Verify:

```powershell
Get-Command ontology-agent
ontology-agent --help
```

If the command is still not found, add UV's tool directory to the user PATH. The usual
location is:

```powershell
$env:USERPROFILE\.local\bin
```

## Pip Alternatives

Inside an activated virtualenv:

```bash
pip install '.[rag]'
ontology-agent --help
```

For a global CLI using the pip ecosystem:

```bash
pipx install '.[rag]'
ontology-agent --help
```

## Development Install

Use this only when developing the package itself:

```bash
uv sync --extra dev --extra rag
uv run --extra dev --extra rag ontology-agent --help
```

## Notes For Teams

Every colleague needs `ontology-agent` on their own machine. If they install with
`uv tool install --force '.[rag]'` and UV warns that the tool directory is not on PATH, they
must run `uv tool update-shell` once.

Generated project Makefiles assume `ontology-agent` is callable from PATH. They do not
require `PYTHONPATH`, temporary virtualenv paths, or exported command variables.

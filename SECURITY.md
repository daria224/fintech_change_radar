# Secret scanning

The repository uses Gitleaks with the default detection rules. Keep real credentials in protected environment variables, never in source, configuration files, examples, or Git history. `.env.example` is the only environment file intentionally allowed in Git; it must contain placeholders only.

## Windows setup

Install the native Gitleaks binary with Windows Package Manager; Docker is not required:

```powershell
winget install --id Gitleaks.Gitleaks --exact
```

After installation, open a new terminal (and restart Codex if it was already running), then from the repository run:

```powershell
.\scripts\setup_secret_checks.ps1
.\scripts\test_secret_checks.ps1
```

The setup script sets this clone's `core.hooksPath` to `.githooks`. Git runs the hooks automatically before commits and pushes, including Git commands invoked during normal Codex work. Hooks fail closed if Gitleaks is missing or reports a finding. The pre-commit hook uses Gitleaks `git --staged` and also rejects staged sensitive filenames, including files added with `git add --force`. An ignored local `.env.local` is not part of the staged scan. The pre-push hook scans each outgoing commit range. Gitleaks output is redacted.

To restore the protection in another clone, install Gitleaks and rerun `setup_secret_checks.ps1`. Git hooks are local to each clone; the setup command is therefore required after cloning. Do not disable GitHub's repository protections or bypass these checks.

## Ignore rules

`.gitignore` and `.dockerignore` exclude environment overrides, local credentials, private-key files, and common local configuration files. `.env.example` remains trackable. Ignore rules do not remove files already tracked by Git, so review `git ls-files` when adding local configuration.

## Manual scan

To scan the repository's Git history, run:

```powershell
gitleaks git --redact --no-banner .
```

If a real secret is reported, stop before committing or pushing. Do not copy its value into logs or chat; remove it safely, rotate it if it may have been exposed, then scan the affected history again.

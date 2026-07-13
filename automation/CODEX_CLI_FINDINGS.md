# Codex CLI Recon Findings (MED-01)

Recon date: 2026-07-13T11:00 (+03:00), on the Windows machine that runs the local `ego_os` runner (`os.fiveseven.ru` deployment host is separate — this recon was performed on the local dev/runner machine only).

## 1. Is the Codex CLI installed on this machine?

**No. The OpenAI Codex CLI is NOT installed on this machine.**

Directly observed probes, both negative:

```
$ where codex
INFO: Could not find files for the given pattern(s).   # (native Windows `where`, output shown transliterated)

$ command -v codex   # via Git Bash
bash: line 1: codex: command not found
(exit code 127)
```

```powershell
PS> Get-Command codex -ErrorAction SilentlyContinue; if ($?) { "FOUND" } else { "NOT FOUND" }
NOT FOUND
```

No `codex --version` probe was possible since no `codex` binary resolves on `PATH`. No other Codex CLI invocation was attempted, per task scope — nothing beyond existence checks (`where`, `command -v`, `Get-Command`) was run.

## 2. Official install command (per OpenAI's own docs, not installed by this task)

Sourced directly from OpenAI's official docs (`learn.chatgpt.com/docs/codex/cli`, redirect target of `developers.openai.com/codex/cli`) and the official `github.com/openai/codex` repository README, fetched during this recon (not recalled from training data):

- **Windows** (this machine's platform):
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
  ```
- **macOS/Linux** (standalone installer):
  ```bash
  curl -fsSL https://chatgpt.com/codex/install.sh | sh
  ```
- **npm** (cross-platform, requires Node.js 22+):
  ```bash
  npm install -g @openai/codex
  ```
- **Homebrew** (macOS):
  ```bash
  brew install --cask codex
  ```
- Platform-specific binaries are also published on the project's GitHub Releases page as an alternative to the above.

First authentication is via "Sign in with ChatGPT" (or another supported sign-in method) on first launch — this itself is a non-diagnostic, account-linking action and was correctly out of scope for this recon.

**None of the above install commands were run.** Installing new global software (whichever method is chosen) is explicitly out of scope for this task and is called out below as a prerequisite for the next stage.

## 3. Recommendation for MED-02

MED-02 (or whichever task first needs to actually invoke Codex CLI non-interactively) requires the Codex CLI to be installed on whichever machine will run it. **This requires an explicit Owner-approved decision** covering:
- which install method to use (npm vs. the official Windows PowerShell installer vs. Homebrew/binary, given this machine's environment already has Node/npm available via other automation/ tooling),
- which machine it's installed on (this dev/runner machine vs. any other host),
- the ChatGPT/ OpenAI account used to authenticate the CLI, and any subscription/plan implications (Codex CLI usage is gated behind ChatGPT sign-in or API key billing).

This task (MED-01) intentionally stops here: no install was performed, consistent with the "recon only" scope and the requirement not to make an owner-approval-requiring change without `owner_approved: true` on record.

## 4. Non-interactive invocation mode, output format, rate-limit/auth-failure surfacing

**Not applicable / not observed.** Since the Codex CLI is not installed on this machine, none of `codex --help`, a headless/`exec`-style invocation, or any output-format/rate-limit/auth-failure behavior could be directly observed in this session. Documenting these from memory or training data would violate the task's "never guessed from memory or training data" constraint, so they are deliberately left undocumented here. This section must be completed as real, observed output once Codex CLI is actually installed (see Section 3) — do not backfill it from assumptions.

# Outbound Engine

An AI-run outbound email system. Claude (via Claude Code) manages lead selection,
message generation, campaign creation, reply handling, and iteration. **Smartlead**
handles sending; **HubSpot** is the CRM; **Slack** is used for review and approval.

This repository is the persistent operating manual for the system. The logic lives
in version-controlled instruction and config files, not in one-off prompts.

## Start here
- **New to this repo?** Read [`GETTING-STARTED.md`](./GETTING-STARTED.md).
- **How the system operates:** read [`CLAUDE.md`](./CLAUDE.md).

## Layout
- `CLAUDE.md`: the operating manual Claude Code reads automatically.
- `instructions/`: reusable "how to do each job" files (research, generation,
  campaign creation, reply handling, analysis; qualification is deferred).
- `config/`: company-specific facts (positioning, personas, Smartlead defaults).
- `scripts/`: Python that Claude Code writes to call the Smartlead / HubSpot / LLM APIs.
- `data/`: local SQLite working state (git-ignored).
- `reviews/`: exported human-review sheets (git-ignored).

## v1 principles
- Runs entirely **locally** (Claude Code + Claude desktop scheduled tasks). No
  servers, queues, or webhooks.
- **3 emails** per sequence.
- **Nothing sends or launches without explicit human approval.**
- Smartlead + HubSpot are the sources of truth; CSV/Sheets are review surfaces only.
- Lead qualification is **deferred** to a later version.

## Status
Scaffold created. Company-specific content in `config/` and parts of `instructions/`
still needs to be filled in. Search the files for `[FILL IN` and `TODO`.

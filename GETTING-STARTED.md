# Getting Started

This walks you from zero to "Claude Code running inside the outbound-engine repo."
Written for someone comfortable with tools but not a developer. Do it once.

---

## 1. Accounts you need

| Account | Why | When |
|---|---|---|
| **Paid Claude plan** (Pro, Max, Team, or Enterprise) OR an Anthropic API key | Claude Code does not work on the free plan | Now |
| **GitHub account** (free) | Hosts the repo | Now |
| **HubSpot** | CRM (you already have this) | Now |
| **The "cheap" LLM API** you'll use for bulk copy | Generates messages at volume | Before Phase 4 (generation) |
| **Google account** | Google Sheets review surface | Before Phase 4 |
| **Smartlead** | Sending infra | **Only after your Phase 0 go/no-go:** don't buy yet |

> Note on sequencing: creating this repo is free and depends on nothing, so it's
> safe to do now, before your Phase 0 spend gate. Smartlead + domains wait for
> go/no-go.

---

## 2. Install Claude Code

Two paths. Pick one.

### Option A: Desktop app (easiest, no terminal)
Anthropic ships a **Claude desktop app that runs Claude Code with a graphical
interface**, with no command line needed. This is a good starting point if the terminal
isn't your comfort zone, and it's also what you'll use later for the **scheduled
reply-check task** (your tracker's Phase 6). Download it for your OS from the Claude
site and sign in with your paid account.

### Option B: Terminal (native installer, recommended by Anthropic)
The native installer bundles everything (no Node.js to manage) and auto-updates.

- **macOS:** open Terminal and run
  ```bash
  curl -fsSL https://claude.ai/install.sh | bash
  ```
- **Windows:** open PowerShell and run
  ```powershell
  irm https://claude.ai/install.ps1 | iex
  ```
  On native Windows, also install **Git for Windows** so Claude Code can run shell
  commands well.

Then verify and log in:
```bash
claude --version      # should print a version like 2.1.x (Claude Code)
claude                # opens a session; follow the browser prompt to authenticate
```

**System requirements:** macOS 13+, Windows 10+, or Ubuntu/Debian Linux; 4GB+ RAM;
internet connection.

---

## 3. Install Git (for version control)

- **Mac:** running `git --version` will offer to install it, or install Xcode
  Command Line Tools.
- **Windows:** install **Git for Windows** (git-scm.com).
- **Easier alternative for non-devs:** install **GitHub Desktop**, a point-and-click
  app that handles cloning, committing, and pushing without terminal commands.

---

## 4. Create the GitHub repo

Do this in the browser (simplest):

1. Go to github.com → **New repository** (the **+** menu, top right → New repository).
2. **Repository name:** `outbound-engine` (or your preference).
3. **Visibility:** **Private.** This repo will reference internal positioning and
   process. Keep it private.
4. Leave "Add a README" **unchecked** (this scaffold already includes one).
5. Click **Create repository.** Leave the page open, since you'll need the URL.

---

## 5. Put this scaffold into the repo

1. Unzip the starter bundle you were given.
2. Get the files onto your machine and into the repo:
   - **With GitHub Desktop:** File → Clone repository → pick `outbound-engine` →
     choose a local folder. Then copy the unzipped files into that folder. GitHub
     Desktop will show all the new files.
   - **With the terminal:**
     ```bash
     git clone https://github.com/YOUR-USERNAME/outbound-engine.git
     cd outbound-engine
     # copy the unzipped scaffold files into this folder, then:
     git add .
     git commit -m "Initial outbound engine scaffold"
     git push
     ```
3. Confirm on github.com that the files are there.

---

## 6. Connect Claude Code to the repo

"Connecting" just means opening Claude Code with this folder as its working
directory:

```bash
cd outbound-engine
claude
```

(Or open the folder in the desktop app.) Claude Code automatically reads `CLAUDE.md`
and now understands the whole system.

Good first thing to type once you're in:
> "Read CLAUDE.md and the files in instructions/ and config/. Summarize how this
> system is supposed to work and list what's still a placeholder that I need to fill
> in."

---

## 7. Set up your credentials file

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env        # Mac/Linux
   copy .env.example .env      # Windows
   ```
2. Fill in the values you have now (HubSpot). Leave the rest until you reach those
   phases. **`.env` is git-ignored and must never be committed.**

---

## 8. Where this maps to your Asana plan

- ✅ **Row 5, Create GitHub repo:** steps 4 and 5 above.
- ✅ **Row 6, Write CLAUDE.md:** done (`CLAUDE.md` in this scaffold; edit to taste).
- ✅ **"Connect Claude Code to the repo":** step 6.
- ⏭ **Phase 0 go/no-go:** still gates Smartlead + domain spend. Do that in parallel.
- ⏭ **Phase 3, data layer / SQLite:** Claude Code will build this in `scripts/` and
  `data/` when you get there.
- ⏭ **Phase 4, generation:** fill in `config/` + `instructions/message-generation.md`
  first, then have Claude Code write the bulk-generation script.

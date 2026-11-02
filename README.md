# Job Apply Agent

An AI assistant that **finds the best jobs for you and applies to them**. Anything it can't finish by itself goes on a short to-do list for you.

You talk to it in plain English, for example: *"find and apply jobs for me"*.

---

## What it does

1. **Searches** job boards of 100+ companies and the web for jobs that match you.
2. **Scores** each job against your resume (from 1 to 5) and saves a short report.
3. **Applies automatically** to the best matches (score 4.0 or higher) with your resume.
4. **Makes a to-do list** (`MANUAL_APPLY.md`) of good jobs it couldn't finish, for example when a site asks for a login, a CAPTCHA, or an email code.
5. **Never lies** on your behalf. It only uses facts from your resume and your answers.

It never sends messages to recruiters, and it never applies to the same job twice.

---

## What you need (one time)

| You need | Why | How to get it |
|---|---|---|
| A Windows 10 or 11 computer | It runs on your PC | |
| **Python 3.12 or newer** | Runs the agent | [python.org/downloads](https://www.python.org/downloads/). During install, **tick "Add python.exe to PATH"**. |
| **Node.js (LTS version)** | Runs the job search engine | [nodejs.org](https://nodejs.org/). Click the big "LTS" button and install. |
| **Git** | Downloads the code | [git-scm.com/download/win](https://git-scm.com/download/win). Click Next on every screen. |
| **Google Chrome** | The agent fills job forms in Chrome | [google.com/chrome](https://www.google.com/chrome/) |
| **Claude Code** | The AI that does the work | [claude.com/claude-code](https://claude.com/claude-code). Needs a Claude Pro or Max plan. |
| **Your resume as a PDF** | So the agent knows about you | Export it from Word or Google Docs as PDF. |

> **Tip:** after installing anything, **close and reopen** PowerShell so it notices the new program.

---

## Step 1: Download this project

1. Press the **Windows key**, type **PowerShell**, and press **Enter**. A blue or black window opens.
2. Copy this line, paste it into PowerShell (right-click pastes), and press **Enter**:

   ```powershell
   cd $HOME\Documents; git clone https://github.com/batm44/job-apply-agent-v2.git job-apply-agent; cd job-apply-agent
   ```

✅ You should now be in the folder `Documents\job-apply-agent`.

---

## Step 2: Run the setup (one click, about 5 minutes)

In the same PowerShell window, paste this and press **Enter**:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

It checks your computer, installs what's needed, downloads the job search engine ([career-ops](https://github.com/career-ops-hq/career-ops)), and tests the browser.

✅ At the end you should see a green **SETUP COMPLETE.**

❌ If you see a red **STOPPED** message, it tells you exactly what to install. Install it, close and reopen PowerShell, and run Step 2 again.

---

## Step 3: Add your resume

1. Open the folder `Documents\job-apply-agent\resume` (the setup created it).
2. Copy your resume PDF into it.

---

## Step 4: Tell the agent about yourself (one time, about 10 minutes)

1. In PowerShell (still in the `job-apply-agent` folder), type `claude` and press **Enter**.
2. When Claude Code opens, type:

   ```
   Set up my profile from my resume
   ```

3. Answer its questions. It reads your resume and only asks what it can't find, such as:
   - Which job titles do you want?
   - Which countries and cities, in order of preference?
   - Do you need visa sponsorship there?
   - Your expected salary, and your notice period.
4. It creates your profile, personalises the job search, and makes a **designed PDF resume** for you. Check it and ask for any changes you want.
5. At the end it asks: **"May I submit applications automatically?"** Say **yes** only if you want that. If you say no, it still finds and scores jobs, and you apply yourself.

✅ Done when Claude says your profile is complete.

---

## Step 5: Find and apply to jobs (every time you want)

Open PowerShell, go to the folder, and start Claude:

```powershell
cd $HOME\Documents\job-apply-agent; claude
```

Then type:

```
find and apply jobs for me
```

You can also add a focus, for example:

- `find and apply jobs for me: only remote jobs`
- `find and apply jobs for me: Netherlands with visa sponsorship`

Claude works for a while (often 20 to 60 minutes) and then tells you:

- how many jobs it found and scored,
- which ones it **applied to** (with the company's confirmation),
- which ones **need you**, listed in `MANUAL_APPLY.md`.

---

## Step 6: Handle your to-do list

Open `MANUAL_APPLY.md` in the project folder. For each job:

1. Read **"Why it needs you"**. It might be a login, an email code, a missing document, or "sponsorship not mentioned".
2. Click the **Apply** link and finish the application. A tailored resume is linked if one was made.
3. Tell Claude when you're done, for example: **"I applied to the Acme job"**, or **"skip the Globex job"**.

Claude records it, so that job is never listed or applied to again.

---

## Where your files are

All of these stay **on your computer only**. They're never uploaded to GitHub.

| Folder or file | What's inside |
|---|---|
| `resume\` | Your original resume and your designed PDF resume |
| `data\profile.json` | Everything the agent knows about you and what you want |
| `applications\` | Tailored resumes and cover letters, one folder per job |
| `daily-runs\` | A summary of each run (`digest.md`) |
| `MANUAL_APPLY.md` | Jobs waiting for you |
| `career-ops\reports\` | A scoring report for every job it evaluated |
| `career-ops\data\applications.md` | A tracker table of every job and its status |

---

## Useful commands

You can also just ask Claude to do these for you. Run them in PowerShell from the project folder:

| What you want | Command |
|---|---|
| Stop all automatic applications | `.\.venv\Scripts\python.exe autoapply.py pause` |
| Turn them back on | `.\.venv\Scripts\python.exe autoapply.py resume` |
| See the status | `.\.venv\Scripts\python.exe autoapply.py status` |
| Rebuild the to-do list | `.\.venv\Scripts\python.exe autoapply.py manual-queue` |

### Optional: run it automatically every day at 09:00

```powershell
powershell -ExecutionPolicy Bypass -File .\register_task.ps1
```

To turn that off again:

```powershell
Unregister-ScheduledTask -TaskName JobApplyDaily -Confirm:$false
```

Your PC must be on and you must be logged in for it to run.

---

## Problems and fixes

| Problem | Fix |
|---|---|
| `git`, `python`, `node` or `claude` "is not recognized" | Install it (see **What you need**), then **close and reopen PowerShell**. |
| "running scripts is disabled on this system" | Use the exact command from Step 2. It includes `-ExecutionPolicy Bypass`. |
| Setup says the browser test failed | Install Google Chrome, then run Step 2 again. |
| It applied to nothing | It only applies to strong matches (4.0/5 or higher) that pass every check. Read the run summary in `daily-runs\` to see why. You can ask Claude to widen your targets. |
| A job keeps asking for an email code or a login | That's expected. The agent never bypasses these, so the job goes to `MANUAL_APPLY.md` for you. |
| You want to change your targets or salary | Tell Claude, for example: "add Germany to my target countries". |

---

## How it stays honest and safe

- It only writes facts that are in your resume or that you told it.
- It never upgrades a degree or title, and never invents numbers or skills.
- If a job requires something you don't clearly have, it skips the job or puts it on your to-do list.
- It records every application in a local journal, so the same job is never applied to twice.
- It never contacts recruiters.
- `pause` stops everything immediately.

---

## For developers

- `autoapply.py`: eligibility rules, scoring, and the submission journal (SQLite). Run `python autoapply.py --help`.
- `browser_mcp.py`: Chrome automation exposed as an MCP tool for Claude Code.
- `documents.py`: exports DOCX resumes and cover letters.
- `DAILY_RUN.md`, `ONBOARDING.md` and `CLAUDE.md`: the instructions the AI agent follows.
- Tests: `.\.venv\Scripts\python.exe -m unittest discover -p "test_*.py"`

Job discovery and scoring are powered by [career-ops](https://github.com/career-ops-hq/career-ops) (MIT licence, by santifer and contributors). It's downloaded separately by `setup.ps1` and isn't included in this repository.

# job-apply-agent: instructions for Claude Code

The user may not be technical. Use plain language, short steps, and do the work for them.

## "Set up my profile" (first time, or when the resume changes)

1. Find the resume PDF in `resume/` (ask for the path if there is none). Extract its text with `.venv\Scripts\python.exe` and `pypdf`.
2. Follow [ONBOARDING.md](ONBOARDING.md): ask only for what the resume does not answer (target roles, countries and cities in order, home country and work rights, which countries need visa sponsorship, salary expectations, notice period, contract preferences). Ask in small batches.
3. Write `data/profile.json` in the shape of [examples/profile.example.json](examples/profile.example.json). Every experience bullet must come from the resume or the user's own words. Copy the resume to `resume/source_resume.pdf` and set `resume_file`.
4. Personalise career-ops in `career-ops/` following its AGENTS.md onboarding: write `cv.md` from the resume, run `node onboard-write.mjs` (profile and portal keywords/locations), and fill `modes/_profile.md` and `modes/_brief.md` from the user's answers. Check with `node doctor.mjs --json` until `onboardingNeeded` is false and `unpersonalized` is empty.
5. Build a designed PDF resume: write a CV JSON payload from `cv.md` to `career-ops/output/cv-master.json`, render it with `node build-cv-html.mjs` (template `templates/cv-template.executive.html`) and `node generate-pdf.mjs --format=a4`, copy it to `resume/resume.pdf`, and set `application_resume_pdf` and `application_resume_source` in `data/profile.json`. Show the user and apply their corrections.
6. Ask the user for explicit consent to automatic submissions. Only after a clear yes, run `.venv\Scripts\python.exe autoapply.py setup --auto-submit` (with `--timezone` set to theirs). Then run `autoapply.py status` and confirm `onboarding_missing` is empty.

## "Find and apply jobs for me"

Read and follow [DAILY_RUN.md](DAILY_RUN.md) end to end. Honour any extra focus the user gives (for example "only remote jobs").

## "I applied to ..." / "skip this job"

Find the job's key in `MANUAL_APPLY.md` and run `autoapply.py mark <key> --as manual_applied --note "..."` (or `--as dismissed`).

## Always

- Never invent facts, metrics, degrees, work rights or experience. Ask instead.
- Never contact recruiters or send messages on the user's behalf.
- Never bypass CAPTCHA, logins or one-time codes; list those jobs in `MANUAL_APPLY.md`.
- Never commit or upload `data/`, `resume/`, `applications/`, `daily-runs/`, `career-ops/` or `MANUAL_APPLY.md`: they hold the user's personal data.

# Custom Instructions -- career-ops (installed by job-apply-agent)

<!-- Copied into career-ops/modes/_custom.md by setup.ps1. It is a user-layer file:
     career-ops updates never overwrite it. Edit freely. -->

## House Rules

- This install is the discovery, scoring and tailoring layer for job-apply-agent (`../DAILY_RUN.md`). When a mode would draft or fill an application, stop at the prepared materials. Submission happens only in the job-apply-agent workflow, through its journal (`autoapply.py claim` / `begin-submit` / `result`) and under the candidate's standing consent in `../data/autoapply-config.json`.
- `../data/profile.json` is the canonical preference file (locations, salary bands, contract rules). If it disagrees with `config/profile.yml` or `modes/_profile.md`, follow profile.json and mention the difference.
- Treat specialist requirements honestly: a skill listed on the CV is not proof of years of production experience in it.

## Custom Workflows

- "daily": run `node scan.mjs`, triage new pipeline rows with `modes/_brief.md`, run a full `oferta` evaluation on the best PASS rows (at most 15 per run), and save reports. `../DAILY_RUN.md` turns reports scoring 4.0/5 or higher into journal entries.

## Output Preferences

- Reports: lead with the score, the location track, sponsorship status and contract type (permanent / fixed-term / contractor plus pay currency).

## Off-Limits

- Never contact recruiters or send LinkedIn/email outreach.
- Never invent metrics, degrees, titles, work rights or experience.

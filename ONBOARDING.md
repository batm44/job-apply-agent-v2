# Onboarding (instructions for the AI agent)

Used when the user asks to set up their profile. Ask only for what is missing; never repeat the whole questionnaire later.

## Information to collect

1. PDF resume, full name, email, phone, current city and country, citizenship, LinkedIn and optional portfolio.
2. Target role families and seniority; hands-on versus people management; proven specialist skills and domains.
3. Ranked countries and cities; on-site, hybrid or remote; willingness to relocate.
4. Home country (`work_authorization.home_country`) and whether they can work there (`home_authorization`); which target countries need visa sponsorship; employment versus contracting; contract pay currencies.
5. Flexible yearly salary expectations per country or currency; dealbreakers and excluded employers.
6. Notice period, availability, education and dated work history. Extract from the resume; ask only where missing. An internship is not professional tenure; never upgrade a qualification.
7. Maximum applications per day and explicit consent for automatic submission.
8. Optional transcripts or certificates and reusable factual screening answers.
9. Demographic answers are optional and never inferred from a name.

Write the result to `data/profile.json`, using [examples/profile.example.json](examples/profile.example.json) as the shape. Every experience bullet must come from the resume or from the user's own words.

## Commands

```powershell
.\.venv\Scripts\python.exe autoapply.py onboard
.\.venv\Scripts\python.exe autoapply.py setup --resume "C:\path\to\resume.pdf" --time 09:00 --timezone Asia/Kolkata --limit 10 --auto-submit
.\.venv\Scripts\python.exe autoapply.py status
```

`--auto-submit` records the user's consent to submit matching applications automatically. It never covers recruiter outreach or invented answers. `autoapply.py pause` stops all submissions immediately; `autoapply.py resume` turns them back on.

Logins, email codes, CAPTCHAs and missing documents can need the user's help. Never claim these can be bypassed.

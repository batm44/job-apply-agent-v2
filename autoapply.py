"""Persistent onboarding, eligibility, ranking and submission journal for the browser agent.

The scheduled host supplies web search and browser tools; this module owns local state.
No passwords, verification codes, API keys, or browser cookies are stored here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TERMINAL = {'submitted', 'attention', 'uncertain', 'submitting', 'reserved', 'manual_applied', 'dismissed'}
WEIGHTS = {'technical': .35, 'authorization': .30, 'compensation': .15, 'growth': .10, 'location': .10}
# Blockers the candidate cannot fix by applying by hand; everything else is a manual-apply candidate.
HARD_BLOCKERS = ('Closed vacancy', 'Role family outside', 'Employer excluded', 'Country outside', 'City outside',
                 'Remote work is outside', 'Posting outside allowed date window', 'Work mode excluded',
                 'Engagement excluded', 'Non-permanent contract', 'Contract pay currency', 'Missing job field',
                 'Employer application URL')
MANUAL_MIN_CAREER_OPS_SCORE = 4.0


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def now():
    return datetime.now(timezone.utc)


def norm(value):
    return ' '.join(re.findall(r'[a-z0-9]+', str(value).lower()))


def role_families(title):
    title = norm(title)
    families = set()
    for family, terms in {
        'science': ('data scientist', 'data science', 'machine learning scientist', 'decision scientist',
                    'credit risk', 'risk modelling', 'risk modeling', 'underwriting'),
        'engineering': ('machine learning engineer', 'ml engineer'),
        'applied': ('applied ai', 'applied scientist', 'ai scientist'),
        'generative': ('genai', 'generative ai', 'llm engineer', 'ai engineer', 'llm'),
        'leadership': ('ai ml technical lead', 'ai technical lead', 'ml technical lead'),
    }.items():
        if any(term in title for term in terms):
            families.add(family)
    return families


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Employer application URL must be HTTPS without credentials')
    keep = {'gh_jid', 'jobid', 'job_id', 'requisitionid', 'rid', 'jid'}
    query = urlencode(sorted((k.lower(), v) for k, v in parse_qsl(parts.query) if k.lower() in keep))
    host = parts.hostname.lower().removeprefix('www.')
    return urlunsplit(('https', host, parts.path.rstrip('/').removesuffix('/apply'), query, ''))


def identity(job):
    return hashlib.sha256((norm(job['company']) + '|' + norm(job['title']) + '|' + norm(job['location'])).encode()).hexdigest()[:20]


def reference(profile, pointer):
    """Resolve a JSON pointer; quoted candidate evidence must point into saved facts."""
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        return None
    item = profile
    try:
        for key in pointer[1:].split('/'):
            key = key.replace('~1', '/').replace('~0', '~')
            item = item[int(key)] if isinstance(item, list) else item[key]
        return item
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def official_evidence(value, today, max_age=7):
    if not isinstance(value, dict) or value.get('source_type') != 'official_employer':
        return False
    try:
        canonical_url(value['url'])
        age = (today - date.fromisoformat(value['checked_on'])).days
        return 0 <= age <= max_age and bool(value.get('quote', '').strip())
    except (KeyError, ValueError, TypeError):
        return False


def home(profile):
    """(home country, work-authorized there?). Older profiles used india_authorization."""
    auth = profile.get('work_authorization', {})
    country = auth.get('home_country') or 'India'
    allowed = auth.get('home_authorization', auth.get('india_authorization'))
    return country, allowed


def onboarding_missing(profile):
    personal = profile.get('personal', {})
    defaults = profile.get('application_defaults', {})
    missing = ['personal.' + k for k in ('name', 'email', 'phone', 'location', 'citizenship') if not personal.get(k)]
    if not profile.get('resume_file') or not Path(profile['resume_file']).is_file():
        missing.append('resume_file')
    if not profile.get('experience'):
        missing.append('experience (review resume extraction)')
    if not profile.get('education'):
        missing.append('education (review resume extraction)')
    if not defaults.get('notice_period'):
        missing.append('application_defaults.notice_period')
    pref = profile.get('preferences', {})
    for key in ('target_roles_priority', 'location_priority', 'salary_preferences_annual_gross_base'):
        if not pref.get(key):
            missing.append('preferences.' + key)
    if not isinstance(home(profile)[1], bool):
        missing.append('work_authorization.home_authorization')
    return missing


def default_config():
    return {'version': 1, 'enabled': True, 'auto_submit': False, 'daily_limit': 10,
            'minimum_score': 75, 'timezone': 'Asia/Kolkata', 'run_time': '09:00',
            'posted_within_days': 14, 'expand_to_days': 30, 'max_applications_per_company_per_day': 2,
            'onboarding_complete': False, 'authorization': None, 'automation_id': None,
            'runner': 'local-agent-host', 'recruiter_outreach': False}


def assess(job, profile, config, today):
    """Conservative gates first; rank only evidence-backed, eligible vacancies."""
    blockers = []
    for key in ('company', 'title', 'location', 'country', 'work_mode', 'url', 'posted_on', 'requirements'):
        if not job.get(key):
            blockers.append('Missing job field: ' + key)
    try:
        canonical_url(job.get('url', ''))
    except ValueError as exc:
        blockers.append(str(exc))
    try:
        age = (today - date.fromisoformat(job['posted_on'])).days
        if age < 0 or age > config['expand_to_days']:
            blockers.append('Posting outside allowed date window')
    except (KeyError, ValueError, TypeError):
        age = None
        blockers.append('Employer posting date unverified')
    if not official_evidence(job.get('posting_evidence'), today):
        blockers.append('Fresh official posting-date evidence required (crawl age is insufficient)')
    if job.get('closed') or job.get('existing_work_rights_required') or job.get('sponsorship') == 'unavailable':
        blockers.append('Closed vacancy or incompatible work-authorization restriction')
    preferences = profile.get('preferences', {})
    targets = preferences.get('target_roles_priority', [])
    requested_families = set().union(*(role_families(t) for t in targets))
    if not role_families(job.get('title', '')).intersection(requested_families):
        blockers.append('Role family outside configured targets')
    if norm(job.get('company', '')) in {norm(c) for c in preferences.get('excluded_employers', [])}:
        blockers.append('Employer excluded by saved preferences')
    if not targets:
        blockers.append('No candidate role preferences')
    seniority = norm(job.get('seniority', ''))
    if seniority not in {'senior', 'lead', 'staff', 'principal', 'vp', 'director', 'associate director', 'manager'}:
        blockers.append('Seniority unspecified or below target; confirm level')
    if seniority in {'director', 'manager', 'associate director'} and job.get('hands_on') is not True:
        blockers.append('Management role must explicitly include hands-on technical work')
    mode = job.get('work_mode')
    allowed_modes = preferences.get('allowed_work_modes')
    if allowed_modes and mode not in allowed_modes:
        blockers.append('Work mode excluded by saved preferences')
    authorization, location = 0, 0
    if mode == 'remote':
        remote_requested = any('remote' in norm(group.get('work_mode', ''))
                               or 'remote' in [norm(m) for m in group.get('work_modes', [])]
                               for group in preferences.get('location_priority', []))
        if not remote_requested:
            blockers.append('Remote work is outside saved location preferences')
        country, authorized = home(profile)
        if authorized is not True:
            blockers.append(f'Candidate {country} work authorization unconfirmed')
        allowed = job.get('remote_allowed_countries', [])
        if not isinstance(allowed, list) or country not in allowed or not official_evidence(job.get('remote_evidence'), today):
            blockers.append(f'Explicit official {country}-remote eligibility required')
        else:
            authorization, location = 100, 85
        if job.get('engagement') not in {'employment', 'contractor'}:
            blockers.append('Employment versus independent contracting must be identified')
        allowed_engagements = preferences.get('allowed_engagements', ['employment', 'contractor'])
        if job.get('engagement') not in allowed_engagements:
            blockers.append('Engagement excluded by saved preferences')
        currencies = next((g['contractor_pay_currencies'] for g in preferences.get('location_priority', [])
                           if g.get('contractor_pay_currencies')), None)
        pay_currency = (job.get('salary') or {}).get('currency')
        if job.get('engagement') == 'contractor' and currencies and pay_currency and pay_currency not in currencies:
            blockers.append('Contract pay currency outside ' + '/'.join(currencies))
    elif mode in {'hybrid', 'onsite'}:
        target_country = None
        for group in preferences.get('location_priority', []):
            if group.get('country') == job.get('country'):
                target_country = group
                cities = group.get('cities', [])
                break
            if job.get('country') in group.get('countries_cities', {}):
                target_country = group
                cities = group['countries_cities'][job['country']]
                break
        if not target_country:
            blockers.append('Country outside saved relocation targets')
        elif not any(norm(city) in norm(job.get('location', '')) for city in cities):
            blockers.append('City outside saved location preferences')
        else:
            location = {1: 100, 2: 75}.get(target_country['priority'], 60)
            configured_modes = target_country.get('work_modes', ['onsite','hybrid'])
            if mode not in [norm(m).replace(' ', '') for m in configured_modes]:
                blockers.append('Work mode excluded for this target country')
        if target_country and target_country.get('permanent_only'):
            if job.get('engagement') != 'employment':
                blockers.append('Permanent employment contract unconfirmed (required for relocation)')
            elif job.get('contract_type') in {'fixed_term', 'temporary'}:
                blockers.append('Non-permanent contract excluded for relocation')
            elif job.get('contract_type') != 'permanent' and not preferences.get('apply_when_contract_type_unstated'):
                blockers.append('Permanent employment contract unconfirmed (required for relocation)')
        at_home = job.get('country') == home(profile)[0] and home(profile)[1] is True
        if target_country and target_country.get('sponsorship_required') is False and at_home:
            authorization = 100
        elif (preferences.get('apply_when_sponsorship_unstated') and job.get('sponsorship') in {None, 'needs_confirmation'}
              and not job.get('sponsorship_evidence')):
            authorization = 70  # Unstated, not refused; the application states the sponsorship need.
        else:
            evidence = job.get('sponsorship_evidence', {})
            if (job.get('sponsorship') != 'verified' or evidence.get('country') != job.get('country')
                    or not official_evidence(evidence, today)):
                blockers.append('Official sponsorship for this role/country needs confirmation')
            else:
                authorization = 100
    else:
        blockers.append('Work mode unverified')
    requirements = job.get('requirements', [])
    if not isinstance(requirements, list):
        raise ValueError('requirements must be a list')
    met, total = 0, 0
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise ValueError('Each qualification must be an object with candidate evidence')
        mandatory = requirement.get('mandatory', True)
        weight = 2 if mandatory else 1
        total += weight
        value = reference(profile, requirement.get('profile_reference'))
        pointer = requirement.get('profile_reference', '')
        allowed_reference = pointer.startswith(('/experience/', '/education/', '/skills_evidence/resume_', '/top_skills/'))
        if requirement.get('evidence_kind') == 'production':
            allowed_reference = pointer.startswith('/experience/')
        evidence = requirement.get('evidence', '')
        quoted_fact = norm(evidence) in norm(json.dumps(value, ensure_ascii=False)) if evidence and value else False
        valid = requirement.get('status') == 'met' and allowed_reference and quoted_fact
        if valid:
            met += weight
        elif mandatory:
            blockers.append('Mandatory qualification not demonstrated: ' + requirement.get('name', 'unnamed'))
    technical = round(100 * met / total, 1) if total else 0
    compensation = 50  # Undisclosed salary never becomes a rejection by itself.
    salary = job.get('salary') or {}
    salary_pref = preferences.get('salary_preferences_annual_gross_base', {}).get(job.get('country'), {})
    if mode == 'remote':
        bands = preferences.get('salary_preferences_annual_gross_base', {})
        salary_pref = bands.get('remote_home_equivalent') or bands.get('remote_india_equivalent', {})
    if salary.get('currency') == salary_pref.get('currency') and salary.get('annual_base_max'):
        compensation = min(100, round(80 * salary['annual_base_max'] / salary_pref['min_preferred'], 1))
    contract_pref = preferences.get('salary_preferences_annual_gross_base', {}).get('contract', {})
    for rate in ('day_rate', 'hourly_rate'):
        floor = contract_pref.get(rate, {}).get(salary.get('currency'))
        if job.get('engagement') == 'contractor' and floor and salary.get(rate + '_max'):
            compensation = min(100, round(80 * salary[rate + '_max'] / floor, 1))
    components = {'technical': technical, 'authorization': authorization, 'compensation': compensation,
                  'growth': 75 if job.get('technical_ownership') else 50, 'location': location}
    score = round(sum(WEIGHTS[k] * v for k, v in components.items()), 1)
    fit = job.get('career_ops_score')  # The full career-ops evaluation decides fit when present.
    if isinstance(fit, (int, float)):
        below = fit < config.get('minimum_career_ops_score', MANUAL_MIN_CAREER_OPS_SCORE)
    else:
        below = score < config['minimum_score']
    if below:
        blockers.append('Below configured match threshold')
    return {'score': score, 'eligible': not blockers, 'blockers': list(dict.fromkeys(blockers)),
            'components': components, 'age_days': age, 'fresh_14_days': age is not None and 0 <= age <= config['posted_within_days']}


class Journal:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / 'data').mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'data/autoapply.sqlite', timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS jobs (
            key TEXT PRIMARY KEY, url TEXT UNIQUE, company TEXT, title TEXT, location TEXT,
            requisition TEXT, status TEXT, payload TEXT, assessment TEXT, run_day TEXT,
            claim TEXT, updated TEXT, artifact TEXT, evidence TEXT, confirmation_url TEXT)''')
        self.db.commit()

    def close(self):
        self.db.close()

    def find(self, job):
        url = canonical_url(job['url'])
        row = self.db.execute('SELECT * FROM jobs WHERE key=? OR url=?', (identity(job), url)).fetchone()
        if row is None and job.get('requisition'):
            row = self.db.execute('SELECT * FROM jobs WHERE company=? AND requisition=?',
                                  (norm(job['company']), norm(job['requisition']))).fetchone()
        return row

    def ingest(self, job, profile, config, today):
        for field in ('company', 'title', 'location', 'url'):
            if not isinstance(job.get(field), str) or not job[field].strip():
                raise ValueError('Missing identity field: ' + field)
        existing = self.find(job)
        if existing and existing['status'] in TERMINAL:
            return dict(existing)  # Re-discovery cannot erase past submission/uncertainty.
        result = assess(job, profile, config, today)
        key = existing['key'] if existing else identity(job)
        self.db.execute('''INSERT INTO jobs(key,url,company,title,location,requisition,status,payload,assessment,updated)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
            payload=excluded.payload,assessment=excluded.assessment,status=excluded.status,updated=excluded.updated''',
            (key, canonical_url(job['url']), norm(job['company']), job['title'], job['location'], norm(job.get('requisition', '')),
             'ready' if result['eligible'] else 'rejected', json.dumps(job), json.dumps(result), now().isoformat()))
        self.db.commit()
        return dict(self.db.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone())

    def migrate(self):
        """Protect existing confirmed and pending forms; never seed stale leads as ready."""
        tracker = read_json(self.root / 'data/applications.json', {})
        registry = read_json(self.root / 'data/opportunities.json', {}).get('opportunities', [])
        by_id = {j['id']: j for j in registry}
        records = {a['id']: a for a in tracker.get('applications', [])}
        records.update(tracker.get('attempts', {}))
        for old_id, record in records.items():
            job = dict(by_id.get(old_id, {}))
            job.update(company=record['company'], title=record.get('role', job.get('title', '')), url=record['url'])
            job.setdefault('location', 'Unknown')
            if self.find(job):
                continue
            status = 'submitted' if record['status'] == 'applied' else 'attention'
            self.db.execute('''INSERT OR IGNORE INTO jobs(key,url,company,title,location,requisition,status,payload,
                assessment,run_day,updated,evidence,confirmation_url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (identity(job), canonical_url(job['url']), norm(job['company']), job['title'], job['location'],
                 norm(job.get('requisition', '')), status, json.dumps(job), '{}', record.get('applied_date'),
                 now().isoformat(), record.get('evidence', ''), record.get('confirmation_url', '')))
        self.db.commit()

    def expire(self):
        cutoff = (now() - timedelta(hours=2)).isoformat()
        self.db.execute("UPDATE jobs SET status='uncertain',evidence='Interrupted run; reconcile with employer before any retry' WHERE status IN ('reserved','submitting') AND updated<?", (cutoff,))
        self.db.commit()

    def claim(self, key, profile, config, day):
        if not config.get('enabled') or not config.get('auto_submit') or not config.get('authorization'):
            raise ValueError('Auto submission is disabled or has no saved authorization')
        missing = onboarding_missing(profile)
        if missing:
            raise ValueError('Incomplete onboarding: ' + ', '.join(missing))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone()
            if not row or row['status'] != 'ready':
                raise ValueError('Job is not ready, already claimed, submitted, or needs attention')
            assessment = assess(json.loads(row['payload']), profile, config, day)
            if not assessment['eligible']:
                raise ValueError('; '.join(assessment['blockers']))
            count = self.db.execute("SELECT COUNT(*) FROM jobs WHERE run_day=? AND status IN ('reserved','submitting','submitted','uncertain','attention')", (str(day),)).fetchone()[0]
            if count >= config['daily_limit']:
                raise ValueError('Daily application limit reached')
            company_count = self.db.execute('SELECT COUNT(*) FROM jobs WHERE run_day=? AND company=?', (str(day), row['company'])).fetchone()[0]
            if company_count >= config['max_applications_per_company_per_day']:
                raise ValueError('Company daily application limit reached')
            token = secrets.token_hex(12)
            self.db.execute("UPDATE jobs SET status='reserved',claim=?,run_day=?,updated=? WHERE key=?", (token, str(day), now().isoformat(), key))
            self.db.commit()
            return token
        except Exception:
            self.db.rollback()
            raise

    def begin_submit(self, key, token, artifact, profile, config, day):
        path = Path(artifact).resolve()
        if not path.is_file() or not path.is_relative_to(self.root.resolve() / 'applications'):
            raise ValueError('Submission document must exist inside the application folder')
        if not config.get('enabled') or not config.get('auto_submit') or not config.get('authorization'):
            raise ValueError('Auto submission is paused')
        if onboarding_missing(profile):
            raise ValueError('Onboarding became incomplete; submission blocked')
        row = self.db.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone()
        if not row or row['status'] != 'reserved' or row['claim'] != token:
            raise ValueError('Reservation token mismatch or submission already started')
        if row['run_day'] != str(day):
            raise ValueError('Reservation is from a previous day; reconcile before continuing')
        assessment = assess(json.loads(row['payload']), profile, config, day)
        if not assessment['eligible']:
            raise ValueError('; '.join(assessment['blockers']))
        changed = self.db.execute("UPDATE jobs SET status='submitting',artifact=?,updated=? WHERE key=? AND claim=? AND status='reserved'", (str(path), now().isoformat(), key, token)).rowcount
        self.db.commit()
        if changed != 1:
            raise ValueError('Submission already started by another runner')

    def result(self, key, token, outcome, evidence, confirmation_url=''):
        if outcome not in {'submitted', 'attention', 'uncertain'} or not evidence.strip():
            raise ValueError('A real browser outcome and nonempty evidence are required')
        row = self.db.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone()
        if not row or row['claim'] != token or row['status'] not in {'reserved', 'submitting'}:
            raise ValueError('No active reservation for this outcome')
        if outcome == 'submitted' and (row['status'] != 'submitting' or not confirmation_url):
            raise ValueError('Confirmed submission requires a submission intent and employer confirmation URL')
        if confirmation_url:
            canonical_url(confirmation_url)
        changed = self.db.execute("UPDATE jobs SET status=?,evidence=?,confirmation_url=?,updated=? WHERE key=? AND claim=? AND status IN ('reserved','submitting')",
                                 (outcome, evidence, confirmation_url, now().isoformat(), key, token)).rowcount
        self.db.commit()
        if changed != 1:
            raise ValueError('Outcome already recorded; reconcile instead of overwriting')

    def mark(self, key, outcome, note, day):
        """Record the candidate's own action on a job the agent could not submit."""
        if outcome not in {'manual_applied', 'dismissed'} or not note.strip():
            raise ValueError('Outcome must be manual_applied or dismissed, with a nonempty note')
        changed = self.db.execute("UPDATE jobs SET status=?,evidence=?,run_day=COALESCE(run_day,?),updated=? WHERE key=? AND status IN ('ready','rejected','attention','uncertain')",
                                  (outcome, note, str(day), now().isoformat(), key)).rowcount
        self.db.commit()
        if changed != 1:
            raise ValueError('Unknown key, already submitted, or currently being submitted by the agent')

    def manual_queue(self):
        """Good matches the agent could not or must not submit itself, best first."""
        queue = []
        for row in self.rows():
            payload = json.loads(row['payload'] or '{}')
            assessment = json.loads(row['assessment'] or '{}')
            fit = payload.get('career_ops_score')
            if row['status'] in {'attention', 'uncertain'}:
                reasons = [row['evidence'] or 'Agent attempt needs your action']
            elif row['status'] == 'rejected':
                blockers = assessment.get('blockers', [])
                good = fit >= MANUAL_MIN_CAREER_OPS_SCORE if isinstance(fit, (int, float)) else False
                if not good or any(b.startswith(HARD_BLOCKERS) for b in blockers):
                    continue
                reasons = [b for b in blockers if b != 'Below configured match threshold'] or blockers
            else:
                continue
            queue.append({'key': row['key'], 'company': payload.get('company', row['company']), 'title': row['title'],
                          'location': row['location'], 'url': row['url'], 'status': row['status'],
                          'career_ops_score': fit, 'policy_score': assessment.get('score'),
                          'report': payload.get('career_ops_report'), 'documents': payload.get('documents_folder'),
                          'reasons': reasons})
        queue.sort(key=lambda q: (q['status'] == 'rejected', -(q['career_ops_score'] or 0)))
        return queue

    def rows(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM jobs ORDER BY updated DESC')]

    def sync_tracker(self):
        path = self.root / 'data/applications.json'
        tracker = read_json(path, {'applications': [], 'stats': {}})
        existing_urls = {canonical_url(a['url']) for a in tracker.get('applications', [])}
        for row in self.rows():
            if row['status'] in {'submitted', 'manual_applied'} and row['url'] not in existing_urls:
                tracker.setdefault('applications', []).append({
                    'id':row['key'], 'company':json.loads(row['payload'])['company'],
                    'role':row['title'], 'url':row['url'], 'status':'applied',
                    'channel':'agent' if row['status'] == 'submitted' else 'manual',
                    'applied_date':row['run_day'], 'evidence':row['evidence'],
                    'confirmation_url':row['confirmation_url'], 'approved':True})
                existing_urls.add(row['url'])
        tracker.setdefault('stats', {})['total'] = len(tracker.get('applications', []))
        tracker['stats']['applied'] = sum(a['status'] == 'applied' for a in tracker.get('applications', []))
        write_json(path, tracker)


def setup(root, args):
    root = Path(root)
    profile = read_json(root / 'data/profile.json', {})
    config = read_json(root / 'data/autoapply-config.json', default_config())
    if args.resume:
        resume = Path(args.resume).resolve()
        if not resume.is_file():
            raise ValueError('Resume file does not exist')
        profile['resume_file'] = str(resume)
    if not profile.get('resume_file') or not Path(profile['resume_file']).is_file():
        raise ValueError('Supply --resume or complete interactive onboarding')
    managed = root / 'resume/source_resume.pdf'
    managed.parent.mkdir(parents=True, exist_ok=True)
    source = Path(profile['resume_file'])
    if source.suffix.lower() != '.pdf':
        raise ValueError('Onboarding currently accepts a PDF resume')
    if source.resolve() != managed.resolve():
        managed.write_bytes(source.read_bytes())
    profile['original_resume_file'] = profile.get('original_resume_file', str(source))
    profile['resume_file'] = str(managed.resolve())
    try:
        from pypdf import PdfReader
        text = '\n\n'.join(page.extract_text() or '' for page in PdfReader(managed).pages)
        (root / 'resume/source_resume_extracted.txt').write_text(text, encoding='utf-8')
    except ImportError:
        if not (root / 'resume/master_resume.md').is_file():
            raise ValueError('Use project Python environment with pypdf to extract the resume')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', args.time):
        raise ValueError('Time must be HH:MM in 24-hour format')
    ZoneInfo(args.timezone)
    if not 1 <= args.limit <= 50:
        raise ValueError('Daily limit must be between 1 and 50')
    config.update(run_time=args.time, timezone=args.timezone, daily_limit=args.limit,
                  onboarding_complete=not onboarding_missing(profile))
    if args.auto_submit:
        config.update(auto_submit=True, authorization={'source': 'Explicit user request for daily autonomous matching applications', 'recorded_at': now().isoformat(), 'scope': 'Matching jobs only; recruiter outreach excluded'})
        profile.setdefault('workflow', {}).update(auto_submit=True,
            approval_required_before_each=['Recruiter email or LinkedIn outreach'],
            standing_application_authorization='Daily automatic submission for jobs passing saved eligibility policy')
    write_json(root / 'data/profile.json', profile)
    write_json(root / 'data/autoapply-config.json', config)
    journal = Journal(root)
    journal.migrate()
    journal.close()
    return {'config': config, 'missing': onboarding_missing(profile)}


def onboard(root):
    """Ask once, only for missing core fields. Re-running preserves saved answers."""
    profile = read_json(root / 'data/profile.json', {})
    personal = profile.setdefault('personal', {})
    for key, label in [('name','Full name'),('email','Email'),('phone','Phone with country code'),('location','Current city/country'),('citizenship','Citizenship')]:
        if not personal.get(key):
            personal[key] = input(label + ': ').strip()
    if not profile.get('resume_file') or not Path(profile['resume_file']).is_file():
        profile['resume_file'] = input('Full path to PDF resume: ').strip().strip('"')
    defaults = profile.setdefault('application_defaults', {})
    if not defaults.get('notice_period'):
        defaults['notice_period'] = input('Notice period / availability: ').strip()
    pref = profile.setdefault('preferences', {})
    if not pref.get('target_roles_priority'):
        pref['target_roles_priority'] = [v.strip() for v in input('Target roles, comma separated: ').split(',') if v.strip()]
    auth = profile.setdefault('work_authorization', {})
    if not auth.get('home_country'):
        auth['home_country'] = input('Country you live in now (e.g. India): ').strip() or 'India'
    home_country = auth['home_country']
    if not isinstance(home(profile)[1], bool):
        auth['home_authorization'] = input(f'Authorized to work in {home_country}? yes/no: ').strip().lower() == 'yes'
    if not pref.get('location_priority'):
        country = input(f'Target country for relocation (blank for {home_country} remote only): ').strip()
        cities = [v.strip() for v in input('Target cities, comma separated (blank for remote): ').split(',') if v.strip()]
        modes = [v.strip() for v in input('Allowed work modes: remote, hybrid, onsite (comma separated): ').split(',') if v.strip()]
        pref['location_priority'] = ([{'priority':1,'country':country,'cities':cities,'work_modes':modes,'sponsorship_required':True}] if country else []) + ([{'priority':3,'work_mode':f'Fully remote from {home_country}','explicit_home_eligibility_required':True}] if 'remote' in modes else [])
        pref['allowed_work_modes'] = modes
    if 'europe_requires_employer_sponsorship' not in auth:
        auth['europe_requires_employer_sponsorship'] = input('Require employer sponsorship for relocation? yes/no: ').strip().lower() == 'yes'
    if not pref.get('salary_preferences_annual_gross_base'):
        currency = input('Preferred annual base currency (e.g. INR, EUR): ').strip().upper()
        minimum = int(input('Preferred minimum annual base (not a hard exclusion): ').strip())
        pref['salary_preferences_annual_gross_base'] = {'remote_home_equivalent': {'currency':currency,'min_preferred':minimum}}
    write_json(root / 'data/profile.json', profile)
    return {'saved':True,'missing':onboarding_missing(profile), 'next':'Review extracted resume into experience/education/skills before enabling auto-submit. See ONBOARDING.md.'}


def plan(root):
    root = Path(root)
    profile = read_json(root / 'data/profile.json', {})
    config = read_json(root / 'data/autoapply-config.json', default_config())
    today = now().astimezone(ZoneInfo(config['timezone'])).date()
    journal = Journal(root)
    journal.migrate()
    journal.expire()
    rows = journal.rows()
    journal.sync_tracker()
    ready = []
    for row in rows:
        if row['status'] == 'ready':
            checked = assess(json.loads(row['payload']), profile, config, today)
            if checked['eligible']:
                ready.append({'key':row['key'], 'job':json.loads(row['payload']), 'assessment':checked})
    ready.sort(key=lambda r:(-r['assessment']['score'], not r['assessment']['fresh_14_days']))
    report = {'date':str(today),'enabled':config['enabled'],'auto_submit':config['auto_submit'],
              'onboarding_missing':onboarding_missing(profile),'daily_limit':config['daily_limit'],
              'search_preferences':profile.get('preferences',{}), 'ready':ready[:config['daily_limit']],
              'attention':[{'key':r['key'],'company':r['company'],'title':r['title'],'status':r['status'],'reason':r['evidence']} for r in rows if r['status'] in {'attention','uncertain','submitting','reserved'}],
              'submitted_count':sum(r['status']=='submitted' for r in rows),
              'runner_instructions':str(root / 'DAILY_RUN.md')}
    journal.close()
    write_json(root / 'data/daily-plan.json', report)
    return report


def write_manual_queue(root, queue, today):
    lines = [f'# Apply manually ({today})', '',
             'Strong matches the agent could not submit, or must not submit without you. '
             'After applying, record it so the agent never retries or re-lists it:', '',
             '```powershell',
             f'& "{sys.executable}" "{Path(root) / "autoapply.py"}" mark <key> --as manual_applied --note "Applied via portal"',
             f'& "{sys.executable}" "{Path(root) / "autoapply.py"}" mark <key> --as dismissed --note "Not interested"',
             '```', '']
    if not queue:
        lines.append('Nothing waiting for you today.')
    for item in queue:
        score = f"{item['career_ops_score']}/5" if item['career_ops_score'] is not None else 'n/a'
        lines += [f"## {item['company']}: {item['title']}", '',
                  f"- Location: {item['location']}  |  Fit (career-ops): {score}  |  Status: {item['status']}",
                  f"- Apply: {item['url']}"]
        if item['report']:
            lines.append(f"- Evaluation: {item['report']}")
        if item['documents']:
            lines.append(f"- Tailored CV / cover letter: {item['documents']}")
        lines += ['- Why it needs you: ' + '; '.join(item['reasons']), f"- Key: `{item['key']}`", '']
    path = Path(root) / 'MANUAL_APPLY.md'
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=ROOT)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('onboard')
    init = sub.add_parser('setup')
    init.add_argument('--resume')
    init.add_argument('--time', default='09:00')
    init.add_argument('--timezone', default='Asia/Kolkata')
    init.add_argument('--limit', type=int, default=10)
    init.add_argument('--auto-submit', action='store_true')
    sub.add_parser('plan')
    sub.add_parser('status')
    sub.add_parser('pause')
    sub.add_parser('resume')
    ingest = sub.add_parser('ingest')
    ingest.add_argument('file', type=Path)
    claim = sub.add_parser('claim')
    claim.add_argument('key')
    intent = sub.add_parser('begin-submit')
    intent.add_argument('key'); intent.add_argument('--claim', required=True); intent.add_argument('--artifact', required=True)
    result = sub.add_parser('result')
    result.add_argument('key'); result.add_argument('--claim', required=True)
    result.add_argument('--outcome', required=True, choices=['submitted','attention','uncertain'])
    result.add_argument('--evidence', required=True); result.add_argument('--confirmation-url', default='')
    export = sub.add_parser('export-documents')
    export.add_argument('folder', type=Path)
    sub.add_parser('manual-queue')
    mark = sub.add_parser('mark')
    mark.add_argument('key'); mark.add_argument('--as', dest='outcome', required=True, choices=['manual_applied','dismissed'])
    mark.add_argument('--note', required=True)
    args = parser.parse_args(argv)
    root = args.home.resolve()
    try:
        if args.command == 'onboard':
            output = onboard(root)
        elif args.command == 'setup':
            output = setup(root, args)
        elif args.command in {'plan','status'}:
            output = plan(root)
        elif args.command == 'export-documents':
            from documents import export_folder
            folder = args.folder.resolve()
            if not folder.is_relative_to(root / 'applications'):
                raise ValueError('Document export folder must be under applications/')
            output = export_folder(folder)
        elif args.command in {'pause','resume'}:
            path = root / 'data/autoapply-config.json'
            config = read_json(path, default_config())
            config['enabled'] = args.command == 'resume'
            write_json(path, config)
            output = {'enabled':config['enabled'], 'note':'Pausing prevents submissions even if the scheduler still wakes the agent.'}
        else:
            config = read_json(root / 'data/autoapply-config.json', default_config())
            profile = read_json(root / 'data/profile.json', {})
            today = now().astimezone(ZoneInfo(config['timezone'])).date()
            journal = Journal(root)
            journal.migrate()
            journal.expire()
            try:
                if args.command == 'ingest':
                    jobs = read_json(args.file)
                    if not isinstance(jobs, list):
                        raise ValueError('Discovery input must be a JSON list')
                    output = [{'key':r['key'],'status':r['status'],'assessment':json.loads(r['assessment'])} for job in jobs for r in [journal.ingest(job,profile,config,today)]]
                elif args.command == 'claim':
                    output = {'key':args.key,'claim':journal.claim(args.key,profile,config,today)}
                elif args.command == 'begin-submit':
                    journal.begin_submit(args.key,args.claim,args.artifact,profile,config,today)
                    output = {'status':'submitting','key':args.key}
                elif args.command == 'mark':
                    journal.mark(args.key,args.outcome,args.note,today)
                    journal.sync_tracker()
                    write_manual_queue(root,journal.manual_queue(),today)
                    output = {'status':args.outcome,'key':args.key}
                elif args.command == 'manual-queue':
                    queue = journal.manual_queue()
                    output = {'file':str(write_manual_queue(root,queue,today)),'count':len(queue),'queue':queue}
                else:
                    journal.result(args.key,args.claim,args.outcome,args.evidence,args.confirmation_url)
                    journal.sync_tracker()
                    output = {'status':args.outcome,'key':args.key}
            finally:
                journal.close()
        print(json.dumps(output,ensure_ascii=False,indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

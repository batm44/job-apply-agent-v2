import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from zipfile import ZipFile

from autoapply import Journal, assess, canonical_url, default_config, identity, norm, onboarding_missing, write_json
from documents import export_folder

TODAY = date(2026, 11, 1)


def evidence(**extra):
    return dict(source_type='official_employer',url='https://careers.example.com/job/123',
                checked_on=str(TODAY),quote='Employer promises work visa support for permanent hires.',**extra)


def profile(root):
    resume = root/'resume.pdf'; resume.write_bytes(b'test resume')
    return {'personal':{'name':'Test Candidate','email':'candidate@example.com','phone':'+919999999999',
                        'location':'India','citizenship':'Indian'},'resume_file':str(resume),
            'experience':[{'bullets':['Owned production model deployment and credit modelling.']}],
            'education':[{'qualification':'B.Tech'}], 'interests':['Production RAG'],
            'skills_evidence':{'resume_listed':['Python']},
            'application_defaults':{'notice_period':'3 months'},'work_authorization':{'india_authorization':True},
            'preferences':{'target_roles_priority':['Senior Data Scientist'],
                'location_priority':[{'priority':1,'country':'Netherlands','cities':['Amsterdam'],'work_modes':['Hybrid','On-site']},
                                     {'priority':3,'work_mode':'Fully remote from India'}],
                'salary_preferences_annual_gross_base':{'Netherlands':{'currency':'EUR','min_preferred':90000}}}}


def job(**changes):
    result={'company':'Example','title':'Senior Data Scientist','location':'Amsterdam','country':'Netherlands',
        'work_mode':'hybrid','seniority':'senior','url':'https://careers.example.com/jobs/123?utm_source=test',
        'requisition':'123','posted_on':'2026-10-30','posting_evidence':evidence(),
        'sponsorship':'verified','sponsorship_evidence':evidence(country='Netherlands'),
        'technical_ownership':True,'engagement':'employment','requirements':[
            {'name':'Production models','status':'met','mandatory':True,'evidence_kind':'production',
             'profile_reference':'/experience/0/bullets/0','evidence':'Owned production model deployment'}]}
    result.update(changes)
    return result


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.profile=profile(self.root); self.config=default_config()

    def assess(self, candidate):
        return assess(candidate,self.profile,self.config,TODAY)

    def test_eligible_job_and_undisclosed_salary(self):
        decision=self.assess(job())
        self.assertTrue(decision['eligible']); self.assertEqual(decision['components']['compensation'],50)

    def test_no_sponsor_register_substitution(self):
        self.assertFalse(self.assess(job(sponsorship='needs_confirmation'))['eligible'])

    def test_wrong_country_policy(self):
        self.assertFalse(self.assess(job(sponsorship_evidence=evidence(country='Germany')))['eligible'])

    def test_stale_official_evidence(self):
        proof=evidence();proof['checked_on']='2026-10-01'
        self.assertFalse(self.assess(job(posting_evidence=proof))['eligible'])

    def test_unknown_future_and_old_dates(self):
        for value in [None,'2026-11-02','2026-09-01']:
            self.assertFalse(self.assess(job(posted_on=value))['eligible'])

    def test_remote_eu_only_rejected(self):
        self.assertFalse(self.assess(job(work_mode='remote',remote_allowed_countries=['Germany'],remote_evidence=evidence()))['eligible'])

    def test_india_remote_requires_arrangement(self):
        remote=job(work_mode='remote',remote_allowed_countries=['India'],remote_evidence=evidence())
        self.assertTrue(self.assess(remote)['eligible'])
        remote['engagement']='unknown';self.assertFalse(self.assess(remote)['eligible'])

    def test_contracting_is_distinguished(self):
        remote=job(work_mode='remote',remote_allowed_countries=['India'],remote_evidence=evidence(),engagement='contractor')
        self.assertTrue(self.assess(remote)['eligible'])

    def test_saved_engagement_and_work_rights_enforced(self):
        remote=job(work_mode='remote',remote_allowed_countries=['India'],remote_evidence=evidence(),engagement='contractor')
        self.profile['preferences']['allowed_engagements']=['employment']
        self.assertFalse(self.assess(remote)['eligible'])
        remote['engagement']='employment';self.profile['work_authorization']['india_authorization']=False
        self.assertFalse(self.assess(remote)['eligible'])

    def test_remote_requires_saved_location_preference(self):
        self.profile['preferences']['location_priority'].pop()
        remote=job(work_mode='remote',remote_allowed_countries=['India'],remote_evidence=evidence())
        self.assertFalse(self.assess(remote)['eligible'])

    def test_role_family_and_employer_preferences(self):
        self.assertFalse(self.assess(job(title='Senior Machine Learning Engineer'))['eligible'])
        self.assertTrue(self.assess(job(title='Senior Machine Learning Scientist'))['eligible'])
        self.profile['preferences']['excluded_employers']=['Example']
        self.assertFalse(self.assess(job())['eligible'])

    def test_unmet_mandatory_degree(self):
        candidate=job();candidate['requirements'].append({'name':'Masters','status':'unknown','mandatory':True})
        self.assertFalse(self.assess(candidate)['eligible'])

    def test_interest_cannot_be_production_evidence(self):
        candidate=job();candidate['requirements'][0].update(profile_reference='/interests/0',evidence='Production RAG')
        self.assertFalse(self.assess(candidate)['eligible'])

    def test_skills_list_is_not_production_history(self):
        candidate=job();candidate['requirements'][0].update(profile_reference='/skills_evidence/resume_listed/0',evidence='Python')
        self.assertFalse(self.assess(candidate)['eligible'])

    def test_fabricated_quote_rejected(self):
        candidate=job();candidate['requirements'][0]['evidence']='Built production RAG agents'
        self.assertFalse(self.assess(candidate)['eligible'])

    def test_wrong_work_mode_and_city(self):
        self.profile['preferences']['allowed_work_modes']=['remote']
        self.assertFalse(self.assess(job())['eligible'])
        del self.profile['preferences']['allowed_work_modes']
        self.assertFalse(self.assess(job(location='Rotterdam'))['eligible'])

    def test_unknown_level_and_non_hands_on_management(self):
        self.assertFalse(self.assess(job(seniority='unknown'))['eligible'])
        self.assertFalse(self.assess(job(seniority='director',hands_on=False))['eligible'])

    def test_malformed_requirements(self):
        with self.assertRaises(ValueError):self.assess(job(requirements=['Python']))

    def test_canonical_tracking_urls(self):
        self.assertEqual(canonical_url('https://www.example.com/jobs/123/apply?utm_source=x'), 'https://example.com/jobs/123')
        for bad in ['http://example.com','javascript:alert(1)','https://user:secret@example.com']:
            with self.assertRaises(ValueError):canonical_url(bad)

    def test_missing_setup_identified(self):
        self.assertEqual(onboarding_missing(self.profile),[])
        self.profile['personal'].pop('phone');self.assertIn('personal.phone',onboarding_missing(self.profile))


    def test_home_country_needs_no_sponsorship(self):
        self.profile['preferences']['location_priority'].append(
            {'priority':4,'country':'India','cities':['Bengaluru'],'work_modes':['Hybrid'],'sponsorship_required':False})
        india=job(location='Bengaluru',country='India',sponsorship=None,sponsorship_evidence=None)
        decision=self.assess(india)
        self.assertNotIn('Official sponsorship for this role/country needs confirmation',decision['blockers'])
        self.assertEqual(decision['components']['authorization'],100)
        self.profile['work_authorization']['india_authorization']=False
        self.assertFalse(self.assess(india)['eligible'])

    def test_relocation_requires_permanent_contract(self):
        self.profile['preferences']['location_priority'][0]['permanent_only']=True
        self.assertIn('Permanent employment contract unconfirmed (required for relocation)',self.assess(job())['blockers'])
        self.assertIn('Non-permanent contract excluded for relocation',self.assess(job(contract_type='fixed_term'))['blockers'])
        self.assertTrue(self.assess(job(contract_type='permanent'))['eligible'])

    def test_unstated_sponsorship_and_contract_allowed_when_opted_in(self):
        self.profile['preferences']['location_priority'][0]['permanent_only']=True
        unstated=job(sponsorship='needs_confirmation',sponsorship_evidence=None,career_ops_score=4.3)
        self.assertFalse(self.assess(unstated)['eligible'])
        self.profile['preferences'].update(apply_when_sponsorship_unstated=True,apply_when_contract_type_unstated=True)
        decision=self.assess(unstated)
        self.assertTrue(decision['eligible'],decision['blockers'])
        self.assertEqual(decision['components']['authorization'],70)
        self.assertFalse(self.assess(dict(unstated,career_ops_score=3.6))['eligible'])
        self.assertFalse(self.assess(dict(unstated,sponsorship='unavailable'))['eligible'])
        self.assertFalse(self.assess(dict(unstated,existing_work_rights_required=True))['eligible'])
        self.assertFalse(self.assess(dict(unstated,contract_type='fixed_term'))['eligible'])

    def test_contract_paid_in_eur_or_usd_only(self):
        self.profile['preferences']['location_priority'][1]['contractor_pay_currencies']=['EUR','USD']
        self.profile['preferences']['salary_preferences_annual_gross_base']['contract']={'day_rate':{'EUR':650}}
        remote=job(work_mode='remote',remote_allowed_countries=['India'],remote_evidence=evidence(),engagement='contractor')
        self.assertTrue(self.assess(dict(remote,salary=None))['eligible'])
        self.assertFalse(self.assess(dict(remote,salary={'currency':'INR','day_rate_max':40000}))['eligible'])
        paid=self.assess(dict(remote,salary={'currency':'EUR','day_rate_max':650}))
        self.assertEqual(paid['components']['compensation'],80)

    def test_analog_science_titles_match_data_scientist_target(self):
        for title in ['Senior Decision Scientist, Fraud','Analytics Manager - Consumer Credit Risk & Underwriting']:
            self.assertNotIn('Role family outside configured targets',self.assess(job(title=title))['blockers'])
        self.assertIn('Role family outside configured targets',self.assess(job(title='Senior Product Manager'))['blockers'])

    def test_home_country_is_configurable(self):
        self.profile['work_authorization']={'home_country':'Brazil','home_authorization':True}
        remote=job(work_mode='remote',remote_allowed_countries=['Brazil'],remote_evidence=evidence())
        self.assertTrue(self.assess(remote)['eligible'])
        self.assertFalse(self.assess(dict(remote,remote_allowed_countries=['India']))['eligible'])
        del self.profile['work_authorization']['home_authorization']
        self.assertIn('work_authorization.home_authorization',onboarding_missing(self.profile))

    def test_ai_engineer_titles_need_generative_target(self):
        self.assertFalse(self.assess(job(title='Senior AI Engineer'))['eligible'])
        self.profile['preferences']['target_roles_priority'].append('GenAI / LLM Engineer')
        self.assertTrue(self.assess(job(title='Senior AI Engineer'))['eligible'])


class JournalTests(PolicyTests):
    def setUp(self):
        super().setUp()
        self.config.update(auto_submit=True,authorization={'source':'test'},daily_limit=2)
        self.journal=Journal(self.root);self.addCleanup(self.journal.close)

    def ready(self, **changes):
        row=self.journal.ingest(job(**changes),self.profile,self.config,TODAY)
        return row['key']

    def test_duplicate_alias_and_requisition(self):
        key=self.ready()
        alias=job(url='https://other.example.com/123',title='Senior Data Scientist - Other label')
        self.assertEqual(self.journal.ingest(alias,self.profile,self.config,TODAY)['key'],key)
        self.assertEqual(len(self.journal.rows()),1)

    def test_single_claim_across_two_connections(self):
        key=self.ready();self.journal.claim(key,self.profile,self.config,TODAY)
        other=Journal(self.root)
        try:
            with self.assertRaises(ValueError):other.claim(key,self.profile,self.config,TODAY)
        finally:other.close()

    def test_daily_budget_reserves_inflight(self):
        self.config['daily_limit']=1
        key=self.ready();self.journal.claim(key,self.profile,self.config,TODAY)
        second=self.ready(company='Other',url='https://other.example.com/456',requisition='456')
        with self.assertRaisesRegex(ValueError,'Daily'):self.journal.claim(second,self.profile,self.config,TODAY)

    def test_pause_prevents_claim_and_submit(self):
        key=self.ready();self.config['enabled']=False
        with self.assertRaises(ValueError):self.journal.claim(key,self.profile,self.config,TODAY)

    def test_submission_needs_intent_and_receipt(self):
        key=self.ready();token=self.journal.claim(key,self.profile,self.config,TODAY)
        with self.assertRaises(ValueError):self.journal.result(key,token,'submitted','Clicked button','https://example.com/success')
        folder=self.root/'applications'/key;folder.mkdir(parents=True);artifact=folder/'resume.docx';artifact.write_bytes(b'doc')
        self.journal.begin_submit(key,token,str(artifact),self.profile,self.config,TODAY)
        with self.assertRaises(ValueError):self.journal.result(key,token,'submitted','Employer receipt missing')
        self.journal.result(key,token,'submitted','Application received','https://example.com/success')
        with self.assertRaises(ValueError):self.journal.result(key,token,'attention','Must not overwrite success')
        self.journal.sync_tracker()
        history=json.loads((self.root/'data/applications.json').read_text())
        self.assertEqual(history['stats']['applied'],1)

    def test_recheck_consent_onboarding_and_day_before_submit(self):
        key=self.ready();token=self.journal.claim(key,self.profile,self.config,TODAY)
        folder=self.root/'applications'/key;folder.mkdir(parents=True)
        artifact=folder/'resume.docx';artifact.write_bytes(b'doc')
        self.config['enabled']=False
        with self.assertRaises(ValueError):self.journal.begin_submit(key,token,artifact,self.profile,self.config,TODAY)
        self.config['enabled']=True;self.config['authorization']=None
        with self.assertRaises(ValueError):self.journal.begin_submit(key,token,artifact,self.profile,self.config,TODAY)
        self.config['authorization']={'source':'test'};saved=self.profile['personal'].pop('phone')
        with self.assertRaises(ValueError):self.journal.begin_submit(key,token,artifact,self.profile,self.config,TODAY)
        self.profile['personal']['phone']=saved
        with self.assertRaisesRegex(ValueError,'previous day'):self.journal.begin_submit(key,token,artifact,self.profile,self.config,TODAY+timedelta(days=1))

    def test_uncertain_never_requeued_by_discovery(self):
        key=self.ready();token=self.journal.claim(key,self.profile,self.config,TODAY)
        self.journal.result(key,token,'uncertain','Lost connection during submit')
        self.assertEqual(self.journal.ingest(job(),self.profile,self.config,TODAY)['status'],'uncertain')

    def test_eligibility_rechecked_before_claim(self):
        key=self.ready();self.profile['experience']=[]
        with self.assertRaises(ValueError):self.journal.claim(key,self.profile,self.config,TODAY)

    def test_legacy_submitted_and_pending_import(self):
        write_json(self.root/'data/opportunities.json',{'opportunities':[dict(job(),id='old')]})
        write_json(self.root/'data/applications.json',{'applications':[{'id':'old','company':'Example','role':'Senior Data Scientist','url':job()['url'],'status':'applied','applied_date':str(TODAY),'evidence':'Employer receipt'}]})
        self.journal.migrate();self.journal.migrate()
        self.assertEqual(len(self.journal.rows()),1)
        self.assertEqual(self.journal.ingest(job(),self.profile,self.config,TODAY)['status'],'submitted')

    def test_interrupted_submission_blocks_retry(self):
        key=self.ready();self.journal.claim(key,self.profile,self.config,TODAY)
        self.journal.db.execute("UPDATE jobs SET updated='2000-01-01T00:00:00+00:00'");self.journal.db.commit();self.journal.expire()
        self.assertEqual(self.journal.rows()[0]['status'],'uncertain')

    def test_manual_queue_keeps_fixable_strong_matches(self):
        self.ready(sponsorship='needs_confirmation',career_ops_score=4.4,career_ops_report='reports/001.md')
        self.ready(company='Weak',url='https://careers.example.com/jobs/2',sponsorship='needs_confirmation',career_ops_score=3.1)
        self.ready(company='Closed',url='https://careers.example.com/jobs/3',closed=True,career_ops_score=4.8)
        queue=self.journal.manual_queue()
        self.assertEqual([q['company'] for q in queue],['Example'])
        self.assertIn('Official sponsorship for this role/country needs confirmation',queue[0]['reasons'])

    def test_failed_attempt_listed_first_then_marked_manually(self):
        self.ready(company='Fixable',url='https://careers.example.com/jobs/4',sponsorship='needs_confirmation',career_ops_score=4.9)
        key=self.ready();token=self.journal.claim(key,self.profile,self.config,TODAY)
        self.journal.result(key,token,'attention','CAPTCHA on submit')
        self.assertEqual([q['status'] for q in self.journal.manual_queue()],['attention','rejected'])
        self.journal.mark(key,'manual_applied','Applied via portal',TODAY);self.journal.sync_tracker()
        self.assertEqual(len(self.journal.manual_queue()),1)
        self.assertEqual(self.journal.ingest(job(),self.profile,self.config,TODAY)['status'],'manual_applied')
        tracker=json.loads((self.root/'data/applications.json').read_text(encoding='utf-8'))
        self.assertEqual(tracker['applications'][0]['channel'],'manual')
        with self.assertRaises(ValueError):self.journal.mark(key,'dismissed','again',TODAY)

    def test_exports_parseable_docx_and_escapes_xml(self):
        folder=self.root/'applications'/'docs';folder.mkdir(parents=True)
        (folder/'resume.md').write_text('# Test Candidate\nBanking & ML <production>\n',encoding='utf-8')
        paths=export_folder(folder)
        with ZipFile(paths['resume']) as z:
            from xml.etree import ElementTree
            ElementTree.fromstring(z.read('word/document.xml'))
            self.assertIn(b'&amp;',z.read('word/document.xml'))


if __name__=='__main__':unittest.main()

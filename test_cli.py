"""Full CLI integration tests with synthetic data; never contact an employer."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from autoapply import default_config, write_json
from test_autoapply import job, profile


SCRIPT = Path(__file__).with_name('autoapply.py')


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_json(self.root / 'data/profile.json', profile(self.root))
        config = default_config()
        config.update(auto_submit=True, authorization={'source': 'Synthetic test only'}, daily_limit=1)
        write_json(self.root / 'data/autoapply-config.json', config)
        today = datetime.now(ZoneInfo(config['timezone'])).date()
        vacancy = job(posted_on=str(today - timedelta(days=1)))
        vacancy['posting_evidence']['checked_on'] = str(today)
        vacancy['sponsorship_evidence']['checked_on'] = str(today)
        discovered = self.root / 'discovered.json'
        write_json(discovered, [vacancy])
        self.key = self.cli('ingest', str(discovered))[0]['key']

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), '--home', str(self.root), *args],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def document(self):
        folder = self.root / 'applications' / self.key
        folder.mkdir(parents=True)
        (folder / 'resume.md').write_text('# Synthetic Candidate\nOwned production models.\n', encoding='utf-8')
        return self.cli('export-documents', str(folder))['resume']

    def test_full_document_and_receipt_lifecycle_is_idempotent(self):
        initial = self.cli('plan')
        self.assertEqual(initial['onboarding_missing'], [])
        self.assertEqual(len(initial['ready']), 1)
        token = self.cli('claim', self.key)['claim']
        artifact = self.document()
        self.cli('begin-submit', self.key, '--claim', token, '--artifact', artifact)
        self.cli('result', self.key, '--claim', token, '--outcome', 'submitted',
                 '--evidence', 'Synthetic employer receipt in isolated integration test',
                 '--confirmation-url', 'https://careers.example.com/receipt')
        self.cli('claim', self.key, success=False)
        for _ in range(2):
            report = self.cli('status')
            self.assertEqual(report['submitted_count'], 1)
            self.assertEqual(report['ready'], [])
        tracker = json.loads((self.root / 'data/applications.json').read_text(encoding='utf-8'))
        self.assertEqual(len(tracker['applications']), 1)

    def test_pause_blocks_reserved_submission_and_other_claims(self):
        token = self.cli('claim', self.key)['claim']
        artifact = self.document()
        self.cli('pause')
        response = self.cli('begin-submit', self.key, '--claim', token, '--artifact', artifact, success=False)
        self.assertIn('paused', response['error'])
        self.cli('claim', self.key, success=False)
        self.assertEqual(self.cli('status')['submitted_count'], 0)


if __name__ == '__main__':
    unittest.main()

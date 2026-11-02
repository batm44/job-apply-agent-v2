"""Browser checks against synthetic pages; never apply to an employer."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from autoapply import Journal, default_config, write_json
from browser_mcp import Browser
from test_autoapply import TODAY, job, profile


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.browser = Browser(self.root)
        await self.browser.start()
        await self.browser.context.route('https://application.example/**', lambda route: route.fulfill(
            content_type='text/html', body='''<title>Synthetic application</title>
            <form><label>Name<input name="name"></label>
            <label>Location<select><option value="in">India</option></select></label>
            <label>Consent<input type="checkbox"></label>
            <label>Resume<input type="file"></label>
            <button type="button" onclick="document.querySelector('output').textContent='Reviewed'">Review</button>
            <button type="submit">Submit</button><output></output></form>'''))
        await self.browser.action('navigate', url='https://application.example/form')

    async def asyncTearDown(self):
        await self.browser.close()
        self.temp.cleanup()

    async def test_fill_upload_screenshot_and_submission_gate(self):
        await self.browser.action('fill', selector='input[name=name]', value='Synthetic Candidate')
        await self.browser.action('select', selector='select', value='in')
        await self.browser.action('check', selector='input[type=checkbox]', value='true')
        folder = self.root / 'applications' / 'test'
        folder.mkdir(parents=True)
        resume = folder / 'resume.txt'
        resume.write_text('Synthetic resume')
        await self.browser.action('upload', selector='input[type=file]', paths=[str(resume)])
        result = await self.browser.action('click', selector='text=Review')
        self.assertIn('Reviewed', json.dumps(result))
        result = await self.browser.action('screenshot', value=str(folder / 'review.png'))
        self.assertTrue(Path(result['path']).is_file())
        with self.assertRaises(ValueError):
            await self.browser.action('click', selector='button[type=submit]')
        with self.assertRaises(ValueError):
            await self.browser.action('submit', selector='button[type=submit]', key='unknown', claim='bad')
        with self.assertRaises(ValueError):
            self.browser.document(self.root / 'secrets.txt')
        with self.assertRaises(ValueError):
            self.browser.screenshot_path(self.root / 'outside.png')
        with self.assertRaises(ValueError):
            await self.browser.action('navigate', url='file:///C:/Windows/win.ini')

    async def test_submission_requires_real_intent_and_honors_pause(self):
        candidate = profile(self.root)
        config = default_config()
        config.update(auto_submit=True, authorization={'source': 'Synthetic test'})
        write_json(self.root / 'data/profile.json', candidate)
        write_json(self.root / 'data/autoapply-config.json', config)
        journal = Journal(self.root)
        try:
            key = journal.ingest(job(), candidate, config, TODAY)['key']
            claim = journal.claim(key, candidate, config, TODAY)
            with self.assertRaises(ValueError):
                self.browser.submission_intent(key, claim)
            artifact = self.root / 'applications' / key / 'resume.txt'
            artifact.parent.mkdir(parents=True)
            artifact.write_text('Synthetic resume')
            journal.begin_submit(key, claim, str(artifact), candidate, config, TODAY)
            self.browser.submission_intent(key, claim)
            config['enabled'] = False
            write_json(self.root / 'data/autoapply-config.json', config)
            with self.assertRaises(ValueError):
                self.browser.submission_intent(key, claim)
        finally:
            journal.close()


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_console_adapter(self):
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).with_name('browser_mcp.py')), '--console',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        try:
            ready = json.loads(await asyncio.wait_for(process.stdout.readline(), 30))
            self.assertTrue(ready['ready'])
            for _ in range(2):
                process.stdin.write(b'{"action":"snapshot"}\n')
                await process.stdin.drain()
                result = json.loads(await asyncio.wait_for(process.stdout.readline(), 30))
                self.assertEqual(result['url'], 'about:blank')
            process.stdin.write(b'{"action":"close"}\n')
            await process.stdin.drain()
            self.assertEqual(await asyncio.wait_for(process.wait(), 30), 0)
        finally:
            if process.returncode is None:
                process.terminate()
                await process.wait()

    async def test_server_handshake_and_tool_discovery(self):
        params = StdioServerParameters(command=sys.executable,
                                       args=[str(Path(__file__).with_name('browser_mcp.py'))])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalog = await session.list_tools()
                self.assertIn('browser_action', [tool.name for tool in catalog.tools])
                result = await session.call_tool('browser_action', {'action': 'snapshot'})
                self.assertFalse(result.isError, result.content)


if __name__ == '__main__':
    unittest.main()

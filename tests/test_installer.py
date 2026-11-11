import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import os

path=Path(__file__).resolve().parents[1] / 'Install_Deep_Research_Agent.py'
spec=importlib.util.spec_from_file_location('installer_under_test',path)
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_payload_matches_portable_source_files(self):
        root=Path(__file__).resolve().parents[1]/'skills'/'deep-research-agent'
        for relative, text in installer.payload_files().items():
            self.assertEqual(text, (root/relative).read_text(encoding='utf-8'))

    def test_actual_install_is_complete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            home=Path(tmp)/'home'
            first=installer.install(home)
            self.assertTrue(first['changed_files'])
            for path in first['changed_files']:
                self.assertTrue(Path(path).is_file())
                self.assertTrue(Path(path).is_relative_to(home))
            self.assertIn('deep_research',tomllib.loads((home/'.codex/config.toml').read_text(encoding='utf-8'))['mcp_servers'])
            self.assertIn('deep_research',json.loads((home/'.claude.json').read_text(encoding='utf-8'))['mcpServers'])
            self.assertTrue((home/'.claude/agents/deep-research-agent.md').is_file())
            second=installer.install(home)
            self.assertEqual(second['changed_files'], [])

    def test_upgrade_preserves_keys_and_appends_missing_settings(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            home=Path(tmp)/'home'
            base=home/'.local/share/deep-research-agent'
            base.mkdir(parents=True)
            env=base/'research.env'
            env.write_text('PERPLEXITY_API_KEY=private-fixture\nRESEARCH_SEARCH_PROVIDER=perplexity\n')
            installer.install(home)
            text=env.read_text()
            self.assertIn('PERPLEXITY_API_KEY=private-fixture',text)
            self.assertIn('RESEARCH_SEARCH_PROVIDER=perplexity',text)
            self.assertIn('SERPAPI_API_KEY=',text)
            self.assertIn('RESEARCH_STRATEGY=balanced',text)
            self.assertEqual(installer.install(home)['changed_files'],[])

    def test_payload_identity_and_no_model_keys(self):
        files=installer.payload_files()
        self.assertEqual(len(files),13)
        self.assertIn('No language-model API calls',files['scripts/research.py'])
        self.assertNotIn('LLM_API_KEY=',files['scripts/research.py'])

    def test_embedded_python_compiles(self):
        for name,text in installer.payload_files().items():
            if name.endswith('.py'):compile(text,name,'exec')

    def test_codex_preserves_existing_values(self):
        entry={'command':'C:\\Python\\python.exe','args':['C:\\tools\\research.py','serve']}
        old='model = "existing-model"\n[mcp_servers.existing]\ncommand = "existing-tool"\n'
        text=installer.codex_config(old,entry)
        parsed=tomllib.loads(text)
        self.assertEqual(parsed['model'],'existing-model')
        self.assertEqual(parsed['mcp_servers']['existing']['command'],'existing-tool')
        self.assertEqual(parsed['mcp_servers']['deep_research']['args'],entry['args'])

    def test_codex_update_is_idempotent(self):
        entry={'command':'python','args':['research.py','serve']}
        once=installer.codex_config('',entry)
        twice=installer.codex_config(once,entry)
        self.assertEqual(once,twice)

    def test_unmanaged_config_conflict_is_not_overwritten(self):
        with self.assertRaises(ValueError):
            installer.codex_config('[mcp_servers.deep_research]\ncommand="unrelated"\n',{'command':'python','args':[]})
        with self.assertRaises(ValueError):
            installer.claude_config('{"mcpServers":{"deep_research":{"command":"unrelated"}}}',{'command':'python','args':[]})

    def test_claude_preserves_other_servers_and_settings(self):
        old=json.dumps({'otherSetting':123,'mcpServers':{'other':{'command':'keep'}}})
        parsed=json.loads(installer.claude_config(old,{'type':'stdio','command':'python','args':['research.py']}))
        self.assertEqual(parsed['otherSetting'],123)
        self.assertEqual(parsed['mcpServers']['other']['command'],'keep')

    def test_dry_run_plans_all_hosts_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)/'research-project'
            plan=installer.install(Path(tmp)/'home',project=project,dry_run=True)
            self.assertFalse(project.exists())
            self.assertTrue(any('.agents/skills/' in p.replace('\\', '/') for p in plan['changed_files']))
            self.assertTrue(any('.claude/agents/' in p.replace('\\', '/') for p in plan['changed_files']))
            self.assertTrue(any('.dsh/skills/' in p.replace('\\', '/') for p in plan['changed_files']))

    def test_backup_write_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.json';path.write_text('old')
            changes=[]
            installer.backed_write(path,'new',changes)
            self.assertEqual(path.read_text(encoding='utf-8'),'new')
            backups=list(Path(tmp).glob('config.json.backup-*'))
            self.assertEqual(len(backups),1)
            self.assertEqual(backups[0].read_text(encoding='utf-8'),'old')


if __name__=='__main__':unittest.main()

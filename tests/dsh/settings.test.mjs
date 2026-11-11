import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, stat, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ensurePrivateConfig, mcpConfiguration, resolveSettings, skillConfiguration, checkPython } from '../../dsh/settings.mjs';

test('default config shares the existing installer state without exposing keys', () => {
  const value = resolveSettings({}, { home: '/home/tester', cwd: '/work', platform: 'linux', env: {} });
  assert.equal(value.envFile, '/home/tester/.local/share/deep-research-agent/research.env');
  assert.equal(value.pythonCommand, 'python3');
  assert.equal(mcpConfiguration(value).serverName, 'deep_research');
  assert.ok(!('env' in mcpConfiguration(value)));
  assert.ok(!JSON.stringify(value).includes('API_KEY'));
});
test('Windows launcher args are passed as separate arguments, never a shell command', () => {
  const value = resolveSettings({ pythonCommand: 'py', pythonArgs: ['-3.11'], dataDir: './private space' }, { home: '/home/tester', cwd: '/work', env: {} });
  const config = mcpConfiguration(value);
  assert.equal(config.command, 'py');
  assert.equal(config.args[0], '-3.11');
  assert.ok(config.args.includes('/work/private space/runs'));
  assert.ok(!('shell' in config));
});
test('custom env path and root are respected and skill scanning stays isolated', () => {
  const value = resolveSettings({}, { home: '/home/tester', cwd: '/work', env: { DEEP_RESEARCH_DATA_DIR: './state', DEEP_RESEARCH_ENV_FILE: './keys.env', DEEP_RESEARCH_PYTHON: 'python' } });
  assert.equal(value.envFile, '/work/keys.env');
  assert.equal(value.dataDir, '/work/state');
  assert.equal(skillConfiguration(value).includeDefaultRoots, false);
  assert.equal(skillConfiguration(value).providerName, 'deep-research-agent-bundle');
});
test('invalid namespace, timeout or executable argument shapes are rejected', () => {
  for (const args of [{ serverName: 'bad namespace' }, { toolCallTimeoutMs: 0 }, { pythonArgs: 'shell string' }, { pythonCommand: 'py\0' }]) assert.throws(() => resolveSettings(args));
});
test('activation creates private example env exactly once and preserves existing keys', async () => {
  const temp = await mkdtemp(join(tmpdir(), 'dsh-deep-research-'));
  try {
    const settings = resolveSettings({ dataDir: join(temp, 'data') });
    assert.equal((await ensurePrivateConfig(settings)).created, true);
    assert.ok((await readFile(settings.envFile, 'utf8')).includes('RESEARCH_SEARCH_PROVIDER=auto'));
    await writeFile(settings.envFile, 'TAVILY_API_KEY=private-fixture\n', 'utf8');
    assert.equal((await ensurePrivateConfig(settings)).created, false);
    assert.equal(await readFile(settings.envFile, 'utf8'), 'TAVILY_API_KEY=private-fixture\n');
    if (process.platform !== 'win32') assert.equal((await stat(settings.envFile)).mode & 0o777, 0o600);
  } finally { await rm(temp, { recursive: true, force: true }); }
});
test('bad Python executable produces a useful error without copying subprocess output', async () => {
  await assert.rejects(checkPython(resolveSettings({ pythonCommand: '__missing_python_for_test__' })), /requires Python 3.11/);
});

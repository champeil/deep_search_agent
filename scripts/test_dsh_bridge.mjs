/** Real Cordis + DSH services + official MCP bridge, without a model or remote search. */
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { Context } from '@deepseek-ai/cordis';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import Tools from '@deepseek-ai/dsh-tools';
import Skills from '@deepseek-ai/dsh-skill';
import * as plugin from '../dsh/index.mjs';

const temp = await mkdtemp(join(tmpdir(), 'dsh-research-bridge-'));
const ctx = new Context();
const fibers = [];
try {
  fibers.push(ctx.plugin(SystemPrompt, {}));
  fibers.push(ctx.plugin(Tools, {}));
  fibers.push(ctx.plugin(Skills, {}));
  for (const fiber of fibers) await fiber.await();
  const research = ctx.plugin(plugin, { dataDir: temp, serverName: 'deep_research', toolCallTimeoutMs: 120000 });
  fibers.push(research);
  await research.await();
  const deadline = Date.now() + 15000;
  while (ctx.tools.definitions().length < 23 && Date.now() < deadline) await delay(50);
  const names = ctx.tools.definitions().map(x => x.name);
  assert.equal(names.filter(x => x.startsWith('mcp__deep_research__')).length, 23);
  const skill = await ctx.skills.get('deep-research-agent', { cwd: temp });
  assert.ok(skill?.content || skill?.body);
  const call = async (name, args) => {
    const definition = ctx.tools.get('mcp__deep_research__' + name);
    const value = await definition.execute(args, { signal: AbortSignal.timeout(10000), deferContext() {}, concludeTurn() {} });
    const data = value.structuredContent ?? JSON.parse(value.content.find(x => x.type === 'text').text);
    assert.equal(data.ok, true);
    return data.result;
  };
  const started = await call('research_begin', { question: 'Offline DSH bridge check', subquestions: [{ id: 'Q1', question: 'Is the workflow wired?' }] });
  const guarded = await call('research_search', { run_id: started.run_id, query: 'must stay offline', round: 1, purpose: 'discovery' });
  assert.equal(guarded.status, 'needs_native');
  const status = await call('research_status', { run_id: started.run_id });
  assert.equal(status.retrieval_usage.remote_api_attempts, 0);
  await research.dispose();
  fibers.pop();
  assert.equal(ctx.tools.definitions().filter(x => x.name.startsWith('mcp__deep_research__')).length, 0);
  assert.equal((await ctx.skills.list({ cwd: temp })).some(x => x.name === 'deep-research-agent'), false);
  console.log(JSON.stringify({ bridge: 'passed', tools: 23, skill: 'loaded', calls: ['research_begin', 'research_search native guard', 'research_status'], remote_api_attempts: 0, unload: 'clean', model_calls: 0 }));
} finally {
  for (const fiber of fibers.reverse()) await fiber.dispose();
  await rm(temp, { recursive: true, force: true });
}

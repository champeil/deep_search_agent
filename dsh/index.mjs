/** Cordis composition adapter. Research remains in the inherited host model. */
import Schema from '@deepseek-ai/schemastery';
import * as mcpClient from '@deepseek-ai/dsh-mcp-client';
import * as skillFilesystem from '@deepseek-ai/dsh-skill-filesystem';
import { checkPython, ensurePrivateConfig, mcpConfiguration, resolveSettings, skillConfiguration } from './settings.mjs';

export const name = 'deep-research-agent';
export const inject = ['tools', 'skills'];
export const Config = Schema.object({
  pythonCommand: Schema.string().description('Python 3.11+ executable; defaults to python3 on Unix and python on Windows.'),
  pythonArgs: Schema.array(Schema.string()).default([]).description('Executable arguments, e.g. ["-3.11"] for Windows py.'),
  dataDir: Schema.string().description('Private state directory; defaults to ~/.local/share/deep-research-agent.'),
  envFile: Schema.string().description('Private research.env path. Existing values are never overwritten.'),
  serverName: Schema.string().default('deep_research'),
  toolCallTimeoutMs: Schema.number().default(120000),
});

export async function apply(ctx, config = {}) {
  const settings = resolveSettings(config);
  await checkPython(settings);
  await ensurePrivateConfig(settings);
  // Each child is owned by this Cordis fiber; unload/HMR disposes the provider and transport.
  ctx.plugin(skillFilesystem, skillConfiguration(settings));
  ctx.plugin(mcpClient, mcpConfiguration(settings));
}

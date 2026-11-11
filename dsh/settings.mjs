/** Pure settings resolution and private config creation. No registry, shell or model calls. */
import { homedir } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdir, open, lstat, readFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const runFile = promisify(execFile);
export const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function resolveSettings(config = {}, runtime = {}) {
  const home = runtime.home ?? homedir();
  const cwd = runtime.cwd ?? process.cwd();
  const platform = runtime.platform ?? process.platform;
  const env = runtime.env ?? process.env;
  const packageRoot = runtime.packageRoot ?? PACKAGE_ROOT;
  function absolute(value, fallback) {
    value = value || fallback;
    if (typeof value !== 'string' || !value.trim() || value.includes('\0')) throw new Error('Expected a nonempty filesystem path');
    if (value === '~') value = home;
    else if (value.startsWith('~/') || value.startsWith('~\\')) value = join(home, value.slice(2));
    return isAbsolute(value) ? value : resolve(cwd, value);
  }
  const dataDir = absolute(config.dataDir || env.DEEP_RESEARCH_DATA_DIR, join(home, '.local', 'share', 'deep-research-agent'));
  const envFile = absolute(config.envFile || env.DEEP_RESEARCH_ENV_FILE, join(dataDir, 'research.env'));
  const pythonCommand = config.pythonCommand || env.DEEP_RESEARCH_PYTHON || (platform === 'win32' ? 'python' : 'python3');
  const pythonArgs = config.pythonArgs ?? [];
  if (typeof pythonCommand !== 'string' || !pythonCommand.trim() || pythonCommand.includes('\0')) throw new Error('Invalid Python command');
  if (!Array.isArray(pythonArgs) || pythonArgs.some(x => typeof x !== 'string' || x.includes('\0'))) throw new Error('pythonArgs must be a string array');
  const serverName = config.serverName || 'deep_research';
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(serverName)) throw new Error('Invalid MCP serverName');
  const timeout = config.toolCallTimeoutMs ?? 120000;
  if (!Number.isInteger(timeout) || timeout < 1000 || timeout > 600000) throw new Error('Invalid toolCallTimeoutMs');
  return {
    dataDir, envFile, pythonCommand, pythonArgs: [...pythonArgs], serverName,
    runRoot: join(dataDir, 'runs'),
    skillRoot: join(packageRoot, 'skills'),
    script: join(packageRoot, 'skills', 'deep-research-agent', 'scripts', 'research.py'),
    envExample: join(packageRoot, 'examples', 'research.env.example'),
    toolCallTimeoutMs: timeout,
  };
}

export async function ensurePrivateConfig(settings) {
  await mkdir(settings.dataDir, { recursive: true, mode: 0o700 });
  await mkdir(dirname(settings.envFile), { recursive: true, mode: 0o700 });
  const template = await readFile(settings.envExample, 'utf8');
  let handle;
  try {
    handle = await open(settings.envFile, 'wx', 0o600);
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    const info = await lstat(settings.envFile);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error('research.env must be a regular file; configure the intended file path');
    return { created: false };
  }
  try {
    await handle.writeFile(template, 'utf8');
    await handle.sync();
  } finally { await handle.close(); }
  return { created: true };
}

export function mcpConfiguration(settings) {
  return {
    serverName: settings.serverName, transport: 'stdio', command: settings.pythonCommand,
    args: [...settings.pythonArgs, settings.script, 'serve', '--root', settings.runRoot, '--env', settings.envFile],
    toolCallTimeoutMs: settings.toolCallTimeoutMs, startupTimeoutMs: 30000,
    failOnStartupError: true,
  };
}

export function skillConfiguration(settings) {
  return { providerName: 'deep-research-agent-bundle', includeDefaultRoots: false,
    customSkillDirs: [settings.skillRoot], watch: false };
}

export async function checkPython(settings) {
  try {
    await runFile(settings.pythonCommand, [...settings.pythonArgs, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'],
      { timeout: 10000, maxBuffer: 100000, windowsHide: true });
  } catch {
    throw new Error('Deep Research Agent requires Python 3.11+. Configure pythonCommand/pythonArgs for the Python installed in the DSH host environment.');
  }
}

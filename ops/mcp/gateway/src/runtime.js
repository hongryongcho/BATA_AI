import fs from 'fs/promises';
import path from 'path';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { fileURLToPath } from 'url';

import YAML from 'yaml';

const execFileAsync = promisify(execFile);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '../../../../');
const REGISTRY_PATH = path.join(REPO_ROOT, 'ops', 'projects.registry.yaml');
const APPROVAL_POLICY_PATH = path.join(REPO_ROOT, 'ops', 'policies', 'approval-policy.yaml');
const LOG_POLICY_PATH = path.join(REPO_ROOT, 'ops', 'policies', 'log-policy.yaml');
const PATH_POLICY_PATH = path.join(REPO_ROOT, 'ops', 'policies', 'path-policy.yaml');
const POWERSHELL_EXE = 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe';

async function readYaml(filePath) {
  const content = await fs.readFile(filePath, 'utf8');
  return YAML.parse(content);
}

export async function loadRegistry() {
  return readYaml(REGISTRY_PATH);
}

export async function loadPolicies() {
  const [approval, logs, paths] = await Promise.all([
    readYaml(APPROVAL_POLICY_PATH),
    readYaml(LOG_POLICY_PATH),
    readYaml(PATH_POLICY_PATH),
  ]);

  return { approval, logs, paths };
}

export async function getProject(projectId) {
  const registry = await loadRegistry();
  const project = registry.projects.find((item) => item.id === projectId);
  if (!project) {
    throw new Error(`Unknown project_id: ${projectId}`);
  }

  return project;
}

export async function getContract(projectId) {
  const project = await getProject(projectId);
  const contract = await readYaml(project.contract);
  return { project, contract };
}

function controlScriptPath(projectRoot, controlCommand) {
  const match = controlCommand.match(/-File\s+([^\s]+)/i);
  if (!match) {
    throw new Error(`Unsupported control format: ${controlCommand}`);
  }

  const scriptPath = match[1].replace(/^['"]|['"]$/g, '');
  return path.resolve(projectRoot, scriptPath);
}

function extractJsonFromStdout(stdout) {
  const trimmed = stdout.trim();
  if (!trimmed) {
    return null;
  }

  const firstBrace = trimmed.indexOf('{');
  const firstBracket = trimmed.indexOf('[');
  const indexes = [firstBrace, firstBracket].filter((value) => value >= 0);
  if (indexes.length === 0) {
    return null;
  }

  const start = Math.min(...indexes);
  const candidate = trimmed.slice(start);
  try {
    return JSON.parse(candidate);
  } catch {
    return null;
  }
}

async function runPowerShellScript(scriptPath, cwd) {
  try {
    const { stdout, stderr } = await execFileAsync(
      POWERSHELL_EXE,
      ['-ExecutionPolicy', 'Bypass', '-File', scriptPath],
      { cwd, windowsHide: true, maxBuffer: 1024 * 1024 * 4 },
    );

    return {
      ok: true,
      exitCode: 0,
      stdout: stdout.trim(),
      stderr: stderr.trim(),
      json: extractJsonFromStdout(stdout),
    };
  } catch (error) {
    return {
      ok: false,
      exitCode: error.code ?? 1,
      stdout: String(error.stdout || '').trim(),
      stderr: String(error.stderr || error.message || '').trim(),
      json: extractJsonFromStdout(String(error.stdout || '')),
    };
  }
}

async function runControl(projectId, controlName) {
  const { project, contract } = await getContract(projectId);
  const command = contract.controls?.[controlName];
  if (!command) {
    throw new Error(`Control '${controlName}' is not defined for ${projectId}`);
  }

  const scriptPath = controlScriptPath(project.path, command);
  return {
    project_id: projectId,
    control: controlName,
    script: scriptPath,
    ...(await runPowerShellScript(scriptPath, project.path)),
  };
}

function normalizeForMatch(value) {
  return value.replace(/\\/g, '/').toLowerCase();
}

function isUnderRoot(resolvedPath, rootPath) {
  const normalizedRoot = normalizeForMatch(path.resolve(rootPath));
  const normalizedFile = normalizeForMatch(path.resolve(resolvedPath));
  return normalizedFile === normalizedRoot || normalizedFile.startsWith(`${normalizedRoot}/`);
}

function pathAllowed(resolvedPath, projectRoot, allowList, denyList) {
  const normalizedFile = normalizeForMatch(resolvedPath);

  for (const denied of denyList) {
    if (normalizedFile.includes(normalizeForMatch(denied))) {
      return false;
    }
  }

  if (!isUnderRoot(resolvedPath, projectRoot)) {
    return false;
  }

  const relative = normalizeForMatch(path.relative(projectRoot, resolvedPath));
  return allowList.some((entry) => {
    const normalizedEntry = normalizeForMatch(entry);
    return relative === normalizedEntry || relative.startsWith(`${normalizedEntry}/`);
  });
}

async function requireApproval(toolName, approved) {
  const policies = await loadPolicies();
  if (!policies.approval.require_approval.includes(toolName)) {
    return;
  }

  if (approved !== true) {
    throw new Error(`Tool '${toolName}' requires approved=true by policy`);
  }
}

async function appendLog(entry) {
  const policies = await loadPolicies();
  const logRoot = policies.logs.logs.root.replace(/^E:/i, 'E:');
  await fs.mkdir(logRoot, { recursive: true });

  const dateKey = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const filePath = path.join(logRoot, `${policies.logs.logs.file_prefix}${dateKey}.jsonl`);
  const redacted = { ...entry };

  for (const key of policies.logs.logs.redact_fields || []) {
    if (key in redacted) {
      redacted[key] = '[REDACTED]';
    }
  }

  await fs.appendFile(filePath, `${JSON.stringify(redacted)}\n`, 'utf8');
}

export async function listProjects() {
  const registry = await loadRegistry();
  return registry.projects.map((project) => ({
    id: project.id,
    name: project.name,
    path: project.path,
    contract: project.contract,
    priority: project.priority,
    tags: project.tags,
  }));
}

export async function readContract(projectId) {
  const { contract } = await getContract(projectId);
  return contract;
}

export async function getStatus(projectId) {
  return runControl(projectId, 'status');
}

export async function getHealth(projectId) {
  return runControl(projectId, 'health');
}

export async function getDiagnostics(projectId) {
  return runControl(projectId, 'diagnose');
}

export async function startProject(projectId, approved = false) {
  await requireApproval('start_project', approved);
  return runControl(projectId, 'start');
}

export async function stopProject(projectId, approved = false) {
  await requireApproval('stop_project', approved);
  return runControl(projectId, 'stop');
}

export async function restartProject(projectId, approved = false) {
  await requireApproval('restart_project', approved);
  const stop = await stopProject(projectId, approved);
  const start = await startProject(projectId, approved);
  return { project_id: projectId, stop, start };
}

export async function runJob(projectId, jobName, approved = false) {
  await requireApproval('run_job', approved);
  const policies = await loadPolicies();
  const allowed = policies.approval.run_job_allowlist?.[projectId] || [];
  if (!allowed.includes(jobName)) {
    throw new Error(`Job '${jobName}' is not allowed for ${projectId}`);
  }

  return runControl(projectId, jobName);
}

export async function tailLogs(projectId, lines = 80) {
  const { project, contract } = await getContract(projectId);
  const policies = await loadPolicies();
  const limit = Math.min(Math.max(Number(lines) || policies.logs.tail_logs.default_lines, 1), policies.logs.tail_logs.max_lines);
  const logDir = contract.logs?.path;
  if (!logDir) {
    throw new Error(`No log path configured for ${projectId}`);
  }

  const entries = await fs.readdir(logDir, { withFileTypes: true }).catch(() => []);
  const files = [];
  for (const entry of entries) {
    if (!entry.isFile()) {
      continue;
    }
    const fullPath = path.join(logDir, entry.name);
    const stat = await fs.stat(fullPath);
    files.push({ name: entry.name, path: fullPath, mtimeMs: stat.mtimeMs });
  }

  if (files.length === 0) {
    return { project_id: projectId, log_path: logDir, lines: [], file: null };
  }

  files.sort((a, b) => b.mtimeMs - a.mtimeMs);
  const latest = files[0];
  const content = await fs.readFile(latest.path, 'utf8');
  const allLines = content.split(/\r?\n/);
  return {
    project_id: projectId,
    file: latest.path,
    line_count: limit,
    lines: allLines.slice(-limit),
  };
}

export async function applyPatchTool(projectId, changes, approved = false) {
  await requireApproval('apply_patch', approved);
  const { project } = await getContract(projectId);
  const policies = await loadPolicies();
  const allowList = policies.paths.per_project?.[projectId]?.allow || [];
  const denyList = policies.paths.global_deny_contains || [];

  const results = [];

  for (const change of changes || []) {
    const resolvedPath = path.resolve(project.path, change.path);
    if (!pathAllowed(resolvedPath, project.path, allowList, denyList)) {
      throw new Error(`Path not allowed by policy: ${change.path}`);
    }

    const fileExists = await fs.access(resolvedPath).then(() => true).catch(() => false);
    if (!fileExists) {
      if ((change.old_text || '') !== '') {
        throw new Error(`Target file does not exist: ${change.path}`);
      }

      await fs.mkdir(path.dirname(resolvedPath), { recursive: true });
      await fs.writeFile(resolvedPath, change.new_text || '', 'utf8');
      results.push({ path: change.path, action: 'created' });
      continue;
    }

    const original = await fs.readFile(resolvedPath, 'utf8');
    const oldText = change.old_text || '';
    const occurrences = oldText ? original.split(oldText).length - 1 : 0;

    if (oldText && occurrences !== 1) {
      throw new Error(`Expected old_text exactly once in ${change.path}, found ${occurrences}`);
    }

    const next = oldText ? original.replace(oldText, change.new_text || '') : `${original}${change.new_text || ''}`;
    await fs.writeFile(resolvedPath, next, 'utf8');
    results.push({ path: change.path, action: 'updated' });
  }

  return { project_id: projectId, results };
}

export async function callTool(toolName, args = {}) {
  const startedAt = Date.now();
  let result;

  switch (toolName) {
    case 'list_projects':
      result = await listProjects();
      break;
    case 'read_contract':
      result = await readContract(args.project_id);
      break;
    case 'get_status':
      result = await getStatus(args.project_id);
      break;
    case 'get_health':
      result = await getHealth(args.project_id);
      break;
    case 'get_diagnostics':
      result = await getDiagnostics(args.project_id);
      break;
    case 'start_project':
      result = await startProject(args.project_id, args.approved);
      break;
    case 'stop_project':
      result = await stopProject(args.project_id, args.approved);
      break;
    case 'restart_project':
      result = await restartProject(args.project_id, args.approved);
      break;
    case 'run_job':
      result = await runJob(args.project_id, args.job_name, args.approved);
      break;
    case 'tail_logs':
      result = await tailLogs(args.project_id, args.lines);
      break;
    case 'apply_patch':
      result = await applyPatchTool(args.project_id, args.changes, args.approved);
      break;
    default:
      throw new Error(`Unknown tool: ${toolName}`);
  }

  await appendLog({
    timestamp: new Date().toISOString(),
    tool: toolName,
    project_id: args.project_id || null,
    approved: args.approved === true,
    duration_ms: Date.now() - startedAt,
    ok: true,
  });

  return result;
}

export const toolDefinitions = [
  {
    name: 'list_projects',
    description: 'List all BATA projects registered in the root registry.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'read_contract',
    description: 'Read a project.contract.yaml for a registered project.',
    inputSchema: {
      type: 'object',
      properties: { project_id: { type: 'string' } },
      required: ['project_id'],
    },
  },
  {
    name: 'get_status',
    description: 'Run the project status control script.',
    inputSchema: {
      type: 'object',
      properties: { project_id: { type: 'string' } },
      required: ['project_id'],
    },
  },
  {
    name: 'get_health',
    description: 'Run the project health control script.',
    inputSchema: {
      type: 'object',
      properties: { project_id: { type: 'string' } },
      required: ['project_id'],
    },
  },
  {
    name: 'get_diagnostics',
    description: 'Run the project diagnostics control script and return parsed JSON when available.',
    inputSchema: {
      type: 'object',
      properties: { project_id: { type: 'string' } },
      required: ['project_id'],
    },
  },
  {
    name: 'start_project',
    description: 'Start a project. Requires approved=true by policy.',
    inputSchema: {
      type: 'object',
      properties: {
        project_id: { type: 'string' },
        approved: { type: 'boolean' },
      },
      required: ['project_id'],
    },
  },
  {
    name: 'stop_project',
    description: 'Stop a project. Requires approved=true by policy.',
    inputSchema: {
      type: 'object',
      properties: {
        project_id: { type: 'string' },
        approved: { type: 'boolean' },
      },
      required: ['project_id'],
    },
  },
  {
    name: 'restart_project',
    description: 'Restart a project. Requires approved=true by policy.',
    inputSchema: {
      type: 'object',
      properties: {
        project_id: { type: 'string' },
        approved: { type: 'boolean' },
      },
      required: ['project_id'],
    },
  },
  {
    name: 'run_job',
    description: 'Run an approved project job such as bata-stock run_report_now. Requires approved=true.',
    inputSchema: {
      type: 'object',
      properties: {
        project_id: { type: 'string' },
        job_name: { type: 'string' },
        approved: { type: 'boolean' },
      },
      required: ['project_id', 'job_name'],
    },
  },
  {
    name: 'tail_logs',
    description: 'Tail the latest log file under the contract log path.',
    inputSchema: {
      type: 'object',
      properties: {
        project_id: { type: 'string' },
        lines: { type: 'number' },
      },
      required: ['project_id'],
    },
  },
  {
    name: 'apply_patch',
    description: 'Apply a safe text replacement patch inside project whitelist paths. Requires approved=true.',
    inputSchema: {
      type: 'object',
      properties: {
        project_id: { type: 'string' },
        approved: { type: 'boolean' },
        changes: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              path: { type: 'string' },
              old_text: { type: 'string' },
              new_text: { type: 'string' },
            },
            required: ['path', 'new_text'],
          },
        },
      },
      required: ['project_id', 'changes'],
    },
  },
];
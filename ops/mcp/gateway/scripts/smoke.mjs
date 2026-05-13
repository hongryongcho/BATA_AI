import {
  listProjects,
  readContract,
  getStatus,
  getHealth,
  getDiagnostics,
  runJob,
} from '../src/runtime.js';

async function main() {
  const projects = await listProjects();
  console.log('PROJECTS', JSON.stringify(projects, null, 2));

  for (const project of projects) {
    const contract = await readContract(project.id);
    console.log(`CONTRACT ${project.id}`, JSON.stringify({ name: contract.name, controls: Object.keys(contract.controls || {}) }));
    console.log(`STATUS ${project.id}`, JSON.stringify(await getStatus(project.id), null, 2));
    console.log(`HEALTH ${project.id}`, JSON.stringify(await getHealth(project.id), null, 2));
    if (contract.controls?.diagnose) {
      console.log(`DIAGNOSTICS ${project.id}`, JSON.stringify(await getDiagnostics(project.id), null, 2));
    }
  }

  console.log('RUN_JOB bata-stock', JSON.stringify(await runJob('bata-stock', 'run_report_now', true), null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
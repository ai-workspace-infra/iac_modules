const DEFAULT_REQUIRED_BRANCH = 'main';

function resolveBranch(context) {
  const { eventName, ref, payload } = context;

  if (eventName === 'workflow_run') {
    return payload.workflow_run?.head_branch || '';
  }

  if (eventName === 'pull_request' || eventName === 'pull_request_target') {
    return payload.pull_request?.head?.ref || '';
  }

  if (typeof ref === 'string' && ref.startsWith('refs/heads/')) {
    return ref.replace('refs/heads/', '');
  }

  return '';
}

async function ensureSuccessfulRun({ github, context, core }, workflowFile, branch) {
  const { data } = await github.rest.actions.listWorkflowRuns({
    owner: context.repo.owner,
    repo: context.repo.repo,
    workflow_id: workflowFile,
    branch,
    per_page: 1,
    status: 'completed'
  });

  if (!data.workflow_runs.length) {
    core.setFailed(`No completed runs of ${workflowFile} found on branch ${branch}.`);
    return false;
  }

  const [run] = data.workflow_runs;

  if (run.conclusion !== 'success') {
    core.setFailed(`Latest ${workflowFile} run (${run.id}) concluded with ${run.conclusion}.`);
    return false;
  }

  core.info(`Dependency workflow ${workflowFile} succeeded on branch ${branch} (run id ${run.id}).`);
  return true;
}

async function evaluateWorkflowStatus({ github, context, core }, options) {
  const {
    dependencyWorkflowFile,
    requiredBranch = DEFAULT_REQUIRED_BRANCH,
  } = options;
  const branch = resolveBranch(context);

  if (!branch) {
    core.info('Unable to determine triggering branch, skipping downstream jobs.');
    core.setOutput('should-run', 'false');
    return;
  }

  if (branch !== requiredBranch) {
    core.info(`Branch ${branch} is not ${requiredBranch}; skipping downstream jobs.`);
    core.setOutput('should-run', 'false');
    return;
  }

  if (context.eventName === 'workflow_run') {
    const conclusion = context.payload.workflow_run?.conclusion;
    if (conclusion !== 'success') {
      core.setFailed(`Upstream workflow ${context.payload.workflow_run?.name} concluded with ${conclusion}.`);
      return;
    }
  }

  const ok = await ensureSuccessfulRun({ github, context, core }, dependencyWorkflowFile, branch);
  if (!ok) {
    return;
  }

  core.setOutput('should-run', 'true');
}

module.exports = {
  evaluateWorkflowStatus,
};

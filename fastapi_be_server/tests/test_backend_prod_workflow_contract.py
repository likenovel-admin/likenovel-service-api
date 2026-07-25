from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy_be_actions.yml"


def test_prod_job_only_runs_from_prod_ref():
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    job_start = lines.index("  BuildAndRunBeServer:")
    job_lines = []

    for line in lines[job_start + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        job_lines.append(line)

    assert "    if: github.ref == 'refs/heads/prod'" in job_lines


def test_prod_build_runs_this_workflow_contract():
    content = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "poetry run python tests/test_backend_prod_workflow_contract.py" in content
    )


if __name__ == "__main__":
    test_prod_job_only_runs_from_prod_ref()
    test_prod_build_runs_this_workflow_contract()

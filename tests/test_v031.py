from pathlib import Path

def test_runner_uses_primary_group_not_nonexistent_solomonjob_group():
    s=Path('scripts/solomon-job-runner.py').read_text()
    assert "grp.getgrgid(job_user.pw_gid).gr_name" in s
    assert "f'--gid={job_group}'" in s
    assert "'--gid=solomonjob'" not in s

def test_mhs_docs_exist():
    assert Path('docs/MHS_REVIEW_AND_SOLOMONPRIME_MAPPING.md').exists()
    assert Path('scripts/seed-mhs-side-project.sh').exists()

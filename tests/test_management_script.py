from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGE_SH = ROOT / "manage.sh"


def test_management_script_runs_tests_before_starting_app():
    script = MANAGE_SH.read_text()

    assert "function run_preflight_tests()" in script
    assert "uv run pytest -q" in script
    assert script.index("run_preflight_tests") < script.index("uv run python app/main.py")


def test_management_script_waits_for_port_to_be_free_before_starting_app():
    script = MANAGE_SH.read_text()

    assert "function wait_for_port_free()" in script
    assert "wait_for_port_free 8081" in script
    assert script.index("wait_for_port_free 8081") < script.index("uv run python app/main.py")


def test_management_script_ignores_empty_lsof_output():
    script = MANAGE_SH.read_text()

    assert 'pid_output=$(lsof -nP -tiTCP:8081 -sTCP:LISTEN 2>/dev/null | sort -u)' in script
    assert 'if [[ -z "$pid_output" ]]; then' in script
    assert "return 0" in script

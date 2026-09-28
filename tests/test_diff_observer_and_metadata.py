import os
import sys
import tempfile
import pytest
from copilot.schemas import SystemEnvironmentMetadata, SilentFailureSnapshot
from copilot.diff_observer import run_observed_command, ACTIVE_FAILURES, resolve_silent_fix
from copilot.cli import main
from copilot import hindsight_service

def test_system_environment_metadata_schema():
    env_meta = SystemEnvironmentMetadata(
        service="checkout-service",
        environment="production",
        git_commit="abcdef1",
        build_id="build-99",
        runtime="python:3.11",
        dependencies={"redis": "7.2.4", "fastapi": "0.109.0"},
        resource_limits={"memory": "512Mi"}
    )
    assert env_meta.service == "checkout-service"
    assert env_meta.dependencies["redis"] == "7.2.4"
    assert env_meta.runtime == "python:3.11"

def test_diff_observer_lifecycle(monkeypatch):
    # Create temporary buggy script
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("def divide():\n    return 10 / 0\n\ndivide()\n")
        temp_path = f.name

    try:
        # 1. Run buggy script - should fail and snapshot
        ret = run_observed_command([sys.executable, temp_path], temp_path)
        assert ret != 0
        assert temp_path in ACTIVE_FAILURES
        snapshot = ACTIVE_FAILURES[temp_path]
        assert "ZeroDivisionError" in snapshot.error_trace
        assert "10 / 0" in snapshot.pre_fix_content

        # 2. Fix the script
        with open(temp_path, "w") as f:
            f.write("def divide():\n    return 10 / 2\n\ndivide()\n")

        # Mock hindsight retain to verify it gets called
        retained = []
        monkeypatch.setattr(hindsight_service.client, "retain", lambda **kwargs: retained.append(kwargs))

        # 3. Run again - should succeed and resolve silent fix
        ret2 = run_observed_command([sys.executable, temp_path], temp_path)
        assert ret2 == 0
        assert temp_path not in ACTIVE_FAILURES
        assert len(retained) == 1
        assert "Silent Code Fix" in retained[0]["content"]
        assert "-    return 10 / 0" in retained[0]["content"]
        assert "+    return 10 / 2" in retained[0]["content"]

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def test_cli_subcommands(capsys, monkeypatch):
    # 1. Test memory inspect CLI command
    monkeypatch.setattr(
        sys,
        "argv",
        ["retrospect", "memory", "inspect", "--service", "checkout-service", "--dependency", "redis=7.2.4"]
    )
    main()
    captured = capsys.readouterr()
    assert "Inspecting Hindsight memory" in captured.out

    # 2. Test retrospect run --file <target> -- <command>
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("print('hello silent observer')\n")
        temp_path = f.name

    try:
        monkeypatch.setattr(
            sys,
            "argv",
            ["retrospect", "run", "--file", temp_path, "--", sys.executable, temp_path]
        )
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 0
        captured_run = capsys.readouterr()
        assert "Diff Observer Active" in captured_run.out
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

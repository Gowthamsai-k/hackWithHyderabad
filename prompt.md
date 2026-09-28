# RETROSPECT SPECIFICATION ADDENDUM: METADATA DRIFT PREVENTION & SILENT FIX OBSERVER

## 1. OBJECTIVE OF THIS ADDENDUM
This module extends the Retrospect SRE Copilot CLI to handle two critical operational realities:
1. **Infrastructure & Metadata Drift Prevention**: Storing precise runtime versions, lockfile dependencies, and Git commit hashes alongside Hindsight memories to eliminate stale cross-version runbook hallucinations.
2. **Silent Resolution & Automated Diff Observation**: Detecting when a developer fixes a bug (such as an out-of-bounds error or script crash) silently without typing into a ticket thread, using process exit codes and line diffs as direct telemetry.
2. UPDATED DATA SCHEMAS (schemas.py)
Append the following Pydantic schemas to schemas.py:

Python
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class SystemEnvironmentMetadata(BaseModel):
    service: str = Field(..., example="checkout-service")
    environment: str = Field(default="production", example="production")
    git_commit: Optional[str] = Field(default=None, example="a9f2c8d")
    build_id: Optional[str] = Field(default=None, example="jenkins-402")
    runtime: str = Field(default="python:3.11", example="python:3.11")
    host_kernel: Optional[str] = None
    dependencies: Dict[str, str] = Field(
        default_factory=dict,
        example={"redis": "7.2.4", "fastapi": "0.110.0"}
    )
    resource_limits: Dict[str, str] = Field(
        default_factory=dict,
        example={"cpu": "2000m", "memory": "4Gi"}
    )

class SilentFailureSnapshot(BaseModel):
    file_path: str
    error_type: str
    error_trace: str
    pre_fix_content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
3. SILENT FIX OBSERVER & EXECUTION WRAPPER (diff_observer.py)
Create diff_observer.py to intercept command executions, record failure snapshots, and compute diffs on clean re-runs:

Python
import difflib
import json
import os
import subprocess
from datetime import datetime
from typing import Optional
from groq import Groq
from hindsight_service import client, BANK_ID
from schemas import SilentFailureSnapshot

ACTIVE_FAILURES: dict[str, SilentFailureSnapshot] = {}
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def run_observed_command(command: list[str], target_file: str) -> int:
    """
    Executes a script/command. If it crashes, snapshots the file.
    If it subsequently succeeds, infers the fix via diff and retains into Hindsight.
    """
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        # Failure detected: snapshot file state
        with open(target_file, "r") as f:
            content = f.read()

        ACTIVE_FAILURES[target_file] = SilentFailureSnapshot(
            file_path=target_file,
            error_type="ProcessCrash",
            error_trace=result.stderr.strip() or result.stdout.strip(),
            pre_fix_content=content
        )
        print(f"[!] Crash recorded in {target_file}. Snapshot saved for silent observation.")
        return result.returncode

    # If execution succeeded, verify if it resolves an active failure
    if target_file in ACTIVE_FAILURES:
        print(f"[*] Clean run detected for {target_file}. Calculating code mutation diff...")
        resolve_silent_fix(target_file)

    return result.returncode

def resolve_silent_fix(target_file: str):
    failure = ACTIVE_FAILURES.pop(target_file)
    with open(target_file, "r") as f:
        current_content = f.read()

    # Generate unified diff
    diff_lines = list(difflib.unified_diff(
        failure.pre_fix_content.splitlines(keepends=True),
        current_content.splitlines(keepends=True),
        fromfile=f"a/{target_file}",
        tofile=f"b/{target_file}"
    ))
    diff_text = "".join(diff_lines)

    if not diff_text.strip():
        return

    # Infer cause and fix from the diff
    prompt = f"""
Analyze this resolved crash where the developer applied a silent fix with zero chat notes.

ERROR STACK TRACE:
{failure.error_trace}

CODE DIFF APPLIED:
{diff_text}

Extract the facts into JSON:
{{
  "root_cause": "Specific bug explanation (e.g. 0-based boundary index error)",
  "failed_attempts": [],
  "verified_fix": "Summary of the exact line change applied",
  "anti_pattern_warning": "What indexing or code pattern caused the error"
}}
Output raw JSON only.
"""

    resp = groq_client.chat.completions.create(
        model="qwen/qwen3-32b",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    analysis = json.loads(resp.choices[0].message.content)

    # Retain directly into Hindsight memory
    client.retain(
        bank_id=BANK_ID,
        content=(
            f"Silent Code Fix in '{target_file}'. "
            f"Root Cause: {analysis['root_cause']}. "
            f"Verified Fix: {analysis['verified_fix']}. "
            f"Code Diff: {diff_text.strip()}"
        ),
        context=f"repo:script-fixes:{target_file}",
        timestamp=datetime.utcnow(),
        metadata={"file": target_file, "type": "silent_code_diff"},
        retain_async=False
    )
    print(f"[*] Hindsight retained silent fix for {target_file}.")
4. METADATA-AWARE MEMORY RETENTION (hindsight_service.py UPDATE)
Update the retain_post_mortem signature to bind environment context:

Python
def retain_post_mortem(
    ticket_id: str,
    service: str,
    post_mortem,
    closed_at: datetime,
    system_env: Optional[SystemEnvironmentMetadata] = None
):
    runtime_info = system_env.runtime if system_env else "unknown"
    dep_summary = json.dumps(system_env.dependencies) if system_env else "{}"
    git_commit = system_env.git_commit if system_env else "HEAD"

    content = (
        f"Incident [{ticket_id}] on '{service}'. "
        f"Runtime: {runtime_info}. Dependencies: {dep_summary}. Git: {git_commit}. "
        f"Root Cause: {post_mortem.root_cause}. "
        f"Verified Fix: {post_mortem.verified_fix}. "
        f"Failed Attempts: {'; '.join(post_mortem.failed_attempts)}. "
        f"Anti-Pattern Warning: {post_mortem.anti_pattern_warning}"
    )

    metadata_payload = {
        "ticket_id": ticket_id,
        "service": service,
        "git_commit": git_commit,
        "type": "verified_post_mortem"
    }
    if system_env:
        metadata_payload.update(system_env.dependencies)

    client.retain(
        bank_id=BANK_ID,
        content=content,
        context=f"service:{service}:incidents",
        timestamp=closed_at,
        metadata=metadata_payload,
        retain_async=False
    )
5. NEW CLI SUBCOMMANDS (cli.py)
Add the run command to the CLI entry point so developers can execute monitored scripts directly:

Bash
# Run a script with active crash and diff observation
retrospect run --file processor.py -- python3 processor.py

# Query memory specifically scoped by dependency version
retrospect memory inspect --service checkout-service --dependency redis=7.2.4
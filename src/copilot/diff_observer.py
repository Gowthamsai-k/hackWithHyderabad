import difflib
import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict
from dotenv import load_dotenv
from groq import Groq
from .hindsight_service import client, BANK_ID
from .schemas import SilentFailureSnapshot

load_dotenv()

def get_env_var(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'\"")
    return val

ACTIVE_FAILURES: Dict[str, SilentFailureSnapshot] = {}

GROQ_API_KEY = get_env_var("GROQ_API_KEY", "")
GROQ_MODEL = get_env_var("GROQ_MODEL", "qwen/qwen3.8-27b")

groq_client = None
if GROQ_API_KEY and GROQ_API_KEY != "your_groq_api_key_here":
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
    except Exception as e:
        print(f"[!] Groq initialization warning in diff_observer: {e}")

def run_observed_command(command: list[str], target_file: str) -> int:
    """
    Executes a script/command. If it crashes, snapshots the file.
    If it subsequently succeeds, infers the fix via diff and retains into Hindsight.
    """
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        # Failure detected: snapshot file state
        content = ""
        if os.path.exists(target_file):
            with open(target_file, "r", encoding="utf-8") as f:
                content = f.read()

        error_trace = result.stderr.strip() or result.stdout.strip()
        ACTIVE_FAILURES[target_file] = SilentFailureSnapshot(
            file_path=target_file,
            error_type="ProcessCrash",
            error_trace=error_trace,
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
    if target_file not in ACTIVE_FAILURES:
        return

    failure = ACTIVE_FAILURES.pop(target_file)
    current_content = ""
    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8") as f:
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
        print(f"[*] No diff detected for {target_file}; code was not modified.")
        return

    print(f"[*] Analyzing code mutation diff for {target_file}:\n{diff_text}")

    analysis = None
    if groq_client:
        prompt = f"""Analyze this resolved crash where the developer applied a silent fix with zero chat notes.

ERROR STACK TRACE:
{failure.error_trace}

CODE DIFF APPLIED:
{diff_text}

Extract the facts into valid JSON matching this exact structure:
{{
  "root_cause": "Specific bug explanation (e.g. 0-based boundary index error)",
  "failed_attempts": [],
  "verified_fix": "Summary of the exact line change applied",
  "anti_pattern_warning": "What indexing or code pattern caused the error"
}}
Output raw JSON only. Do not include markdown code fences.
"""
        try:
            resp = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").removeprefix("json").strip()
            analysis = json.loads(raw)
        except Exception as e:
            print(f"[!] Groq silent diff analysis failed: {e}")

    if not analysis:
        analysis = {
            "root_cause": f"Runtime exception in {target_file}: {failure.error_trace[:120]}",
            "failed_attempts": [],
            "verified_fix": f"Applied code mutation in {target_file}",
            "anti_pattern_warning": "Avoid unverified boundary assumptions"
        }

    # Retain directly into Hindsight memory
    try:
        client.retain(
            bank_id=BANK_ID,
            content=(
                f"Silent Code Fix in '{target_file}'. "
                f"Root Cause: {analysis.get('root_cause')}. "
                f"Verified Fix: {analysis.get('verified_fix')}. "
                f"Anti-Pattern Warning: {analysis.get('anti_pattern_warning')}. "
                f"Code Diff: {diff_text.strip()}"
            ),
            context=f"repo:script-fixes:{target_file}",
            timestamp=datetime.now(timezone.utc),
            metadata={"file": target_file, "type": "silent_code_diff"},
            retain_async=False
        )
        print(f"[*] Hindsight retained silent fix for {target_file}.")
    except Exception as e:
        print(f"[!] Hindsight retention failed for silent fix: {e}")

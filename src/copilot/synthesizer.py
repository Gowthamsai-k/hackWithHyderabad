import os
import json
import re
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq
from .schemas import PostMortemExtraction
from .hindsight_service import retain_post_mortem

load_dotenv()

def get_env_var(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'\"")
    return val

GROQ_API_KEY = get_env_var("GROQ_API_KEY", "")
GROQ_MODEL = get_env_var("GROQ_MODEL", "qwen/qwen3.8-27b")

groq_client = None
if GROQ_API_KEY and GROQ_API_KEY != "your_groq_api_key_here":
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
    except Exception as e:
        print(f"[!] Groq client initialization warning: {e}")

def clean_llm_json(raw_text: str) -> dict:
    """Strips markdown code fences and returns parsed dictionary."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)

def _heuristic_post_mortem(service: str, filtered_logs: list, filtered_chat: list) -> PostMortemExtraction:
    """Fallback extraction if Groq API key is not configured or unavailable."""
    failed_steps = []
    verified_fix = "Applied exception handling guard and updated service configuration"
    anti_pattern = "DO NOT ignore uncaught exceptions or suppress error stack traces."

    for msg in filtered_chat:
        text = msg.get("text", "")
        if "restart" in text.lower() and ("crashing" in text.lower() or "still" in text.lower() or "errors" in text.lower() or "re-triggered" in text.lower()):
            failed_steps.append("Rolling restart of service pods")
            anti_pattern = "Do not perform rolling restarts; they re-trigger connection pool exhaustion."
        elif "patch" in text.lower() or "scale" in text.lower() or "pool" in text.lower() or "helm" in text.lower():
            verified_fix = text

    root_cause = f"Unhandled runtime error in {service}."
    for line in filtered_logs:
        if "ERROR" in line or "Exception" in line:
            root_cause = line.strip()
            break

    return PostMortemExtraction(
        root_cause=root_cause,
        failed_attempts=failed_steps if failed_steps else ["Unverified manual process restart"],
        verified_fix=verified_fix,
        anti_pattern_warning=anti_pattern
    )

def run_idle_post_mortem(
    ticket_id: str, 
    service: str, 
    filtered_logs: list, 
    filtered_chat: list, 
    closed_at: datetime,
    bank_id: str = None,
    extra_metadata: dict = None
):
    """Synthesizes root causes, failed steps, and fixes from the complete incident bundle."""
    prompt = f"""
You are an expert SRE Post-Mortem Compiler. Analyze this resolved incident bundle for service '{service}'.

SANITIZED INCIDENT LOGS:
{json.dumps(filtered_logs, indent=2)}

FILTERED TRIAGE CHAT:
{json.dumps(filtered_chat, indent=2)}

Extract the incident facts into valid JSON matching this exact structure:
{{
  "root_cause": "Detailed technical root cause",
  "failed_attempts": ["List of attempted actions that failed or had no effect"],
  "verified_fix": "The specific action that resolved the outage",
  "anti_pattern_warning": "Warning future engineers what NOT to do based on failed attempts"
}}
Output raw JSON only. Ensure the output is valid JSON format.
"""

    post_mortem = None

    if groq_client:
        try:
            model_to_use = get_env_var("GROQ_MODEL", "qwen/qwen3.8-27b")
            response = groq_client.chat.completions.create(
                model=model_to_use,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            parsed = clean_llm_json(response.choices[0].message.content)
            post_mortem = PostMortemExtraction(**parsed)
            print(f"[*] Successfully synthesized post-mortem using Groq ({model_to_use}) for {ticket_id}")
        except Exception as e:
            print(f"[!] Groq synthesis failed ({e}). Falling back to heuristic extractor.")

    if not post_mortem:
        post_mortem = _heuristic_post_mortem(service, filtered_logs, filtered_chat)
        print(f"[*] Generated post-mortem synthesis for {ticket_id} via fallback extractor.")

    # Ingest permanently into Hindsight memory with metadata
    retain_post_mortem(ticket_id, service, post_mortem, closed_at, bank_id=bank_id, extra_metadata=extra_metadata)
    return post_mortem

def _extract_stack_trace_info(logs_text: str, default_filename: str = "app.py") -> tuple[str, str]:
    """Parses stack trace to extract actual target filename and line number."""
    m_java = re.search(r'at\s+[\w\.\$]+\(([\w]+\.java):(\d+)\)', logs_text)
    if m_java:
        return m_java.group(1), m_java.group(2)
        
    m_py = re.search(r'File "([^"]+)", line (\d+)', logs_text)
    if m_py:
        return os.path.basename(m_py.group(1)), m_py.group(2)

    return default_filename, "1"

def _extract_learnt_outcome(recalled_text: str) -> tuple[Optional[str], Optional[str]]:
    """Extracts verified fix and anti-pattern warning from recalled Hindsight memory text."""
    if not recalled_text or "No prior" in recalled_text or "First occurrence" in recalled_text:
        return None, None
    
    fix = None
    anti = None

    # Search for Verified Fix
    fix_m = re.search(r"(?:✅ \*\*Verified Fix:\*\*|Verified Fix:)\s*(.+)", recalled_text)
    if fix_m:
        fix = fix_m.group(1).strip()

    # Search for Anti-Pattern Warning
    anti_m = re.search(r"(?:⚠️ \*\*Anti-Pattern Warning:\*\*|Anti-Pattern Warning:|Anti-Pattern:)\s*(.+)", recalled_text)
    if anti_m:
        anti = anti_m.group(1).strip()

    if not fix and recalled_text.strip():
        fix = recalled_text.strip()

    return fix, anti

def synthesize_remediation_and_anti_pattern(
    service: str, 
    error_type: str, 
    raw_logs: list,
    recalled_runbook: str = None
) -> tuple[str, str, str]:
    """
    Synthesizes remediation patch and anti-pattern WITHOUT using LLM.
    - First-time incident: Explicitly states it is the first time and no prior learnt outcome is available.
    - Second-time incident onwards: Learns from the first time by attaching the learnt outcome (verified fix) from memory.
    """
    has_prior_memory = bool(recalled_runbook and "No prior" not in recalled_runbook and "First occurrence" not in recalled_runbook)

    if has_prior_memory:
        fix, anti = _extract_learnt_outcome(recalled_runbook)
        if fix:
            patch = f"[Learnt Outcome from Incident History]\nVerified Fix: {fix}"
        else:
            patch = f"[Learnt Outcome from Incident History]\n{recalled_runbook}"
        
        anti_pattern = anti or "DO NOT repeat failed operational procedures from past outages."
        rationale = f"Learnt outcome retrieved from institutional memory for service '{service}'."
        return patch, anti_pattern, rationale
    else:
        patch = f"First-time incident observed for service '{service}'. No prior institutional memory or learnt outcome available."
        anti_pattern = f"First-time incident on '{service}': Avoid manual unverified code/config changes without root-cause analysis."
        rationale = f"First-time failure signatures require post-mortem analysis upon resolution to capture institutional runbooks."
        return patch, anti_pattern, rationale

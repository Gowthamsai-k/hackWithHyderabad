import os
import json
import re
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq
from .schemas import PostMortemExtraction
from .hindsight_service import retain_post_mortem

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3-32b")

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
    verified_fix = "Scaled capacity and patched service configuration"
    anti_pattern = "Avoid unverified rolling restarts during pool exhaustion"

    for msg in filtered_chat:
        text = msg.get("text", "")
        if "restart" in text.lower() and ("crashing" in text.lower() or "still" in text.lower() or "errors" in text.lower() or "re-triggered" in text.lower()):
            failed_steps.append("Rolling restart of service pods")
            anti_pattern = "Do not perform rolling restarts; they re-trigger connection pool exhaustion."
        elif "patch" in text.lower() or "scale" in text.lower() or "pool" in text.lower() or "helm" in text.lower():
            verified_fix = text

    root_cause = f"Resource starvation and connection exhaustion under ingress surge for {service}."
    for line in filtered_logs:
        if "ERROR" in line:
            root_cause = line.split("ERROR")[-1].strip()
            break

    return PostMortemExtraction(
        root_cause=root_cause,
        failed_attempts=failed_steps if failed_steps else ["Rolling restart on active service"],
        verified_fix=verified_fix,
        anti_pattern_warning=anti_pattern
    )

def run_idle_post_mortem(ticket_id: str, service: str, filtered_logs: list, filtered_chat: list, closed_at: datetime):
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
Output raw JSON only. Do NOT include markdown code blocks.
"""

    post_mortem = None

    if groq_client:
        try:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            parsed = clean_llm_json(response.choices[0].message.content)
            post_mortem = PostMortemExtraction(**parsed)
            print(f"[*] Successfully synthesized post-mortem using Groq ({GROQ_MODEL}) for {ticket_id}")
        except Exception as e:
            print(f"[!] Groq synthesis failed ({e}). Falling back to heuristic extractor.")

    if not post_mortem:
        post_mortem = _heuristic_post_mortem(service, filtered_logs, filtered_chat)
        print(f"[*] Generated post-mortem synthesis for {ticket_id} via fallback extractor.")

    # Ingest permanently into Hindsight memory
    retain_post_mortem(ticket_id, service, post_mortem, closed_at)
    return post_mortem

def synthesize_remediation_and_anti_pattern(service: str, error_type: str, raw_logs: list) -> tuple[str, str, str]:
    """
    Synthesizes a tailored unified-diff remediation patch and anti-pattern warning
    for incoming crash alerts. Uses Groq LLM if configured; otherwise applies
    context-aware heuristic patterns based on the language and stack trace.
    """
    logs_text = "\n".join(raw_logs[-20:]) if raw_logs else ""
    lower_logs = logs_text.lower()
    lower_err = (error_type or "").lower()

    if groq_client:
        prompt = f"""You are an expert SRE and Software Engineer. A runtime crash occurred in service '{service}'.
Error Type: {error_type}
Recent Logs & Stack Trace:
{logs_text}

Provide:
1. remediation_patch: A unified diff (diff format with - and + lines) showing the exact code or config fix needed.
2. anti_pattern: A clear directive stating what NOT to do (e.g. "DO NOT ...").
3. anti_pattern_rationale: 1-2 sentences explaining why that anti-pattern fails or worsens the issue.

Respond with valid JSON matching:
{{
  "remediation_patch": "...",
  "anti_pattern": "...",
  "anti_pattern_rationale": "..."
}}
Output raw JSON only. Do NOT include markdown code fences.
"""
        try:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = clean_llm_json(response.choices[0].message.content)
            patch = data.get("remediation_patch", "").strip()
            anti = data.get("anti_pattern", "").strip()
            rationale = data.get("anti_pattern_rationale", "").strip()
            if patch and anti:
                return patch, anti, rationale
        except Exception as e:
            print(f"[!] Groq patch generation failed ({e}). Using context-aware heuristic.")

    # Context-aware fallback based on stack trace / language
    if any(k in lower_err or k in lower_logs for k in ["indexoutofbound", "outofbounds", "indexerror"]):
        m = re.search(r"at\s+([\w\.\$]+)\.([\w\$]+)\(([\w]+\.java):(\d+)\)", logs_text)
        file_ref = m.group(3) if m else "App.java"
        line_ref = m.group(4) if m else "1"
        patch = f"""// {file_ref} (around line {line_ref})
- for (int i = 0; i <= items.length; i++) {{
+ for (int i = 0; i < items.length; i++) {{"""
        anti = "DO NOT suppress IndexOutOfBoundsException with empty try-catch blocks."
        rationale = "Suppressing bounds exceptions masks batch truncation, causing silent data drops and unfulfilled operations."
        return patch, anti, rationale

    elif "nullpointerexception" in lower_err or "nullpointer" in lower_logs:
        m = re.search(r"at\s+([\w\.\$]+)\.([\w\$]+)\(([\w]+\.java):(\d+)\)", logs_text)
        file_ref = m.group(3) if m else "App.java"
        line_ref = m.group(4) if m else "1"
        patch = f"""// {file_ref} (around line {line_ref})
- return target.process();
+ if (target == null) {{
+     logger.warn("Target instance is null; returning default");
+     return Optional.empty();
+ }}
+ return Optional.of(target.process());"""
        anti = "DO NOT catch generic java.lang.Throwable or java.lang.Exception to ignore NPE."
        rationale = "Catching generic exceptions conceals missing dependencies or uninitialized state, causing zombie threads."
        return patch, anti, rationale

    elif "zerodivisionerror" in lower_err or "division by zero" in lower_logs:
        patch = """# math/calculation.py
- return numerator / denominator
+ if denominator == 0:
+     return 0.0
+ return numerator / denominator"""
        anti = "DO NOT catch ZeroDivisionError without returning a sensible default."
        rationale = "Swallowing ZeroDivisionError leaves downstream calculations in an undefined state."
        return patch, anti, rationale

    elif "keyerror" in lower_err:
        patch = """# handler.py
- value = data['target_key']
+ value = data.get('target_key', default_fallback)"""
        anti = "DO NOT disable dictionary schema validation."
        rationale = "Allowing malformed JSON payloads bypasses downstream data contract guarantees."
        return patch, anti, rationale

    elif "redis" in lower_logs or "connectionpool" in lower_logs or "connection timeout" in lower_logs:
        patch = """# config/deployment.yaml
- POOL_MAX_ACTIVE: 20
+ POOL_MAX_ACTIVE: 80
+ POOL_IDLE_TIMEOUT: 45s"""
        anti = "DO NOT perform rolling pod restarts."
        rationale = "Rolling restarts under active load re-trigger immediate socket starvation and drop in-flight transactions."
        return patch, anti, rationale

    # Generic fallback
    patch = f"""// {service} error remediation
- // Unchecked invocation
+ try {{
+     validateInput(request);
+     executeSafe(request);
+ }} catch ({error_type or 'Exception'} ex) {{
+     logger.error("Handled boundary failure: " + ex.getMessage());
+ }}"""
    anti = "DO NOT restart the service container blindly without fixing the root cause."
    rationale = "Container restarts under identical load conditions replay the crash loop and degrade cluster availability."
    return patch, anti, rationale


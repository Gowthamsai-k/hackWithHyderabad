import os
import json
import re
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq
from schemas import PostMortemExtraction
from hindsight_service import retain_post_mortem

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

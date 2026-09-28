from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class AlertTriggerPayload(BaseModel):
    service: str = Field(..., description="Service identifier, e.g. checkout-service")
    error_type: str = Field(..., description="Classification of error, e.g. Redis::ConnectionTimeout")
    raw_logs: List[str]

class CommentPayload(BaseModel):
    author: str
    text: str

class PostMortemExtraction(BaseModel):
    root_cause: str = Field(description="The verified technical root cause.")
    failed_attempts: List[str] = Field(default_factory=list, description="Actions tried that failed or caused regressions.")
    verified_fix: str = Field(description="The specific action that resolved the outage.")
    anti_pattern_warning: str = Field(description="Actionable rule warning future engineers against dead-end steps.")

class Ticket(BaseModel):
    id: str
    service: str
    severity: str
    status: str  # OPEN, RESOLVED
    created_at: datetime
    raw_logs: List[str]
    comments: List[Dict[str, Any]] = Field(default_factory=list)
    hindsight_runbook: Optional[str] = None
    final_post_mortem: Optional[PostMortemExtraction] = None
    is_recurring: bool = False
    reduction_stats: Optional[Dict[str, Any]] = None
    agent_trace: List[Dict[str, Any]] = Field(default_factory=list)

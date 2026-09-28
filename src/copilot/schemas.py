from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AlertTriggerPayload(BaseModel):
    service: str = Field(..., description="Service identifier, e.g. checkout-service")
    error_type: str = Field(..., description="Classification of error, e.g. Redis::ConnectionTimeout")
    raw_logs: List[str]
    title: Optional[str] = None
    description: Optional[str] = None
    region: Optional[str] = None
    degraded_pods: Optional[str] = None
    error_spike: Optional[str] = None
    detection_source: Optional[str] = None
    blast_radius: Optional[List[str]] = None
    remediation_patch: Optional[str] = None
    anti_pattern: Optional[str] = None
    anti_pattern_rationale: Optional[str] = None
    environment_metadata: Optional[Dict[str, Any]] = None

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
    title: Optional[str] = None
    description: Optional[str] = None
    region: Optional[str] = None
    degraded_pods: Optional[str] = None
    error_spike: Optional[str] = None
    detection_source: Optional[str] = None
    blast_radius: List[str] = Field(default_factory=list)
    remediation_patch: Optional[str] = None
    anti_pattern: Optional[str] = None
    anti_pattern_rationale: Optional[str] = None
    comments: List[Dict[str, Any]] = Field(default_factory=list)
    hindsight_runbook: Optional[str] = None
    final_post_mortem: Optional[PostMortemExtraction] = None
    is_recurring: bool = False
    reduction_stats: Optional[Dict[str, Any]] = None
    agent_trace: List[Dict[str, Any]] = Field(default_factory=list)
    environment_metadata: Optional[Dict[str, Any]] = None

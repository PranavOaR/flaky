from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TestResult:
    test_id: str
    status: str  # 'passed' | 'failed' | 'error' | 'skipped'
    duration_s: float
    stdout: str


@dataclass
class RunRecord:
    run_index: int
    seed: int
    started_at: str
    duration_s: float
    results: list[TestResult] = field(default_factory=list)


@dataclass
class RootCause:
    category: str           # 'ordering' | 'timing' | 'randomness' | 'network' | 'unknown'
    confidence: str         # 'high' | 'medium' | 'low'
    evidence: list[str] = field(default_factory=list)


@dataclass
class FlakinessReport:
    test_id: str
    total_runs: int
    pass_count: int
    fail_count: int
    pass_rate: float
    flakiness_score: float                    # wilson lower bound on failure rate
    confidence_interval: tuple[float, float]  # (lower, upper) on failure rate
    is_flaky: bool
    severity: str                             # 'none' | 'low' | 'medium' | 'high' | 'critical'
    root_cause: Optional[RootCause] = None


@dataclass
class FixSuggestion:
    test_id: str
    root_cause_category: str
    template_fix: str             # always present
    code_snippet: Optional[str]   # python code block to display, if applicable
    ai_fix: Optional[str]         # only when --ai flag was used and API succeeded
    source: str                   # 'template' | 'ai' | 'template+ai'
    from_cache: bool              # True when ai_fix was retrieved from the DB cache

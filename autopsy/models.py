from dataclasses import dataclass, field


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

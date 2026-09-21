"""离线验收；所有子命令使用同一个 Python，不启动真实渠道。"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
COMMANDS = [
    ["-m", "ruff", "check", "."],
    ["-m", "ruff", "format", "--check", "."],
    [
        "-m",
        "pytest",
        "-q",
        "-m",
        "not live_wechat and not live_llm",
        "--cov",
        "--cov-branch",
        "--cov-report=term-missing",
        "--cov-report=json:reports/coverage-core.json",
        "--junitxml=reports/junit.xml",
    ],
    [
        "-m",
        "wechat_cs",
        "demo",
        "--scenario",
        "examples/scenarios/basic.json",
        "--report",
        "reports/demo.json",
    ],
    ["-m", "pytest", "-q", "tests/test_m2.py::test_a26_crash_recovery_subprocess"],
    ["-m", "wechat_cs", "doctor", "--adapter", "mock", "--report", "reports/doctor-mock.json"],
]


def main():
    REPORTS.mkdir(exist_ok=True)
    results = []
    for i, command in enumerate(COMMANDS):
        actual = [sys.executable, *command]
        start = datetime.now(UTC).isoformat()
        result = subprocess.run(actual, cwd=ROOT, text=True, capture_output=True)
        log = REPORTS / f"qa-{i + 1}.txt"
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        print(f"{i + 1}: exit={result.returncode} {log.name}")
        results.append(
            {
                "command": actual,
                "started_at": start,
                "exit_code": result.returncode,
                "evidence": str(log.relative_to(ROOT)),
            }
        )
    coverage = REPORTS / "coverage-core.json"
    if coverage.exists():
        totals = json.loads(coverage.read_text())["totals"]
        branches = totals["covered_branches"] / totals["num_branches"] * 100
    else:
        branches = 0
    success = all(r["exit_code"] == 0 for r in results) and branches >= 85
    report = {
        "status": "PASS" if success else "FAIL",
        "results": results,
        "core_branch_percent": branches,
        "windows": "NOT_RUN",
        "live_llm": "NOT_RUN",
    }
    (REPORTS / "qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"core branches: {branches:.2f}%")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

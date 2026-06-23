#!/usr/bin/env python3
"""Simple live Nexus memory eval harness.

This intentionally avoids extra dependencies. It writes synthetic memories to a
dedicated eval agent and checks whether recall returns expected keywords.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class EvalCase:
    name: str
    setup: list[dict[str, Any]]
    query: str
    expected_any: list[str]
    unexpected_any: list[str] | None = None
    limit: int = 5


@dataclass
class EvalResult:
    name: str
    passed: bool
    expected_found: list[str]
    unexpected_found: list[str]
    top_results: list[str]


CASES = [
    EvalCase(
        name="preference_recall_after_noise",
        setup=[
            {"content": "User prefers concise implementation summaries with explicit validation steps.", "memory_type": "preference", "importance": 0.9, "tags": ["preference"]},
            {"content": "Ephemeral note: discussed weather and lunch plans.", "memory_type": "observation", "importance": 0.1, "tags": ["noise"]},
        ],
        query="How should responses be summarized for this user?",
        expected_any=["concise", "validation"],
        unexpected_any=["weather", "lunch"],
    ),
    EvalCase(
        name="latest_correction_recall",
        setup=[
            {"content": "Old preference: user wanted very long explanations.", "memory_type": "preference", "importance": 0.3, "tags": ["old"]},
            {"content": "Correction: user now wants direct answers first, details only when useful.", "memory_type": "preference", "importance": 0.95, "tags": ["correction", "latest"]},
        ],
        query="What is the latest preference for answer style?",
        expected_any=["direct", "details only"],
    ),
    EvalCase(
        name="recurring_bug_fix_command",
        setup=[
            {"content": "Fix for asyncpg migration startup failure: run python3 -m compileall app scripts, then restart docker compose.", "memory_type": "lesson", "importance": 0.9, "tags": ["bugfix", "asyncpg"]},
        ],
        query="How did we fix the asyncpg migration startup failure?",
        expected_any=["compileall", "docker compose"],
    ),
    EvalCase(
        name="project_architecture_decision",
        setup=[
            {"content": "Architecture decision: raw session messages are preserved in sessions/messages and durable facts link back via memory_sources.", "memory_type": "decision", "importance": 0.9, "tags": ["architecture", "sessions"]},
        ],
        query="Where are raw session messages preserved and how are facts linked?",
        expected_any=["sessions", "memory_sources"],
    ),
]


class Client:
    def __init__(self, url: str, secret: str):
        self.url = url.rstrip("/")
        self.secret = secret

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}


def run_case(client: Client, case: EvalCase, agent_id: str) -> EvalResult:
    for item in case.setup:
        payload = {**item, "agent_id": agent_id, "metadata": {"eval": case.name, **item.get("metadata", {})}}
        client.request("POST", "/v1/memory/save", payload)
    # Let async queues/transactions settle for deployments with background work.
    time.sleep(0.1)
    recalled = client.request("POST", "/v1/memory/recall", {
        "query": case.query,
        "agent_id": agent_id,
        "limit": case.limit,
        "search_modes": ["vector", "lexical", "temporal"],
    })
    texts = [r.get("content", "") for r in recalled.get("results", [])]
    joined = "\n".join(texts).lower()
    expected_found = [kw for kw in case.expected_any if kw.lower() in joined]
    unexpected_found = [kw for kw in (case.unexpected_any or []) if kw.lower() in joined]
    return EvalResult(
        name=case.name,
        passed=bool(expected_found) and not unexpected_found,
        expected_found=expected_found,
        unexpected_found=unexpected_found,
        top_results=texts[:3],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.getenv("NEXUS_URL", "http://localhost:7777"))
    parser.add_argument("--secret", default=os.getenv("NEXUS_SECRET", ""))
    parser.add_argument("--agent-id", default=f"eval-{int(time.time())}")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.secret:
        print("NEXUS_SECRET is required", file=sys.stderr)
        return 2

    client = Client(args.url, args.secret)
    results = [run_case(client, case, args.agent_id) for case in CASES]
    passed = sum(1 for r in results if r.passed)
    output = {
        "agent_id": args.agent_id,
        "passed": passed,
        "total": len(results),
        "success_rate": passed / max(len(results), 1),
        "results": [asdict(r) for r in results],
    }
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Nexus memory evals: {passed}/{len(results)} passed ({output['success_rate']:.0%})")
        for r in results:
            mark = "PASS" if r.passed else "FAIL"
            print(f"[{mark}] {r.name} expected={r.expected_found} unexpected={r.unexpected_found}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

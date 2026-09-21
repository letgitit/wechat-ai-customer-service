"""只用 phase2 合成夹具，运行真实检索/政策；Mock 机械摘录不是质量验证。"""

import importlib.util
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from wechat_cs.config import Config
from wechat_cs.knowledge import KnowledgeBase, tokens, validate
from wechat_cs.knowledge_answer import KnowledgeReplies
from wechat_cs.knowledge_sources import digest

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "docs/phase2"
OUT = ROOT / "reports/phase2"


def load(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    spec = importlib.util.spec_from_file_location("score", PACK / "scripts/score_predictions.py")
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    cases, evidence = load(PACK / "fixtures/cases.jsonl"), load(PACK / "fixtures/evidence.jsonl")
    summaries = {}
    for label, types in [
        ("manual-only", ["manual"]),
        ("manual-history", ["manual", "history"]),
        ("all-sources", ["manual", "history", "code"]),
    ]:
        predictions = []
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            settings = directory / "config.toml"
            settings.write_text(
                Path("examples/knowledge.toml")
                .read_text()
                .replace("../.runtime/knowledge.sqlite3", "kb.sqlite3")
            )
            config = replace(
                Config(),
                knowledge_enabled=True,
                knowledge_config=str(settings),
                binding_id="test-group-a",
            )
            kb = KnowledgeBase(directory / "kb.sqlite3")
            try:
                for case in cases:
                    assert case["synthetic"] is True
                    kb.db.execute("DELETE FROM evidence")
                    reverse = {}
                    for original in evidence:
                        if original["evidence_id"] not in case["corpus_evidence_ids"]:
                            continue
                        validate(original, "evidence")
                        assert original["synthetic"] is True
                        locator = original["locator"]
                        path = (PACK / locator["path"]).resolve()
                        assert path.is_relative_to(PACK / "fixtures")
                        text = "\n".join(
                            path.read_text().splitlines()[
                                locator["start_line"] - 1 : locator["end_line"]
                            ]
                        )
                        assert text == original["text"] and digest(text) == original["content_hash"]
                        e = dict(original)
                        # Distinct fixture authorization snapshots may share the same locator.
                        e["source_id"] += ":" + digest([e["status"], e["valid_until"]])[:12]
                        e["evidence_id"] = digest(
                            [e["source_id"], e["revision"], locator, e["content_hash"]]
                        )
                        reverse[e["evidence_id"]] = original["evidence_id"]
                        kb.db.execute(
                            "INSERT INTO evidence VALUES(?,?,?,?,?,?)",
                            (
                                e["evidence_id"],
                                e["source_id"],
                                "synthetic-fixture-eval",
                                json.dumps(e),
                                "verified-fixture-locator",
                                " ".join(tokens(text)),
                            ),
                        )
                    kb.db.commit()
                    provider = KnowledgeReplies(config)
                    # Trusted synthetic test scope, never taken from a customer question.
                    provider.scope = {**case["trusted_scope"], "deployed_revision": "fixture-v21"}
                    provider.settings["retrieval"] = {"source_types": types}
                    result = provider.generate(case["question"])
                    retrieved = [reverse[e["evidence_id"]] for e in result["retrieval"]["evidence"]]
                    predictions.append(
                        {
                            "case_id": case["case_id"],
                            "retrieved_evidence_ids": retrieved,
                            "prompt_evidence_ids": [
                                reverse[key] for key in result["model_input_evidence_ids"]
                            ],
                            "cited_evidence_ids": [
                                reverse[c["evidence_id"]] for c in result["draft"]["citations"]
                            ],
                            "action": result["draft"]["action"],
                            "customer_reply": result["review"]["safe_customer_reply"],
                            "elapsed_ms": result["elapsed_ms"],
                            "synthetic": True,
                            "generation": "MOCK_EXTRACTIVE",
                            "external_calls": 0,
                        }
                    )
            finally:
                kb.close()
        report = scorer.score(cases, predictions, k=8)
        times = sorted(p["elapsed_ms"] for p in predictions)
        report.update(
            synthetic=True,
            generation="MOCK_EXTRACTIVE",
            live_model="NOT_RUN",
            semantic_retrieval="NOT_RUN",
            real_customer_quality="NOT_RUN",
            human_adoption="NOT_RUN",
            unsupported_claim_rate="NOT_RUN",
            citation_entailment="NOT_RUN",
            cost=0,
            latency_scope="local mock only",
            p50_ms=times[len(times) // 2],
            p95_ms=times[int(len(times) * 0.95) - 1],
        )
        (OUT / f"{label}-predictions.jsonl").write_text(
            "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in predictions)
        )
        (OUT / f"{label}-metrics.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        summaries[label] = {k: v for k, v in report.items() if k != "cases"}
    (OUT / "evaluation.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

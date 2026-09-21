"""CLI 复用；不会建立微信适配器。"""

import json
from dataclasses import replace
from pathlib import Path

from .config import load_config
from .knowledge import KnowledgeBase, bound_scope, load_settings
from .knowledge_answer import KnowledgeReplies


def add_commands(sub):
    for command, actions in [
        ("kb", ["ingest", "status", "search"]),
        ("answer", ["preview", "explain"]),
    ]:
        group = sub.add_parser(command).add_subparsers(dest="operation", required=True)
        for action in actions:
            cmd = group.add_parser(action)
            cmd.add_argument("--config", required=True, help="knowledge TOML")
            cmd.add_argument("--report")
            cmd.add_argument("--offline", action="store_true")
            if action in {"search", "preview", "explain"}:
                cmd.add_argument("--group", required=action != "explain")
                cmd.add_argument("--query", required=action != "explain")
            if action == "explain":
                cmd.add_argument("--task-id")
            if action == "ingest":
                cmd.add_argument("--manifest")
    cmd = sub.add_parser("eval")
    cmd.add_argument("--config", required=True)
    cmd.add_argument("--cases", required=True)
    cmd.add_argument("--predictions", required=True)
    cmd.add_argument("--offline", action="store_true", required=True)
    cmd.add_argument("--report")


def execute(args):
    settings = load_settings(args.config)
    if settings.get("model", {}).get("provider", "mock") != "mock":
        raise ValueError("CLI_OFFLINE_ONLY")
    kb = KnowledgeBase(settings["knowledge"]["db_path"])
    try:
        if args.command == "kb":
            if args.operation == "ingest":
                return kb.ingest(args.manifest or settings["knowledge"]["manifest"])
            if args.operation == "status":
                return {
                    "chunks": len(kb.evidence()),
                    "index_revision": kb.revision(),
                    "semantic_retrieval": "NOT_RUN",
                    "mode": "shadow",
                    "auto_send": False,
                }
            return kb.search(args.query, bound_scope(settings, args.group))
        if args.command == "answer":
            if getattr(args, "task_id", None):
                row = kb.db.execute(
                    "SELECT body FROM shadow WHERE task_id=?", (args.task_id,)
                ).fetchone()
                if row is None:
                    raise ValueError("TASK_NOT_FOUND")
                return json.loads(row[0])
            if not args.query or not args.group:
                raise ValueError("QUERY_AND_GROUP_REQUIRED")
            config = replace(
                load_config(None),
                knowledge_enabled=True,
                knowledge_config=args.config,
                binding_id=args.group,
            )
            return KnowledgeReplies(config).generate(args.query)
        cases = [
            json.loads(line) for line in Path(args.cases).read_text().splitlines() if line.strip()
        ]
        predictions = []
        for case in cases:
            if case.get("synthetic") is not True:
                raise ValueError("SYNTHETIC_EVAL_ONLY")
            # Labels never enter provider: only question and a locally registered group are used.
            group = case["trusted_scope"]["group_id"]
            config = replace(
                load_config(None),
                knowledge_enabled=True,
                knowledge_config=args.config,
                binding_id=group,
            )
            result = KnowledgeReplies(config).generate(case["question"])
            predictions.append(
                {
                    "case_id": case["case_id"],
                    "synthetic": True,
                    "action": result["draft"]["action"],
                    "customer_reply": result["review"]["safe_customer_reply"],
                    "retrieved_evidence_ids": [
                        e["evidence_id"] for e in result["retrieval"]["evidence"]
                    ],
                    "prompt_evidence_ids": result["model_input_evidence_ids"],
                    "cited_evidence_ids": [c["evidence_id"] for c in result["draft"]["citations"]],
                    "elapsed_ms": result["elapsed_ms"],
                    "model": "mock",
                }
            )
        output = Path(args.predictions)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in predictions))
        return {
            "status": "PASS",
            "synthetic": True,
            "predictions": len(predictions),
            "quality": "NOT_RUN",
            "semantic_retrieval": "NOT_RUN",
            "note": "IDs are content-derived; map fixture labels by source/locator before scoring.",
        }
    finally:
        kb.close()

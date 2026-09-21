"""本地知识库；先授权后召回，无跨租户缓存。"""

import fnmatch
import json
import logging
import math
import re
import sqlite3
import tempfile
import time
import tomllib
from datetime import date
from pathlib import Path

import jieba
from jsonschema import Draft202012Validator, FormatChecker

from .knowledge_sources import (
    SENSITIVE,
    SourceError,
    blocks,
    digest,
    history_records,
    read_source,
)

TOKENIZER_VERSION = "jieba-search-0.42.1-exact-v1"
STOP_WORDS = set(
    (
        "的 了 是 在 有 和 与 我 你 他 它 吗 呢 吧 啊 怎么 如何 为什么 "
        "请 一个 这个 那个 是否 怎么办 不存在 页面"
    ).split()
)
jieba.setLogLevel(logging.ERROR)
TOKENIZER = jieba.Tokenizer()
TOKENIZER.tmp_dir = tempfile.gettempdir()
SCHEMAS = Path(__file__).with_name("schemas")


def validate(value, name):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def tokens(text):
    result = list(TOKENIZER.cut_for_search(text))
    for word in re.findall(r"[A-Za-z0-9_:/.-]+", text):
        result.append(word)
        result.extend(re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+", word))
    return sorted(
        {
            w.casefold()
            for w in result
            if w.strip() and w not in STOP_WORDS and any(c.isalnum() for c in w)
        }
    )


def allowed(e, scope, *, external=False, embedding=False):
    today = scope.get("as_of", date.today().isoformat())
    version = scope.get("deployed_version")
    return bool(
        version
        and version != "unknown"
        and e["product_id"] == scope.get("product_id")
        and e["version"] == version
        and (scope.get("tenant_id") in e["tenant_ids"] or "shared" in e["tenant_ids"])
        and (scope.get("group_id") in e["group_ids"] or "shared" in e["group_ids"])
        and e["status"] == "active"
        and e["reviewer"].strip()
        and e["valid_from"] <= today
        and (e["valid_until"] is None or today <= e["valid_until"])
        and e["allow_customer_derivation"]
        and (e["source_type"] != "code" or e["revision"] == scope.get("deployed_revision"))
        and (not external or e["allow_external_generation"])
        and (not embedding or e["allow_external_embedding"])
    )


def load_settings(path):
    path = Path(path).resolve()
    data = tomllib.loads(path.read_text())
    k = data.get("knowledge", {})
    if k.get("mode", "shadow") != "shadow" or k.get("auto_send", False) is not False:
        raise ValueError("KNOWLEDGE_SHADOW_ONLY")
    if k.get("require_review", True) is not True:
        raise ValueError("REVIEW_REQUIRED")
    for key in ("db_path", "manifest"):
        if key not in k:
            raise ValueError("KNOWLEDGE_PATH_REQUIRED")
        k[key] = str((path.parent / k[key]).resolve())
    bindings = data.get("group_bindings", [])
    if len({b["id"] for b in bindings}) != len(bindings):
        raise ValueError("DUPLICATE_BINDING")
    for binding in bindings:
        if any(
            not isinstance(binding.get(key), str) or not binding[key]
            for key in ("id", "tenant_id", "product_id", "deployed_version")
        ):
            raise ValueError("INVALID_BINDING")
    if data.get("embedding", {}).get("provider", "disabled") != "disabled":
        raise ValueError("EMBEDDING_BACKEND_NOT_CONFIGURED")
    data["knowledge"] = k
    return data


def bound_scope(settings, group):
    matches = [b for b in settings["group_bindings"] if b["id"] == group]
    if len(matches) != 1:
        raise ValueError("UNKNOWN_BINDING")
    return {**matches[0], "group_id": group}


def rrf(*rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            scores[key] = scores.get(key, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda key: (-scores[key], key)), scores


class KnowledgeBase:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS evidence (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, manifest TEXT NOT NULL,
          body TEXT NOT NULL, parser TEXT NOT NULL, tokens TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS shadow (
          task_id TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS policy_audit (
          id INTEGER PRIMARY KEY, time TEXT DEFAULT CURRENT_TIMESTAMP, source TEXT NOT NULL,
          before_policy TEXT, after_policy TEXT);
        CREATE TABLE IF NOT EXISTS source_audit (
          id INTEGER PRIMARY KEY, time TEXT DEFAULT CURRENT_TIMESTAMP,
          source TEXT NOT NULL, old_hash TEXT, new_hash TEXT);
        """)
        version = self.db.execute("SELECT value FROM meta WHERE key='tokenizer'").fetchone()
        if version and version[0] != TOKENIZER_VERSION:
            raise ValueError("TOKENIZER_REBUILD_REQUIRED")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES (?,?)", ("tokenizer", TOKENIZER_VERSION))
        self.db.commit()

    def close(self):
        self.db.close()

    def evidence(self):
        return [
            json.loads(row[0]) for row in self.db.execute("SELECT body FROM evidence ORDER BY id")
        ]

    def revision(self):
        return digest(
            [
                tuple(row)
                for row in self.db.execute("SELECT id,body,parser FROM evidence ORDER BY id")
            ]
        )

    def ingest(self, manifest):
        manifest = Path(manifest).resolve()
        sources = tomllib.loads(manifest.read_text()).get("sources", [])
        if len({s["id"] for s in sources}) != len(sources):
            raise ValueError("DUPLICATE_SOURCE")
        pending, report = {}, []
        for source in sources:
            if not source.get("enabled", False):
                continue
            root = (manifest.parent / source["root"]).absolute()
            if source["type"] == "code" and source.get("role") != "product":
                raise ValueError("PRODUCT_ROLE_REQUIRED")
            if not source.get("include") or any(
                ".." in Path(p).parts or Path(p).is_absolute() for p in source["include"]
            ):
                raise ValueError("INVALID_INCLUDE")
            # Only explicitly supplied roots/globs; no default application root.
            paths = sorted(
                {
                    p
                    for pattern in source["include"]
                    for p in root.glob(pattern)
                    if p.is_file() or p.is_symlink()
                }
            )
            if not paths:
                report.append({"source": source["id"], "status": "MISSING_OR_EMPTY"})
            for path in paths:
                relative = path.relative_to(root).as_posix()
                if any(fnmatch.fnmatch(relative, p) for p in source.get("exclude", [])):
                    continue
                try:
                    relative, raw = read_source(root, path, source)
                    entries = []
                    if source["type"] == "history":
                        for row in history_records(path, raw):
                            if (
                                row.get("resolved") is not True
                                or row.get("review_status") != "approved"
                            ):
                                continue
                            if not row.get("reviewer") or not row.get("resolution"):
                                continue
                            if (
                                row.get("tenant_id") not in source["tenant_ids"]
                                or row.get("group_id") not in source["group_ids"]
                                or row.get("product_id") != source["product_id"]
                            ):
                                continue
                            local = {
                                **source,
                                "version": row["version"],
                                "reviewer": row["reviewer"],
                                "tenant_ids": [row["tenant_id"]],
                                "group_ids": [row["group_id"]],
                            }
                            text = "\n".join(
                                f"{k}: {row.get(k, '')}"
                                for k in ("question", "context", "answer", "resolution")
                            )
                            entries.append(
                                (
                                    local,
                                    text,
                                    {
                                        "start_line": row["_source_lines"][0],
                                        "end_line": row["_source_lines"][1],
                                        "section": row["case_id"],
                                    },
                                    "reviewed-case",
                                )
                            )
                    else:
                        entries = [
                            (source, text, locator, parser)
                            for text, locator, parser in blocks(path, raw, source["type"])
                        ]
                    for metadata, text, locator, parser in entries:
                        if SENSITIVE.search(text):
                            raise SourceError("SENSITIVE_CONTENT_REJECTED")
                        e = {
                            k: metadata[k]
                            for k in (
                                "product_id",
                                "version",
                                "revision",
                                "status",
                                "tenant_ids",
                                "group_ids",
                                "valid_from",
                                "valid_until",
                                "reviewer",
                                "audience",
                                "allow_customer_derivation",
                                "allow_external_generation",
                                "allow_external_embedding",
                                "synthetic",
                            )
                            if k in metadata
                        }
                        e.setdefault("valid_until", None)
                        e.update(
                            source_id=source["id"],
                            source_type=source["type"],
                            text=text,
                            locator={"path": relative, **locator},
                            content_hash=digest(text),
                        )
                        e["evidence_id"] = digest(
                            [source["id"], e["revision"], e["locator"], e["content_hash"]]
                        )
                        validate(e, "evidence")
                        if e["locator"]["end_line"] < e["locator"]["start_line"]:
                            raise SourceError("INVALID_LOCATOR")
                        pending[e["evidence_id"]] = (e, parser)
                    report.append(
                        {
                            "source": source["id"],
                            "path": relative,
                            "status": "IMPORTED",
                            "chunks": len(entries),
                        }
                    )
                except Exception as exc:
                    # File atomicity: partial chunks from failed file must not survive.
                    pending = {
                        key: value
                        for key, value in pending.items()
                        if not (
                            value[0]["source_id"] == source["id"]
                            and value[0]["locator"]["path"] == relative
                        )
                    }
                    reason = str(exc) if isinstance(exc, SourceError) else type(exc).__name__
                    report.append(
                        {
                            "source": source["id"],
                            "path": relative,
                            "status": "BLOCKED",
                            "reason": reason,
                        }
                    )
        old = {
            row[0]: row[1]
            for row in self.db.execute(
                "SELECT id,body FROM evidence WHERE manifest=?", (str(manifest),)
            )
        }
        changed = removed = 0
        with self.db:
            for key in old.keys() - pending.keys():
                self.db.execute("DELETE FROM evidence WHERE id=?", (key,))
                self.db.execute(
                    "INSERT INTO source_audit(source,old_hash) VALUES(?,?)",
                    (json.loads(old[key])["source_id"], digest(old[key])),
                )
                self.audit_policy(json.loads(old[key]), None)
                removed += 1
            for key, (e, parser) in pending.items():
                body = json.dumps(e, ensure_ascii=False, sort_keys=True)
                owner = self.db.execute(
                    "SELECT manifest FROM evidence WHERE id=?", (key,)
                ).fetchone()
                if owner and owner[0] != str(manifest):
                    raise ValueError("SOURCE_OWNERSHIP_CONFLICT")
                if old.get(key) == body:
                    continue
                self.db.execute(
                    "INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?,?)",
                    (key, e["source_id"], str(manifest), body, parser, " ".join(tokens(e["text"]))),
                )
                self.db.execute(
                    "INSERT INTO source_audit(source,old_hash,new_hash) VALUES(?,?,?)",
                    (e["source_id"], digest(old[key]) if key in old else None, digest(body)),
                )
                self.audit_policy(json.loads(old[key]) if key in old else None, e)
                changed += 1
        return {
            "files": report,
            "changed": changed,
            "removed": removed,
            "index_revision": self.revision(),
            "tokenizer": TOKENIZER_VERSION,
        }

    def audit_policy(self, before, after):
        def policy(e):
            return (
                json.dumps({k: v for k, v in e.items() if k != "text"}, ensure_ascii=False)
                if e
                else None
            )

        self.db.execute(
            "INSERT INTO policy_audit(source,before_policy,after_policy) VALUES(?,?,?)",
            ((after or before)["source_id"], policy(before), policy(after)),
        )

    def search(
        self,
        query,
        scope,
        *,
        external=False,
        vector=None,
        top_k=8,
        budget=12000,
        deadline=None,
        source_types=None,
        aliases=None,
    ):
        started = time.monotonic()
        if len(query) > 1000 or (deadline and started >= deadline):
            raise ValueError("QUERY_LIMIT")
        expansion = [v for k, values in (aliases or {}).items() if k in query for v in values]
        expanded_query = " ".join([query, *expansion])
        candidates = {
            e["evidence_id"]: e
            for e in self.evidence()
            if allowed(e, scope, external=external)
            and (source_types is None or e["source_type"] in source_types)
        }
        # ponytail: O(n) authorized FTS partition; persistent partitions when scale requires.
        with sqlite3.connect(":memory:") as fts:
            fts.execute("CREATE VIRTUAL TABLE hits USING fts5(id UNINDEXED, body)")
            fts.executemany(
                "INSERT INTO hits VALUES(?,?)",
                [(key, " ".join(tokens(e["text"]))) for key, e in candidates.items()],
            )
            terms = tokens(expanded_query)[:128]
            match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            lexical = (
                [
                    row[0]
                    for row in fts.execute(
                        "SELECT id FROM hits WHERE hits MATCH ? ORDER BY bm25(hits),id LIMIT 20",
                        (match,),
                    )
                ]
                if match
                else []
            )
        ranks, trace = rrf(lexical)
        mode, reason = "lexical", "embedding_disabled; semantic_retrieval=NOT_RUN"
        if vector is not None:
            try:
                vector_candidates = {
                    key: e
                    for key, e in candidates.items()
                    if not vector.external or allowed(e, scope, embedding=True)
                }
                vectors = vector.encode([query, *[e["text"] for e in vector_candidates.values()]])
                if len(vectors) != len(vector_candidates) + 1 or any(
                    len(v) != vector.dimension or not all(math.isfinite(x) for x in v)
                    for v in vectors
                ):
                    raise ValueError("VECTOR_DIMENSION_OR_VALUE")

                def unit(v):
                    norm = math.sqrt(sum(x * x for x in v))
                    if not norm:
                        raise ValueError("ZERO_VECTOR")
                    return [x / norm for x in v]

                q = unit(vectors[0])
                scores = {
                    key: sum(a * b for a, b in zip(q, unit(v), strict=True))
                    for key, v in zip(vector_candidates, vectors[1:], strict=True)
                }
                ranked = sorted(scores, key=lambda key: (-scores[key], key))[:20]
                ranks, trace = rrf(lexical, ranked)
                mode, reason = "hybrid_rrf", ""
            except Exception:
                mode, reason = "lexical", "embedding_failed; semantic_retrieval=DEGRADED"
        selected, used = [], 0
        for key in ranks:
            e = candidates[key]
            if used + len(e["text"]) > budget:
                continue
            selected.append(e)
            used += len(e["text"])
            if len(selected) >= top_k:
                break
        if deadline and time.monotonic() >= deadline:
            raise ValueError("DEADLINE_EXCEEDED")
        return {
            "evidence": selected,
            "scope": scope,
            "query": query,
            "query_expansion": expansion,
            "rank_trace": trace,
            "parser_trace": {
                row[0]: row[1]
                for row in self.db.execute("SELECT id,parser FROM evidence")
                if row[0] in {e["evidence_id"] for e in selected}
            },
            "retrieval_mode": mode,
            "degraded_reason": reason,
            "index_revision": self.revision(),
            "elapsed_ms": (time.monotonic() - started) * 1000,
            "tokenizer": TOKENIZER_VERSION,
            "embedding": None
            if vector is None
            else {
                "model": vector.model,
                "dimension": vector.dimension,
                "normalization": "l2",
                "source_revision": self.revision(),
            },
        }

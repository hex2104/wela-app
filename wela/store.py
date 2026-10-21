"""Case storage on local disk: cases/<id>/result.json + events.jsonl.gz"""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
from datetime import datetime
from typing import List, Optional

from .models import Event

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cases")


def _dir(case_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", case_id or ""):
        raise ValueError("bad case id")
    return os.path.join(ROOT, case_id)


def new_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name or "case").strip("-")[:40] or "case"
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slug


def save(case_id: str, result: dict, events: List[Event]) -> None:
    d = _dir(case_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    with gzip.open(os.path.join(d, "events.jsonl.gz"), "wt", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")


def load_result(case_id: str) -> Optional[dict]:
    p = os.path.join(_dir(case_id), "result.json")
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


_cache = {}


def load_events(case_id: str) -> List[dict]:
    if case_id in _cache:
        return _cache[case_id]
    p = os.path.join(_dir(case_id), "events.jsonl.gz")
    out = []
    if os.path.isfile(p):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            out = [json.loads(line) for line in fh if line.strip()]
    _cache.clear()
    _cache[case_id] = out
    return out


def list_cases() -> List[dict]:
    if not os.path.isdir(ROOT):
        return []
    out = []
    for cid in sorted(os.listdir(ROOT), reverse=True):
        p = os.path.join(ROOT, cid, "result.json")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                r = json.load(fh)
        except Exception:
            continue
        out.append({"id": cid, "name": r.get("case_name") or cid, "computer": r.get("computer"),
                    "generated": r.get("generated"), "counts": r.get("counts"), "coverage": r.get("coverage")})
    return out


def delete(case_id: str) -> None:
    d = _dir(case_id)
    _cache.pop(case_id, None)
    if os.path.isdir(d):
        shutil.rmtree(d)

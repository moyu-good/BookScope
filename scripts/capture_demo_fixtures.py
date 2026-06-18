"""把 BookScope 13 个功能在公有领域《三国演义》上真跑一遍，捕获真实响应。

产出 web/src/demo/captured-fixtures.json，给静态 demo 用。

红线（违反即作废）：
1. API key 绝不进任何文件——只从 os.environ["DEEPSEEK_API_KEY"] 读，放进发给
   后端的请求体里（BYOK）。不写进脚本、不写进 fixtures、不写进日志。
2. 绝不出现真名路径——只用相对路径 _demo_book/sanguo.epub。

跑法：
    DEEPSEEK_API_KEY=sk-xxx python scripts/capture_demo_fixtures.py

增量保存：每跑完一个功能就落盘，可随时中断重跑。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

# Windows 控制台默认 cp932/gbk，中文 print 会崩——强制 stdout/stderr UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

# --- 配置（key 绝不在这里，只从 env 读）-------------------------------------
BASE = "http://127.0.0.1:8000"
BOOK_PATH = Path("_demo_book/sanguo.epub")  # 相对路径，绝不带真名
BOOK_TITLE = "三国演义"
PROVIDER = "deepseek"
MODEL = "deepseek-v4-flash"  # 最便宜的大众档
OUT_PATH = Path("web/src/demo/captured-fixtures.json")

from dotenv import load_dotenv  # 从 gitignored .env 读 key（不进命令行/transcript）

load_dotenv()
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: 环境变量 DEEPSEEK_API_KEY 未设置。", file=sys.stderr)
    sys.exit(1)

# 长上下文 / 整本进上下文的功能给长超时；快路径给短一点。
LONG_TIMEOUT = 900  # 15 分钟
SHORT_TIMEOUT = 300  # 5 分钟


def _base_body(session_id: str) -> dict:
    """所有 agent 端点共用的 BYOK body 骨架。"""
    return {
        "book_session_id": session_id,
        "provider": PROVIDER,
        "api_key": API_KEY,
        "model": MODEL,
    }


def _scrub(obj):
    """产出前自查：把任何 sk- 开头的串替换成占位（双保险，正常不该命中）。"""
    if isinstance(obj, str):
        if obj.startswith("sk-") or API_KEY in obj:
            return "<REDACTED>"
        return obj
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


class Capture:
    def __init__(self) -> None:
        self.data: dict = {
            "json": {},
            "sse": {},
            "meta": {
                "book": BOOK_TITLE,
                "chapters_used": "未知",
                "model": MODEL,
                "provider": PROVIDER,
                "cost_est": "",
                "skipped": [],
                "failures": {},
                "notes": "",
                "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
        # 已有产物则续写（增量重跑）
        if OUT_PATH.exists():
            try:
                prev = json.loads(OUT_PATH.read_text(encoding="utf-8"))
                self.data["json"].update(prev.get("json", {}))
                self.data["sse"].update(prev.get("sse", {}))
            except Exception:
                pass

    def save(self) -> None:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        clean = _scrub(self.data)
        OUT_PATH.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def record_json(self, key: str, resp) -> None:
        self.data["json"][key] = resp
        self.save()
        print(f"  [saved json] {key}")

    def record_fail(self, key: str, reason: str) -> None:
        self.data["meta"]["failures"][key] = reason
        self.save()
        print(f"  [FAIL] {key}: {reason}")


def post_json(path: str, body: dict, timeout: int) -> tuple[bool, object]:
    """发 JSON POST，返回 (ok, payload)。payload 是解析后的响应或错误描述。"""
    try:
        r = requests.post(BASE + path, json=body, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        return False, f"请求异常: {type(exc).__name__}: {exc}"
    if r.status_code != 200:
        try:
            return False, {"status": r.status_code, "body": r.json()}
        except Exception:
            return False, {"status": r.status_code, "body": r.text[:500]}
    try:
        return True, r.json()
    except Exception as exc:
        return False, f"JSON 解析失败: {exc}"


def upload_book() -> str | None:
    """上传整本三国，返回 session_id。"""
    print(f"上传 {BOOK_PATH} ...")
    if not BOOK_PATH.exists():
        print(f"ERROR: 书文件不存在 {BOOK_PATH}", file=sys.stderr)
        return None
    with BOOK_PATH.open("rb") as fh:
        files = {"file": ("sanguo.epub", fh, "application/epub+zip")}
        form = {
            "book_title": BOOK_TITLE,
            "language": "zh",
            "provider": PROVIDER,
            "api_key": API_KEY,
            "model": MODEL,
        }
        try:
            r = requests.post(
                BASE + "/api/books/upload",
                files=files,
                data=form,
                timeout=LONG_TIMEOUT,
            )
        except requests.exceptions.RequestException as exc:
            print(f"ERROR: 上传请求异常 {exc}", file=sys.stderr)
            return None
    if r.status_code != 200:
        print(f"ERROR: 上传失败 {r.status_code}: {r.text[:800]}", file=sys.stderr)
        return None
    payload = r.json()
    sid = payload["session_id"]
    cd = payload.get("chapter_detection") or {}
    print(f"  session_id={sid}")
    print(
        f"  chunk_count={payload.get('chunk_count')} "
        f"character_count={payload.get('character_count')} "
        f"chapters_detected={cd.get('chapters_detected')}"
    )
    return sid


def capture_sessions(cap: Capture) -> None:
    print("GET /api/sessions ...")
    try:
        r = requests.get(BASE + "/api/sessions", timeout=30)
        if r.status_code == 200:
            cap.record_json("GET /api/sessions", r.json())
        else:
            cap.record_fail("GET /api/sessions", f"status {r.status_code}")
    except requests.exceptions.RequestException as exc:
        cap.record_fail("GET /api/sessions", str(exc))


def capture_sse_ask(cap: Capture, sid: str) -> None:
    """旗舰问答 SSE，录原始响应体全文（保留 data: ...\\n\\n 框架）。"""
    question = "诸葛亮和刘备的关系是怎么一步步发展起来的？"
    body = {
        "question": question,
        "book_session_id": sid,
        "provider": PROVIDER,
        "api_key": API_KEY,
        "model": MODEL,
    }
    print(f"POST /api/agent/ask/stream (SSE) ... 问：{question}")
    try:
        r = requests.post(
            BASE + "/api/agent/ask/stream",
            json=body,
            timeout=LONG_TIMEOUT,
            stream=True,
        )
    except requests.exceptions.RequestException as exc:
        cap.record_fail("POST /api/agent/ask/stream", f"请求异常: {exc}")
        return
    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:500]
        cap.record_fail(
            "POST /api/agent/ask/stream", f"status {r.status_code}: {detail}"
        )
        return
    # 原样收字节流，保留 SSE 帧框架
    chunks: list[str] = []
    for raw in r.iter_content(chunk_size=None):
        if raw:
            chunks.append(raw.decode("utf-8", errors="replace"))
    sse_text = "".join(chunks)
    cap.data["sse"]["POST /api/agent/ask/stream"] = sse_text
    cap.save()
    print(f"  [saved sse] 共 {len(sse_text)} 字符")


def main() -> None:
    cap = Capture()

    # 0. 上传建会话（全本）
    sid = upload_book()
    if not sid:
        cap.data["meta"]["notes"] = "上传失败，无法继续"
        cap.save()
        sys.exit(1)
    cap.data["meta"]["session_id"] = sid
    cap.save()

    # 1. GET /api/sessions（书架）
    capture_sessions(cap)

    # 2. SSE 旗舰问答
    capture_sse_ask(cap, sid)

    # 3. suggest-questions / check-citations 之外的 JSON 功能，逐个调。
    #    check-citations 依赖一次 ask 的 answer+citations，单独处理。

    base = _base_body(sid)

    jobs: list[tuple[str, str, dict, int]] = [
        # (fixture key, path, body, timeout)
        (
            "POST /api/agent/suggest-questions",
            "/api/agent/suggest-questions",
            dict(base),
            SHORT_TIMEOUT,
        ),
        (
            "POST /api/agent/character-graph",
            "/api/agent/character-graph",
            {**base, "unit": "person"},
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/timeline",
            "/api/agent/timeline",
            dict(base),
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/pacing-curve",
            "/api/agent/pacing-curve",
            dict(base),
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/consistency-scan",
            "/api/agent/consistency-scan",
            dict(base),
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/entity-recall",
            "/api/agent/entity-recall",
            {**base, "entity": "赵云"},
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/recap",
            "/api/agent/recap",
            {**base, "up_to_chapter": 30},
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/motif-tracking",
            "/api/agent/motif-tracking",
            {**base, "motif": "忠义"},
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/argument-structure",
            "/api/agent/argument-structure",
            dict(base),
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/concept-evolution",
            "/api/agent/concept-evolution",
            {**base, "concept": "天下大势"},
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/writing-technique",
            "/api/agent/writing-technique",
            dict(base),
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/study-cards",
            "/api/agent/study-cards",
            dict(base),
            LONG_TIMEOUT,
        ),
        (
            "POST /api/agent/style-issues",
            "/api/agent/style-issues",
            dict(base),
            LONG_TIMEOUT,
        ),
        # —— 下一程·可视化深化新增的 7 个端点（批量 live-verify + demo fixture）——
        ("POST /api/agent/character-flow", "/api/agent/character-flow", dict(base), LONG_TIMEOUT),
        ("POST /api/agent/narrative-curve", "/api/agent/narrative-curve", dict(base), LONG_TIMEOUT),
        ("POST /api/agent/relationship-timeline", "/api/agent/relationship-timeline", dict(base), LONG_TIMEOUT),
        ("POST /api/agent/character-arc", "/api/agent/character-arc", dict(base), LONG_TIMEOUT),
        ("POST /api/agent/foreshadow-arcs", "/api/agent/foreshadow-arcs", dict(base), LONG_TIMEOUT),
        ("POST /api/agent/subplot-weave", "/api/agent/subplot-weave", dict(base), LONG_TIMEOUT),
        ("POST /api/agent/character-voice", "/api/agent/character-voice", {**base, "character": "诸葛亮"}, LONG_TIMEOUT),
        # —— #7 精读注释层:编排已有源端点,默认伏笔+矛盾两层 ——
        ("POST /api/agent/annotations", "/api/agent/annotations", {**base, "layers": ["foreshadow", "contradiction"]}, LONG_TIMEOUT),
    ]

    # 跳过已捕获成功的（增量重跑）
    for key, path, body, timeout in jobs:
        if key in cap.data["json"]:
            print(f"跳过已有: {key}")
            continue
        print(f"POST {path} ...")
        t0 = time.time()
        ok, payload = post_json(path, body, timeout)
        dt = time.time() - t0
        if ok:
            cap.record_json(key, payload)
            print(f"  OK in {dt:.1f}s")
        else:
            cap.record_fail(key, str(payload)[:800])

    # 4. check-citations：拿 SSE 答案里的 answer + citations 喂回去核验。
    if "POST /api/agent/check-citations" not in cap.data["json"]:
        cc_done = _capture_check_citations(cap)
        if not cc_done:
            print("  check-citations 未捕获（见 failures）")

    cap.save()
    print("\n=== 完成 ===")
    print(f"成功 JSON: {len(cap.data['json'])} 个")
    print(f"SSE: {'有' if cap.data['sse'] else '无'}")
    print(f"失败: {list(cap.data['meta']['failures'].keys())}")


def _extract_answer_from_sse(sse_text: str) -> tuple[str, list] | None:
    """从 SSE 原文里抽 final_answer 的 answer + citations。"""
    answer = ""
    citations: list = []
    for block in sse_text.split("\n\n"):
        if "final_answer" not in block:
            continue
        for line in block.splitlines():
            if line.startswith("data:"):
                try:
                    payload = json.loads(line[len("data:") :].strip())
                except Exception:
                    continue
                if payload.get("answer"):
                    answer = payload["answer"]
                if payload.get("citations"):
                    citations = payload["citations"]
    if answer:
        return answer, citations
    return None


def _capture_check_citations(cap: Capture) -> bool:
    """check-citations 用 SSE 答案的 answer + citations 当输入。"""
    sse_text = cap.data["sse"].get("POST /api/agent/ask/stream", "")
    extracted = _extract_answer_from_sse(sse_text) if sse_text else None
    if not extracted:
        cap.record_fail(
            "POST /api/agent/check-citations",
            "无可用 answer+citations（SSE 未成功或无 final_answer）",
        )
        return False
    answer, citations = extracted
    body = {
        "answer": answer,
        "citations": citations,
        "provider": PROVIDER,
        "api_key": API_KEY,
        "model": MODEL,
    }
    print("POST /api/agent/check-citations ...")
    ok, payload = post_json(
        "/api/agent/check-citations", body, SHORT_TIMEOUT
    )
    if ok:
        cap.record_json("POST /api/agent/check-citations", payload)
        return True
    cap.record_fail("POST /api/agent/check-citations", str(payload)[:800])
    return False


if __name__ == "__main__":
    main()

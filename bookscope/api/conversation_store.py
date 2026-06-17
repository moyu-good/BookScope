"""对话持久化层（ADR-009 Phase 1a，D-3）。

多轮追问的落盘后端。一场对话一个 JSON 文件，挂在它从属的 book session
目录下::

    data/sessions/<session_id>/
      metadata.json / book_text.json / chunks.json / ...   # 不动
      conversations/
        <conversation_id>.json   # 本模块负责读写

文件结构（ADR-009 D-3）::

    {
      "conversation_id": "...",
      "book_session_id": "...",
      "turns": [
        {
          "turn_index": 1,
          "question": "这本书节奏是不是前密后疏？",
          "rewritten_question": "",      # 指代消解 Phase 1b 才填，本步留空
          "answer": "...",
          "citations": [{"chapter": 3, "snippet": "...", "chunk_id": "..."}],
          "evidence_chunk_ids": ["r0-chunk-3", ...],
          "created_at": "2026-06-11T08:30:00Z"
        }
      ],
      "registry_chunk_ids": ["r0-chunk-3", ...]   # 跨轮证据指针（Phase 2 预热用）
    }

### 设计取舍

- **对话从属于书**，所以放 session 目录下，不另起顶层 ``data/conversations/``
  ——删书即删对话，生命周期自然绑定（ADR-009 D-3）。
- **可变与不可变分开存**：书的工件是 ingest 一次性产物，对话是每轮增长的
  日志。追问一轮只往对话文件追加，不重写整个 session。
- **登记表落盘只存 chunk_id 指针**，全文从同目录 chunks.json 重建——这是
  方案 C 持久化便宜的来源。Phase 1a 先把 ``registry_chunk_ids`` 字段建起来
  （收集本轮 evidence_chunk_ids 的并集），跨轮预热的消费留 Phase 2。
- 与 ADR-005 "JSON-on-disk、人眼可读、rsync 即备份" 的习惯一致，不上二进制。

### 本步（Phase 1a）只做骨架

- ``rewritten_question`` 字段留空——指代消解（question_processor 改写）是
  Phase 1b。
- ``registry_chunk_ids`` 只记录、不消费——跨轮预热是 Phase 2。
- 提供：新建对话、追加一轮、读取历史轮次。前情提要的拼接放路由层
  （``routes/agent.py``），本模块只管存取。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_CONVERSATIONS_DIR = "conversations"


class ConversationStoreError(Exception):
    """``ConversationStore`` 层所有错误的根基类。"""


class ConversationNotFound(ConversationStoreError):
    """按 ``conversation_id`` 找不到对话文件。"""


class ConversationCorrupted(ConversationStoreError):
    """对话文件损坏 / JSON 解析失败 / 结构不对，无法还原。"""


class JSONFileConversationStore:
    """基于本地 JSON 文件的对话存储（ADR-009 D-3）。

    Args:
        root: book session 数据根目录（默认 ``data/sessions``）。对话文件
            落在 ``<root>/<session_id>/conversations/<conversation_id>.json``。
            测试可传 ``tmp_path``。

    并发：用一把全局锁串行读写。单用户场景够用——同一对话并发两问的处理
    （ADR-009 Open Q-4，倾向加锁拒绝 409）留后续，本步不引入。
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def create(self, session_id: str) -> str:
        """开一场新对话，返回新生成的 conversation_id。

        只生成 id 与空骨架并落盘，不写任何轮次——第一轮答完再 ``append_turn``。
        """
        conversation_id = uuid.uuid4().hex
        data = {
            "conversation_id": conversation_id,
            "book_session_id": session_id,
            "turns": [],
            "registry_chunk_ids": [],
        }
        with self._lock:
            self._write(session_id, conversation_id, data)
        return conversation_id

    def append_turn(
        self,
        session_id: str,
        conversation_id: str,
        *,
        question: str,
        answer: str,
        citations: list[dict],
        rewritten_question: str = "",
    ) -> int:
        """往对话末尾追加一轮，返回这一轮的 turn_index（从 1 起）。

        ``evidence_chunk_ids`` 从本轮 citations 里收集（去重保序），并入对话
        级 ``registry_chunk_ids``——Phase 2 跨轮预热的指针台账。
        ``rewritten_question`` 本步固定留空（指代消解 Phase 1b 才填）。

        Raises:
            ConversationNotFound: conversation_id 不存在（追问续不上）。
            ConversationCorrupted: 对话文件损坏。
        """
        with self._lock:
            data = self._read(session_id, conversation_id)
            turns = data.get("turns", [])
            turn_index = len(turns) + 1
            evidence_chunk_ids = _collect_chunk_ids(citations)
            turns.append(
                {
                    "turn_index": turn_index,
                    "question": question,
                    "rewritten_question": rewritten_question,
                    "answer": answer,
                    "citations": list(citations),
                    "evidence_chunk_ids": evidence_chunk_ids,
                    "created_at": _utc_now_iso(),
                }
            )
            data["turns"] = turns
            data["registry_chunk_ids"] = _merge_chunk_ids(
                data.get("registry_chunk_ids", []), evidence_chunk_ids
            )
            self._write(session_id, conversation_id, data)
            return turn_index

    def get_turns(self, session_id: str, conversation_id: str) -> list[dict]:
        """读取一场对话的全部历史轮次（按 turn_index 升序，即落盘顺序）。

        Raises:
            ConversationNotFound: conversation_id 不存在。
            ConversationCorrupted: 对话文件损坏。
        """
        with self._lock:
            data = self._read(session_id, conversation_id)
        turns = data.get("turns", [])
        if not isinstance(turns, list):
            raise ConversationCorrupted(
                f"conversation {conversation_id!r} 的 turns 不是列表"
            )
        return turns

    def get_last_turn(
        self, session_id: str, conversation_id: str
    ) -> dict | None:
        """读最后一轮；空对话（刚 create、还没 append）返回 None。"""
        turns = self.get_turns(session_id, conversation_id)
        return turns[-1] if turns else None

    def exists(self, session_id: str, conversation_id: str) -> bool:
        """对话文件是否存在。不抛错，只返回布尔。"""
        return self._conversation_path(session_id, conversation_id).is_file()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _conversation_path(self, session_id: str, conversation_id: str) -> Path:
        """对话文件路径。拒绝路径穿越（同 session_storage 的安全检查）。"""
        for part in (session_id, conversation_id):
            if "/" in part or "\\" in part or ".." in part:
                raise ValueError(f"invalid id: {part!r}")
        return (
            self._root
            / session_id
            / _CONVERSATIONS_DIR
            / f"{conversation_id}.json"
        )

    def _write(
        self, session_id: str, conversation_id: str, data: dict[str, Any]
    ) -> None:
        path = self._conversation_path(session_id, conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)

    def _read(self, session_id: str, conversation_id: str) -> dict[str, Any]:
        path = self._conversation_path(session_id, conversation_id)
        if not path.is_file():
            raise ConversationNotFound(
                f"conversation {conversation_id!r}（session {session_id!r}）不存在"
            )
        try:
            with path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
        except json.JSONDecodeError as exc:
            raise ConversationCorrupted(
                f"conversation {conversation_id!r} JSON 解析失败：{exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ConversationCorrupted(
                f"conversation {conversation_id!r} 不是 JSON 对象"
            )
        return data


# ---------------------------------------------------------------------------
# module-level helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """ISO-8601 UTC 时间戳（精度到秒）。脚本环境可用 datetime。"""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _collect_chunk_ids(citations: list[dict]) -> list[str]:
    """从本轮 citations 里收集 chunk_id，去重保序。

    citation 没 chunk_id（如 fast_path 自动拼的、或 None）就跳过——
    evidence_chunk_ids 是给 Phase 2 凭 id 重拉全文用的，None 拉不了。
    """
    out: list[str] = []
    seen: set[str] = set()
    for cite in citations:
        if not isinstance(cite, dict):
            continue
        chunk_id = cite.get("chunk_id")
        if isinstance(chunk_id, str) and chunk_id and chunk_id not in seen:
            seen.add(chunk_id)
            out.append(chunk_id)
    return out


def _merge_chunk_ids(existing: list[str], incoming: list[str]) -> list[str]:
    """把新一轮的 chunk_id 并进对话级登记表，去重保序。"""
    out = list(existing) if isinstance(existing, list) else []
    seen = set(out)
    for chunk_id in incoming:
        if chunk_id not in seen:
            seen.add(chunk_id)
            out.append(chunk_id)
    return out


__all__ = [
    "ConversationCorrupted",
    "ConversationNotFound",
    "ConversationStoreError",
    "JSONFileConversationStore",
]

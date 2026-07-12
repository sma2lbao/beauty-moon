"""Chunk 定位计算单元：为每个 chunk 计算字符偏移与标题层级路径。

纯字符串计算，无 DB / 向量库 / 网络依赖，可独立单测。全程 fail-safe：
任何计算失败都降级为 None，绝不抛异常、绝不阻断摄取。
"""
import logging
import re

from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

MAX_HEADING_PATH = 1000
_HEADING_SEP = " > "
# markdown ATX 标题：行首 1-6 个 # + 空格 + 标题文本
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$", re.MULTILINE)


class LocatorInfo(TypedDict):
    """单个 chunk 的定位信息。"""

    char_start: int | None
    char_end: int | None
    heading_path: str | None


def _parse_headings(content: str) -> list[tuple[int, int, str]]:
    """解析 markdown 标题，返回 (offset, level, title) 列表（按 offset 升序）。"""
    headings: list[tuple[int, int, str]] = []
    for m in _HEADING_RE.finditer(content):
        level = len(m.group(1))
        title = m.group(2).strip()
        if title:
            headings.append((m.start(), level, title))
    return headings


def _heading_path_at(headings: list[tuple[int, int, str]], offset: int) -> str | None:
    """给定字符偏移，回溯层级栈得到从顶层到最近层级的标题路径。"""
    stack: list[tuple[int, str]] = []  # (level, title)
    for h_offset, level, title in headings:
        if h_offset > offset:
            break
        # 弹出所有 >= 当前 level 的栈顶，保证层级递增
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
    if not stack:
        return None
    path = _HEADING_SEP.join(title for _, title in stack)
    if len(path) > MAX_HEADING_PATH:
        # 从末尾保留最靠近 chunk 的层级
        path = "…" + path[-(MAX_HEADING_PATH - 1):]
    return path


def locate(content: str, splits: list[str]) -> list[LocatorInfo]:
    """为每个 split 计算 char_start/char_end 与 heading_path。

    Args:
        content: 文档原文全文。
        splits: 各 chunk 的文本，顺序与切分结果一致。

    Returns:
        与 splits 等长的定位信息列表，一一对应。
    """
    try:
        headings = _parse_headings(content)
    except Exception:  # noqa: BLE001 — fail-safe，heading 解析失败整篇降级
        logger.warning("heading 解析失败，heading_path 全部降级为 None", exc_info=True)
        headings = []
        heading_disabled = True
    else:
        heading_disabled = False

    result: list[LocatorInfo] = []
    cursor = 0
    for split_text in splits:
        char_start: int | None = None
        char_end: int | None = None
        idx = content.find(split_text, cursor)
        if idx != -1:
            char_start = idx
            char_end = idx + len(split_text)
            cursor = char_end  # 游标推进，避免重复内容误匹配

        heading_path = (
            None
            if heading_disabled or char_start is None
            else _heading_path_at(headings, char_start)
        )
        result.append(
            LocatorInfo(
                char_start=char_start,
                char_end=char_end,
                heading_path=heading_path,
            )
        )
    return result

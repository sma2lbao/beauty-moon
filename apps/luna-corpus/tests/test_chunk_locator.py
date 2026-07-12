"""chunk_locator 定位计算单元测试。"""
from unittest.mock import patch

from app.services.chunk_locator import LocatorInfo, locate


def test_markdown_multi_level_headings():
    content = (
        "# 第2章 环境准备\n"
        "\n"
        "## 2.1 安装依赖\n"
        "先安装依赖包。\n"
        "## 2.2 配置\n"
        "然后配置环境。\n"
    )
    splits = ["先安装依赖包。", "然后配置环境。"]

    result = locate(content, splits)

    assert len(result) == 2
    # 第一段落在 2.1 下
    assert result[0]["char_start"] == content.index("先安装依赖包。")
    assert result[0]["char_end"] == result[0]["char_start"] + len("先安装依赖包。")
    assert result[0]["heading_path"] == "第2章 环境准备 > 2.1 安装依赖"
    # 第二段落在 2.2 下
    assert result[1]["heading_path"] == "第2章 环境准备 > 2.2 配置"
    assert result[1]["char_start"] == content.index("然后配置环境。")


def test_plain_text_no_headings():
    content = "第一段没有标题。\n\n第二段也没有。"
    splits = ["第一段没有标题。", "第二段也没有。"]

    result = locate(content, splits)

    assert [r["heading_path"] for r in result] == [None, None]
    assert result[0]["char_start"] == 0
    assert result[1]["char_start"] == content.index("第二段也没有。")


def test_repeated_content_cursor_advances():
    # 相同文本出现两次，游标推进保证第二个 chunk 不回退误匹配
    content = "重复段。\n重复段。"
    splits = ["重复段。", "重复段。"]

    result = locate(content, splits)

    assert result[0]["char_start"] == 0
    assert result[1]["char_start"] == content.index("重复段。", 1)
    assert result[1]["char_start"] > result[0]["char_start"]


def test_split_not_found_yields_none():
    content = "原文内容。"
    splits = ["不存在的文本"]

    result = locate(content, splits)

    assert result[0]["char_start"] is None
    assert result[0]["char_end"] is None
    assert result[0]["heading_path"] is None


def test_oversized_heading_truncated_from_end():
    long_title = "标" * 1100
    content = f"# {long_title}\n正文。"
    splits = ["正文。"]

    result = locate(content, splits)

    path = result[0]["heading_path"]
    assert path is not None
    assert len(path) <= 1000
    assert path.startswith("…")
    # 末尾层级被保留
    assert path.endswith("标")


def test_multilevel_oversized_heading_truncated_from_end():
    """多级标题超长时，截断后保留最靠近 chunk 的末尾层级。"""
    long_title = "长" * 1100
    content = (
        f"# 顶层\n"
        f"## 第二层\n"
        f"### {long_title}\n"
        "正文在这里。"
    )
    splits = ["正文在这里。"]

    result = locate(content, splits)

    path = result[0]["heading_path"]
    assert path is not None
    assert len(path) <= 1000
    assert path.startswith("…")
    # 最内层标题（###）的标题文本被保留
    assert path.endswith("长")


def test_parse_headings_exception_all_heading_path_none():
    """_parse_headings 抛异常时，locate() 不抛异常且所有 heading_path 为 None，offset 仍正常。"""
    content = "# 标题\n\n正文内容。"
    splits = ["正文内容。"]

    with patch(
        "app.services.chunk_locator._parse_headings",
        side_effect=RuntimeError("boom"),
    ):
        result = locate(content, splits)

    assert len(result) == 1
    assert result[0]["heading_path"] is None
    assert result[0]["char_start"] is not None
    assert result[0]["char_end"] is not None


def test_heading_path_at_exception_single_chunk_degraded():
    """_heading_path_at 对单个 chunk 抛异常时，仅该 chunk 降级，不影响其他 chunk 与 offset。"""
    from app.services.chunk_locator import _heading_path_at as original_fn

    content = "# 标题\n\n第一段。\n\n第二段。"
    splits = ["第一段。", "第二段。"]

    call_count = 0

    def mock_heading_path_at(headings, offset):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        return original_fn(headings, offset)

    with patch(
        "app.services.chunk_locator._heading_path_at",
        side_effect=mock_heading_path_at,
    ):
        result = locate(content, splits)

    assert len(result) == 2
    # 第一个 chunk heading 降级为 None
    assert result[0]["heading_path"] is None
    assert result[0]["char_start"] is not None
    assert result[0]["char_end"] is not None
    # 第二个 chunk 不受牵连
    assert result[1]["heading_path"] == "标题"
    assert result[1]["char_start"] is not None
    assert result[1]["char_end"] is not None

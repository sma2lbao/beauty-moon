"""命令行接口。

用法（两种等价入口）：
    uv run ink <命令> [参数]            # console script 入口
    uv run python -m ink <命令> [参数]  # 模块入口

命令：
    scan / ingest <路径>    摄取文档（递归扫描 .md/.txt/.pdf/.docx，向量化入库）
    search <问题>           纯向量检索（默认；--hybrid 走完整混合检索 + 重排管线）
    query <问题>            混合检索 + 重排 + DeepSeek 生成回答（附引用列表）
"""

import argparse
import sys
from pathlib import Path

from .config import get_settings


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="ink",
        description="ink：本地优先的个人知识库（RAG 问答）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # 摄取：scan 为主命令名，ingest 为官方别名（两者完全等价）
    p_scan = sub.add_parser(
        "scan",
        aliases=["ingest"],
        help="递归扫描目录并摄取文档（.md/.txt/.pdf/.docx，支持增量更新）",
    )
    p_scan.add_argument("path", help="待扫描的文件或目录路径")

    # 纯检索：不调用 LLM，便于验证向量库内容
    p_search = sub.add_parser("search", help="检索预览（不调用 LLM）")
    p_search.add_argument("question", help="检索问题")
    p_search.add_argument("--top-k", type=int, default=5, help="返回命中数量（默认 5）")
    p_search.add_argument(
        "--hybrid",
        action="store_true",
        help="走完整 M3 管线：向量 + BM25 混合检索 → bge-reranker 重排",
    )

    # 完整问答：检索 + 重排 + DeepSeek 生成
    p_query = sub.add_parser("query", help="混合检索 + 重排 + DeepSeek 生成回答（附引用）")
    p_query.add_argument("question", help="提问内容")
    p_query.add_argument("--top-k", type=int, default=10, help="混合检索每路取数（默认 10）")
    p_query.add_argument("--top-n", type=int, default=5, help="重排后保留数量（默认 5）")

    return parser


def _print_nodes(nodes) -> None:
    """按统一格式打印检索结果（编号 / 分数 / 文件名（页码）/ 摘要）。"""
    for i, node in enumerate(nodes, start=1):
        meta = node.node.metadata
        name = meta.get("file_name", "?")
        if meta.get("page"):
            name += f"（第 {meta['page']} 页）"
        print(f"[{i}] score={node.score:.4f}  {name}")
        text = node.node.get_content().replace("\n", " ")
        print(f"    {text[:160]}{'…' if len(text) > 160 else ''}")


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口（返回进程退出码）。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command in ("scan", "ingest"):
        from .scan import run_scan

        run_scan(path=Path(args.path), settings=settings)

    elif args.command == "search":
        if args.hybrid:
            # 完整 M3 管线：向量 + BM25 → RRF 融合 → reranker 重排
            from .query import retrieve

            nodes = retrieve(args.question, settings, top_k=max(args.top_k * 2, 10),
                             top_n=args.top_k)
        else:
            # 轻量路径：纯向量检索（加载快，适合调试）
            from .query import load_index
            from .readers import load_embed_model

            embed_model = load_embed_model(settings)
            index = load_index(settings, embed_model)
            nodes = index.as_retriever(similarity_top_k=args.top_k).retrieve(args.question)
        if not nodes:
            print("（向量库为空或无命中；请先执行 ink scan <路径> 摄取文档）")
            return 1
        _print_nodes(nodes)

    elif args.command == "query":
        from .query import run_query

        try:
            answer, citations = run_query(
                args.question, settings, top_k=args.top_k, top_n=args.top_n
            )
        except ValueError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        print(answer)
        if citations:
            print("\n来源：")
            for c in citations:
                print(f"  [{c.index}] {c.label}")

    return 0

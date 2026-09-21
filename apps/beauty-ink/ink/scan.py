"""扫描摄取模块（M2：四种格式 + 增量更新）。

流程：递归扫描 → 计算文件 hash 增量判断 → 按扩展名读取解析 →
分格式切分（Markdown 用 MarkdownNodeParser，其余用 SentenceSplitter）→
向量化写入 ChromaDB。

增量规则（按文件内容 hash）：
- 未入库的文件      → 新增（读取 → 切分 → 向量化插入）
- hash 未变化       → 跳过（不解析、不向量化）
- hash 变化         → 先删除该文件全部旧节点，再重新插入
"""

from pathlib import Path

from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import BaseNode

from .config import Settings
from .readers import (
    SUPPORTED_EXTS,
    compute_file_hash,
    iter_supported_files,
    load_embed_model,
    read_documents,
)
from .store import delete_by_source, get_collection, get_stored_hashes, get_vector_store


def build_splitter(ext: str, settings: Settings) -> MarkdownNodeParser | SentenceSplitter:
    """按扩展名选择切分器。

    Markdown 走 MarkdownNodeParser（按标题结构切分，保留层级）；
    其余格式（txt/pdf/docx）走 SentenceSplitter（定长切分 512 / 重叠 64）。
    """
    if ext == ".md":
        return MarkdownNodeParser()
    return SentenceSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )


def split_documents(documents: list[Document], settings: Settings) -> list[BaseNode]:
    """按来源文件的扩展名分组切分，返回合并后的节点列表。

    同一扩展名的文档共用一个切分器实例；PDF 按页生成的 Document
    会继承页码 metadata，切分后的节点同样保留。
    """
    by_ext: dict[str, list[Document]] = {}
    for doc in documents:
        ext = Path(doc.metadata["source"]).suffix.lower()
        by_ext.setdefault(ext, []).append(doc)
    nodes: list[BaseNode] = []
    for ext, docs in by_ext.items():
        nodes.extend(build_splitter(ext, settings).get_nodes_from_documents(docs))
    return nodes


def run_scan(path: Path, settings: Settings) -> None:
    """扫描摄取主流程（含增量更新）。

    Args:
        path: 待扫描的文件或目录路径。
        settings: 全局配置。
    """
    files = iter_supported_files(path)
    if not files:
        print(f"未在 {path} 找到受支持的文档（当前支持：{', '.join(sorted(SUPPORTED_EXTS))}）")
        return

    print(f"扫描 {path}：发现 {len(files)} 个文件")

    # ---- 增量判断：先只算 hash，跳过的文件不做任何解析 ----
    collection = get_collection(settings)
    stored = get_stored_hashes(collection, [str(f) for f in files])

    added: list[Document] = []      # 新文件的全部 Document
    updated: list[Document] = []    # 已变化文件的全部 Document
    skipped = 0                     # 未变化文件数

    for f in files:
        new_hash = compute_file_hash(f)
        old_hash = stored.get(str(f))
        if old_hash == new_hash:
            skipped += 1
            print(f"  = 跳过  {f.name}")
        else:
            docs = read_documents(f)
            if old_hash is None:
                added.extend(docs)
                print(f"  + 新增  {f.name}")
            else:
                updated.extend(docs)
                print(f"  ~ 更新  {f.name}")

    print(f"统计：新增 {len({d.metadata['source'] for d in added})} / "
          f"更新 {len({d.metadata['source'] for d in updated})} / "
          f"跳过 {skipped} 个未变化文件")

    to_ingest = added + updated
    if not to_ingest:
        return  # 全部跳过：不加载模型，零开销退出

    # ---- 更新的文件：先删除旧节点，再插入新节点 ----
    for source in {d.metadata["source"] for d in updated}:
        delete_by_source(collection, source)

    # ---- 切分 + 向量化 + 插入 ----
    print(f"\n提示：Embedding 模型 {settings.embedding_model} 首次运行需从 HuggingFace 下载，"
          "体积较大的模型（如 bge-m3 约 2GB）请耐心等待…")
    embed_model = load_embed_model(settings)
    nodes = split_documents(to_ingest, settings)
    print(f"切分为 {len(nodes)} 个文本块，开始向量化并写入 ChromaDB（{settings.chroma_dir}）…")

    storage_context = StorageContext.from_defaults(vector_store=get_vector_store(settings))
    VectorStoreIndex(
        nodes=nodes,
        storage_context=storage_context,
        embed_model=embed_model,
    )
    print(f"完成：本次入库 {len(to_ingest)} 个文档 / {len(nodes)} 个文本块。")

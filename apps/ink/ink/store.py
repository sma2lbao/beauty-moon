"""向量库模块：ChromaDB 的创建、查询与增量维护。

持久化位置由 Settings.chroma_dir 决定（默认 ./data/chroma）。
"""

import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore

from .config import Settings


def get_collection(settings: Settings) -> chromadb.Collection:
    """获取（必要时创建）ChromaDB 持久化 collection。

    直接返回 chromadb 原生 Collection，供增量维护（按 metadata 查询 / 删除）使用。
    """
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    return client.get_or_create_collection(name=settings.chroma_collection)


def get_vector_store(settings: Settings) -> ChromaVectorStore:
    """获取绑定到指定 collection 的 ChromaVectorStore，供索引读写使用。"""
    return ChromaVectorStore(chroma_collection=get_collection(settings))


def get_stored_hashes(collection: chromadb.Collection, sources: list[str]) -> dict[str, str]:
    """查询一批文件当前已入库的内容 hash。

    Args:
        collection: Chroma 原生 collection。
        sources: 文件绝对路径列表（对应 metadata 中的 source 键）。

    Returns:
        {source: file_hash}；未入库的文件不出现在结果中。
    """
    if not sources:
        return {}
    result = collection.get(where={"source": {"$in": sources}}, include=["metadatas"])
    hashes: dict[str, str] = {}
    for meta in result.get("metadatas") or []:
        if meta and "source" in meta and "file_hash" in meta:
            # 同一文件的所有节点 hash 一致，取任一即可
            hashes[meta["source"]] = meta["file_hash"]
    return hashes


def delete_by_source(collection: chromadb.Collection, source: str) -> None:
    """删除某文件已入库的全部节点（内容变化时，先删旧再插新）。"""
    collection.delete(where={"source": source})

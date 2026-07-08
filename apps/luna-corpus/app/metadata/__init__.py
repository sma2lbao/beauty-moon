"""元数据 Schema、校验与分面聚合。

`schema` 定义字段类型与字段定义的 Pydantic 模型；`models` 是字段定义 ORM；
`validation` 按 schema 校验并归一化上传元数据；`facets` 做全库分面聚合。
过滤条件到 Chroma where / post-filter 的翻译在 `app.retrieval.filters`。
"""

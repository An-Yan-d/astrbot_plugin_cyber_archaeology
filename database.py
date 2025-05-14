"""
database.py
"""
from pymilvus import connections, Collection, utility, FieldSchema, CollectionSchema, DataType
from typing import List, Dict, Any,Optional


class Database:
    def __init__(self,db_path,config):
        self._db_path =db_path
        self.config=config


    def add(self, message_id:str,embedding:List[float]) -> None:
        """
        添加新记录
        :param record: 要添加的记录字典
        :return: 插入记录的ID或插入结果
        """
        pass

    def clear(self) -> None:
        """
        根据ID删除记录
        :param record_id: 要删除的记录ID
        :return: 是否删除成功
        """
        pass

    def search(self, message_id:str) -> str:
        """
        根据条件搜索记录
        :param manager_id: 搜索的
        :return: 匹配的记录列表
        """
        pass


    def similar_search(self, embedding:List[float],limits:int) -> Optional[list]:
        """
        根据条件搜索记录
        :param embedding: 查询的消息embedding
        :return: messager_id
        """
        pass

    def exists(self, message_id: str) -> bool:
        pass




class MilvusDatabase(Database):
    def __init__(self, config):
        super().__init__( config)

        # 从配置中提取参数
        self.collection_name = config.get("collection_name", "message_embeddings")
        self.embedding_dim = config.get("embedding_dim", 768)
        self.index_params = config.get("index_params", {
            "index_type": "IVF_FLAT",
            "metric_type": "COSINE",
            "params": {"nlist": 128}
        })

        # 初始化集合（连接已由DatabaseManager建立）
        self.collection = self._init_collection()


    def _init_collection(self):
        # 创建集合（如果不存在）
        if not utility.has_collection(self.collection_name):
            # 定义字段模式
            fields = [
                FieldSchema(name="message_id", dtype=DataType.VARCHAR,
                            is_primary=True, max_length=100),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR,
                            dim=self.embedding_dim)
            ]

            # 创建集合模式
            schema = CollectionSchema(fields, description="Message embeddings storage")

            # 创建集合
            collection = Collection(self.collection_name, schema)

            # 创建索引
            collection.create_index(
                field_name="embedding",
                index_params=self.index_params
            )
        else:
            collection = Collection(self.collection_name)

        collection.load()
        return collection

    def add(self, message_id: str, embedding: List[float]) -> None:
        # 构造插入数据
        data = [
            [message_id],
            [embedding]
        ]

        # 执行插入操作
        self.collection.insert(data)
        self.collection.flush()


    def clear(self) -> None:
        # 删除整个集合
        utility.drop_collection(self.collection_name)
        # 重新初始化集合
        self.collection = self._init_collection()

    def search(self, message_id: str) -> str:
        # 构建查询表达式
        expr = f'message_id == "{message_id}"'

        # 执行查询
        results = self.collection.query(
            expr=expr,
            output_fields=["message_id", "embedding"]
        )

        # 格式化返回结果
        return results[0]["message_id"]

    def similar_search(self, embedding: List[float],limits:int) -> Optional[list]:
        # 准备搜索参数
        search_params = {
            "metric_type": self.index_params["metric_type"],
            "params": {"nprobe": 10}
        }

        # 执行向量搜索
        results = self.collection.search(
            data=[embedding],
            anns_field="embedding",
            param=search_params,
            limit=limits,
            output_fields=["message_id"]
        )

        # 处理搜索结果
        if len(results) > 0:
            return [
                hit.entity.get("message_id")
                for hit in results[0]
            ]
        return []

    def exists(self, message_id: str) -> bool:
        expr = f'message_id == "{message_id}"'
        results = self.collection.query(
            expr=expr,
            output_fields=["message_id"]
        )
        return len(results) > 0




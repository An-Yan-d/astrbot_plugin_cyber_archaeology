"""
database.py
"""
from pymilvus import connections, Collection, utility,  CollectionSchema
from typing import List, Dict, Any,Optional
from astrbot.api import logger

class Database:
    def __init__(self,config,fields):
        self.config=config
        self.fields=fields


    def add(self, message_id:int,embedding:List[float]) -> None:
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

    def search(self, message_id:int) -> int:
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

    def exists(self, message_id: int) -> bool:
        pass




class MilvusDatabase(Database):
    def __init__(self, config,fields):
        super().__init__(config,fields)

        # 从配置中提取参数
        self.collection_name = config.get("collection_name", "message_embeddings")
        self.index_params = config.get("index_params", {
            "index_type": "IVF_FLAT",
            "metric_type": "COSINE",
            "params": {"nlist": 128}
        })
        self.connection_alias = config.get("connection_alias", "default")

        # 初始化集合（连接已由DatabaseManager建立）
        self.collection = self._init_collection()

    def _init_collection(self):
        if not utility.has_collection(self.collection_name, using=self.connection_alias):
            # 定义字段模式

            logger.info(f"fields[_init_collection]向量参数为{self.fields[1]}")
            # 创建集合模式
            schema = CollectionSchema(self.fields, description="Message embeddings storage")

            # 创建集合
            collection = Collection(self.collection_name, schema, using=self.connection_alias)

            # 创建索引（保持不变）
            collection.create_index(
                field_name="embedding",
                index_params=self.index_params
            )
        else:
            collection = Collection(self.collection_name, using=self.connection_alias)

        collection.load()
        return collection

    def add(self, message_id: int, embedding: List[float]) -> None:
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
        utility.drop_collection(self.collection_name,using=self.connection_alias)
        # 重新初始化集合
        self.collection = self._init_collection()


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

    def exists(self, message_id: int) -> bool:
        results = self.collection.query(
            expr=f"message_id in [{message_id}]",
            output_fields=["message_id"],
            limit=1
        )
        return len(results) > 0




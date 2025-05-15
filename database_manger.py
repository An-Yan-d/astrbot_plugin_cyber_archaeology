"""
database_manager.py
"""
import os
import time
from typing import Optional

from pymilvus import utility, connections, MilvusClient, FieldSchema, DataType
from pymilvus.exceptions import MilvusException
from astrbot.api import logger

from .database import Milvuscollection


class DatabaseManager:
    """管理多个独立数据库实例的工厂类（支持lite模式）"""

    def __init__(self, base_config,dim):
        self.base_config = base_config.copy()
        self.dim=dim
        self.fields = [
            FieldSchema(
                name="message_id",
                dtype=DataType.INT64,
                is_primary=True
            ),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=self.dim
            )
        ]
        self.databases = {}  # {db_id: MilvusDatabase}
        self.client: Optional[MilvusClient] = None  # lite模式专用client
        self.__initialized = True
        self.isconnected=False
        self.connection_alias = "lite" if base_config.get("islite", True) else "server"

        self.connect()

    def _connect_lite(self) -> None:
        """嵌入式模式连接（带异常分类）"""
        lite_path = self.base_config["lite_path"]
        try:
            os.makedirs(lite_path, exist_ok=True)
            lite_db_path=os.path.join(lite_path,"milvus_lite.db")
            # 初始化客户端
            self.client = MilvusClient(lite_db_path)
            connections.connect(alias=self.connection_alias, uri=lite_db_path)
            logger.info(f"Lite模式连接成功，路径：{lite_db_path}")
        except MilvusException as e:
            logger.error(f"Lite模式连接失败：{str(e)}")
            raise

    def _connect_server(self) -> None:
        """服务器模式连接（带异常处理）"""
        host = self.base_config.get("host", "localhost")
        port = self.base_config.get("port", "19530")
        user = self.base_config.get("user", "")
        password = self.base_config.get("password", "")

        try:
            connections.connect(
                alias=self.connection_alias,
                host=host,
                port=port,
                user=user,
                password=password
            )
            logger.info(f"服务器模式连接成功：{host}:{port}")
        except MilvusException as e:
            # 如果是认证相关问题，可以手动检查错误信息
            if "authentication" in str(e).lower():
                logger.critical(f"认证失败：{e}")
            else:
                logger.error(f"服务器连接失败：{e}")
            raise

    def connect(self, retries: int = 2) -> None:
        """显式建立连接（带重试机制）"""
        self.disconnect()  # 先断开旧连接
        for attempt in range(retries + 1):
            try:
                if self.base_config.get("islite", True):
                    self._connect_lite()
                else:
                    self._connect_server()
                self.isconnected=True
                return
            except MilvusException as e:
                if attempt == retries:
                    raise
                logger.warning(f"连接尝试 {attempt+1}/{retries} 失败，5秒后重试...")
                time.sleep(5)

    def disconnect(self) -> None:
        """安全关闭所有连接"""
        if self.isconnected:
            alias = "lite" if self.base_config.get("islite", True) else "server"
            try:
                connections.disconnect(alias)
                if self.client:
                    self.client.close()
                    self.client = None
                logger.info(f"成功断开 {alias} 模式连接")
                self.isconnected=False
            except MilvusException as e:
                logger.error(f"断开连接时发生错误：{str(e)}")
                raise

    def get_collection(self, db_id: str) -> 'Milvuscollection':
        if not self.isconnected:
            self.connect()
        if db_id not in self.databases:
            config = self.base_config.copy()
            config.update({
                "collection_name": db_id,
                "connection_alias": self.connection_alias  # 传递连接别名
            })
            self.databases[db_id] = Milvuscollection(config, self.fields)
        return self.databases[db_id]

    def clear_collection(self, group_id: str) -> None:
        """清空名字包含db_id的所有collection"""
        if not self.isconnected:
            self.connect()

        try:
            collections = utility.list_collections(using=self.connection_alias)
            for collection_name in collections:
                if group_id in collection_name:
                    if collection_name in self.databases:
                        del self.databases[collection_name]
                    utility.drop_collection(collection_name,using=self.connection_alias)
                    logger.info(f"已删除集合: {collection_name}")
        except Exception as e:
            logger.error(f"删除集合时发生错误: {str(e)}")
            raise

    def clear(self) -> None:
        """
        清空所有数据库实例
        执行步骤：
        1. 删除所有Milvus集合
        2. 清除实例缓存
        """
        if not self.isconnected:
            self.connect()

        try:
            collections = utility.list_collections(using=self.connection_alias)
            for collection_name in collections:
                if collection_name in self.databases:
                    del self.databases[collection_name]
                utility.drop_collection(collection_name,using=self.connection_alias)
                logger.info(f"已删除集合: {collection_name}")
        except Exception as e:
            logger.error(f"删除所有集合时发生错误: {str(e)}")
            raise
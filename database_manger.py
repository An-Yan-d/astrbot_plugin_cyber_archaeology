from database import MilvusDatabase
from astrbot.api import logger

class DatabaseManager:
    """管理多个独立数据库实例的工厂类（新增clear方法）"""
    _instance = None

    def __new__(cls, base_config):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, base_config):
        if self.__initialized:
            return
        self.base_config = base_config.copy()
        self.databases = {}  # {db_id: MilvusDatabase}
        self.__initialized = True

    def get_database(self, db_id: str) -> 'MilvusDatabase':
        if db_id not in self.databases:
            config = self.base_config.copy()
            config["collection_name"] = db_id
            self.databases[db_id] = MilvusDatabase(None, config)
        return self.databases[db_id]

    def remove_database(self, db_id: str) -> None:
        if db_id in self.databases:
            self.databases[db_id].clear()
            del self.databases[db_id]

    def clear(self) -> None:
        """
        清空所有数据库实例
        执行步骤：
        1. 删除所有Milvus集合
        2. 清除实例缓存
        """
        # 删除所有集合
        for db in self.databases.values():
            try:
                db.clear()
            except Exception as e:
                logger.info(f"删除集合 {db.collection_name} 失败: {str(e)}")
        # 清空实例缓存
        self.databases.clear()
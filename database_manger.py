"""
database_manager.py
"""
from database import MilvusDatabase
from astrbot.api import logger
from pymilvus import connections


class DatabaseManager:
    """管理多个独立数据库实例的工厂类（支持lite模式）"""
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

        # 判断运行模式
        if base_config.get("islite"):
            self._setup_lite_mode()
        else:
            self._setup_server_mode()

        self.__initialized = True

    def _setup_lite_mode(self):
        """配置嵌入式lite模式连接"""
        from milvus import default_server  # 延迟导入避免强依赖

        # 启动嵌入式服务器
        default_server.set_base_dir(self.base_config["lite_path"])
        default_server.start()

        # 获取动态分配的端口
        lite_port = default_server.listen_port

        # 建立连接
        connections.connect(
            alias="default",
            host="127.0.0.1",
            port=lite_port
        )

    def _setup_server_mode(self):
        """配置标准服务器模式连接"""
        host = self.base_config.get("host", "localhost")
        port = self.base_config.get("port", "19530")
        user = self.base_config.get("user", "")
        password = self.base_config.get("password", "")

        connections.connect(
            alias="default",
            host=host,
            port=port,
            user=user,
            password=password
        )


    def get_database(self, db_id: str) -> 'MilvusDatabase':
        if db_id not in self.databases:
            config = self.base_config.copy()
            config["collection_name"] = db_id
            self.databases[db_id] = MilvusDatabase(config)
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
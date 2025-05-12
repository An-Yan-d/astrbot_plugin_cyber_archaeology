from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker
import os
import shutil

Base = declarative_base()
class Database:
    def __init__(self,config):
        self._db_path = os.path.join("data","astrbot_plugin_cyber_archaeology","db")
        self.sessions ={}
        self.config=config


    async def _init_db(self, session_id: str):
        # 按群号创建独立数据库文件
        db_path = os.path.join(self._db_path, f"{session_id}.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # 创建新引擎并初始化表结构[1,2](@ref)
        engine = create_engine(f'sqlite:///{db_path}')
        if not os.path.exists(db_path):
            Base.metadata.create_all(engine)
        return engine


    async def get_session(self, unified_msg_origin: str):
        """获取指定群组的数据库会话"""
        session_id=":".join([self.config["embedding_conf"]["whichprovider"].replace("/", "") ,self.config["embedding_conf"]["embed_model"].replace("/", "") ,unified_msg_origin])
        if session_id not in self.sessions:
            engine = await self._init_db(session_id)
            Session = sessionmaker(bind=engine)
            self.sessions[session_id] = Session()
        return self.sessions[session_id]

    async def clear(self):
        """清空所有群聊记录"""
        # 关闭所有现存会话
        for session in self.database.sessions.values():
            session.close()
        self.database.sessions.clear()

        # 删除整个数据库目录
        if os.path.exists(self._db_path):
            shutil.rmtree(self._db_path)
            logger.info(f"已删除数据库目录: {self._db_path}")

        # 重建目录
        os.makedirs(self._db_path, exist_ok=True)

        return event.plain_result("已清空所有群聊的历史记录")


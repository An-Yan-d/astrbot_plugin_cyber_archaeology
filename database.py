from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker
import os

Base = declarative_base()
class Database:
    def __init__(self,config):
        self._db_path = os.path.join("data","plugins","astrbot_plugin_cyber_archaeology","db")
        self.sessions ={}
        self.config=config


    def _init_db(self, session_id: str):
        # 按群号创建独立数据库文件
        db_path = os.path.join(self._db_path, f"{session_id}.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # 创建新引擎并初始化表结构[1,2](@ref)
        engine = create_engine(f'sqlite:///{db_path}')
        if not os.path.exists(db_path):
            Base.metadata.create_all(engine)
        return engine


    def get_session(self, unified_msg_origin: str):
        """获取指定群组的数据库会话"""
        session_id=self.config["embedding_conf"]["whichprovider"]+":"+unified_msg_origin
        if session_id not in self.sessions:
            engine = self._init_db(session_id)
            Session = sessionmaker(bind=engine)
            self.sessions[session_id] = Session()
        return self.sessions[session_id]
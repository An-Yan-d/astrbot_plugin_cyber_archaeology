import os
import json
import asyncio
import numpy as np
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain

Base = declarative_base()


class ChatHistory(Base):
    __tablename__ = 'chat_history'
    id = Column(Integer, primary_key=True)
    group_id = Column(String(64))
    sender_id = Column(String(64))
    message = Column(Text)
    embedding = Column(Text)  # 存储JSON格式的embedding


@register("CyberArchaeology", "AnYan", "本插件利用embedding，根据描述查询意思相符的历史信息。", "0.1")
class QQArchaeology(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.engine = self._init_db()
        self.session = sessionmaker(bind=self.engine)()

        # 初始化数据库表
        if not os.path.exists(self._db_path):
            Base.metadata.create_all(self.engine)

    @property
    def _db_path(self):
        return os.path.join(
            self.context.get_data_dir(),
            "qqsearcher.db"
        )

    def _init_db(self):
        return create_engine(f"sqlite:///{self._db_path}")

    async def get_embedding(self, text: str) -> List[float]:
        """调用Ollama获取embedding"""
        try:
            import requests
            resp = requests.post(
                f"{self.config['ollama_api_url']}/api/embeddings",
                json={
                    "model": self.config["embed_model"],
                    "prompt": text
                }
            )
            return resp.json()["embedding"]
        except Exception as e:
            self.logger.error(f"获取embedding失败: {str(e)}")
            return []

    @filter.command("search",alias={'考古'})
    async def search_command(self, event: AstrMessageEvent, query: str):
        """搜索历史记录 示例：/search 关键词"""
        if not query:
            yield event.plain_result("请输入搜索内容")
            return

        # 获取查询embedding
        query_embedding = await self.get_embedding(query)
        if not query_embedding:
            yield event.plain_result("Embedding服务不可用")
            return

        # 计算相似度
        results = []
        query_vec = np.array(query_embedding)
        for record in self.session.query(ChatHistory).all():
            if not record.embedding:
                continue
            db_vec = np.array(json.loads(record.embedding))
            similarity = np.dot(query_vec, db_vec) / (
                    np.linalg.norm(query_vec) * np.linalg.norm(db_vec)
            )
            results.append((similarity, record))

        # 排序并取前K个
        results.sort(reverse=True, key=lambda x: x[0])
        top_results = results[:self.config["top_k"]]

        # 构造返回结果
        if not top_results:
            yield event.plain_result("未找到相关记录")
            return

        response = ["找到以下相关记录："]
        for idx, (score, record) in enumerate(top_results, 1):
            response.append(
                f"{idx}. [相似度{score:.2f}] {record.sender_id}: {record.message}"
            )

        yield event.plain_result("\n".join(response))

    @filter.event_message_type("group_message")
    async def save_history(self, event: AstrMessageEvent):
        """保存群聊历史记录"""
        try:
            # 获取消息文本
            message = event.message_str

            # 跳过空消息和命令消息
            if not message or message.startswith("/"):
                return

            # 生成embedding
            embedding = await self.get_embedding(message)

            # 存储记录
            new_record = ChatHistory(
                group_id=event.get_group_id(),
                sender_id=event.get_sender_id(),
                message=message,
                embedding=json.dumps(embedding)
            )
            self.session.add(new_record)
            self.session.commit()
        except Exception as e:
            self.logger.error(f"保存记录失败: {str(e)}")
            self.session.rollback()

    async def terminate(self):
        """关闭数据库连接"""
        self.session.close()
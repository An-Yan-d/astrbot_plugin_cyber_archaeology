import os
import json
import asyncio
import numpy as np
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain

Base = declarative_base()


class ChatHistory(Base):
    __tablename__ = 'chat_history'
    id = Column(Integer, primary_key=True)
    group_id = Column(String(64))
    message_id = Column(Text)
    embedding = Column(Text)  # 存储JSON格式的embedding


@register("astrbot_plugin_cyber_archaeology", "AnYan", "本插件利用embedding，根据描述查询意思相符的历史信息。", "0.1")
class QQArchaeology(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._db_path=os.path.join("data","plugins","astrbot_plugin_cyber_archaeology","qqarchaeology.db")
        self.engine = self._init_db()
        self.session = sessionmaker(bind=self.engine)()


        # 初始化数据库表
        if not os.path.exists(self._db_path):
            Base.metadata.create_all(self.engine)



    def _init_db(self):
        return create_engine(f"sqlite:///{self._db_path}")

    async def get_embedding(self, text: str) -> List[float]:
        """调用Ollama获取embedding（异步版本）"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.config['ollama_api_url']}/api/embeddings",
                    json={
                        "model": self.config["embed_model"],
                        "prompt": text
                    }
                )
                resp.raise_for_status()  # 自动处理4xx/5xx状态码
                return resp.json()["embedding"]
        except httpx.HTTPStatusError as e:
            logger.error(f"API错误: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"网络请求失败: {str(e)}")
        except json.JSONDecodeError:
            logger.error("响应数据解析失败")
        except Exception as e:
            logger.error(f"未知错误: {str(e)}")

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


        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        assert isinstance(event, AiocqhttpMessageEvent)
        client = event.bot

        for rec in  top_results:
            # 构造获取群消息历史的请求参数
            payloads = {
                "message_id": rec[1].message_id,
            }

            # 调用API获取群聊历史消息
            msg = await client.api.call_action("get_msg", **payloads)

            # 处理消息历史记录，对其格式化
            message_text = ""
            messagechain = msg.get("message", [])
            for part in messagechain:
                if part['type'] == 'text':
                    message_text += part['data']['text'].strip() + " "
                elif part['type'] == 'json':  # 处理JSON格式的分享卡片等特殊消息
                    try:
                        json_content = json.loads(part['data']['data'])
                        if 'desc' in json_content.get('meta', {}).get('news', {}):
                            message_text += f"[分享内容]{json_content['meta']['news']['desc']} "
                    except:
                        pass

                # 表情消息处理
                elif part['type'] == 'face':
                    message_text += "[表情] "

                # 生成标准化的消息记录格式
            if message_text:
                yield event.plain_result(message_text)


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
                message_id=event.message_id,
                embedding=json.dumps(embedding)
            )
            self.session.add(new_record)
            self.session.commit()
        except Exception as e:
            logger.error(f"保存记录失败: {str(e)}")
            self.session.rollback()

    async def terminate(self):
        """关闭数据库连接"""
        self.session.close()
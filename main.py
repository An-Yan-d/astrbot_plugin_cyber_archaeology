import os
import json
import numpy as np
from typing import List

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain


Base = declarative_base()

def cal_similarity(v1, v2):
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

class ClusterCenter(Base):
    __tablename__ = 'cluster_centers'
    id = Column(Integer, primary_key=True)
    initial_embedding = Column(Text)
    center_embedding = Column(Text)  # 中心向量
    member_count = Column(Integer)   # 成员数量


class ChatHistory(Base):
    __tablename__ = 'chat_history'
    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey('cluster_centers.id'))  # 所属簇ID
    message_id = Column(Text)
    embedding = Column(Text)  # 存储JSON格式的embedding


class ClusterManager:
    def __init__(self, session, config):
        self.session = session
        self.config = config

    async def find_nearest_cluster(self, embedding: List[float]):
        # 获取所有簇中心
        clusters = self.session.query(ClusterCenter).all()
        if not clusters:
            return None

        # 计算与各簇中心的相似度
        query_vec = np.array(embedding)
        max_similarity = -1
        best_cluster = None
        for cluster in clusters:
            center_vec = np.array(json.loads(cluster.center_embedding))
            similarity = cal_similarity(query_vec, center_vec)
            if similarity > max_similarity:
                max_similarity = similarity
                best_cluster = cluster

        return best_cluster if max_similarity > self.config["cluster_threshold"] else None

    async def update_cluster_center(self, cluster: ClusterCenter, new_embedding: List[float]):
        # 增量更新簇中心（加权平均）
        old_center = np.array(json.loads(cluster.center_embedding))
        new_center = (old_center * cluster.member_count + np.array(new_embedding)) / (cluster.member_count + 1)
        cluster.center_embedding = json.dumps(new_center.tolist())
        cluster.member_count += 1


        initial_center=json.loads(cluster.initial_embedding)
        if cal_similarity(np.array(initial_center), new_center)<self.config["cluster_threshold"]:

            logger.info("test")
            cluster1= await self.new_cluster(initial_center)
            cluster2= await self.new_cluster(new_center.tolist())

            records = self.session.query(ChatHistory).filter_by(cluster_id=cluster.id).all()
            for record in records:
                vec = np.array(json.loads(record.embedding))
                similarity1 = cal_similarity(np.array(initial_center), vec)
                similarity2 = cal_similarity(new_center, vec)
                if similarity1 > similarity2:
                    record.cluster_id=cluster1.id
                    await self.update_cluster_center(cluster1,json.loads(record.embedding))
                else:
                    record.cluster_id = cluster2.id
                    await self.update_cluster_center(cluster2, json.loads(record.embedding))
            self.session.delete(cluster)


    async def new_cluster(self,new_embedding: List[float]):
        new_cluster = ClusterCenter(
            initial_embedding = json.dumps(new_embedding),
            center_embedding = json.dumps(new_embedding),
            member_count = 1
        )
        self.session.add(new_cluster)
        self.session.commit()
        return  new_cluster



@register("astrbot_plugin_cyber_archaeology", "AnYan", "本插件利用embedding，根据描述查询意思相符的历史信息。", "2.4")
class QQArchaeology(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._db_path=os.path.join("data","plugins","astrbot_plugin_cyber_archaeology","db")
        self.sessions ={}


    def _init_db(self, unified_msg_origin: str):
        # 按群号创建独立数据库文件
        db_path = os.path.join(self._db_path, f"{unified_msg_origin}.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # 创建新引擎并初始化表结构[1,2](@ref)
        engine = create_engine(f'sqlite:///{db_path}')
        if not os.path.exists(db_path):
            Base.metadata.create_all(engine)
        return engine

    def get_session(self, unified_msg_origin: str):
        """获取指定群组的数据库会话"""
        if unified_msg_origin not in self.sessions:
            engine = self._init_db(unified_msg_origin)
            Session = sessionmaker(bind=engine)
            self.sessions[unified_msg_origin] = Session()
        return self.sessions[unified_msg_origin]

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
                print(resp)
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
        unified_msg_origin = event.unified_msg_origin
        session = self.get_session(unified_msg_origin)  # 获取当前群的会话
        group_id=event.get_group_id()

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

        # 将查询范围限制在当前群数据库
        candidate_clusters = []
        clusters = session.query(ClusterCenter).all()
        query_vec = np.array(query_embedding)
        for cluster in clusters:
            center_vec = np.array(json.loads(cluster.center_embedding))
            similarity = cal_similarity(query_vec, center_vec)
            if similarity > self.config["cluster_threshold"]:
                candidate_clusters.append(cluster)

        # 第二阶段：在候选簇内精确搜索
        results = []
        for cluster in candidate_clusters:
            records = session.query(ChatHistory).filter_by(cluster_id=cluster.id).all()
            for record in records:
                db_vec = np.array(json.loads(record.embedding))
                similarity = cal_similarity(query_vec, db_vec)
                if similarity > self.config["threshold"]:
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

        for k,rec in  enumerate(top_results):
            payloads ={
                "group_id": group_id,
                "message": [
                    {
                        "type": "reply",
                        "data": {
                                    "id": rec[1].message_id
                                }
                    },
                    {
                        "type": "text",
                        "data": {
                            "text": f"第{k+1}相似历史记录"
                        }
                    }
            ]
            }
            msg = await client.api.call_action("send_group_msg", **payloads)

        event.stop_event()

            # 构造获取群消息历史的请求参数
            # payloads = {
            #     "message_id": rec[1].message_id,
            # }
            #
            # # 调用API获取群聊历史消息
            # msg = await client.api.call_action("get_msg", **payloads)
            #
            # # 处理消息历史记录，对其格式化
            # message_text = ""
            # messagechain = msg.get("message", [])
            # for part in messagechain:
            #     if part['type'] == 'text':
            #         message_text += part['data']['text'].strip() + " "
            #     elif part['type'] == 'json':  # 处理JSON格式的分享卡片等特殊消息
            #         try:
            #             json_content = json.loads(part['data']['data'])
            #             if 'desc' in json_content.get('meta', {}).get('news', {}):
            #                 message_text += f"[分享内容]{json_content['meta']['news']['desc']} "
            #         except:
            #             pass
            #
            #     # 表情消息处理
            #     elif part['type'] == 'face':
            #         message_text += "[表情] "
            #
            #     # 生成标准化的消息记录格式
            # if message_text:
            #     yield event.plain_result(message_text)


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def save_history(self, event: AstrMessageEvent):
        """保存群聊历史记录"""
        try:
            unified_msg_origin = event.unified_msg_origin
            session = self.get_session(unified_msg_origin)  # 获取对应群组的会话

            # 获取消息文本
            messagechain = event.message_obj.message

            message=" ".join([comp.text for comp in messagechain if isinstance(comp, Plain)])

            # logger.info(" ".join([comp.text for comp in messagechain if isinstance(comp, Plain)]))
            # 跳过空消息和命令消息和过短对话
            if (not message) or message.startswith("/") or len(message.strip())<3:
                return

            # 生成embedding
            embedding = await self.get_embedding(message)

            if not embedding:
                return

            cluster_manager = ClusterManager(session,self.config)
            nearest_cluster = await cluster_manager.find_nearest_cluster(embedding)

            if nearest_cluster:
                # 加入现有簇
                new_record = ChatHistory(
                    cluster_id=nearest_cluster.id,
                    message_id=event.message_obj.message_id,
                    embedding=json.dumps(embedding)
                )
                await cluster_manager.update_cluster_center(nearest_cluster, embedding)
            else:
                # 创建新簇
                new_cluster= await cluster_manager.new_cluster(embedding)
                new_record = ChatHistory(
                    cluster_id=new_cluster.id,
                    message_id=event.message_obj.message_id,
                    embedding=json.dumps(embedding)
                )
            session.add(new_record)
            session.commit()
        except Exception as e:
            logger.error(f"保存记录失败: {str(e)}")
            unified_msg_origin = event.unified_msg_origin
            self.get_session(unified_msg_origin).rollback()

    async def terminate(self):
        """关闭所有数据库连接"""
        for unified_msg_origin, session in self.sessions.items():
            session.close()
        self.sessions.clear()

    @filter.command_group("cyber_archaeology",alias={'ca'})
    def cyber_archaeology(self):
        pass


    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("clear_all", alias={'清空所有记录'})
    async def clear_all_command(self, event: AstrMessageEvent):
        """清空所有群聊记录 示例：/ca clear_all"""
        import shutil
        try:
            # 关闭所有现存会话
            for session in self.sessions.values():
                session.close()
            self.sessions.clear()

            # 删除整个数据库目录
            if os.path.exists(self._db_path):
                shutil.rmtree(self._db_path)
                logger.info(f"已删除数据库目录: {self._db_path}")

            # 重建目录
            os.makedirs(self._db_path, exist_ok=True)

            yield event.plain_result("已清空所有群聊的历史记录")
        except Exception as e:
            logger.error(f"清空所有记录失败: {str(e)}")
            yield event.plain_result("清空操作失败，请检查日志")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("clear", alias={'清空本群记录'})
    async def clear_current_command(self, event: AstrMessageEvent):
        """清空当前群聊记录 示例：/ca clear"""
        try:
            session = self.get_session(event.unified_msg_origin)

            # 删除当前群所有记录
            session.query(ChatHistory).delete()
            session.commit()

            yield event.plain_result("本群历史记录已清空")
        except Exception as e:
            logger.error(f"清空本群记录失败: {str(e)}")
            unified_msg_origin = event.unified_msg_origin
            self.get_session(unified_msg_origin).rollback()
            yield event.plain_result("清空操作失败，请检查日志")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("load_history")
    async def load_history_command(self, event: AstrMessageEvent, count: int = None, seq: int = 0):
        """读取插件未安装前bot所保存的历史数据当前群聊记录 示例：/ca load_history <读取消息条数:int> [初始消息序号:int]"""
        try:
            session = self.get_session(event.unified_msg_origin)

            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            assert isinstance(event, AiocqhttpMessageEvent)
            client = event.bot

            if count is None:
                yield event.plain_result(
                    "未传入要导入的聊天记录数量")
                event.stop_event()
                return

            payloads = {
                "group_id": event.get_group_id(),
                "message_seq": seq,
                "count": count,
                "reverseOrder": False
            }

            # 调用API获取群聊历史消息
            ret = await client.api.call_action("get_group_msg_history", **payloads)

            myid_post = await client.api.call_action("get_login_info", **payloads)
            myid = myid_post.get("user_id", {})

            # 处理消息历史记录，对其格式化
            messages = ret.get("messages", [])
            chat_lines = {}
            success_num=0
            for msg in messages:
                # 解析发送者信息
                sender = msg.get('sender', {})
                message_id = msg['message_id']
                if myid == sender.get('user_id', ""):
                    continue
                # 提取所有文本内容（兼容多段多类型文本消息）
                message_text_chain = []
                for part in msg['message']:
                    if part['type'] == 'text':
                        message_text_chain.append(part['data']['text'].strip("\t\n\r"))

                message_text=" ".join(message_text_chain)
                # 检查message_text的第一个字符是否为"/"，如果是则跳过当前循环（用于跳过用户调用Bot的命令）
                if (not message_text) or message_text.startswith("/") or len(message_text.strip())<3:
                    continue
                chat_lines[message_id]=message_text


                # 获取embedding
                embedding = await self.get_embedding(message_text)

                if not embedding:
                    return

                # 获取选取最近的簇，如果没有则创建一个新簇
                cluster_manager = ClusterManager(session, self.config)
                nearest_cluster = await cluster_manager.find_nearest_cluster(embedding)

                if nearest_cluster:
                    # 加入现有簇
                    new_record = ChatHistory(
                        cluster_id=nearest_cluster.id,
                        message_id=message_id,
                        embedding=json.dumps(embedding)
                    )
                    await cluster_manager.update_cluster_center(nearest_cluster, embedding)
                else:
                    # 创建新簇
                    new_cluster = await cluster_manager.new_cluster(embedding)
                    new_record = ChatHistory(
                        cluster_id=new_cluster.id,
                        message_id=message_id,
                        embedding=json.dumps(embedding)
                    )
                session.add(new_record)
                success_num += 1
                if success_num%100==0:
                    logger.info(f"已成功导入{success_num}条历史消息")
            session.commit()

            yield event.plain_result(f"成功导入{success_num}条本群历史记录")
        except Exception as e:
            logger.error(f"导入本群记录失败: {str(e)}")
            unified_msg_origin = event.unified_msg_origin
            self.get_session(unified_msg_origin).rollback()
            yield event.plain_result("导入本群记录失败，请检查日志")




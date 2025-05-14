import os
import json
import numpy as np
import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from .database_manger import DatabaseManager
from .embedding_api import EmbeddingProvider





@register("astrbot_plugin_cyber_archaeology", "AnYan", "本插件利用embedding，根据描述查询意思相符的历史信息。", "3.0")
class QQArchaeology(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config["plugin_conf"]

        self.embeddingProvider = EmbeddingProvider(config)
        database_config=config["Milvus"]
        database_config["lite_path"]=os.path.join("data","astrbot_plugin_cyber_archaeology","milvus_lite_db")
        database_config["embedding_dim"]=self.embeddingProvider.get_dim()
        self.databaseManager =  DatabaseManager(database_config)





    @filter.command("search",alias={'考古'})
    async def search_command(self, event: AstrMessageEvent, query: str):
        """搜索历史记录 示例：/search 关键词"""
        unified_msg_origin = event.unified_msg_origin
        database = self.databaseManager.get_database(unified_msg_origin)  # 获取当前群的会话
        group_id=event.get_group_id()

        if not query:
            yield event.plain_result("请输入搜索内容")
            return

        # 获取查询embedding
        query_embedding = await self.embeddingProvider.get_embedding(query)
        if not query_embedding:
            yield event.plain_result("Embedding服务不可用")
            return



        # 排序并取前K个
        top_results = database.similar_search(query_embedding,self.config["plugin_conf"]["top_k"])

        # 构造返回结果
        if not top_results:
            yield event.plain_result("未找到相关记录")
            return


        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        assert isinstance(event, AiocqhttpMessageEvent)
        client = event.bot

        for k,message_id in  enumerate(top_results):
            payloads ={
                "group_id": group_id,
                "message": [
                    {
                        "type": "reply",
                        "data": {
                                    "id":message_id
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
            await client.api.call_action("send_group_msg", **payloads)

        event.stop_event()



    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def save_history(self, event: AstrMessageEvent):
        """保存群聊历史记录"""
        unified_msg_origin = event.unified_msg_origin
        database = self.databaseManager.get_database(unified_msg_origin)  # 获取对应群组的会话
        try:

            # 获取消息文本
            messagechain = event.message_obj.message

            message=" ".join([comp.text for comp in messagechain if isinstance(comp, Plain)])

            # logger.info(" ".join([comp.text for comp in messagechain if isinstance(comp, Plain)]))
            # 跳过空消息和命令消息和过短对话
            if (not message) or message.startswith("/") or len(message.strip())<3:
                return

            # 生成embedding
            embedding = await self.embeddingProvider.get_embedding(message)

            if not embedding:
                return
            database.add(event.message_obj.message_id,embedding)
        except Exception as e:
            logger.error(f"保存记录失败: {str(e)}")

    async def terminate(self):
        """关闭所有数据库连接"""
        self.databaseManager.clear()

    @filter.command_group("cyber_archaeology",alias={'ca'})
    def cyber_archaeology(self):
        pass


    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("clear_all", alias={'清空所有记录'})
    async def clear_all_command(self, event: AstrMessageEvent):
        """清空所有群聊记录 示例：/ca clear_all"""
        try:
            self.databaseManager.clear()
            yield event.plain_result("所有群历史记录已清空")
        except Exception as e:
            logger.error(f"清空所有记录失败: {str(e)}")
            yield event.plain_result("清空操作失败，请检查日志")


    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("clear", alias={'清空本群记录'})
    async def clear_current_command(self, event: AstrMessageEvent):
        """清空当前群聊记录 示例：/ca clear"""
        try:
            self.databaseManager.remove_database(event.unified_msg_origin)
            yield event.plain_result("本群历史记录已清空")
        except Exception as e:
            logger.error(f"清空本群记录失败: {str(e)}")
            yield event.plain_result("清空操作失败，请检查日志")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("load_history")
    async def load_history_command(self, event: AstrMessageEvent, count: int = None, seq: int = 0):
        """读取插件未安装前bot所保存的历史数据当前群聊记录 示例：/ca load_history <读取消息条数:int> [初始消息序号:int]"""
        database = self.databaseManager.get_database(event.unified_msg_origin)
        try:
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

                if database.exists(message_id):
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
                embedding = await self.embeddingProvider.get_embedding(message_text)

                if not embedding:
                    return

                # 获取选取最近的簇，如果没有则创建一个新簇

                database.add(message_id, embedding)
                success_num += 1
                if success_num%100==0:
                    logger.info(f"已成功导入{success_num}条历史消息")

            yield event.plain_result(f"成功导入{success_num}条本群历史记录")
        except Exception as e:
            logger.error(f"导入本群记录失败: {str(e)}")
            yield event.plain_result("导入本群记录失败，请检查日志")




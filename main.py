import os
import re
import asyncio
from typing import  Optional

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot.api import logger
from astrbot.core.utils.session_waiter import (
    session_waiter,
    SessionController,
)

from .database_manger import DatabaseManager






@register("astrbot_plugin_cyber_archaeology", "AnYan", "本插件利用embedding，根据描述查询意思相符的历史信息。", "4.0.1")
class QQArchaeology(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context=context
        self.config = config["plugin_conf"]
        self.database_config=config["Milvus"]

        self._isinited=False

        self.database_manager:Optional[DatabaseManager]=None
        self.current_model:Optional[str]=None
        self.provider:Optional[Star]=None
        self.dim:Optional[int]=None


    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        await self._init_attempt()


    async def _init_attempt(self):
        if not self._isinited or not self.current_model or not self.provider or self.current_model!=self.provider.get_model_name():
            try:
                await self._init()
                self._isinited=True
            except Exception:
                self._isinited=False
        return  self._isinited

    async def _init(self):

        try:
            # 初始化Embedding服务
            self.provider = self.context.get_registered_star("astrbot_plugin_embedding_adapter").star_cls
            logger.info(f"Embedding依赖插件调用成功，目前的provider为{self.provider.get_provider_name()}")
        except AttributeError as e:
            logger.error("未找到注册的embedding插件，请检查插件依赖")
            raise
        except Exception as e:
            logger.error(f"初始化embedding服务时发生未知错误: {str(e)}", exc_info=True)
            raise

        try:
            # 自动读取维度
            self.dim = await self.provider.get_dim_async()
            logger.info(f"读取到的向量维度: {self.dim}")
        except AttributeError as e:
            logger.error(f"Embedding服务缺少get_dim_async()方法")
            raise
        except Exception as e:
            logger.error(f"配置数据库参数时发生错误: {str(e)}", exc_info=True)
            raise

        try:

            self.current_model = self.provider.get_model_name()
            logger.info(f"调用模型为{self.current_model}")
        except AttributeError as e:
            logger.error("Provider 缺少 get_model_name() 方法")
            raise
        except Exception as e:
            logger.error(f"获取模型名称失败: {str(e)}")
            raise

        try:
            if self.database_manager is not None:
                self.database_manager.disconnect()
            # 初始化数据库管理器
            logger.info("Milvus数据库初始化启动")
            self.database_manager = DatabaseManager(self.database_config, self.dim)
            logger.info(f"Milvus数据库初始化成功,维数：{self.dim}")
        except ConnectionError as e:
            logger.error("数据库连接失败，请检查配置参数")
            raise
        except ValueError as e:
            logger.error("数据库参数验证失败: " + str(e))
            raise
        except Exception as e:
            logger.error(f"初始化数据库时发生未知错误: {str(e)}", exc_info=True)
            raise





    def get_unified_db_id(self,unified_msg_origin):
        """用于给数据库分配唯一识别码"""
        unified_db_id= self.provider.get_model_name() + "_" + unified_msg_origin
        return re.sub(r'[^a-zA-Z0-9]', '_', unified_db_id)


    async def terminate(self):
        """关闭所有数据库连接"""
        self.database_manager.disconnect()


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def save_history(self, event: AstrMessageEvent):
        """保存群聊历史记录"""
        if await self._init_attempt():
            unified_msg_origin = event.unified_msg_origin

            db_id = self.get_unified_db_id(unified_msg_origin)
            # logger.info(f"[save_history]db_id:{db_id}")
            collection = self.database_manager.get_collection(db_id)
            try:

                # 获取消息文本
                messagechain = event.message_obj.message

                message=" ".join([comp.text for comp in messagechain if isinstance(comp, Plain)])

                # logger.info(" ".join([comp.text for comp in messagechain if isinstance(comp, Plain)]))
                # 跳过空消息和命令消息和过短对话
                if (not message) or message.startswith("/") or len(message.strip())<3:
                    return

                # 生成embedding
                embedding = await self.provider.get_embedding_async(message)

                if not embedding:
                    return
                collection.add(int(event.message_obj.message_id),embedding)
            except Exception as e:
                logger.error(f"保存记录失败: {str(e)}")



    @filter.command("search", alias={'考古'})
    async def search_command(self, event: AstrMessageEvent, query: str):
        """搜索历史记录 示例：/search 关键词"""

        if await self._init_attempt():
            unified_msg_origin = event.unified_msg_origin
            db_id = self.get_unified_db_id( unified_msg_origin)
            collection = self.database_manager.get_collection(db_id)  # 获取当前群的会话
            group_id = event.get_group_id()

            if not query:
                yield event.plain_result("请输入搜索内容")
                return

            # 获取查询embedding
            query_embedding = await self.provider.get_embedding_async(query)
            if not query_embedding:
                yield event.plain_result("Embedding服务不可用")
                return

            # 排序并取前K个
            top_results = collection.similar_search(query_embedding, self.config["top_k"])

            # 构造返回结果
            if not top_results:
                yield event.plain_result("未找到相关记录")
                return

            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            assert isinstance(event, AiocqhttpMessageEvent)
            client = event.bot

            for k, message_id in enumerate(top_results):
                payloads = {
                    "group_id": group_id,
                    "message": [
                        {
                            "type": "reply",
                            "data": {
                                "id": message_id
                            }
                        },
                        {
                            "type": "text",
                            "data": {
                                "text": f"第{k + 1}相似历史记录"
                            }
                        }
                    ]
                }
                await client.api.call_action("send_group_msg", **payloads)

        event.stop_event()

    @filter.command_group("cyber_archaeology",alias={'ca'})
    def cyber_archaeology(self):
        pass


    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("clear_all", alias={'清空所有记录'})
    async def clear_all_command(self, event: AstrMessageEvent):
        """清空所有群聊记录 示例：/ca clear_all"""
    
        if await self._init_attempt():

            yield event.plain_result("是否清空所有群历史记录？\n回复YES确认，超时(30s)默认不清空")

            @session_waiter(timeout=30, record_history_chains=False) # 注册一个会话控制器，设置超时时间为 30 秒，不记录历史消息链
            async def waiter(controller: SessionController, event: AstrMessageEvent):
                if event.is_admin():
                    if event.message_str == "YES" or event.message_str == "yes" or event.message_str == "y":
                        try:
                            self.database_manager.clear()
                            await event.send(MessageChain().message("所有群历史记录已清空"))  
                        except Exception as e:
                            logger.error(f"清空所有记录失败: {str(e)}")
                            await event.send(MessageChain().message("清空操作失败，请检查日志"))  
                        
                    else:
                        await event.send(MessageChain().message("清空操作取消"))
                else:
                    await event.send(MessageChain().message("非管理员回复，任务取消（建议私聊使用本命令）"))

                
                controller.stop()
                

            try:
                await waiter(event)
            except TimeoutError: # 当超时后，会话控制器会抛出 TimeoutError
                yield event.plain_result("超时了，默认操作取消")
            except Exception as e:
                logger.error(f"会话控制器发生错误: {str(e)}")
                yield event.plain_result("发生错误，请检查日志")

            
        else:
            yield event.plain_result("插件未成功启动")


    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("clear", alias={'清空本群记录'})
    async def clear_current_command(self, event: AstrMessageEvent, group_id:int=None):
        """清空当前群聊记录 示例：/ca clear [群号:int]"""
        if await self._init_attempt():
            try:
                if group_id is None:
                    unified_msg_origin = event.unified_msg_origin
                else:
                    unified_msg_origin = event.get_platform_name()+":"+"GroupMessage"+":"+str(group_id)
                db_id = self.get_unified_db_id(unified_msg_origin)
                self.database_manager.clear_collection(db_id)

                group_id=unified_msg_origin.split(":")[-1]
                yield event.plain_result(f"清空群{group_id}记录成功")
            except Exception as e:
                logger.error(f"清空本群记录失败: {str(e)}")
                yield event.plain_result("清空操作失败，请检查日志")
                return
        else:
            yield event.plain_result("插件未成功启动")


    async def load_history_from_aiocqhttp(self, event: AstrMessageEvent, count: int, seq: int ,group_id:int):
        """读取插件未安装前bot所保存的历史数据当前群聊记录 示例：/ca load_history <读取消息条数:int> [初始消息序号:int]"""
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        assert isinstance(event, AiocqhttpMessageEvent)
        client = event.bot

        payloads = {
        "group_id": group_id,
        "message_seq": seq,
        "count": count,
        "reverseOrder": False
        }

        ret = await client.api.call_action("get_group_msg_history", **payloads)

        messages = ret.get("messages", [])

        return messages



    async def format_history_from_aiocqhttp(self, messages, myid, collection):

        # 处理消息历史记录，对其格式化

        chat_list = []
        message_id_list = []


        
        for msg in messages:
            # 解析发送者信息
            sender = msg.get('sender', {})
            message_id = msg['message_id']

            if int(myid) == sender.get('user_id', ""):
                continue

            if collection.exists(message_id):
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
            chat_list.append(message_text)
            message_id_list.append(message_id)
        


        
        return  chat_list,message_id_list



    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("load_history")
    async def load_history_command(self, event: AstrMessageEvent, count: int = None, seq: int = 0):
        """读取插件未安装前bot所保存的历史数据当前群聊记录 示例：/ca load_history <读取消息条数:int> [初始消息序号:int]"""
        if await self._init_attempt():
            if count is None:
                yield event.plain_result("未传入要导入的聊天记录数量")
                event.stop_event()
                return
            

            try:
                unified_msg_origin = event.unified_msg_origin
                db_id = self.get_unified_db_id(unified_msg_origin)
                collection = self.database_manager.get_collection(db_id)
            except Exception as e:
                logger.error(f"获取群聊记录失败: {str(e)}")
                yield event.plain_result("获取群聊记录失败，请检查日志")
                event.stop_event()
                return
                

            if collection is None:
                yield event.plain_result("未找到指定群号的历史记录")
                event.stop_event()
                return

            try:
                # 调用API获取群聊历史消息
                messages=await self.load_history_from_aiocqhttp(event, count, seq, event.get_group_id())
                if not messages:
                    yield event.plain_result("未找到指定群号的历史记录")
                    event.stop_event()
                    return
                myid=event.get_self_id()

                chat_list,message_id_list = await self.format_history_from_aiocqhttp(messages, myid, collection)
                logger.info(f"成功读取{len(chat_list)}条群聊历史记录")
                if not chat_list:
                    yield event.plain_result("没有可导入的聊天记录")
                    event.stop_event()
                    return
                
            except Exception as e:
                logger.error(f"获取群聊历史记录失败: {str(e)}")
                yield event.plain_result("获取群聊历史记录失败，请检查日志")
                event.stop_event()
                return
            
            try:
                # 获取embedding
                embeddings = await self.provider.get_embeddings_async(chat_list)
                if len(embeddings) != len(chat_list):
                    logger.error(f"生成的embedding数量为{len(embeddings)}")
                    raise ValueError("读取的历史记录数量与生成的embedding数量不一致")
                logger.info(f"成功生成embeddings")
                collection.add_list(message_id_list, embeddings)

                yield event.plain_result(f"成功导入{len(chat_list)}条群聊历史记录")
            except Exception as e:
                logger.error(f"导入群聊记录失败: {str(e)}")
                yield event.plain_result(f"导入群聊记录失败，请检查日志")
            
        else:
            yield event.plain_result("插件未成功启动")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("load_group_history", alias={'lgh'})
    async def load_group_history_command(self, event: AstrMessageEvent,group_id:int=None, count: int = None, seq: int = 0):
        """读取插件未安装前bot所保存的指定群聊的历史数据记录 示例：/ca load_group_history <群号:int> <读取消息条数:int> [初始消息序号:int]"""
        if await self._init_attempt():
            if count is None:
                yield event.plain_result("未传入要导入的聊天记录数量")
                event.stop_event()
                return
            
            if group_id is None:
                yield event.plain_result("未传入要导入的群号")
                event.stop_event()
                return
            try:
                unified_msg_origin = event.get_platform_name()+":"+"GroupMessage"+":"+str(group_id)
                db_id = self.get_unified_db_id(unified_msg_origin)
                collection = self.database_manager.get_collection(db_id)
            except Exception as e:
                logger.error(f"获取群聊记录失败: {str(e)}")
                yield event.plain_result("获取群聊记录失败，请检查日志")
                event.stop_event()
                return

            if collection is None:
                yield event.plain_result("未找到指定群号的历史记录")
                event.stop_event()
                return


            # 调用API获取群聊历史消息
            try:
                messages=await self.load_history_from_aiocqhttp(event, count, seq, group_id)
                if not messages:
                    yield event.plain_result("未找到指定群号的历史记录")
                    event.stop_event()
                    return
                myid=event.get_self_id()

                chat_list,message_id_list = await self.format_history_from_aiocqhttp(messages, myid, collection)
                
                logger.info(f"成功读取{len(chat_list)}条群聊历史记录")
                if not chat_list:
                    yield event.plain_result("没有可导入的聊天记录")
                    event.stop_event()
                    return
                
            except Exception as e:
                logger.error(f"获取群聊历史记录失败: {str(e)}")
                yield event.plain_result("获取群聊历史记录失败，请检查日志")
                event.stop_event()
                return
                
            try:
                # 获取embedding
                embeddings = await self.provider.get_embeddings_async(chat_list)
                if len(embeddings) != len(chat_list):
                    logger.error(f"生成的embedding数量为{len(embeddings)}")
                    raise ValueError("读取的历史记录数量与生成的embedding数量不一致")
                logger.info(f"成功生成embeddings")
                collection.add_list(message_id_list, embeddings)

                yield event.plain_result(f"成功导入{len(chat_list)}条群聊历史记录")
            except Exception as e:
                logger.error(f"导入群聊{group_id}记录失败: {str(e)}")
                yield event.plain_result(f"导入群聊{group_id}记录失败，请检查日志")
        else:
            yield event.plain_result("插件未成功启动")


    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("restart")
    async def restart(self, event: AstrMessageEvent):
        """重启插件 示例：/ca restart"""
        try:
            await self._init()
            self._isinited = True
            yield event.plain_result("插件重启成功")
        except Exception as e:
            self._isinited = False
            yield event.plain_result(f"启动失败，详情参见控制台")


    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("set_limit", alias={'set_k'})
    async def set_limit(self, event: AstrMessageEvent, limit: int):
        """设置搜索结果限制 示例：/ca set_limit 10"""
        if not limit:
            yield event.plain_result("请输入限制数量")
            return
        try:
            self.config["top_k"] = limit
            self.config.save_config()
            yield event.plain_result(f"搜索结果限制已设置为{limit}")
        except Exception as e:
            yield event.plain_result(f"设置失败，详情参见控制台")


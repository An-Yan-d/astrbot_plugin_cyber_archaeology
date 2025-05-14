import os
import re
import asyncio

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from .database_manger import DatabaseManager




@register("astrbot_plugin_cyber_archaeology", "AnYan", "本插件利用embedding，根据描述查询意思相符的历史信息。", "3.0")
class QQArchaeology(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context=context
        self.config = config["plugin_conf"]
        self.database_config=config["Milvus"]
        self._isinited=False
        self.databaseManager:DatabaseManager
        self.Provider:Star
        self.current_model:str
        self.dim:int


    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        await self._init_attempt()


    async def _init_attempt(self):
        if hasattr(self, 'current_model') :
            logger.info(f"[_init_attempt]{self.current_model}?={self.Provider.get_model_name()}")
        if not self._isinited or not hasattr(self, 'current_model') or self.current_model!=self.Provider.get_model_name():
            try:
                await self._init()
                self._isinited=True
            except Exception:
                self._isinited=False
        return  self._isinited

    async def _init(self):

        try:
            # 初始化Embedding服务
            self.Provider = self.context.get_registered_star("astrbot_plugin_embedding_adapter").star_cls
            logger.info("Embedding依赖插件调用成功")
        except AttributeError as e:
            logger.error("未找到注册的embedding插件，请检查插件依赖")
            raise RuntimeError("缺失embedding插件依赖") from e
        except Exception as e:
            logger.error(f"初始化embedding服务时发生未知错误: {str(e)}", exc_info=True)
            raise RuntimeError("初始化Embedding服务错误") from e

        try:
            # 自动读取维度
            self.dim = await self.Provider.get_dim_async()
            logger.info(f"读取到的向量维度: {self.dim}")
        except AttributeError as e:
            logger.error("Embedding服务缺少get_dim_async()方法")
            raise RuntimeError("不兼容的embedding服务") from e
        except Exception as e:
            logger.error(f"配置数据库参数时发生错误: {str(e)}", exc_info=True)
            raise RuntimeError("读取维度错误") from e

        try:
            logger.info("模型名字更新前")
            self.current_model = self.Provider.get_model_name()
        except AttributeError as e:
            logger.error("Provider 缺少 get_model_name() 方法")
            raise RuntimeError("不兼容的Provider") from e
        except Exception as e:
            logger.error(f"获取模型名称失败: {str(e)}")
            raise RuntimeError("获取模型错误") from e

        logger.info("Milvus数据库初始化启动try前")
        try:
            if hasattr(self, 'databaseManager') and self.databaseManager is not None:
                self.databaseManager.disconnect()
            # 初始化数据库管理器
            logger.info("Milvus数据库初始化启动")
            self.databaseManager = DatabaseManager(self.database_config, self.dim)
            logger.info(f"Milvus数据库初始化成功,维数：{self.dim}")
        except ConnectionError as e:
            logger.error("数据库连接失败，请检查配置参数")
            raise RuntimeError("数据库连接失败") from e
        except ValueError as e:
            logger.error("数据库参数验证失败: " + str(e))
            raise RuntimeError("数据库参数验证失败") from e
        except Exception as e:
            logger.error(f"初始化数据库时发生未知错误: {str(e)}", exc_info=True)
            raise RuntimeError("Milvus数据库初始化失败") from e





    def get_unified_db_id(self,unified_msg_origin):
        """用于给数据库分配唯一识别码"""
        unified_db_id= self.Provider.get_model_name()+"_"+unified_msg_origin
        return re.sub(r'[^a-zA-Z0-9]', '_', unified_db_id)


    async def terminate(self):
        """关闭所有数据库连接"""
        self.databaseManager.disconnect()


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def save_history(self, event: AstrMessageEvent):
        """保存群聊历史记录"""
        if await self._init_attempt():
            unified_msg_origin = event.unified_msg_origin

            db_id = self.get_unified_db_id(unified_msg_origin)
            logger.info(f"db_id[save_history]:{db_id}")
            database = self.databaseManager.get_database(db_id)
            try:

                # 获取消息文本
                messagechain = event.message_obj.message

                message=" ".join([comp.text for comp in messagechain if isinstance(comp, Plain)])

                # logger.info(" ".join([comp.text for comp in messagechain if isinstance(comp, Plain)]))
                # 跳过空消息和命令消息和过短对话
                if (not message) or message.startswith("/") or len(message.strip())<3:
                    return

                # 生成embedding
                embedding = await self.Provider.get_embedding(message)

                if not embedding:
                    return
                database.add(int(event.message_obj.message_id),embedding)
            except Exception as e:
                logger.error(f"保存记录失败: {str(e)}")



    @filter.command("search", alias={'考古'})
    async def search_command(self, event: AstrMessageEvent, query: str):
        """搜索历史记录 示例：/search 关键词"""

        if await self._init_attempt():
            unified_msg_origin = event.unified_msg_origin
            db_id = self.get_unified_db_id( unified_msg_origin)
            database = self.databaseManager.get_database(db_id)  # 获取当前群的会话
            group_id = event.get_group_id()

            if not query:
                yield event.plain_result("请输入搜索内容")
                return

            # 获取查询embedding
            query_embedding = await self.Provider.get_embedding(query)
            if not query_embedding:
                yield event.plain_result("Embedding服务不可用")
                return

            # 排序并取前K个
            top_results = database.similar_search(query_embedding, self.config["top_k"])

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
            try:
                self.databaseManager.clear()
                yield event.plain_result("所有群历史记录已清空")
            except Exception as e:
                logger.error(f"清空所有记录失败: {str(e)}")
                yield event.plain_result("清空操作失败，请检查日志")
        else:
            yield event.plain_result("插件未成功启动")


    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("clear", alias={'清空本群记录'})
    async def clear_current_command(self, event: AstrMessageEvent):
        """清空当前群聊记录 示例：/ca clear"""
        if await self._init_attempt():
            try:
                unified_msg_origin = event.unified_msg_origin
                db_id = self.get_unified_db_id(unified_msg_origin)
                self.databaseManager.clear_database(db_id)
                yield event.plain_result("本群历史记录已清空")
            except Exception as e:
                logger.error(f"清空本群记录失败: {str(e)}")
                yield event.plain_result("清空操作失败，请检查日志")
                raise
        else:
            yield event.plain_result("插件未成功启动")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cyber_archaeology.command("load_history")
    async def load_history_command(self, event: AstrMessageEvent, count: int = None, seq: int = 0):
        """读取插件未安装前bot所保存的历史数据当前群聊记录 示例：/ca load_history <读取消息条数:int> [初始消息序号:int]"""
        if await self._init_attempt():
            unified_msg_origin = event.unified_msg_origin
            db_id = self.get_unified_db_id(unified_msg_origin)
            database = self.databaseManager.get_database(db_id)
            try:
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
                assert isinstance(event, AiocqhttpMessageEvent)
                client = event.bot

                if count is None:
                    yield event.plain_result("未传入要导入的聊天记录数量")
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
                    embedding = await self.Provider.get_embedding(message_text)


                    database.add(message_id, embedding)
                    success_num += 1
                    if success_num%100==0:
                        logger.info(f"已成功导入{success_num}条历史消息")

                yield event.plain_result(f"成功导入{success_num}条本群历史记录")
            except Exception as e:
                logger.error(f"导入本群记录失败: {str(e)}")
                yield event.plain_result("导入本群记录失败，请检查日志")
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

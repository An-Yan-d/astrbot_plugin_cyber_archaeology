
# CyberArchaeology 赛博考古插件

[![License](https://img.shields.io/badge/License-AGPL%20v3-orange.svg)](https://opensource.org/licenses/AGPL-3.0) [![AstrBot](https://img.shields.io/badge/AstrBot-3.5%2B-blue.svg)](https://github.com/Soulter/AstrBot) ![Version](https://img.shields.io/badge/Version-4.0-success) [![GitHub](https://img.shields.io/badge/author-AnYan-blue)](https://github.com/TheAnyan)

[![Moe Counter](https://count.getloli.com/@cyberArchaeology?name=cyberArchaeology&theme=nixietube-1&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)](https://github.com/TheAnyan/astrbot_plugin_cyber_archaeology)


基于embedding技术的群聊记忆挖掘工具，实现历史消息的智能回溯与聚合分析。通过Embedding生成语义向量，构建动态聚类算法，打造群组专属的数字记忆库。

需安装依赖插件[astrbot_plugin_embedding_adapter
](https://github.com/TheAnyan/astrbot_plugin_embedding_adapter)。

仅支持aiocqhttp。

喜欢的话点个🌟吧！

## 🌟 核心功能

1. **实时语义归档** - 自动分析每条消息的深层语义特征
2. **多维模糊检索** - 基于语义相似度实现模糊语义检索
3. **分布式记忆库** - 每个群组独立数据库隔离存储（`data/astrbot_plugin_cyber_archaeology`）

## ⚙️ 插件安装
astrbot插件市场搜索astrbot_plugin_cyber_archaeology，点击安装，等待完成即可。

## ⚙️基础配置

请在astrbot面板配置，插件管理 -> astrbot_plugin_cyber_archaeology -> 操作 -> 插件配置

> [!NOTE]
> 
> 如果没有大规模的数据存储需求，推荐选择lite模式（存储100万~1000万条消息）,只需要填写lite模式保存地址 (lite_path)这一项配置



## 🛠️ 使用指南
### 基础命令
| 命令格式                      | 功能描述                     | 示例                     |
|----------------------------|--------------------------|------------------------|
| `/search <关键词>`          | 语义相似度检索               | `/search 项目进度`       |
| `/ca clear_all`            | 清空所有群组记录(管理员权限)   | `/ca clear_all`         |
| `/ca clear`                | 清空当前群组记录(管理员权限)   | `/ca clear`             |

### 高级功能
```bash
批量导入历史消息
/ca load_history <导入条数> [起始消息序号]

示例：导入最近100条历史消息
/ca load_history 100

示例：从第500条消息开始导入200条
/ca load_history 200 500
```

## 🧠 实现原理
1. **语义向量化**  
   通过Ollama API将文本转换为语义向量

2. **查询历史信息**  
   将embedding向量，基于向量数据库Milvus的近似查询



## ⚠️ 注意事项
1. 本插件的embedding模型调取依赖于插件[astrbot_plugin_embedding_adapter](https://github.com/TheAnyan/astrbot_plugin_embedding_adapter)
2. 建议执行`/ca load_history <读取消息条数:int> [初始消息序号:int]`导入插件安装前的历史消息
3. 消息存储路径：`data/astrbot_plugin_cyber_archaeology/*.db`
4. 任何问题都可以通过issue反馈


## 📜 开源协议
本项目采用 AGPLv3 协议开源，基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件体系开发。

import httpx
import json
from datetime import datetime as dt
from typing import List,Optional
from astrbot.api import logger

class EmbeddingProvider:
    def __init__(self,config):
        self.config=config
        self.starttime=dt.now()
        self.access_token=""

    async def get_embedding(self, text: str) -> Optional[list]:
        """获取embedding（异步版本）"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if self.config["embedding_conf"]["whichprovider"]=="ollama":
                    url=self.config["embedding_conf"]['ollama_api_url']
                    response = await client.post(
                        f"{url}/api/embeddings",
                        json={
                            "model": self.config["embedding_conf"]["embed_model"],
                            "prompt": text
                        }
                    )
                    response.raise_for_status()  # 自动处理4xx/5xx状态码
                    return response.json()["embedding"]
                elif self.config["embedding_conf"]["whichprovider"]=="openai":
                    api_key=self.config["embedding_conf"]["api_key"]
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    }
                    payload = {
                        "model": self.config["embedding_conf"]["embed_model"],
                        "input": text.replace("\n", " ")
                    }
                    response = await client.post(self.config["embedding_conf"]["api_url"], headers=headers, json=payload)
                    response.raise_for_status()  # 自动处理4xx/5xx状态码
                    return response.json()["data"][0]["embedding"]
                elif self.config["embedding_conf"]["whichprovider"]=="baidu":
                    if abs((dt.now()-self.starttime).days)<30 or not self.access_token:
                        self.access_token = await self.get_access_token()
                    params = {"access_token":self.access_token}
                    payload = {"input": [text]}
                    headers = {"Content-Type": "application/json"}
                    response = await client.post(self.config["embedding_conf"]["api_url"]+"/"+self.config["embedding_conf"]["embed_model"],headers=headers, params=params, json=payload)
                    response.raise_for_status()  # 自动处理4xx/5xx状态码
                    return response.json()["data"][0]["embedding"]
                else:
                    return None

        except httpx.HTTPStatusError as e:
            logger.error(f"API错误: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"网络请求失败: {str(e)}")
        except json.JSONDecodeError:
            logger.error("响应数据解析失败")
        except Exception as e:
            logger.error(f"未知错误: {str(e)}")

    async def get_access_token(self) -> Optional[str]:
        """异步获取Access Token（有效期30天）"""
        auth_url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.config["embedding_conf"]["api_key"],
            "client_secret": self.config["embedding_conf"]["secret_key"]
        }
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        # payload = json.dumps("", ensure_ascii=False)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(auth_url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()["access_token"]
        except httpx.HTTPStatusError as e:
            logger.error(f"鉴权失败 HTTP错误: {e.response.status_code}")
        except httpx.ConnectError as e:
            logger.error(f"错误详情: {e.__cause__}")
        except KeyError:
            logger.error("响应缺少access_token字段")
        return None
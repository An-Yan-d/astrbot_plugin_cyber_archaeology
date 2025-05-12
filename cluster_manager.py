import json
import numpy as np
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey,exists
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .database import Base
from .utils import *


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

        return best_cluster if max_similarity > self.config["plugin_conf"]["cluster_threshold"] else None

    async def update_cluster_center(self, cluster: ClusterCenter, new_embedding: List[float]):
        # 增量更新簇中心（加权平均）
        old_center = np.array(json.loads(cluster.center_embedding))
        new_center = (old_center * cluster.member_count + np.array(new_embedding)) / (cluster.member_count + 1)
        cluster.center_embedding = json.dumps(new_center.tolist())
        cluster.member_count += 1


        initial_center=json.loads(cluster.initial_embedding)
        if cal_similarity(np.array(initial_center), new_center)<self.config["plugin_conf"]["cluster_threshold"]:

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

    async def is_repeated_message(self,message_id):

        return self.session.query(
            exists().where(ChatHistory.message_id == message_id)  # message_id 是 Text 类型，需用字符串比较
        ).scalar()
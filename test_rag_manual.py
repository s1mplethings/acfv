#!/usr/bin/env python3
"""
手动测试 RAG 向量数据库的功能
运行此脚本以验证 RAG 模块的基本操作
"""

import os
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.acfv.rag_vector_database import RAGVectorDatabase

def test_rag_basic():
    """测试 RAG 数据库的基本功能"""
    print("=== RAG 向量数据库手动测试 ===\n")

    # 创建临时数据库文件
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        db_path = tmp.name

    try:
        # 初始化数据库
        print("1. 初始化 RAG 数据库...")
        rag_db = RAGVectorDatabase(database_path=db_path)
        print(f"   数据库路径: {db_path}")

        # 添加测试数据
        print("\n2. 添加测试剪辑数据...")
        test_clips = [
            {
                "clip_path": "/test/clip1.mp4",
                "transcript_text": "This is a great gaming moment with amazing gameplay",
                "video_name": "Game Stream 1",
                "start_time": 10.0,
                "end_time": 20.0,
                "rating": 5
            },
            {
                "clip_path": "/test/clip2.mp4",
                "transcript_text": "Epic boss fight scene with intense action",
                "video_name": "Game Stream 2",
                "start_time": 15.0,
                "end_time": 25.0,
                "rating": 4
            },
            {
                "clip_path": "/test/clip3.mp4",
                "transcript_text": "Funny moment when the player fails spectacularly",
                "video_name": "Game Stream 3",
                "start_time": 5.0,
                "end_time": 15.0,
                "rating": 3
            }
        ]

        for clip in test_clips:
            success = rag_db.add_liked_clip_vector(
                clip_path=clip["clip_path"],
                transcript_text=clip["transcript_text"],
                video_name=clip["video_name"],
                clip_start_time=clip["start_time"],
                clip_end_time=clip["end_time"],
                user_rating=clip["rating"]
            )
            print(f"   添加剪辑 {clip['clip_path']}: {'成功' if success else '失败'}")

        # 生成向量
        print("\n3. 生成向量嵌入...")
        created_count = rag_db.ensure_embeddings()
        print(f"   生成向量数量: {created_count}")

        # 测试关键词相似度
        print("\n4. 测试关键词相似度计算...")
        test_queries = [
            "amazing gameplay",
            "boss fight",
            "funny fail"
        ]

        for query in test_queries:
            score = rag_db.calculate_similarity_score(query)
            print(f"   查询 '{query}': 相似度 = {score:.3f}")

        # 测试向量相似度查询
        print("\n5. 测试向量相似度查询...")
        for query in test_queries:
            results = rag_db.query_similar(query, top_k=2)
            print(f"   查询 '{query}':")
            for i, result in enumerate(results, 1):
                print(f"     {i}. {result['clip_path']} (相似度: {result['similarity']:.3f})")

        # 显示所有剪辑
        print("\n6. 显示所有存储的剪辑...")
        all_clips = rag_db.get_all_clips()
        for i, clip in enumerate(all_clips, 1):
            print(f"   {i}. {clip['video_name']} - {clip['clip_path']} (评分: {clip['user_rating']})")

        print("\n=== 测试完成 ===")

    finally:
        # 清理临时文件
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"\n清理临时数据库文件: {db_path}")

def test_chinese_support():
    """测试中文支持"""
    print("\n=== 测试中文支持 ===\n")

    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        db_path = tmp.name

    try:
        rag_db = RAGVectorDatabase(database_path=db_path, ensure_english=True)

        # 添加中文测试数据
        chinese_clips = [
            {
                "clip_path": "/test/chinese1.mp4",
                "transcript_text": "这是一个精彩的游戏时刻，玩法非常棒",
                "video_name": "中文游戏直播 1",
                "start_time": 0.0,
                "end_time": 10.0,
                "rating": 5
            }
        ]

        for clip in chinese_clips:
            rag_db.add_liked_clip_vector(
                clip_path=clip["clip_path"],
                transcript_text=clip["transcript_text"],
                video_name=clip["video_name"],
                clip_start_time=clip["start_time"],
                clip_end_time=clip["end_time"],
                user_rating=clip["rating"]
            )

        # 生成向量
        created = rag_db.ensure_embeddings()
        print(f"生成中文向量: {created} 个")

        # 测试查询
        query = "精彩游戏"
        score = rag_db.calculate_similarity_score(query)
        print(f"中文查询 '{query}': 关键词相似度 = {score:.3f}")

        results = rag_db.query_similar(query, top_k=1)
        if results:
            print(f"向量相似度查询结果: 相似度 = {results[0]['similarity']:.3f}")

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

if __name__ == "__main__":
    # 运行基本测试
    test_rag_basic()

    # 运行中文测试
    test_chinese_support()

    print("\n提示: 如果看到向量生成失败的警告，这是正常的 - 缺少 sentence-transformers 依赖")
    print("要启用完整功能，请安装: pip install sentence-transformers transformers")
import os
import json
import logging
from typing import Optional, Dict, Any, List

import re
import numpy as np

class RAGVectorDatabase:
    """RAG向量数据库类 - 增强版（自动向量化，英文优先）"""
    
    def __init__(
        self,
        database_path: str = "rag_database.json",
        embedding_model_name: str = "all-MiniLM-L6-v2",
        ensure_english: bool = True,
    ):
        """
        初始化RAG向量数据库
        
        Args:
            database_path: 数据库文件路径
        """
        self.database_path = database_path
        self.embedding_model_name = embedding_model_name
        self.ensure_english = ensure_english
        self.data = self._load_database()
        
        # 懒加载模型（运行时按需导入第三方依赖；缺失时优雅降级）
        self._embedder = None  # type: ignore
        self._translator = None  # type: ignore
        logging.info(f"RAG向量数据库初始化完成: {database_path}")
    
    def _load_database(self) -> Dict[str, Any]:
        """加载数据库文件"""
        if os.path.exists(self.database_path):
            try:
                with open(self.database_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.warning(f"加载RAG数据库失败: {e}")
                return {"clips": [], "vectors": {}}
        else:
            return {"clips": [], "vectors": {}}
    
    def _save_database(self):
        """保存数据库到文件"""
        try:
            with open(self.database_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存RAG数据库失败: {e}")
    
    def add_liked_clip_vector(self, clip_path: str, transcript_text: str, 
                             video_name: str, clip_start_time: float, 
                             clip_end_time: float, user_rating: int) -> bool:
        """
        添加喜欢的切片向量到数据库
        
        Args:
            clip_path: 切片文件路径
            transcript_text: 转录文本
            video_name: 视频名称
            clip_start_time: 切片开始时间
            clip_end_time: 切片结束时间
            user_rating: 用户评分
            
        Returns:
            bool: 是否添加成功
        """
        try:
            clip_info = {
                "clip_path": clip_path,
                "transcript_text": transcript_text,
                "video_name": video_name,
                "clip_start_time": clip_start_time,
                "clip_end_time": clip_end_time,
                "user_rating": user_rating,
                "added_time": self._get_current_timestamp()
            }
            
            # 添加到数据库
            self.data["clips"].append(clip_info)
            
            # 保存数据库
            self._save_database()
            
            logging.info(f"成功添加切片到RAG数据库: {clip_path}")
            return True
            
        except Exception as e:
            logging.error(f"添加切片到RAG数据库失败: {e}")
            return False
    
    def calculate_similarity_score(self, text: str) -> float:
        """
        计算文本与数据库中已有切片的相似度分数
        
        Args:
            text: 要比较的文本
            
        Returns:
            float: 相似度分数 (0.0-1.0)
        """
        try:
            if not self.data["clips"]:
                return 0.0
            
            # 简单的文本相似度计算（基于关键词匹配）
            # 这里使用基础的实现，实际应用中可以使用更复杂的向量相似度算法
            
            text_lower = text.lower()
            max_similarity = 0.0
            
            import re
            # 统一 token 提取函数（字母数字片段）
            def _tokens(txt: str):
                if not txt:
                    return set()
                return set(re.findall(r"[a-z0-9]+", txt.lower()))

            text_words = _tokens(text)
            if not text_words:
                return 0.0

            for clip in self.data["clips"]:
                transcript_words = _tokens(clip.get("transcript_text", ""))
                if not transcript_words:
                    continue
                # Jaccard
                intersection = text_words.intersection(transcript_words)
                if not intersection:
                    continue
                union = text_words.union(transcript_words)
                if not union:
                    continue
                jaccard_similarity = len(intersection) / len(union)
                rating_factor = clip.get("user_rating", 5) / 5.0
                weighted_similarity = jaccard_similarity * rating_factor
                max_similarity = max(max_similarity, weighted_similarity)
            
            return max_similarity
            
        except Exception as e:
            logging.error(f"计算RAG相似度分数失败: {e}")
            return 0.0

    # ----------------------------- 新增：自动向量化逻辑 -----------------------------
    def _lazy_init_embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer  # 延迟导入
                self._embedder = SentenceTransformer(self.embedding_model_name)
            except Exception as e:
                logging.warning(f"未能加载SentenceTransformer，向量功能将禁用：{e}")
                self._embedder = None

    def _lazy_init_translator(self):
        if self._translator is None and self.ensure_english:
            try:
                from transformers import pipeline  # 延迟导入
                self._translator = pipeline("translation", model="Helsinki-NLP/opus-mt-zh-en")
            except Exception as e:
                logging.warning(f"未能加载翻译模型，将跳过中文转英文：{e}")
                self._translator = None

    def _looks_non_english(self, text: str) -> bool:
        # 简单中文字符检测或非 ASCII 比例过高
        if re.search(r"[\u4e00-\u9fff]", text):
            return True
        non_ascii = sum(1 for ch in text if ord(ch) > 127)
        return non_ascii > max(3, len(text) * 0.2)

    def _maybe_to_english(self, text: str) -> str:
        if not self.ensure_english:
            return text
        if not text:
            return text
        if not self._looks_non_english(text):
            return text
        self._lazy_init_translator()
        if self._translator is None:
            return text
        try:
            out = self._translator(text, max_length=512)
            if isinstance(out, list) and out:
                return out[0].get("translation_text", text)
        except Exception:
            pass
        return text

    def _embed_text(self, text: str) -> List[float]:
        self._lazy_init_embedder()
        # 若嵌入器不可用，则返回空向量，调用方需自行跳过
        if self._embedder is None:
            return []
        english_text = self._maybe_to_english(text)
        try:
            vec = self._embedder.encode([english_text], convert_to_tensor=False)
            arr = np.array(vec).astype("float32")[0]
            # 归一化以便余弦计算
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            return arr.tolist()
        except Exception as e:
            logging.warning(f"文本向量化失败，跳过：{e}")
            return []

    def ensure_embeddings(self) -> int:
        """为尚未向量化的切片生成英文向量；返回本次新增向量的数量"""
        try:
            created = 0
            vectors = self.data.setdefault("vectors", {})
            for clip in self.data.get("clips", []):
                clip_id = clip.get("clip_path")
                if not clip_id:
                    continue
                if clip_id in vectors and isinstance(vectors[clip_id], dict) and "vector" in vectors[clip_id]:
                    continue
                text = clip.get("transcript_text", "")
                if not text:
                    continue
                vec = self._embed_text(text)
                if not vec:
                    # 嵌入器不可用或失败，跳过生成
                    continue
                vectors[clip_id] = {
                    "vector": vec,
                    "model": self.embedding_model_name,
                    "lang": "en" if not self._looks_non_english(text) else "auto-en",
                }
                created += 1
            if created:
                self._save_database()
            return created
        except Exception as e:
            logging.error(f"生成嵌入失败: {e}")
            return 0

    def query_similar(self, text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """对输入文本做英文向量化并与已存向量做余弦相似度，返回 top_k 结果"""
        try:
            # 确保所有向量已就绪（只处理缺失项，自动且一次性）
            self.ensure_embeddings()
            vectors = self.data.get("vectors", {})
            if not vectors:
                return []
            # 构造矩阵
            keys = []
            mat = []
            for k, v in vectors.items():
                if not isinstance(v, dict) or "vector" not in v:
                    continue
                keys.append(k)
                mat.append(v["vector"])
            if not mat:
                return []
            mat = np.array(mat, dtype="float32")
            # 归一化已在存储时完成，这里再次保护
            norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
            mat = mat / norms
            # 查询向量
            q_vec = self._embed_text(text)
            if not q_vec:
                return []
            q = np.array(q_vec, dtype="float32")[None, :]
            # 余弦相似度
            sims = (q @ mat.T)[0]
            order = np.argsort(-sims)[: top_k]
            # 回填元信息
            results = []
            clip_map = {c["clip_path"]: c for c in self.data.get("clips", [])}
            for idx in order:
                clip_path = keys[idx]
                meta = clip_map.get(clip_path, {})
                results.append({
                    "clip_path": clip_path,
                    "video_name": meta.get("video_name"),
                    "start": meta.get("clip_start_time"),
                    "end": meta.get("clip_end_time"),
                    "similarity": float(sims[idx]),
                })
            return results
        except Exception as e:
            logging.error(f"相似度查询失败: {e}")
            return []
    
    def _get_current_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_all_clips(self) -> list:
        """获取所有切片信息"""
        return self.data.get("clips", [])
    
    def clear_database(self):
        """清空数据库"""
        self.data = {"clips": [], "vectors": {}}
        self._save_database()
        logging.info("RAG数据库已清空") 
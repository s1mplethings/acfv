"""RAG preference summary tab."""

from __future__ import annotations

import os
import re
from collections import Counter
from statistics import mean, median
from typing import Dict, List

from PyQt5 import QtCore, QtWidgets

from acfv.rag_vector_database import RAGVectorDatabase
from acfv.runtime.storage import processing_path

from .base import TabHandle


class RAGPreferenceWidget(QtWidgets.QWidget):
    """Compact viewer that summarizes current RAG preferences."""

    def __init__(self, config_manager) -> None:
        super().__init__()
        self.config_manager = config_manager
        self.db_path = self._resolve_db_path()
        self.db: RAGVectorDatabase | None = None
        self._build_ui()
        self._init_db()
        self.refresh_summary()

    # ---- setup ------------------------------------------------------- #

    def _resolve_db_path(self) -> str:
        path = self.config_manager.get("RAG_DB_PATH")
        if not path:
            path = str(processing_path("rag_database.json"))
            self.config_manager.set("RAG_DB_PATH", path, persist=True)
        return os.path.abspath(str(path))

    def _init_db(self) -> None:
        try:
            self.db = RAGVectorDatabase(database_path=self.db_path)
            self.path_edit.setText(self.db_path)
            self._set_status(f"已加载数据库: {self.db_path}")
        except Exception as exc:  # noqa: BLE001
            self.db = None
            self._set_status(f"RAG 数据库加载失败: {exc}")

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 8, 10, 8)

        # Path row
        path_row = QtWidgets.QHBoxLayout()
        path_label = QtWidgets.QLabel("RAG 数据库")
        self.path_edit = QtWidgets.QLineEdit(self.db_path)
        self.path_edit.setReadOnly(True)
        btn_open = QtWidgets.QPushButton("打开目录")
        btn_open.clicked.connect(self._open_dir)
        path_row.addWidget(path_label)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(btn_open)
        layout.addLayout(path_row)

        # Buttons
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_refresh = QtWidgets.QPushButton("刷新总结")
        self.btn_refresh.clicked.connect(self.refresh_summary)
        self.btn_embed = QtWidgets.QPushButton("生成/补全向量")
        self.btn_embed.clicked.connect(self.ensure_embeddings)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addWidget(self.btn_embed)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # Summary box
        self.summary_box = QtWidgets.QPlainTextEdit()
        self.summary_box.setReadOnly(True)
        self.summary_box.setPlaceholderText("这里会展示根据你已评分/收藏的剪辑提取的偏好总结。")
        self.summary_box.setMinimumHeight(240)
        layout.addWidget(self.summary_box, 1)

        # Status label
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: #444;")
        layout.addWidget(self.status_label)

    # ---- actions ----------------------------------------------------- #

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _open_dir(self) -> None:
        directory = os.path.dirname(self.db_path) or "."
        QtGui = None
        try:
            from PyQt5 import QtGui as _QtGui  # type: ignore

            QtGui = _QtGui
        except Exception:
            QtGui = None
        if QtGui:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(directory))

    def ensure_embeddings(self) -> None:
        if not self.db:
            self._set_status("数据库未加载，无法生成向量。")
            return
        created = self.db.ensure_embeddings()
        self._set_status(f"生成/补全向量 {created} 条。")
        self.refresh_summary()

    def refresh_summary(self) -> None:
        if not self.db:
            self.summary_box.setPlainText("数据库未加载，无法生成偏好总结。")
            return
        clips = self.db.get_all_clips()
        if not clips:
            self.summary_box.setPlainText("数据库为空，先导入或添加剪辑。")
            return
        summary_lines = self._build_summary(clips)
        self.summary_box.setPlainText("\n".join(summary_lines))
        self._set_status(f"已分析 {len(clips)} 条剪辑。")

    # ---- summary logic ------------------------------------------------ #

    def _build_summary(self, clips: List[Dict[str, object]]) -> List[str]:
        ratings = [c.get("user_rating") for c in clips if isinstance(c.get("user_rating"), (int, float))]
        durations = []
        videos = Counter()
        topic_items: List[Dict[str, object]] = []
        vectors = self.db.data.get("vectors", {}) if self.db and hasattr(self.db, "data") else {}
        vector_ready = sum(
            1 for c in clips if c.get("clip_path") in vectors and isinstance(vectors.get(c.get("clip_path")), dict)
        )

        for c in clips:
            try:
                start = float(c.get("clip_start_time") or c.get("start") or 0.0)
                end = float(c.get("clip_end_time") or c.get("end") or 0.0)
                if end > start:
                    durations.append(end - start)
            except Exception:
                pass
            video_name = str(c.get("video_name") or "").strip()
            if video_name:
                videos[video_name] += 1
            text = str(c.get("transcript_text") or c.get("text") or "")
            if text.strip():
                clip_path = c.get("clip_path")
                vec = None
                if clip_path and isinstance(vectors, dict):
                    entry = vectors.get(clip_path)
                    if isinstance(entry, dict):
                        vec = entry.get("vector")
                topic_items.append({"text": text, "vector": vec})

        lines: List[str] = []
        lines.append(
            f"共 {len(clips)} 条偏好剪辑，平均评分 {mean(ratings):.2f}" if ratings else f"共 {len(clips)} 条偏好剪辑（暂无评分字段）。"
        )
        if durations:
            lines.append(f"偏好时长: 平均 {mean(durations):.1f}s · 中位 {median(durations):.1f}s")
        if videos:
            top_videos = ", ".join(f"{name}({cnt})" for name, cnt in videos.most_common(3))
            lines.append(f"常见视频/主播: {top_videos}")
        lines.extend(self._build_topic_summary(topic_items))
        if vectors:
            pct = (vector_ready / max(1, len(clips))) * 100
            lines.append(f"向量覆盖率: {pct:.0f}%（用于个性化相似度）")
        else:
            lines.append("向量覆盖率: 0%（点击“生成/补全向量”后启用相似度计算）")

        if ratings:
            high = sum(1 for r in ratings if r >= 4)
            low = sum(1 for r in ratings if r <= 2)
            if high > low * 2:
                lines.append("偏好倾向：高分集中，喜好方向较清晰。")
            elif low > high:
                lines.append("偏好倾向：评分分散，建议补充更多明确的高分样本。")
        return lines

    def _build_topic_summary(self, items: List[Dict[str, object]]) -> List[str]:
        texts_all = [str(item.get("text") or "").strip() for item in items if str(item.get("text") or "").strip()]
        if len(texts_all) < 2:
            return ["主题模型: 样本不足（至少需要 2 条文本）"]

        stopwords = {
            "and", "the", "with", "this", "that", "what", "you", "have", "for", "but",
            "are", "was", "when", "where", "how", "just", "like", "get", "got",
            "i", "me", "my", "we", "our", "us", "your", "youre", "im", "ive",
            "so", "thank", "thanks", "much", "follow", "raid", "good",
            "的", "了", "是", "我", "你", "他", "她", "它", "我们", "你们", "他们",
            "啊", "吗", "呀", "吧", "就", "都", "和", "与", "在", "有", "也", "很",
        }

        def _tokenize(text: str) -> List[str]:
            tokens = re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}", text.lower())
            return [tok for tok in tokens if tok not in stopwords]

        items_with_vec = []
        for item in items:
            text = str(item.get("text") or "").strip()
            vec = item.get("vector")
            if text and isinstance(vec, list) and vec:
                items_with_vec.append((text, vec))

        data_texts = texts_all
        data_matrix = None
        try:
            import numpy as np
        except Exception:
            np = None

        if items_with_vec and np is not None:
            data_texts = [t for t, _ in items_with_vec]
            data_matrix = np.array([v for _, v in items_with_vec], dtype="float32")
        else:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
            except Exception:
                return ["主题模型: 未能加载 scikit-learn，无法生成主题"]
            vectorizer = TfidfVectorizer(tokenizer=_tokenize, token_pattern=None, min_df=1, max_df=0.6, max_features=2000)
            try:
                tfidf = vectorizer.fit_transform(data_texts)
            except ValueError:
                return ["主题模型: 文本不足以生成主题"]
            data_matrix = tfidf.toarray()

        n_docs = len(data_texts)
        if n_docs < 2:
            return ["主题模型: 样本不足（至少需要 2 条文本）"]

        try:
            from sklearn.cluster import KMeans
            from sklearn.metrics import silhouette_score
        except Exception:
            return ["主题模型: 未能加载 scikit-learn，无法生成主题"]

        def _choose_k(data):
            max_k = min(6, n_docs - 1)
            if max_k < 2:
                km = KMeans(n_clusters=2 if n_docs >= 2 else 1, n_init=10, random_state=0)
                labels = km.fit_predict(data)
                return km, labels
            best_km = None
            best_labels = None
            best_score = -1.0
            for k in range(2, max_k + 1):
                km = KMeans(n_clusters=k, n_init=10, random_state=0)
                labels = km.fit_predict(data)
                try:
                    score = silhouette_score(data, labels)
                except Exception:
                    score = -1.0
                if score > best_score:
                    best_score = score
                    best_km = km
                    best_labels = labels
            if best_km is None or best_labels is None:
                best_km = KMeans(n_clusters=2, n_init=10, random_state=0)
                best_labels = best_km.fit_predict(data)
            return best_km, best_labels

        kmeans, labels = _choose_k(data_matrix)
        n_topics = len(set(labels)) if labels is not None else 0
        if not n_topics:
            return ["主题模型: 聚类失败，无法生成主题"]

        llm, model_name = self._get_topic_llm()
        llm_note = f" · LLM: {model_name}" if llm else " · LLM 不可用"
        lines = [f"主题模型: {n_topics} 个主题（基于 {n_docs} 段文本{llm_note}）"]

        try:
            import numpy as np
        except Exception:
            np = None

        clusters = {}
        for idx, label in enumerate(labels):
            clusters.setdefault(int(label), []).append(idx)

        order = sorted(clusters.keys(), key=lambda k: len(clusters[k]), reverse=True)
        centers = getattr(kmeans, "cluster_centers_", None)

        for rank, label in enumerate(order, start=1):
            idxs = clusters[label]
            rep_texts = [data_texts[i] for i in idxs]
            if centers is not None and np is not None:
                center = centers[label]
                distances = [(i, float(np.linalg.norm(data_matrix[i] - center))) for i in idxs]
                distances.sort(key=lambda x: x[1])
                rep_texts = [data_texts[i] for i, _ in distances[:4]]
            topic_label = self._label_topic_llm(rep_texts, llm, stopwords)
            lines.append(f"主题{rank}: {topic_label}")
        return lines

    def _get_topic_llm(self):
        if getattr(self, "_topic_llm_checked", False):
            return getattr(self, "_topic_llm", None), getattr(self, "_topic_llm_model", "")
        self._topic_llm_checked = True
        model_name = str(
            self.config_manager.get("RAG_TOPIC_LLM_MODEL")
            or self.config_manager.get("LOCAL_SUMMARY_MODEL")
            or os.environ.get("RAG_TOPIC_LLM_MODEL")
            or os.environ.get("LOCAL_SUMMARY_MODEL")
            or "google/gemma-3-4b-it"
        ).strip()
        self._topic_llm_model = model_name
        if not model_name or model_name.lower() in {"off", "none", "disable", "disabled"}:
            self._topic_llm = None
            return None, model_name
        try:
            from transformers import pipeline
        except Exception:
            self._topic_llm = None
            return None, model_name
        try:
            self._topic_llm_task = "text2text-generation"
            device_id = self._resolve_hf_device_id()
            self._topic_llm = pipeline("text2text-generation", model=model_name, device=device_id)
        except Exception:
            try:
                self._topic_llm_task = "text-generation"
                device_id = self._resolve_hf_device_id()
                self._topic_llm = pipeline("text-generation", model=model_name, device=device_id)
            except Exception:
                self._topic_llm = None
        return self._topic_llm, model_name

    def _resolve_hf_device_id(self) -> int:
        enable_gpu = bool(self.config_manager.get("ENABLE_GPU_ACCELERATION", True))
        if not enable_gpu:
            return -1
        try:
            import torch
        except Exception:
            return -1
        if not torch.cuda.is_available():
            return -1
        llm_device = self.config_manager.get("LLM_DEVICE", 0)
        try:
            llm_device_id = int(llm_device)
        except (TypeError, ValueError):
            llm_device_id = None
        if llm_device_id is not None:
            return llm_device_id if llm_device_id >= 0 else -1
        gpu_device = str(self.config_manager.get("GPU_DEVICE", "cuda:0") or "cuda:0")
        if gpu_device.startswith("cuda"):
            parts = gpu_device.split(":")
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
        return 0

    def _label_topic_llm(self, texts: List[str], llm, stopwords: set) -> str:
        texts = [re.sub(r"\s+", " ", t).strip() for t in texts if t and t.strip()]
        if not texts:
            return "（无有效文本）"
        use_chinese = any(re.search(r"[\u4e00-\u9fff]", t) for t in texts)
        snippets = [t[:220] for t in texts[:4]]
        if llm:
            if use_chinese:
                prompt = (
                    "根据以下剪辑转录内容，输出一个简短主题标签（2-6个词），只输出标签。\n"
                    "要求：不要直接引用原句，避免感谢/关注/打招呼/订阅/raid 等泛用语。\n"
                )
            else:
                prompt = (
                    "Given the following clip transcripts, return a short topic label (2-6 words). "
                    "Only return the label. Do not quote full sentences, and ignore generic "
                    "phrases like thanks, follows, greetings, subs, raids.\n"
                )
            prompt += "\n".join(f"- {s}" for s in snippets)
            try:
                output = llm(prompt, max_new_tokens=24, num_beams=4, do_sample=False, truncation=True)
                if isinstance(output, list) and output:
                    label = output[0].get("generated_text") or output[0].get("summary_text") or ""
                    if getattr(self, "_topic_llm_task", "") == "text-generation" and label.startswith(prompt):
                        label = label[len(prompt):]
                    label = label.strip().splitlines()[0]
                    if label:
                        return label
            except Exception:
                pass
        tokens = Counter()
        for text in snippets:
            for tok in re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}", text.lower()):
                if tok in stopwords:
                    continue
                tokens[tok] += 1
        if tokens:
            return ", ".join(tok for tok, _ in tokens.most_common(5))
        return "（无法生成主题）"


def create_rag_pref_tab(main_window, config_manager) -> TabHandle:
    widget = RAGPreferenceWidget(config_manager)
    return TabHandle(title="RAG 偏好", widget=widget, controller=widget)

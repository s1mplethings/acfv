#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速 RAG 功能测试脚本

用法（PowerShell）：
  # 放大权重便于观察
  $env:RAG_ENABLE="1"
  $env:RAG_WEIGHT="1.0"
  D:/anaconda/envs/3.10/python.exe tools/test_rag_pipeline.py

测试内容：
1. 写入两类偏好片段 seed (搞笑 / 思考)。
2. 构造若干候选文本，计算 Jaccard 相似 -> rag_prior。
3. 模拟最终得分 = base_score + RAG_WEIGHT * rag_prior。
4. 演示清空数据库后 rag_prior 变为 0 的对比。

不依赖实际视频/转录，可单独运行。
"""
from __future__ import annotations
import os, json, math
from pathlib import Path
from textwrap import shorten

DB_PATH = Path("data/rag_database.json")
CORPUS_PATH = Path("data/rag_corpus.jsonl")  # 行式语料库（评分/转写汇总）

SEED_CLIPS = [
    {"id": "like_funny", "text": "funny hype moment chat spam laugh frog dance", "score": 0.95},
    {"id": "like_strategy", "text": "calm strategy thinking analyze card game turn calculation", "score": 0.90},
]

CANDIDATES = [
    {"id": "c1", "text": "chat goes hype everyone laugh frog emote spam"},
    {"id": "c2", "text": "quiet calculation strategic turn planning analyze next card"},
    {"id": "c3", "text": "singing background music nothing special idle scene"},
    {"id": "c4", "text": "fast reaction funny scream moment"},
]

# --- 简单 tokenizer 与 jaccard 与项目保持一致（近似） ---
import re
TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")

def tokenize(text: str):
    return set(t.lower() for t in TOKEN_RE.findall(text))

def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b: return 0.0
    inter = a & b
    if not inter: return 0.0
    return len(inter) / len(a | b)

# --- 数据库读写 ---

def load_db():
    """优先按环境变量决定读取来源:
    USE_CORPUS=1 -> 从 rag_corpus.jsonl 构造一个临时的 clips 列表（只做词重叠测试, 不写回）
    否则 -> 使用 rag_database.json （正式偏好数据库）
    """
    use_corpus = os.environ.get("USE_CORPUS", "0") == "1"
    if use_corpus:
        # 从语料构造：每行 JSON，取 content/text 字段；若存在 rating 则可按阈值过滤
        clips = []
        if CORPUS_PATH.exists():
            with CORPUS_PATH.open("r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    text = obj.get("content") or obj.get("text") or obj.get("transcript") or ""
                    if not text:
                        continue
                    rating = obj.get("rating") or obj.get("score") or 0
                    # 可选过滤：只保留评分较高的
                    min_rating = float(os.environ.get("CORPUS_MIN_RATING", 0))
                    try:
                        r_val = float(rating)
                    except Exception:
                        r_val = 0
                    if r_val < min_rating:
                        continue
                    clips.append({
                        "id": f"corpus_{i}",
                        "text": text,
                        "score": r_val
                    })
        return {"clips": clips, "vectors": {}}
    # 默认读取数据库
    if DB_PATH.exists():
        try:
            return json.loads(DB_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clips": [], "vectors": {}}

def save_db(db):
    # 如果在 corpus 模式下，不写回（保持只读演示）
    if os.environ.get("USE_CORPUS", "0") == "1":
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def seed_database():
    db = load_db()
    existing = {c.get("id") for c in db.get("clips", [])}
    added = 0
    for c in SEED_CLIPS:
        if c["id"] not in existing:
            db["clips"].append(c)
            added += 1
    save_db(db)
    return added


def clear_database():
    if os.environ.get("USE_CORPUS", "0") == "1":
        # 语料模式不清空真实文件，只提示
        print("(USE_CORPUS=1) 跳过清空 rag_corpus.jsonl，只会基于其内容临时计算")
        return
    save_db({"clips": [], "vectors": {}})

# --- 计算 rag_prior ---

def calc_rag_prior(text: str, db) -> float:
    tokens_c = tokenize(text)
    best = 0.0
    for clip in db.get("clips", []):
        tokens_l = tokenize(clip.get("text", ""))
        score = jaccard(tokens_c, tokens_l)
        if score > best:
            best = score
    return best  # 0~1


def run_phase(label: str):
    db = load_db()
    use_corpus = os.environ.get("USE_CORPUS", "0") == "1"
    rag_weight = float(os.environ.get("RAG_WEIGHT", 0.2)) if os.environ.get("RAG_ENABLE", "0") == "1" else 0.0
    source_label = "rag_corpus.jsonl(临时)" if use_corpus else str(DB_PATH)
    print(f"\n=== {label} | RAG_ENABLE={os.environ.get('RAG_ENABLE','0')} RAG_WEIGHT={rag_weight} SOURCE={source_label} ===")
    print(f"偏好条目数: {len(db.get('clips', []))}")

    rows = []
    for cand in CANDIDATES:
        base = 0.40  # 假设一个基础模型分
        rag_prior = calc_rag_prior(cand["text"], db) if rag_weight > 0 else 0.0
        final = base + rag_weight * rag_prior
        rows.append((cand["id"], rag_prior, final, cand["text"]))
    # 排序按最终分
    rows.sort(key=lambda r: r[2], reverse=True)
    print(f"ID   rag_prior  final_score  text")
    for r in rows:
        print(f"{r[0]:<4} {r[1]:<9.4f}  {r[2]:<10.4f}  {shorten(r[3], 60)}")

    if rag_weight == 0.0:
        print("⚠️  RAG 未启用或权重为 0，rag_prior 全 0")
    else:
        any_pos = any(r[1] > 0 for r in rows)
        if any_pos:
            print("✅  已看到非 0 rag_prior，说明 RAG 生效")
        else:
            if use_corpus and not DB_PATH.exists():
                print("❌  全部 0，语料模式下可能 corpus 里没有与候选重叠的词或过滤太严 (CORPUS_MIN_RATING)")
            else:
                print("❌  全部 0，偏好库为空或无词重叠")


def main():
    use_corpus = os.environ.get("USE_CORPUS", "0") == "1"
    if use_corpus:
        print("🔎 当前为语料模式 (USE_CORPUS=1)：从 data/rag_corpus.jsonl 构造临时偏好集合。")
        print("    可用 $env:CORPUS_MIN_RATING=4 限制最低评分过滤。")
        run_phase("Phase (Corpus 单次)")
    else:
        # 数据库模式完整三阶段
        clear_database()
        run_phase("Phase A: 空数据库 (基线)")
        added = seed_database()
        print(f"\n写入种子条目: {added}")
        run_phase("Phase B: 写入偏好后")
        os.environ["RAG_ENABLE"] = "0"
        run_phase("Phase C: 人为关闭 RAG 对比")
    print("\n完成。你可以设置 USE_CORPUS=1 切换到语料测试模式。")

if __name__ == "__main__":
    # 默认启用 RAG 便于演示
    os.environ.setdefault("RAG_ENABLE", "1")
    main()

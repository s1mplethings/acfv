#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量同步历史评分到 data 目录 (rag_corpus.jsonl + 可选 rag_database.json)

使用场景:
  - 之前已经产生了大量评分文件，但实时写入 RAG 未启用/路径不一致。
  - 需要一次性把现有评分集中汇总到 data/rag_corpus.jsonl，并(可选)写入 rag_database.json 供后续分析 rag_prior 使用。

支持源文件:
 1. clips/<video_name>/**/acfv_ratings.jsonl (人工评分累积)
 2. clips/<video_name>/data/ratings.json (自动分析生成 topN 评分)

去重策略: 以 (video_name, clip_filename, start_sec, end_sec) 作为主键，不重复写入。

用法示例 (PowerShell):
  # 最简单：只同步语料
  python tools/sync_ratings_to_rag.py

  # 同步并写入 rag_database.json，向量化
  python tools/sync_ratings_to_rag.py --update-rag-db --rebuild-embeddings

  # 设置最小分数阈值 (只导入 >=4.0)
  python tools/sync_ratings_to_rag.py --min-score 4

参数:
  --clips-base-dir  指定 clips 根目录 (默认读取配置 CLIPS_BASE_DIR 或 'clips')
  --project-root    指定项目根 (默认脚本所在上级)
  --min-score       最低导入分数 (包含边界)
  --update-rag-db   同步到 rag_database.json
  --rebuild-embeddings  同步后立即补全缺失向量
  --rag-db-path     自定义 rag_database 路径 (默认 'rag_database.json')
  --dry-run         仅统计不写入
  --verbose         输出更多细节
"""
from __future__ import annotations
import os, sys, json, argparse, logging
from typing import Dict, Any, List, Tuple, Set

# --------------------- 辅助: 读取配置 ---------------------

def _load_config_manager():
    try:
        from acfv.config import config_manager  # type: ignore
        return config_manager
    except Exception:
        return None

# --------------------- 源扫描逻辑 -------------------------

def scan_acfv_ratings_jsonl(root: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn == 'acfv_ratings.jsonl':
                fpath = os.path.join(dirpath, fn)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                                results.append(obj)
                            except Exception:
                                continue
                except Exception as e:
                    logging.warning(f"读取失败 {fpath}: {e}")
    return results

def scan_ratings_json(root: str) -> List[Dict[str, Any]]:
    # 结构: clips/<video_name>/data/ratings.json
    results: List[Dict[str, Any]] = []
    for video_name in os.listdir(root):
        vdir = os.path.join(root, video_name)
        if not os.path.isdir(vdir):
            continue
        data_dir = os.path.join(vdir, 'data')
        ratings_path = os.path.join(data_dir, 'ratings.json')
        if os.path.exists(ratings_path):
            try:
                with open(ratings_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for clip_fn, rec in data.items():
                        try:
                            results.append({
                                'video_name': video_name,
                                'clip_filename': clip_fn,
                                'clip_path': os.path.join(data_dir, '..', 'output_clips', clip_fn).replace('..'+os.sep, ''),
                                'start_sec': rec.get('start'),
                                'end_sec': rec.get('end'),
                                'score': rec.get('rating'),
                                'text': rec.get('text'),
                                'source_type': 'analysis_topN'
                            })
                        except Exception:
                            continue
            except Exception as e:
                logging.warning(f"读取失败 {ratings_path}: {e}")
    return results

# --------------------- 归一化与合并 -----------------------

def normalize_record(obj: Dict[str, Any]) -> Dict[str, Any]:
    # 兼容 acfv_ratings.jsonl 与 ratings.json 提取的结构
    return {
        'video_name': obj.get('video_name') or obj.get('video') or '',
        'batch_name': obj.get('batch_name'),
        'clip_filename': obj.get('clip_filename') or obj.get('clip') or obj.get('filename'),
        'clip_path': obj.get('clip_path'),
        'start_sec': obj.get('start_sec') if obj.get('start_sec') is not None else obj.get('start'),
        'end_sec': obj.get('end_sec') if obj.get('end_sec') is not None else obj.get('end'),
        'score': obj.get('score') if obj.get('score') is not None else obj.get('rating'),
        'tags': obj.get('tags'),
        'notes': obj.get('notes'),
        'content': obj.get('content') or obj.get('text'),
        'source_type': obj.get('source_type') or 'manual_rating'
    }

# --------------------- rag_corpus 去重写入 ----------------

def load_existing_corpus_keys(corpus_path: str) -> Set[str]:
    keys: Set[str] = set()
    if not os.path.exists(corpus_path):
        return keys
    try:
        with open(corpus_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    obj = json.loads(line.strip())
                    k = f"{obj.get('video_name')}|{obj.get('clip_filename')}|{obj.get('start_sec')}|{obj.get('end_sec')}"
                    keys.add(k)
                except Exception:
                    continue
    except Exception:
        pass
    return keys

# --------------------- RAG DB 写入 ------------------------

def update_rag_database(records: List[Dict[str, Any]], rag_db_path: str, min_score: float, rebuild: bool, verbose: bool):
    try:
        from rag_vector_database import RAGVectorDatabase
    except Exception as e:
        logging.error(f"无法导入 RAGVectorDatabase: {e}")
        return

    db = RAGVectorDatabase(database_path=rag_db_path)
    existing = {c.get('clip_path') for c in db.get_all_clips()}
    added = 0
    for r in records:
        sc = r.get('score')
        if sc is None: continue
        try:
            if float(sc) < min_score:
                continue
        except Exception:
            continue
        cpath = r.get('clip_path')
        if not cpath or cpath in existing:
            continue
        db.add_liked_clip_vector(
            clip_path=cpath,
            transcript_text=r.get('content') or '',
            video_name=r.get('video_name') or '',
            clip_start_time=r.get('start_sec') or 0.0,
            clip_end_time=r.get('end_sec') or 0.0,
            user_rating=int(round(float(sc))) if isinstance(sc, (int, float)) else 5
        )
        existing.add(cpath)
        added += 1
    if rebuild:
        try:
            new_vecs = db.ensure_embeddings()
            logging.info(f"[RAG] 新增切片 {added}, 新增向量 {new_vecs}")
        except Exception as e:
            logging.warning(f"[RAG] 向量生成失败: {e}")
    else:
        logging.info(f"[RAG] 新增切片 {added}, 未请求生成向量")

# --------------------- 主流程 -----------------------------

def main():
    parser = argparse.ArgumentParser(description='同步历史评分到 RAG 语料 / 数据库')
    parser.add_argument('--clips-base-dir', type=str, default=None)
    parser.add_argument('--project-root', type=str, default=None)
    parser.add_argument('--min-score', type=float, default=1.0, help='导入最小分数 (含)')
    parser.add_argument('--update-rag-db', action='store_true', help='写入 rag_database.json')
    parser.add_argument('--rebuild-embeddings', action='store_true', help='写入后生成缺失向量')
    parser.add_argument('--rag-db-path', type=str, default=None)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

    cfg = _load_config_manager()
    project_root = args.project_root or (os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    clips_base_dir = args.clips_base_dir or (cfg.get('CLIPS_BASE_DIR') if cfg else 'clips')
    clips_root = os.path.join(project_root, clips_base_dir) if not os.path.isabs(clips_base_dir) else clips_base_dir
    rag_db_path = args.rag_db_path or (cfg.get('RAG_DB_PATH') if (cfg and cfg.get('RAG_DB_PATH')) else 'rag_database.json')
    if not os.path.isabs(rag_db_path):
        rag_db_path = os.path.join(project_root, rag_db_path)

    if args.verbose:
        logging.info(f"项目根: {project_root}")
        logging.info(f"clips 根: {clips_root}")
        logging.info(f"rag_db: {rag_db_path}")

    # 扫描源
    manual_raw = scan_acfv_ratings_jsonl(clips_root)
    auto_raw = scan_ratings_json(clips_root)
    if args.verbose:
        logging.info(f"发现手动评分条目: {len(manual_raw)}")
        logging.info(f"发现分析 topN 条目: {len(auto_raw)}")

    # 归一化
    all_norm = [normalize_record(r) for r in (manual_raw + auto_raw)]

    # 过滤分数
    filtered = []
    for r in all_norm:
        sc = r.get('score')
        try:
            if sc is None or float(sc) < args.min_score:
                continue
        except Exception:
            continue
        filtered.append(r)

    # 准备写入 corpus
    corpus_path = os.path.join(project_root, 'data', 'rag_corpus.jsonl')
    os.makedirs(os.path.dirname(corpus_path), exist_ok=True)
    existing_keys = load_existing_corpus_keys(corpus_path)
    new_lines = []
    for r in filtered:
        k = f"{r.get('video_name')}|{r.get('clip_filename')}|{r.get('start_sec')}|{r.get('end_sec')}"
        if k in existing_keys:
            continue
        new_lines.append(r)
        existing_keys.add(k)

    logging.info(f"待追加语料条目: {len(new_lines)} / 筛选后总数 {len(filtered)} (min_score={args.min_score})")

    if not args.dry_run and new_lines:
        with open(corpus_path, 'a', encoding='utf-8') as f:
            for obj in new_lines:
                f.write(json.dumps(obj, ensure_ascii=False) + '\n')
        logging.info(f"已写入语料: {corpus_path}")
    elif not new_lines:
        logging.info("没有新的语料需要写入 (可能全部已存在或被阈值过滤)")

    # 可选写入 RAG 数据库
    if args.update_rag_db:
        update_rag_database(new_lines, rag_db_path, args.min_score, args.rebuild_embeddings, args.verbose)

    logging.info("同步完成")

if __name__ == '__main__':
    main()

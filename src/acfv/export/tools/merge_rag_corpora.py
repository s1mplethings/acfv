#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并分散的 rag_corpus.jsonl / 评分语料为一个大的 data/rag_corpus.jsonl

使用场景：
  - 之前在 modules/data 或打包目录、历史运行目录里生成了多个 rag_corpus.jsonl
  - 现在希望统一成一个去重的总语料（且不再需要 tags 字段）

规则：
 1. 自动扫描以下候选位置：
    - 项目根目录下的 data/rag_corpus.jsonl (作为基准)
    - modules/data/rag_corpus.jsonl
    - dist/InterestRating/_internal/modules/data/rag_corpus.jsonl (打包内展开)
    - 所有 clips/**/runs/**/acfv_ratings.jsonl (把评分也抽成语料)
 2. 统一字段：
    {source, video_name, batch_name, clip_filename, start_sec, end_sec, score, notes, content}
 3. 去重键： video_name|clip_filename|start_sec|end_sec
 4. content 若为空，尝试：
    - 读取对应视频目录 data/transcription.json (截取片段重用) —— 与运行时逻辑一致（可选：简单拼接所有文本）
    - 回退到 clip 文件名 tokens
 5. 写回 project_root/data/rag_corpus.jsonl

运行：
  python tools/merge_rag_corpora.py --rebuild
  可选参数：
    --no-transcript   合并时不再尝试读取转写（加速）
    --verbose         输出更多日志

"""
import os
import sys
import json
import argparse
import re
from typing import List, Dict, Set

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(PROJECT_ROOT, '..'))

DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
TARGET_PATH = os.path.join(DATA_DIR, 'rag_corpus.jsonl')

CANDIDATE_PATHS = [
    TARGET_PATH,
    os.path.join(PROJECT_ROOT, 'modules', 'data', 'rag_corpus.jsonl'),
    os.path.join(PROJECT_ROOT, 'dist', 'InterestRating', '_internal', 'modules', 'data', 'rag_corpus.jsonl'),
]

# 评分文件匹配 (clips/**/runs/**/acfv_ratings.jsonl)


def iter_rating_files() -> List[str]:
    out = []
    clips_dir = os.path.join(PROJECT_ROOT, 'clips')
    if not os.path.isdir(clips_dir):
        return out
    for root, dirs, files in os.walk(clips_dir):
        if 'acfv_ratings.jsonl' in files:
            out.append(os.path.join(root, 'acfv_ratings.jsonl'))
    return out

def load_lines(path: str) -> List[dict]:
    items = []
    if not os.path.exists(path):
        return items
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except Exception:
                    continue
    except Exception as e:
        print(f"[WARN] 读取失败 {path}: {e}")
    return items

TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)

def build_content_from_filename(name: str) -> str:
    base = os.path.basename(name or '')
    base = re.sub(r"_\d+(?:\.\d+)?s-\d+(?:\.\d+)?s\.[Mm][Pp]4$", "", base)
    toks = TOKEN_RE.findall(base.lower())
    return ' '.join(toks) if toks else base

def maybe_extract_transcript(video_name: str, start_sec, end_sec, use_transcript: bool) -> str:
    if not use_transcript:
        return ''
    # 查找 transcript
    clips_base = os.path.join(PROJECT_ROOT, 'clips')
    video_dir = os.path.join(clips_base, video_name)
    trans_path = os.path.join(video_dir, 'data', 'transcription.json')
    if not os.path.exists(trans_path):
        return ''
    try:
        with open(trans_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        segments = []
        if isinstance(data, dict):
            if isinstance(data.get('segments'), list):
                segments = data['segments']
            elif isinstance(data.get('result'), list):
                segments = data['result']
        elif isinstance(data, list):
            segments = data
        texts = []
        for seg in segments:
            try:
                s = float(seg.get('start', seg.get('from', -1)))
                e = float(seg.get('end', seg.get('to', -1)))
                if s == -1 or e == -1:
                    continue
                if start_sec is None or end_sec is None:
                    continue
                if e < start_sec or s > end_sec:
                    continue
                t = seg.get('text') or seg.get('content') or ''
                if t:
                    texts.append(t.strip())
            except Exception:
                continue
        if texts:
            return ' '.join(texts)
    except Exception:
        return ''
    return ''

def normalize_entry(raw: dict, use_transcript: bool, verbose: bool=False) -> dict:
    video_name = raw.get('video_name')
    if not video_name:
        # 尝试从 source / clip_path 推断
        for k in ('source', 'clip_path'):
            p = raw.get(k)
            if p:
                parts = os.path.normpath(p).split(os.sep)
                if 'clips' in parts:
                    idx = parts.index('clips')
                    if idx + 1 < len(parts):
                        video_name = parts[idx+1]
                        break
        raw['video_name'] = video_name
    clip_filename = raw.get('clip_filename') or os.path.basename(raw.get('source') or raw.get('clip_path') or '')
    start_sec = raw.get('start_sec')
    end_sec = raw.get('end_sec')
    content = raw.get('content') or ''
    if not content:
        # transcript first
        content = maybe_extract_transcript(video_name, start_sec, end_sec, use_transcript)
    if not content:
        content = build_content_from_filename(clip_filename)
    entry = {
        'source': raw.get('source') or raw.get('clip_path'),
        'video_name': video_name,
        'batch_name': raw.get('batch_name'),
        'clip_filename': clip_filename,
        'start_sec': start_sec,
        'end_sec': end_sec,
        'score': raw.get('score'),
        'notes': raw.get('notes') or '',
        'content': content,
    }
    if verbose:
        print(f"[ENTRY] {video_name} {clip_filename} {start_sec}-{end_sec} score={entry['score']} content_len={len(entry['content'] or '')}")
    return entry

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-transcript', action='store_true', help='不尝试读取转写（加速）')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    use_transcript = not args.no_transcript

    os.makedirs(DATA_DIR, exist_ok=True)

    # 基础候选文件
    sources = []
    for p in CANDIDATE_PATHS:
        if os.path.exists(p):
            sources.append(p)
    # 评分文件
    rating_files = iter_rating_files()
    sources.extend(rating_files)

    if args.verbose:
        print(f"发现候选文件 {len(sources)} 个：")
        for s in sources:
            print("  -", s)

    all_entries = []
    for sp in sources:
        objs = load_lines(sp)
        all_entries.extend(objs)
    if args.verbose:
        print(f"读取原始条目: {len(all_entries)}")

    norm_entries = []
    seen_keys: Set[str] = set()
    for obj in all_entries:
        try:
            ne = normalize_entry(obj, use_transcript, args.verbose)
            key = f"{ne.get('video_name')}|{ne.get('clip_filename')}|{ne.get('start_sec')}|{ne.get('end_sec')}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            norm_entries.append(ne)
        except Exception as e:
            if args.verbose:
                print(f"[SKIP] 规格化失败: {e}")
            continue

    # 写出
    with open(TARGET_PATH, 'w', encoding='utf-8') as f:
        for e in norm_entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"✅ 合并完成: {TARGET_PATH}  条目数={len(norm_entries)}  (去重后)")
    if args.verbose:
        by_video = {}
        for e in norm_entries:
            by_video.setdefault(e['video_name'], 0)
            by_video[e['video_name']] += 1
        print("按视频计数:")
        for v, c in sorted(by_video.items(), key=lambda x: -x[1])[:20]:
            print(f"  {v}: {c}")

if __name__ == '__main__':
    main()

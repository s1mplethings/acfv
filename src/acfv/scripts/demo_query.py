from __future__ import annotations

import argparse
from pathlib import Path

from acfv.ragstack import DEFAULT_DB_PATH, DEFAULT_FAISS_INDEX_PATH, DEFAULT_ID_MAP_PATH
from acfv.ragstack.agent.orchestrator import Orchestrator
from acfv.ragstack.preference import parser as preference_parser
from acfv.ragstack.storage import db as storage_db
from acfv.ragstack.storage.models import UserInteraction


def main():
    parser = argparse.ArgumentParser(description="Minimal CLI to test retrieval + preference.")
    parser.add_argument("--user", type=str, default="demo")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--index", type=Path, default=DEFAULT_FAISS_INDEX_PATH)
    parser.add_argument("--id-map", type=Path, default=DEFAULT_ID_MAP_PATH)
    args = parser.parse_args()

    orch = Orchestrator(db_path=args.db, index_path=args.index, id_map_path=args.id_map)
    storage_db.init_db(args.db)

    pref_text = input("写一段你的偏好(支持 +标签 / 不要标签 / 时长>60)：").strip()
    if pref_text:
        orch.set_preference_text(args.user, pref_text)
        print(f"偏好已解析: {preference_parser.parse_preference_text(pref_text)}")

    while True:
        query = input("\n输入查询（空行退出）: ").strip()
        if not query:
            break
        clips, scores, ctx = orch.handle_query(args.user, query, mode="auto")
        print(f"Top {min(5, len(clips))} 结果：")
        for clip, score in list(zip(clips, scores))[:5]:
            print(f"- clip_id={clip.clip_id} score={score:.3f} tags={clip.tags} summary={clip.summary_text}")
        print("\n上下文示例：")
        print(ctx)

        fb = input("反馈 like/dislike <clip_id> (或回车跳过): ").strip()
        if fb:
            try:
                fb_type, clip_id_str = fb.split()
                clip_id = int(clip_id_str)
                interaction = UserInteraction(user_id=args.user, clip_id=clip_id, feedback_type=fb_type, watch_ratio=None)
                storage_db.insert_interaction(args.db, interaction)
                # use zeroed clip; real update needs tags -> fetch from db
                clip_obj = storage_db.get_clips(args.db, [clip_id])[0]
                orch.set_preference_text(args.user, pref_text or "")
                from acfv.ragstack.preference.engine import update_user_preferences_from_interaction
                update_user_preferences_from_interaction(args.db, args.user, clip_obj, fb_type, None)
                print("已记录反馈并更新偏好。")
            except Exception as exc:
                print(f"反馈格式错误: {exc}")


if __name__ == "__main__":
    main()

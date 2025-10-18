"""Agent可调用的应用动作封装。

目的: 让智能体调用现有程序功能(下载/处理/生成索引/获取进度等), 而不是只做评分。
注意: 这些函数在Agent线程中执行, 涉及GUI/线程的操作只提交任务, 不直接阻塞等待。
"""
import os
import json
import weakref
from typing import List, Optional

try:
    from langchain_core.tools import tool
except ImportError:  # 允许未安装时导入失败, 主程序会提示
    def tool(fn):
        return fn

_main_window_ref: Optional[weakref.ReferenceType] = None


def set_main_window(mw):
    """由GUI在初始化Agent前调用, 注册MainWindow引用"""
    global _main_window_ref
    _main_window_ref = weakref.ref(mw)


def _get_mw():
    if _main_window_ref is None:
        return None
    return _main_window_ref()


def _video_root() -> str:
    mw = _get_mw()
    if mw and getattr(mw, 'config_manager', None):
        return mw.config_manager.get("twitch_download_folder", "./data/twitch")
    return "./data/twitch"


@tool
def list_videos() -> str:
    """列出当前可用的视频文件列表。返回JSON字符串: {videos: [...]}"""
    root = _video_root()
    if not os.path.exists(root):
        return json.dumps({"videos": [], "msg": f"目录不存在: {root}"}, ensure_ascii=False)
    videos = [f for f in os.listdir(root) if os.path.isfile(os.path.join(root, f))]
    return json.dumps({"videos": videos}, ensure_ascii=False)


@tool
def start_process_video(path: str) -> str:
    """开始处理指定视频(异步). 参数: path=文件绝对路径或文件名。返回JSON."""
    mw = _get_mw()
    if not mw:
        return json.dumps({"ok": False, "error": "MainWindow未注册"}, ensure_ascii=False)
    # 解析绝对路径
    if not os.path.isabs(path):
        candidate = os.path.join(_video_root(), path)
    else:
        candidate = path
    if not os.path.exists(candidate):
        return json.dumps({"ok": False, "error": f"视频不存在: {candidate}"}, ensure_ascii=False)

    # 通过GUI线程提交任务
    from PyQt5.QtCore import QTimer
    def _run():
        # 设置列表选中方便兼容旧逻辑
        try:
            if getattr(mw, 'local_manager', None) and hasattr(mw.local_manager, 'list_local'):
                lw = mw.local_manager.list_local
                for row in range(lw.count()):
                    if lw.item(row).text() == os.path.basename(candidate):
                        lw.setCurrentRow(row)
                        break
            mw.process_selected_video()
        except Exception as e:  # 仅日志
            import logging
            logging.error(f"start_process_video 触发失败: {e}")
    QTimer.singleShot(0, _run)
    return json.dumps({"ok": True, "submitted": True, "path": candidate}, ensure_ascii=False)


@tool
def generate_indexes() -> str:
    """为已评分切片生成内容索引(异步)。返回JSON。"""
    mw = _get_mw()
    if not mw:
        return json.dumps({"ok": False, "error": "MainWindow未注册"}, ensure_ascii=False)
    from PyQt5.QtCore import QTimer
    def _run():
        try:
            mw.generate_content_indexes_for_rated_clips()
        except Exception as e:
            import logging
            logging.error(f"generate_indexes 执行失败: {e}")
    QTimer.singleShot(0, _run)
    return json.dumps({"ok": True, "submitted": True}, ensure_ascii=False)


@tool
def get_status() -> str:
    """获取当前处理状态/进度。返回JSON: {status, progress}."""
    mw = _get_mw()
    if not mw:
        return json.dumps({"status": "unknown", "progress": 0}, ensure_ascii=False)
    status = ''
    try:
        status = mw.status_label.text()
    except Exception:
        status = 'N/A'
    progress = float(getattr(mw, '_current_progress_percent', 0.0) or 0.0)
    return json.dumps({"status": status, "progress": progress}, ensure_ascii=False)


@tool
def stop_processing() -> str:
    """停止当前处理。返回JSON。"""
    mw = _get_mw()
    if not mw:
        return json.dumps({"ok": False, "error": "MainWindow未注册"}, ensure_ascii=False)
    from PyQt5.QtCore import QTimer
    def _run():
        try:
            mw.stop_processing()
        except Exception as e:
            import logging
            logging.error(f"stop_processing 执行失败: {e}")
    QTimer.singleShot(0, _run)
    return json.dumps({"ok": True, "submitted": True}, ensure_ascii=False)


def get_agent_tools():
    """返回需要注册到Agent的工具列表"""
    # 追加可选的 Twitch 相关工具（若可用）
    tools = [list_videos, start_process_video, generate_indexes, get_status, stop_processing, rate_clip]
    try:
        from langchain_core.tools import tool as _tool  # 确保装饰器存在
    except Exception:
        pass
    try:
        # 动态追加在文件后部定义的函数（避免顶部导入失败）
        tools.extend([list_streamer_vods, download_vods_by_index, download_latest_vods])  # noqa
    except Exception:
        pass
    return tools


@tool
def rate_clip(path: str, rating: int = 3, notes: str = "") -> str:
    """对指定切片进行评分。参数: path=切片文件路径, rating=评分(1-5), notes=备注。返回JSON。"""
    mw = _get_mw()
    if not mw:
        return json.dumps({"ok": False, "error": "MainWindow未注册"}, ensure_ascii=False)
    
    try:
        import os
        # 验证切片文件是否存在
        if not os.path.exists(path):
            return json.dumps({"ok": False, "error": f"切片文件不存在: {path}"}, ensure_ascii=False)
        
        # 验证评分范围
        if not (1 <= rating <= 5):
            return json.dumps({"ok": False, "error": "评分必须在1-5之间"}, ensure_ascii=False)
        
        # 通过GUI线程执行评分操作
        from PyQt5.QtCore import QTimer
        result_container = {"success": False, "error": None}
        
        def _run():
            try:
                # 获取切片管理器
                clips_manager = getattr(mw, 'clips_manager', None)
                if not clips_manager:
                    result_container["error"] = "切片管理器不可用"
                    return
                
                # 构造评分数据
                rating_data = {
                    "rating": rating,
                    "notes": notes,
                    "timestamp": __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # 调用切片管理器的评分方法
                if hasattr(clips_manager, '_save_rating'):
                    clips_manager._save_rating(path, rating_data)
                    result_container["success"] = True
                else:
                    result_container["error"] = "评分功能不可用"
                    
            except Exception as e:
                import logging
                logging.error(f"rate_clip 执行失败: {e}")
                result_container["error"] = str(e)
        
        QTimer.singleShot(0, _run)
        
        # 简单的等待机制（非阻塞）
        import time
        for _ in range(10):  # 最多等待1秒
            time.sleep(0.1)
            if result_container["success"] or result_container["error"]:
                break
        
        if result_container["success"]:
            return json.dumps({
                "ok": True, 
                "rated": True, 
                "path": path, 
                "rating": rating,
                "notes": notes
            }, ensure_ascii=False)
        else:
            error_msg = result_container["error"] or "评分操作超时"
            return json.dumps({"ok": False, "error": error_msg}, ensure_ascii=False)
            
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


# ================== Twitch 相关扩展工具 ==================
@tool
def list_streamer_vods(streamer: str, limit: int = 10) -> str:
    """列出某个主播最新的 VOD (不下载)。参数: streamer=主播登录名, limit=数量(默认10, <=20)。返回JSON: {vods:[{id,title,created_at}]}."""
    mw = _get_mw()
    if not mw:
        return json.dumps({"ok": False, "error": "MainWindow未注册"}, ensure_ascii=False)
    try:
        tab = getattr(mw, 'twitch_tab', None)
        if not tab:
            return json.dumps({"ok": False, "error": "Twitch标签不可用"}, ensure_ascii=False)
        # 需要 client_id / token
        cid = mw.config_manager.get("twitch_client_id")
        tok = mw.config_manager.get("twitch_oauth_token")
        if not cid or not tok:
            return json.dumps({"ok": False, "error": "缺少 Twitch client_id 或 oauth_token"}, ensure_ascii=False)
        downloader = tab.downloader
        vods = downloader.fetch_vods(cid, tok, streamer)
        # 过滤只取一个主播的
        filtered = [
            {"id": v.get("id"), "title": v.get("title"), "created_at": v.get("created_at")}
            for v in vods if v.get("channel") == streamer
        ][: max(1, min(int(limit), 20))]
        # 保存在 tab 供后续按序号下载
        tab._last_list_vods_cache = filtered  # 临时缓存
        return json.dumps({"ok": True, "vods": filtered}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@tool
def download_vods_by_index(indexes: str, folder: str = "") -> str:
    """下载最近一次 list_streamer_vods 结果里的指定序号 VOD。参数: indexes=逗号分隔下标(从1开始), folder=下载目录(可省, 默认为配置)。返回JSON。"""
    mw = _get_mw()
    if not mw:
        return json.dumps({"ok": False, "error": "MainWindow未注册"}, ensure_ascii=False)
    try:
        tab = getattr(mw, 'twitch_tab', None)
        if not tab or not getattr(tab, 'downloader', None):
            return json.dumps({"ok": False, "error": "Twitch标签不可用"}, ensure_ascii=False)
        vod_cache = getattr(tab, '_last_list_vods_cache', None)
        if not vod_cache:
            return json.dumps({"ok": False, "error": "没有可下载列表，请先调用 list_streamer_vods"}, ensure_ascii=False)
        # 解析序号
        idx_list = []
        for part in indexes.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                val = int(part)
                if val >= 1 and val <= len(vod_cache):
                    idx_list.append(val - 1)
            except Exception:
                continue
        if not idx_list:
            return json.dumps({"ok": False, "error": "序号无效"}, ensure_ascii=False)
        folder = folder or mw.config_manager.get("replay_download_folder") or mw.config_manager.get("twitch_download_folder", "./data/twitch")
        if not os.path.isdir(folder):
            return json.dumps({"ok": False, "error": f"目录无效: {folder}"}, ensure_ascii=False)

        # 异步提交下载线程 (使用 GUI 逻辑 download_vod 的简化复制)
        from PyQt5.QtCore import QTimer
        def _run():
            try:
                # 构造 vod 对象列表 (需要 id/title/created_at)
                vods = []
                for i in idx_list:
                    vods.append({
                        'id': vod_cache[i]['id'],
                        'title': vod_cache[i]['title'],
                        'created_at': vod_cache[i]['created_at'],
                        'channel': ''  # 非必须
                    })
                # 启动下载线程
                from acfv.processing.twitch_downloader import TwitchDownloadWorker
                tab.download_worker = TwitchDownloadWorker(
                    tab.downloader, "download_vods", vods, folder, parent=mw
                )
                tab.download_worker.start()
            except Exception as e:  # 日志即可
                import logging
                logging.error(f"download_vods_by_index 执行失败: {e}")
        QTimer.singleShot(0, _run)
        return json.dumps({"ok": True, "submitted": True, "count": len(idx_list)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@tool
def download_latest_vods(streamer: str, count: int = 1) -> str:
    """直接获取并下载某主播最新 count 个 VOD。参数: streamer, count(<=5)。返回JSON。"""
    mw = _get_mw()
    if not mw:
        return json.dumps({"ok": False, "error": "MainWindow未注册"}, ensure_ascii=False)
    try:
        tab = getattr(mw, 'twitch_tab', None)
        if not tab:
            return json.dumps({"ok": False, "error": "Twitch标签不可用"}, ensure_ascii=False)
        cid = mw.config_manager.get("twitch_client_id")
        tok = mw.config_manager.get("twitch_oauth_token")
        if not cid or not tok:
            return json.dumps({"ok": False, "error": "缺少 Twitch client_id 或 oauth_token"}, ensure_ascii=False)
        downloader = tab.downloader
        vods = downloader.fetch_vods(cid, tok, streamer)
        target = [v for v in vods if v.get('channel') == streamer][: max(1, min(int(count), 5))]
        folder = mw.config_manager.get("replay_download_folder") or mw.config_manager.get("twitch_download_folder", "./data/twitch")
        if not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        from PyQt5.QtCore import QTimer
        def _run():
            try:
                from acfv.processing.twitch_downloader import TwitchDownloadWorker
                tab.download_worker = TwitchDownloadWorker(
                    tab.downloader, "download_vods", target, folder, parent=mw
                )
                tab.download_worker.start()
            except Exception as e:
                import logging
                logging.error(f"download_latest_vods 启动失败: {e}")
        QTimer.singleShot(0, _run)
        return json.dumps({"ok": True, "submitted": True, "count": len(target)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

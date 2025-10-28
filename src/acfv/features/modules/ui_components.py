# ui_components.py - UI组件模块

import os
import sys
import json
import logging
import threading
import subprocess
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from datetime import datetime
# 移除RAG依赖，切片页不再进行RAG处理

try:
    from PyQt5.QtWidgets import *
    from PyQt5.QtCore import *
    from PyQt5.QtGui import *
    PYTQT5_AVAILABLE = True
except ImportError:
    PYTQT5_AVAILABLE = False
    print("PyQt5 模块未安装，将跳过相关功能")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("OpenCV 模块未安装，将使用FFmpeg替代")

# 安全导入numpy，处理兼容性问题
try:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import numpy
    NUMPY_AVAILABLE = True
except Exception as e:
    NUMPY_AVAILABLE = False
    print(f"Numpy模块导入警告: {e}")
    if 'dtype size changed' in str(e):
        print("这是numpy版本兼容性问题，但不影响基本功能")

class SimpleThumbnailManager:
    """简化的缩略图管理器 - 只保留基本逻辑"""
    
    def __init__(self, thumbnail_dir="thumbnails"):
        self.thumbnail_dir = os.path.abspath(thumbnail_dir)
        # 自动创建缩略图目录
        try:
            os.makedirs(self.thumbnail_dir, exist_ok=True)
            logging.info(f"缩略图目录已创建: {self.thumbnail_dir}")
        except Exception as e:
            logging.error(f"创建缩略图目录失败: {e}")
            # 回退到当前目录下的thumbnails
            self.thumbnail_dir = os.path.abspath("./thumbnails")
            os.makedirs(self.thumbnail_dir, exist_ok=True)
    
    def get_thumbnail_path(self, video_path):
        """根据视频路径生成缩略图路径"""
        # 使用原文件名（不包含扩展名）作为缩略图文件名
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        # 清理文件名中的非法字符
        safe_name = "".join(c for c in video_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        # 如果文件名太长，截取前100个字符
        if len(safe_name) > 100:
            safe_name = safe_name[:100]
        # 如果清理后文件名为空，使用哈希
        if not safe_name.strip():
            import hashlib
            safe_name = hashlib.md5(video_path.encode('utf-8')).hexdigest()[:16]
        return os.path.join(self.thumbnail_dir, f"{safe_name}.jpg")
    
    def has_thumbnail(self, video_path):
        """检查视频是否已有缩略图"""
        thumbnail_path = self.get_thumbnail_path(video_path)
        return os.path.exists(thumbnail_path)
    
    def get_thumbnail(self, video_path):
        """获取缩略图（返回QImage）"""
        if not self.has_thumbnail(video_path):
            return None
        
        try:
            thumbnail_path = self.get_thumbnail_path(video_path)
            image = QImage(thumbnail_path)
            return image if not image.isNull() else None
        except Exception as e:
            logging.error(f"读取缩略图失败: {e}")
            return None
    
    def save_thumbnail(self, video_path, image):
        """保存缩略图"""
        try:
            thumbnail_path = self.get_thumbnail_path(video_path)
            if isinstance(image, QPixmap):
                image = image.toImage()
            
            if isinstance(image, QImage):
                return image.save(thumbnail_path, "JPEG", quality=85)
        except Exception as e:
            logging.error(f"保存缩略图失败: {e}")
        return False
    
    def remove_thumbnail(self, video_path):
        """删除缩略图"""
        try:
            thumbnail_path = self.get_thumbnail_path(video_path)
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
                return True
        except Exception as e:
            logging.error(f"删除缩略图失败: {e}")
        return False
    
    def cleanup_orphaned_thumbnails(self, video_paths):
        """清理孤儿缩略图（对应的视频文件已不存在）"""
        try:
            # 获取所有缩略图文件
            if not os.path.exists(self.thumbnail_dir):
                return
            
            # 生成所有有效视频的缩略图路径集合
            valid_thumbnail_paths = set()
            for video_path in video_paths:
                if os.path.exists(video_path):
                    valid_thumbnail_paths.add(self.get_thumbnail_path(video_path))
            
            # 删除无效的缩略图
            for filename in os.listdir(self.thumbnail_dir):
                if filename.endswith('.jpg'):
                    thumbnail_path = os.path.join(self.thumbnail_dir, filename)
                    if thumbnail_path not in valid_thumbnail_paths:
                        try:
                            os.remove(thumbnail_path)
                            logging.info(f"删除孤儿缩略图: {filename}")
                        except Exception as e:
                            logging.error(f"删除孤儿缩略图失败 {filename}: {e}")
        except Exception as e:
            logging.error(f"清理孤儿缩略图失败: {e}")

# 全局缩略图管理器实例 - 使用专门的缩略图文件夹
thumbnail_manager = SimpleThumbnailManager("thumbnails")

class Worker(QThread):
    """通用工作线程"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress_update = pyqtSignal(str)
    progress_percent = pyqtSignal(int)

    def __init__(self, func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._should_stop = False

    def run(self):
        try:
            # 检查线程是否应该停止
            if self._should_stop:
                return
                
            import inspect
            sig = inspect.signature(self.func)
            if 'progress_callback' in sig.parameters:
                self.kwargs['progress_callback'] = self.emit_progress
            res = self.func(*self.args, **self.kwargs)
            
            # 再次检查是否应该停止
            if not self._should_stop:
                self.finished.emit(res)
        except Exception as e:
            if not self._should_stop:
                self.error.emit(str(e))

    def emit_progress(self, stage, current, total, message=""):
        if self._should_stop:
            return
            
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_percent.emit(percent)
        progress_text = f"[{stage}] {current}/{total} - {message}"
        self.progress_update.emit(progress_text)
    
    def stop(self):
        """停止线程"""
        self._should_stop = True
        self.quit()
        if not self.wait(2000):  # 等待2秒
            self.terminate()
            self.wait(1000)


class SimpleThumbnailLoader(QThread):
    """简化的缩略图加载器"""
    
    thumbnail_loaded = pyqtSignal(int, QImage, str)
    progress_update = pyqtSignal(str)
    batch_completed = pyqtSignal()

    def __init__(self, video_files, parent=None, max_workers=4):
        super().__init__(parent)
        self.video_files = video_files
        self.max_workers = max_workers  # 增加默认线程数以提升速度
        self._should_stop = False

    def extract_thumbnail(self, filepath):
        """提取缩略图（只使用OpenCV，更稳定）"""
        # 只使用OpenCV方法
        if CV2_AVAILABLE:
            image = self.extract_thumbnail_opencv(filepath)
            if image is not None:
                return image
        
        # 如果OpenCV不可用或失败，返回None
        return None

    def is_valid_thumbnail(self, image):
        """检查缩略图是否有效（不是全黑、全白或噪点图）"""
        if image.isNull() or image.width() == 0 or image.height() == 0:
            return False
        
        try:
            # 转换为灰度图并计算统计信息
            gray_image = image.convertToFormat(QImage.Format_Grayscale8)
            width, height = gray_image.width(), gray_image.height()
            
            # 采样检查（只检查部分像素以提升性能）
            sample_points = min(1000, width * height // 10)  # 采样10%的像素
            pixel_values = []
            
            for i in range(0, sample_points):
                x = (i * 7) % width  # 使用质数步长避免规律采样
                y = (i * 11) % height
                pixel = gray_image.pixel(x, y)
                # QImage.pixel返回RGB值，取R通道（因为是灰度图，RGB相等）
                gray_value = (pixel >> 16) & 0xFF
                pixel_values.append(gray_value)
            
            if not pixel_values:
                return False
                
            # 计算统计信息
            import statistics
            mean_val = statistics.mean(pixel_values)
            
            # 检查是否全黑或全白
            if mean_val < 5 or mean_val > 250:
                logging.debug("检测到全黑或全白缩略图")
                return False
            
            # 检查方差（太小说明图像单调，可能是损坏的）
            try:
                variance = statistics.variance(pixel_values)
                if variance < 10:  # 方差太小，图像过于单调
                    logging.debug("检测到单调缩略图（方差过小）")
                    return False
            except statistics.StatisticsError:
                return False
                
            return True
            
        except Exception as e:
            logging.debug(f"缩略图质量检查出错: {e}")
            return True  # 出错时默认认为有效
    
    def extract_thumbnail_opencv(self, filepath):
        """使用OpenCV提取中间帧 - 简化稳定版本"""
        try:
            cap = cv2.VideoCapture(filepath)
            if not cap.isOpened():
                return None
                
            # 获取视频信息
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 计算中间帧位置
            if total_frames > 100:  # 有足够帧数的视频
                target_frame = total_frames // 2  # 真正的中间帧
            elif total_frames > 30:  # 短视频使用1/3处
                target_frame = total_frames // 3
            else:  # 很短的视频使用第10帧
                target_frame = min(10, total_frames - 1) if total_frames > 0 else 0
            
            # 跳转到目标帧
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            cap.release()
            
            if ret and frame is not None:
                # 检查帧是否有效
                if frame.shape[0] > 0 and frame.shape[1] > 0:
                    # 缩放到目标尺寸
                    frame = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_LINEAR)
                    h, w, _ = frame.shape
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
                
        except Exception as e:
            logging.debug(f"OpenCV提取缩略图失败 {os.path.basename(filepath)}: {e}")
        
        return None

    def create_placeholder(self, text="NO THUMB"):
        """创建占位图"""
        image = QImage(320, 180, QImage.Format_RGB32)
        
        # 根据文本类型使用不同颜色
        if "ERROR" in text or "损坏" in text or "DAMAGED" in text:
            image.fill(QColor(120, 60, 60))  # 深红色背景表示错误
            text_color = QColor(255, 200, 200)  # 浅红色文字
        elif "NO THUMB" in text:
            image.fill(Qt.darkGray)  # 深灰色背景
            text_color = Qt.white
        else:
            image.fill(Qt.darkGray)
            text_color = Qt.white
            
        painter = QPainter(image)
        painter.setPen(text_color)
        font = QFont("Arial", 12, QFont.Bold)
        painter.setFont(font)
        painter.drawText(image.rect(), Qt.AlignCenter, text)
        painter.end()
        return image

    def run(self):
        """加载所有缩略图 - 简化版本，只使用OpenCV"""
        total_files = len(self.video_files)
        
        for i, (filename, filepath) in enumerate(self.video_files):
            if self._should_stop:
                break
            
            try:
                # 检查是否已有缓存缩略图
                cached_image = None
                if thumbnail_manager.has_thumbnail(filepath):
                    try:
                        cached_image = thumbnail_manager.get_thumbnail(filepath)
                    except Exception as e:
                        logging.debug(f"读取缓存缩略图失败 {filename}: {e}")
                        
                if cached_image and not cached_image.isNull():
                    self.thumbnail_loaded.emit(i, cached_image, filename)
                    self.progress_update.emit(f"缓存 {i+1}/{total_files}: {filename}")
                    continue
                
                # 只使用OpenCV生成新缩略图
                image = None
                if CV2_AVAILABLE:
                    try:
                        image = self.extract_thumbnail_opencv(filepath)
                    except Exception as e:
                        logging.debug(f"OpenCV提取缩略图失败 {filename}: {e}")
                
                if image is None or image.isNull():
                    # 创建占位图
                    try:
                        image = self.create_placeholder("NO THUMB")
                    except Exception as e:
                        logging.error(f"创建占位图失败: {e}")
                        continue
                else:
                    # 保存缩略图
                    try:
                        thumbnail_manager.save_thumbnail(filepath, image)
                    except Exception as e:
                        logging.debug(f"保存缩略图失败: {e}")
                
                self.thumbnail_loaded.emit(i, image, filename)
                self.progress_update.emit(f"生成 {i+1}/{total_files}: {filename}")
                
            except Exception as e:
                logging.error(f"处理缩略图失败 {filename}: {e}")
                # 发送错误占位图
                try:
                    error_image = self.create_placeholder("ERROR")
                    self.thumbnail_loaded.emit(i, error_image, filename)
                except Exception as e2:
                    logging.error(f"创建错误占位图也失败: {e2}")
        
        if not self._should_stop:
            try:
                self.batch_completed.emit()
            except Exception as e:
                logging.error(f"发送批量完成信号失败: {e}")
                logging.error(f"处理缩略图失败 {filename}: {e}")
                # 发送错误占位图
                try:
                    error_image = self.create_placeholder("ERROR")
                    self.thumbnail_loaded.emit(i, error_image, filename)
                except Exception as e2:
                    logging.error(f"创建错误占位图也失败: {e2}")
        
        if not self._should_stop:
            try:
                self.batch_completed.emit()
            except Exception as e:
                logging.error(f"发送批量完成信号失败: {e}")

    def stop(self):
        """停止线程"""
        self._should_stop = True
        self.quit()
        if not self.wait(2000):
            self.terminate()
            self.wait(1000)


class OptimizedClipThumbnailLoader(QThread):
    """优化的切片缩略图加载线程 - 简化为只使用OpenCV"""
    thumbnail_loaded = pyqtSignal(dict, QImage)
    progress_update = pyqtSignal(str)
    batch_completed = pyqtSignal()

    def __init__(self, clips, parent=None, max_workers=2, batch_size=8):
        super().__init__(parent)
        self.clips = clips
        self.max_workers = max_workers
        self.batch_size = batch_size
        self._should_stop = False

    def extract_thumbnail_opencv(self, filepath):
        """使用OpenCV提取中间帧 - 简化版本"""
        try:
            cap = cv2.VideoCapture(filepath)
            if not cap.isOpened():
                return None
                
            # 获取视频信息
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 计算中间帧位置
            if total_frames > 100:
                target_frame = total_frames // 2  # 真正的中间帧
            elif total_frames > 30:
                target_frame = total_frames // 3
            else:
                target_frame = min(10, total_frames - 1) if total_frames > 0 else 0
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            cap.release()
            
            if ret and frame is not None:
                if frame.shape[0] > 0 and frame.shape[1] > 0:
                    frame = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_LINEAR)
                    h, w, _ = frame.shape
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
                
        except Exception as e:
            logging.debug(f"OpenCV提取切片缩略图失败 {os.path.basename(filepath)}: {e}")
        
        return None

    def extract_thumbnail_opencv(self, filepath, use_middle_frame=True, use_random_middle=False):
        """使用OpenCV提取缩略图 - 简化版本"""
        if not CV2_AVAILABLE:
            return None
        
        try:
            cap = cv2.VideoCapture(filepath)
            if not cap.isOpened():
                return None
                
            # 获取视频信息
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 简化的中间帧计算
            if total_frames > 100:
                target_frame = total_frames // 2  # 真正的中间帧
            elif total_frames > 30:
                target_frame = total_frames // 3
            else:
                target_frame = min(10, total_frames - 1) if total_frames > 0 else 0
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            cap.release()
            
            if ret and frame is not None:
                frame = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_LINEAR)
                h, w, _ = frame.shape
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
                
        except Exception as e:
            logging.debug(f"OpenCV提取缩略图失败: {os.path.basename(filepath)}, 错误: {e}")
        
        return None

    def load_single_clip_thumbnail(self, clip):
        """加载单个切片缩略图 - 简化版本，只使用OpenCV"""
        if self._should_stop:
            return None
        
        try:
            clip_path = clip["path"]
            filename = clip.get('file', os.path.basename(clip_path))
            logging.debug(f"[ClipThumb] 开始加载: {filename}")
            
            # 首先检查缓存
            cached_image = thumbnail_manager.get_thumbnail(clip_path)
            if cached_image:
                logging.debug(f"[ClipThumb] 使用缓存: {filename}")
                return clip, cached_image
            
            # 只使用OpenCV提取缩略图
            image = None
            if CV2_AVAILABLE:
                image = self.extract_thumbnail_opencv(clip_path)
            
            # 如果失败了，返回占位符
            if image is None:
                image = QImage(320, 180, QImage.Format_RGB32)
                image.fill(Qt.darkGray)
                painter = QPainter(image)
                painter.setPen(Qt.white)
                font = QFont("Arial", 12)
                painter.setFont(font)
                painter.drawText(image.rect(), Qt.AlignCenter, "NO\nTHUMB")
                painter.end()
                logging.warning(f"[ClipThumb] 生成占位: {filename}")
            
            # 保存到缓存
            thumbnail_manager.save_thumbnail(clip_path, image)
            
            return clip, image
            
        except Exception as e:
            logging.error(f"加载切片缩略图失败: {clip.get('path', '')}, 错误: {e}")
            img = QImage(320, 180, QImage.Format_RGB32)
            img.fill(Qt.black)
            painter = QPainter(img)
            painter.setPen(Qt.white)
            font = QFont("Arial", 12)
            painter.setFont(font)
            painter.drawText(img.rect(), Qt.AlignCenter, "ERR")
            painter.end()
            return clip, img

    def run(self):
        """并行加载切片缩略图 - 线程安全版本"""
        try:
            total_clips = len(self.clips)
            if total_clips == 0:
                return
                
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # 提交所有任务 - 和直播回放一样
                future_to_clip = {}
                for clip in self.clips:
                    if self._should_stop:
                        break
                    
                    # 确保clip是有效的字典
                    if not isinstance(clip, dict) or not clip.get('path'):
                        continue
                        
                    future = executor.submit(self.load_single_clip_thumbnail, clip)
                    future_to_clip[future] = clip
                
                # 收集结果 - 和直播回放一样
                completed_count = 0
                for future in as_completed(future_to_clip):
                    if self._should_stop:
                        break
                    
                    try:
                        result = future.result(timeout=30)
                        if result and len(result) == 2:
                            clip_res, image = result
                            # 验证结果有效性
                            if isinstance(clip_res, dict) and hasattr(image, 'isNull') and not image.isNull():
                                self.thumbnail_loaded.emit(clip_res, image)
                                progress_name = clip_res.get('file', '')
                            else:
                                clip_res = future_to_clip.get(future, {})
                                progress_name = clip_res.get('file', '') if isinstance(clip_res, dict) else ''
                        else:
                            clip_res = future_to_clip.get(future, {})
                            progress_name = clip_res.get('file', '') if isinstance(clip_res, dict) else ''
                            
                        completed_count += 1
                        if progress_name:
                            self.progress_update.emit(
                                f"加载切片缩略图 {completed_count}/{total_clips}: {progress_name}"
                            )
                        else:
                            self.progress_update.emit(
                                f"加载切片缩略图 {completed_count}/{total_clips}"
                            )
                        
                    except Exception as e:
                        logging.error(f"切片缩略图加载任务异常: {e}")
                        completed_count += 1
                        # 继续处理其他任务，不中断整个流程
                        
        except Exception as e:
            logging.error(f"缩略图加载线程异常: {e}")
            # 确保线程能够正常结束，不崩溃
        
        if not self._should_stop:
            self.batch_completed.emit()

    def stop(self):
        """停止线程"""
        self._should_stop = True
        self.quit()
        if not self.wait(2000):
            self.terminate()
            self.wait(1000)


class SimpleClipThumbnailLoader(QThread):
    """简化的切片缩略图加载器"""
    
    thumbnail_loaded = pyqtSignal(dict, QImage)
    progress_update = pyqtSignal(str)
    batch_completed = pyqtSignal()

    def __init__(self, clips, parent=None):
        super().__init__(parent)
        self.clips = clips
        self._should_stop = False

    def extract_thumbnail(self, filepath):
        """提取缩略图（只使用OpenCV）"""
        # 只使用OpenCV方法
        if CV2_AVAILABLE:
            image = self.extract_thumbnail_opencv(filepath)
            if image is not None:
                return image
        
        return None

    def extract_thumbnail_opencv(self, filepath):
        """使用OpenCV提取中间帧 - 优化版本，重点使用中间帧"""
        try:
            cap = cv2.VideoCapture(filepath)
            if not cap.isOpened():
                return None
            
            # 获取视频信息来计算真正的中间帧
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            if total_frames > 0:
                # 使用真正的中间帧
                target_frame = total_frames // 2
            else:
                # 如果无法获取帧数，估算中间位置
                fps = cap.get(cv2.CAP_PROP_FPS) or 25
                target_frame = int(15 * fps)  # 估算15秒处作为中间点
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            cap.release()
            
            if ret and frame is not None:
                # 直接缩放
                frame = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_LINEAR)
                h, w, _ = frame.shape
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
                
        except Exception as e:
            logging.debug(f"OpenCV提取切片缩略图失败: {e}")
        return None

    def create_placeholder(self, text="NO THUMB"):
        """创建占位图"""
        image = QImage(320, 180, QImage.Format_RGB32)
        image.fill(Qt.darkGray)
        painter = QPainter(image)
        painter.setPen(Qt.white)
        font = QFont("Arial", 12)
        painter.setFont(font)
        painter.drawText(image.rect(), Qt.AlignCenter, text)
        painter.end()
        return image

    def run(self):
        """加载所有切片缩略图"""
        total_clips = len(self.clips)
        
        for i, clip in enumerate(self.clips):
            if self._should_stop:
                break
            
            try:
                if not isinstance(clip, dict) or not clip.get('path'):
                    continue
                
                clip_path = clip["path"]
                filename = clip.get('file', os.path.basename(clip_path))
                
                # 检查是否已有缩略图
                cached_image = thumbnail_manager.get_thumbnail(clip_path)
                if cached_image:
                    self.thumbnail_loaded.emit(clip, cached_image)
                    self.progress_update.emit(f"加载切片缩略图 {i+1}/{total_clips}: {filename}")
                    continue
                
                # 生成新缩略图
                image = self.extract_thumbnail(clip_path)
                
                if image is None:
                    image = self.create_placeholder()
                else:
                    # 保存缩略图
                    thumbnail_manager.save_thumbnail(clip_path, image)
                
                self.thumbnail_loaded.emit(clip, image)
                self.progress_update.emit(f"加载切片缩略图 {i+1}/{total_clips}: {filename}")
                
            except Exception as e:
                logging.error(f"处理切片缩略图失败: {e}")
                error_image = self.create_placeholder("ERROR")
                self.thumbnail_loaded.emit(clip, error_image)
        
        if not self._should_stop:
            self.batch_completed.emit()

    def stop(self):
        """停止线程"""
        self._should_stop = True
        self.quit()
        if not self.wait(2000):
            self.terminate()
            self.wait(1000)


class SettingsDialog(QDialog):
    """设置对话框"""
    
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.monitor_runtime = None
        self.monitor_config = None
        self.monitor_cfg_path = None
        try:
            from acfv.runtime import stream_monitor as monitor_runtime
            self.monitor_runtime = monitor_runtime
            self.monitor_config, self.monitor_cfg_path, _ = monitor_runtime.load_stream_monitor_config(None)
        except Exception as exc:
            logging.warning(f"直播监控配置不可用：{exc}")
        self.setWindowTitle("程序设置")
        self.setMinimumWidth(700)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 创建标签页
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # 基本设置标签页
        self.init_basic_tab(tabs)
        
        # 权重设置标签页
        self.init_weights_tab(tabs)

        # 直播监控设置
        self.init_monitor_tab(tabs)
        
        # 底部按钮
        self.init_buttons(layout)
    
    def init_basic_tab(self, tabs):
        tab_basic = QWidget()
        form_basic = QFormLayout(tab_basic)
        
        # 输出切片数量
        self.edit_max_clips = QLineEdit(str(self.config_manager.get("MAX_CLIP_COUNT")))
        form_basic.addRow("输出切片数量:", self.edit_max_clips)
        
        # 切片基础目录
        self.edit_clips_base_dir = QLineEdit(self.config_manager.get("CLIPS_BASE_DIR"))
        clips_dir_layout = QHBoxLayout()
        clips_dir_layout.addWidget(self.edit_clips_base_dir)
        clips_dir_btn = QPushButton("选择")
        clips_dir_btn.clicked.connect(self.choose_clips_dir)
        clips_dir_layout.addWidget(clips_dir_btn)
        form_basic.addRow("切片基础目录:", clips_dir_layout)
        
        # 回放下载目录
        self.edit_replay_download_dir = QLineEdit(self.config_manager.get("replay_download_folder", "./data/twitch"))
        replay_dir_layout = QHBoxLayout()
        replay_dir_layout.addWidget(self.edit_replay_download_dir)
        replay_dir_btn = QPushButton("选择")
        replay_dir_btn.clicked.connect(self.choose_replay_dir)
        replay_dir_layout.addWidget(replay_dir_btn)
        form_basic.addRow("回放下载目录:", replay_dir_layout)
        
        # Whisper模型
        self.edit_whisper = QLineEdit(self.config_manager.get("WHISPER_MODEL"))
        form_basic.addRow("Whisper 模型:", self.edit_whisper)

        # HuggingFace Token（隐藏显示切换）
        hf_layout = QHBoxLayout()
        hf_token_value = self.config_manager.get("HUGGINGFACE_TOKEN", "") or ""
        self.edit_hf_token = QLineEdit(hf_token_value)
        self.edit_hf_token.setPlaceholderText("hf_xxx...")
        self.edit_hf_token.setEchoMode(QLineEdit.Password)
        self.edit_hf_token.setClearButtonEnabled(True)
        self.edit_hf_token.setToolTip("在此填写 HuggingFace 访问令牌，用于需要 HuggingFace Hub 的功能。")
        self.btn_toggle_hf = QPushButton("显示")
        self.btn_toggle_hf.setCheckable(True)
        self.btn_toggle_hf.setFixedWidth(60)
        self.btn_toggle_hf.setToolTip("点击临时显示或隐藏令牌内容")
        self.btn_toggle_hf.toggled.connect(self.toggle_hf_visibility)
        hf_layout.addWidget(self.edit_hf_token)
        hf_layout.addWidget(self.btn_toggle_hf)
        form_basic.addRow("HuggingFace Token:", hf_layout)
        
        # 文本情绪模型路径
        self.edit_local_emotion = QLineEdit(self.config_manager.get("LOCAL_EMOTION_MODEL_PATH"))
        form_basic.addRow("文本情绪模型路径:", self.edit_local_emotion)
        
        # 视频情绪模型文件
        self.edit_video_emotion = QLineEdit(self.config_manager.get("VIDEO_EMOTION_MODEL_PATH"))
        form_basic.addRow("视频情绪模型文件:", self.edit_video_emotion)
        
        # 视频情绪分析段长度
        self.edit_emotion_segment_length = QLineEdit(str(self.config_manager.get("VIDEO_EMOTION_SEGMENT_LENGTH")))
        form_basic.addRow("视频情绪分析段长度(秒):", self.edit_emotion_segment_length)
        
        # LLM设备
        self.edit_llm_device = QLineEdit(str(self.config_manager.get("LLM_DEVICE")))
        form_basic.addRow("LLM_DEVICE (GPU=0/CPU=-1):", self.edit_llm_device)
        
        # 检查点设置
        self.edit_checkpoint_interval = QLineEdit(str(self.config_manager.get("CHECKPOINT_INTERVAL", 10)))
        form_basic.addRow("检查点保存间隔:", self.edit_checkpoint_interval)
        
        self.edit_max_workers = QLineEdit(str(self.config_manager.get("MAX_WORKERS", 4)))
        form_basic.addRow("并行工作线程数:", self.edit_max_workers)
        
        self.edit_gpu_device = QLineEdit(str(self.config_manager.get("GPU_DEVICE", "cuda:0")))
        form_basic.addRow("GPU设备:", self.edit_gpu_device)
        
        # 切片配置
        self.edit_min_clip_duration = QLineEdit(str(self.config_manager.get("MIN_CLIP_DURATION", 60.0)))
        form_basic.addRow("最小切片时长(秒):", self.edit_min_clip_duration)
        
        self.edit_clip_context_extend = QLineEdit(str(self.config_manager.get("CLIP_CONTEXT_EXTEND", 15.0)))
        form_basic.addRow("前后文扩展时长(秒):", self.edit_clip_context_extend)
        
        self.edit_clip_merge_threshold = QLineEdit(str(self.config_manager.get("CLIP_MERGE_THRESHOLD", 10.0)))
        form_basic.addRow("切片合并阈值(秒):", self.edit_clip_merge_threshold)
        
        # 语义合并配置
        self.edit_semantic_similarity_threshold = QLineEdit(str(self.config_manager.get("SEMANTIC_SIMILARITY_THRESHOLD", 0.75)))
        form_basic.addRow("语义相似度阈值(0-1):", self.edit_semantic_similarity_threshold)
        
        self.edit_semantic_max_time_gap = QLineEdit(str(self.config_manager.get("SEMANTIC_MAX_TIME_GAP", 60.0)))
        form_basic.addRow("语义合并最大间隔(秒):", self.edit_semantic_max_time_gap)
        

        
        # 开关选项
        self.checkbox_enable_gpu = QCheckBox()
        self.checkbox_enable_gpu.setChecked(self.config_manager.get("ENABLE_GPU_ACCELERATION", True))
        form_basic.addRow("启用GPU加速:", self.checkbox_enable_gpu)
        
        self.checkbox_enable_video_emotion = QCheckBox()
        self.checkbox_enable_video_emotion.setChecked(self.config_manager.get("ENABLE_VIDEO_EMOTION"))
        self.checkbox_enable_video_emotion.toggled.connect(self.on_video_emotion_toggled)
        form_basic.addRow("启用视频情绪分析:", self.checkbox_enable_video_emotion)
        
        self.checkbox_merge_nearby_clips = QCheckBox()
        self.checkbox_merge_nearby_clips.setChecked(self.config_manager.get("MERGE_NEARBY_CLIPS", True))
        form_basic.addRow("合并相邻切片:", self.checkbox_merge_nearby_clips)
        
        self.checkbox_enable_semantic_merge = QCheckBox()
        self.checkbox_enable_semantic_merge.setChecked(self.config_manager.get("ENABLE_SEMANTIC_MERGE", True))
        form_basic.addRow("启用语义合并:", self.checkbox_enable_semantic_merge)
        
        # 检查点管理
        self.init_checkpoint_management(form_basic)
        
        tabs.addTab(tab_basic, "基本设置")
    
    def init_weights_tab(self, tabs):
        tab_weights = QWidget()
        form_weights = QFormLayout(tab_weights)
        
        self.edit_chat_density = QLineEdit(str(self.config_manager.get("CHAT_DENSITY_WEIGHT")))
        form_weights.addRow("Chat 密度权重:", self.edit_chat_density)
        
        self.edit_chat_sentiment = QLineEdit(str(self.config_manager.get("CHAT_SENTIMENT_WEIGHT")))
        form_weights.addRow("Chat 情绪权重:", self.edit_chat_sentiment)
        
        self.edit_video_emotion_weight = QLineEdit(str(self.config_manager.get("VIDEO_EMOTION_WEIGHT")))
        form_weights.addRow("视频情绪权重:", self.edit_video_emotion_weight)
        
        self.edit_interest_threshold = QLineEdit(str(self.config_manager.get("INTEREST_SCORE_THRESHOLD")))
        form_weights.addRow("兴趣分数阈值:", self.edit_interest_threshold)
        
        tabs.addTab(tab_weights, "权重设置")

    def init_monitor_tab(self, tabs):
        tab_monitor = QWidget()
        form = QFormLayout(tab_monitor)

        if not self.monitor_runtime or not self.monitor_config:
            label = QLabel("当前环境未安装 StreamGet 或直播监控模块，无法编辑相关设置。")
            label.setWordWrap(True)
            form.addRow(label)
            tabs.addTab(tab_monitor, "监控")
            return

        self.monitor_ffmpeg_edit = QLineEdit(self.monitor_config.ffmpeg_path)
        form.addRow("ffmpeg 路径:", self.monitor_ffmpeg_edit)

        self.monitor_quality_combo = QComboBox()
        self.monitor_quality_combo.addItems(["OD", "UHD", "HD", "SD", "LD"])
        idx = self.monitor_quality_combo.findText(self.monitor_config.default_quality)
        if idx >= 0:
            self.monitor_quality_combo.setCurrentIndex(idx)
        form.addRow("默认清晰度:", self.monitor_quality_combo)

        self.monitor_poll_spin = QSpinBox()
        self.monitor_poll_spin.setRange(5, 3600)
        self.monitor_poll_spin.setValue(int(self.monitor_config.default_poll_interval))
        form.addRow("默认轮询间隔(秒):", self.monitor_poll_spin)

        self.monitor_format_combo = QComboBox()
        self.monitor_format_combo.addItems(["mp4", "flv", "ts", "mkv"])
        idx = self.monitor_format_combo.findText(self.monitor_config.default_format)
        if idx >= 0:
            self.monitor_format_combo.setCurrentIndex(idx)
        form.addRow("默认封装格式:", self.monitor_format_combo)

        self.monitor_output_edit = QLineEdit(str(self.monitor_config.output_root))
        out_layout = QHBoxLayout()
        out_layout.addWidget(self.monitor_output_edit)
        btn_choose = QPushButton("选择")
        btn_choose.clicked.connect(self.choose_monitor_output_dir)
        out_layout.addWidget(btn_choose)
        form.addRow("输出根目录:", out_layout)

        tabs.addTab(tab_monitor, "监控")

    def choose_monitor_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择输出根目录", self.monitor_output_edit.text())
        if directory:
            self.monitor_output_edit.setText(directory)
    
    def init_checkpoint_management(self, form):
        checkpoint_layout = QHBoxLayout()
        
        btn_view_checkpoint = QPushButton("查看检查点")
        btn_view_checkpoint.clicked.connect(self.view_checkpoint_info)
        btn_view_checkpoint.setStyleSheet("QPushButton { padding: 5px 15px; }")
        checkpoint_layout.addWidget(btn_view_checkpoint)
        
        btn_clear_checkpoint = QPushButton("清理检查点")
        btn_clear_checkpoint.clicked.connect(self.clear_checkpoint_confirm)
        btn_clear_checkpoint.setStyleSheet("QPushButton { padding: 5px 15px; background-color: #dc3545; color: white; }")
        checkpoint_layout.addWidget(btn_clear_checkpoint)
        
        form.addRow("检查点管理:", checkpoint_layout)
    
    def init_buttons(self, layout):
        btns = QHBoxLayout()
        btn_ok = QPushButton("保存并关闭")
        btn_ok.clicked.connect(self.on_save)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)
    
    def choose_clips_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择切片基础目录", self.edit_clips_base_dir.text())
        if d:
            self.edit_clips_base_dir.setText(d)
            
    def choose_replay_dir(self):
        """选择回放下载目录"""
        d = QFileDialog.getExistingDirectory(self, "选择回放下载目录", self.edit_replay_download_dir.text())
        if d:
            self.edit_replay_download_dir.setText(d)

    def toggle_hf_visibility(self, checked):
        """切换 HuggingFace token 的显示/隐藏。"""
        if checked:
            self.edit_hf_token.setEchoMode(QLineEdit.Normal)
            self.btn_toggle_hf.setText("隐藏")
        else:
            self.edit_hf_token.setEchoMode(QLineEdit.Password)
            self.btn_toggle_hf.setText("显示")
    
    def on_video_emotion_toggled(self, checked):
        self.edit_video_emotion.setEnabled(checked)
        self.edit_emotion_segment_length.setEnabled(checked)
        self.edit_video_emotion_weight.setEnabled(checked)
    
    def view_checkpoint_info(self):
        try:
            # analyze_data 位于 processing 包下，不能使用当前包的相对导入
            from acfv.processing.analyze_data import CheckpointManager
            checkpoint_manager = CheckpointManager()
            
            if not checkpoint_manager.has_checkpoint():
                QMessageBox.information(self, "检查点信息", "当前没有保存的检查点。")
                return
            
            checkpoint_info = checkpoint_manager.get_checkpoint_info()
            if checkpoint_info:
                progress_percent = checkpoint_info['processed_count']/checkpoint_info['total_count']*100 if checkpoint_info['total_count'] > 0 else 0
                
                info_text = f"""检查点详细信息:

📹 视频文件: {os.path.basename(checkpoint_info['video_path'])}
📊 分析进度: {checkpoint_info['processed_count']}/{checkpoint_info['total_count']} 片段
💾 完成度: {progress_percent:.1f}%
⏰ 上次保存: {checkpoint_info['last_save_time']}
🔧 配置哈希: {checkpoint_info['config_hash'][:16]}...

💡 提示: 下次处理视频时将自动询问是否继续此任务。"""
                
                QMessageBox.information(self, "检查点信息", info_text)
            else:
                QMessageBox.warning(self, "错误", "无法读取检查点信息。")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"查看检查点信息失败: {e}")
    
    def clear_checkpoint_confirm(self):
        try:
            from acfv.processing.analyze_data import CheckpointManager
            checkpoint_manager = CheckpointManager()
            
            if not checkpoint_manager.has_checkpoint():
                QMessageBox.information(self, "提示", "当前没有保存的检查点。")
                return
            
            checkpoint_info = checkpoint_manager.get_checkpoint_info()
            if checkpoint_info:
                progress_percent = checkpoint_info['processed_count']/checkpoint_info['total_count']*100 if checkpoint_info['total_count'] > 0 else 0
                
                reply = QMessageBox.question(
                    self, "确认清理", 
                    f"确定要清理检查点吗？\n\n将删除以下进度:\n📹 {os.path.basename(checkpoint_info['video_path'])}\n💾 {progress_percent:.1f}% 完成度\n\n此操作无法撤销！",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                
                if reply == QMessageBox.Yes:
                    checkpoint_manager.clear_checkpoint()
                    QMessageBox.information(self, "完成", "检查点已清理。")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"清理检查点失败: {e}")
    
    def on_save(self):
        # 保存所有设置
        self.config_manager.set("MAX_CLIP_COUNT", int(self.edit_max_clips.text().strip() or 0))
        self.config_manager.set("CLIPS_BASE_DIR", self.edit_clips_base_dir.text().strip())
        self.config_manager.set("replay_download_folder", self.edit_replay_download_dir.text().strip())
        self.config_manager.set("WHISPER_MODEL", self.edit_whisper.text().strip())
        self.config_manager.set("HUGGINGFACE_TOKEN", self.edit_hf_token.text().strip())
        self.config_manager.set("LOCAL_EMOTION_MODEL_PATH", self.edit_local_emotion.text().strip())
        self.config_manager.set("VIDEO_EMOTION_MODEL_PATH", self.edit_video_emotion.text().strip())
        self.config_manager.set("VIDEO_EMOTION_SEGMENT_LENGTH", float(self.edit_emotion_segment_length.text().strip() or 4.0))
        self.config_manager.set("ENABLE_VIDEO_EMOTION", self.checkbox_enable_video_emotion.isChecked())
        self.config_manager.set("LLM_DEVICE", int(self.edit_llm_device.text().strip()))
        self.config_manager.set("CHAT_DENSITY_WEIGHT", float(self.edit_chat_density.text().strip()))
        self.config_manager.set("CHAT_SENTIMENT_WEIGHT", float(self.edit_chat_sentiment.text().strip()))
        self.config_manager.set("VIDEO_EMOTION_WEIGHT", float(self.edit_video_emotion_weight.text().strip()))
        self.config_manager.set("INTEREST_SCORE_THRESHOLD", float(self.edit_interest_threshold.text().strip()))
        self.config_manager.set("CHECKPOINT_INTERVAL", int(self.edit_checkpoint_interval.text().strip() or 10))
        self.config_manager.set("MAX_WORKERS", int(self.edit_max_workers.text().strip() or 4))
        self.config_manager.set("GPU_DEVICE", self.edit_gpu_device.text().strip())
        self.config_manager.set("ENABLE_GPU_ACCELERATION", self.checkbox_enable_gpu.isChecked())
        
        # 保存切片配置
        self.config_manager.set("MIN_CLIP_DURATION", float(self.edit_min_clip_duration.text().strip() or 60.0))
        self.config_manager.set("CLIP_CONTEXT_EXTEND", float(self.edit_clip_context_extend.text().strip() or 15.0))
        self.config_manager.set("CLIP_MERGE_THRESHOLD", float(self.edit_clip_merge_threshold.text().strip() or 10.0))
        self.config_manager.set("MERGE_NEARBY_CLIPS", self.checkbox_merge_nearby_clips.isChecked())
        
        # 保存语义合并配置
        self.config_manager.set("ENABLE_SEMANTIC_MERGE", self.checkbox_enable_semantic_merge.isChecked())
        self.config_manager.set("SEMANTIC_SIMILARITY_THRESHOLD", float(self.edit_semantic_similarity_threshold.text().strip() or 0.75))
        self.config_manager.set("SEMANTIC_MAX_TIME_GAP", float(self.edit_semantic_max_time_gap.text().strip() or 60.0))

        if self.monitor_runtime and self.monitor_config:
            self.monitor_config.ffmpeg_path = self.monitor_ffmpeg_edit.text().strip() or "ffmpeg"
            self.monitor_config.default_quality = self.monitor_quality_combo.currentText()
            self.monitor_config.default_poll_interval = self.monitor_poll_spin.value()
            self.monitor_config.default_format = self.monitor_format_combo.currentText()
            output_root = self.monitor_output_edit.text().strip()
            if output_root:
                self.monitor_config.output_root = Path(output_root)
            self.monitor_runtime.save_stream_monitor_config(self.monitor_config, self.monitor_cfg_path)

        
        self.config_manager.save()
        self.accept()


class ClipRatingDialog(QDialog):
    """切片评分对话框"""
    
    def __init__(self, clip_path, rating_file, parent=None):
        super().__init__(parent)
        self.clip_path = clip_path
        self.rating_file = rating_file
        self.clip_name = os.path.basename(clip_path)
        
        self.setWindowTitle(f"评分: {self.clip_name}")
        self.resize(600, 400)
        self.init_ui()
        self.load_existing_rating()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 视频预览
        self.preview = QLabel("视频预览")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(240)
        self.load_video_preview()
        layout.addWidget(self.preview)
        
        # 播放按钮
        btn_open = QPushButton("播放视频")
        btn_open.clicked.connect(self.play_video)
        layout.addWidget(btn_open)
        
        # 评分滑块
        self.init_rating_slider(layout)
        
        # 备注
        layout.addWidget(QLabel("备注:"))
        self.notes = QTextEdit()
        layout.addWidget(self.notes)
        
        # 按钮
        self.init_buttons(layout)
    
    def load_video_preview(self):
        cap = cv2.VideoCapture(self.clip_path)
        ret, frame = cap.read()
        if ret:
            h, w, _ = frame.shape
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
            pix = QPixmap.fromImage(img).scaled(
                560, 315, Qt.KeepAspectRatio | Qt.SmoothTransformation
            )
            self.preview.setPixmap(pix)
        cap.release()
    
    def init_rating_slider(self, layout):
        rating_layout = QHBoxLayout()
        rating_layout.addWidget(QLabel("评分:"))
        
        self.rating_slider = QSlider(Qt.Horizontal)
        self.rating_slider.setMinimum(1)
        self.rating_slider.setMaximum(5)
        self.rating_slider.setValue(3)
        self.rating_slider.setTickPosition(QSlider.TicksBelow)
        self.rating_slider.setTickInterval(1)
        rating_layout.addWidget(self.rating_slider)
        
        self.rating_label = QLabel("3 | 一般")
        self.rating_slider.valueChanged.connect(self.update_rating_label)
        rating_layout.addWidget(self.rating_label)
        
        layout.addLayout(rating_layout)
    
    def init_buttons(self, layout):
        btns = QHBoxLayout()
        btn_save = QPushButton("保存评分")
        btn_save.clicked.connect(self.save_rating)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_save)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)
    
    def update_rating_label(self):
        v = self.rating_slider.value()
        mapping = {
            1: ("非常不喜欢", "#d9534f"),
            2: ("不喜欢", "#f0ad4e"),
            3: ("一般", "#5bc0de"),
            4: ("喜欢", "#5cb85c"),
            5: ("非常喜欢", "#4cae4c"),
        }
        text, color = mapping.get(v, ("一般", "#5bc0de"))
        self.rating_label.setText(f"{v} | {text}")
        # 简单着色
        self.rating_label.setStyleSheet(f"color:{color}; font-weight:bold;")
    
    def play_video(self):
        if sys.platform.startswith('win'):
            os.startfile(self.clip_path)
        elif sys.platform.startswith('darwin'):
            subprocess.call(['open', self.clip_path])
        else:
            subprocess.call(['xdg-open', self.clip_path])
    
    def load_existing_rating(self):
        if os.path.exists(self.rating_file):
            try:
                with open(self.rating_file, 'r', encoding='utf-8') as f:
                    ratings = json.load(f)
                    
                clip_basename = os.path.basename(self.clip_path)
                if clip_basename in ratings:
                    rating_data = ratings[clip_basename]
                    self.rating_slider.setValue(rating_data.get('rating', 3))
                    self.notes.setText(rating_data.get('notes', ''))
            except Exception as e:
                logging.error(f"加载评分失败: {e}")
    
    def save_rating(self):
        ratings = {}
        if os.path.exists(self.rating_file):
            try:
                with open(self.rating_file, 'r', encoding='utf-8') as f:
                    ratings = json.load(f)
            except Exception:
                pass
        
        clip_basename = os.path.basename(self.clip_path)
        # 合并保存，保留已有的 text/start/end/duration 等字段，避免覆盖丢失
        existing = ratings.get(clip_basename, {}) if isinstance(ratings, dict) else {}
        try:
            new_entry = dict(existing)
        except Exception:
            new_entry = {}  # 回退
        new_entry.update({
            'rating': self.rating_slider.value(),
            'notes': self.notes.toPlainText(),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        ratings[clip_basename] = new_entry
        
        try:
            with open(self.rating_file, 'w', encoding='utf-8') as f:
                json.dump(ratings, f, ensure_ascii=False, indent=2)
                # 移除评分后的RAG自动处理
                self.accept()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存评分失败: {e}")

    def _infer_video_dir(self, clip_path: str):
        """从切片路径推断视频目录与名称：.../clips/<video_name>/runs/run_xxx/output_clips/file.mp4"""
        p = os.path.abspath(clip_path)
        # 向上查找 'runs' 目录
        d = os.path.dirname(p)
        for _ in range(5):
            name = os.path.basename(d)
            if name == 'runs':
                video_dir = os.path.dirname(d)
                return video_dir, os.path.basename(video_dir)
            d = os.path.dirname(d)
        # 回退：返回父目录
        video_dir = os.path.dirname(os.path.dirname(os.path.dirname(p)))
        return video_dir, os.path.basename(video_dir)

    def _parse_time_from_filename(self, filename: str):
        """从文件名中解析起止时间：..._<start>s-<end>s.mp4"""
        try:
            m = re.search(r"_(\d+(?:\.\d+)?)s-(\d+(?:\.\d+)?)s\.[Mm][Pp]4$", filename)
            if m:
                return float(m.group(1)), float(m.group(2))
        except Exception:
            pass
        return None, None

    def _extract_transcript_text(self, video_dir_path: str, start_s: float, end_s: float) -> str:
        """提取与片段时间范围重叠的转录文本并拼接（仅用于英文向量生成）"""
        try:
            if not video_dir_path:
                return ""
            transcript_candidates = [
                os.path.join(video_dir_path, 'data', 'transcription.json'),
                os.path.join(video_dir_path, 'transcription.json'),
            ]
            for fp in transcript_candidates:
                if os.path.exists(fp):
                    with open(fp, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    texts = []
                    for seg in data if isinstance(data, list) else []:
                        try:
                            st = float(seg.get('start', 0))
                            et = float(seg.get('end', 0))
                            if start_s is None or end_s is None or (et >= start_s and st <= end_s):
                                txt = str(seg.get('text', '')).strip()
                                if txt:
                                    texts.append(txt)
                        except Exception:
                            continue
                    return '\n'.join(texts)[:4000]
        except Exception as e:
            logging.debug(f"_extract_transcript_text异常：{e}")
        return ""


# 兼容性别名，保持向后兼容
VideoThumbnailLoader = SimpleThumbnailLoader
ClipThumbnailLoader = SimpleClipThumbnailLoader

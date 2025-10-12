# video_emotion_infer.py - 分段YOLO处理器和情绪推理
import os
import cv2
import json
import numpy as np
import subprocess
import tempfile
from pathlib import Path
from sklearn.cluster import DBSCAN

# 尝试导入YOLO，如果失败则提供fallback
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    # 将print语句移到函数内部，避免在导入时执行
    YOLO_AVAILABLE = False

class SegmentedYOLOProcessor:
    def __init__(self, yolo_weights="best.pt", segment_length=4.0, confidence_threshold=0.5):
        """
        分段YOLO处理器 - 每N秒动态检测和裁剪
        
        Args:
            yolo_weights: YOLO模型权重文件
            segment_length: 分段长度（秒）
            confidence_threshold: 检测置信度阈值
        """
        self.segment_length = segment_length
        self.confidence_threshold = confidence_threshold
        self.yolo_model = None
        self.yolo_available = YOLO_AVAILABLE
        
        if not YOLO_AVAILABLE:
            print("❌ YOLO不可用，将跳过目标检测")
            return
            
        try:
            print(f"🔍 加载YOLO模型: {yolo_weights}")
            
            # 检查权重文件是否存在
            if not os.path.exists(yolo_weights):
                print(f"⚠️ YOLO权重文件不存在: {yolo_weights}")
                print("🔄 尝试使用预训练模型...")
                # 使用ultralytics的预训练模型
                yolo_weights = "yolov8n.pt"  # 小模型，快速下载
            
            self.yolo_model = YOLO(yolo_weights)
            print("✅ YOLO模型加载成功")
        except Exception as e:
            print(f"❌ YOLO模型加载失败: {e}")
            print("⚠️ 将跳过YOLO处理")
            self.yolo_available = False

    def get_video_info(self, video_path):
        """获取视频基本信息"""
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = total_frames / fps if fps > 0 else 0
        cap.release()
        
        return {
            'fps': fps,
            'total_frames': total_frames,
            'width': width,
            'height': height,
            'duration': duration
        }

    def detect_segment_boxes(self, video_path, start_time, end_time, sample_interval=0.5):
        """
        检测指定时间段内的目标框
        
        Args:
            video_path: 视频路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
            sample_interval: 采样间隔（秒）
        """
        if not self.yolo_available or self.yolo_model is None:
            return []
            
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        boxes = []
        current_time = start_time
        
        while current_time < end_time:
            frame_number = int(current_time * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            
            ret, frame = cap.read()
            if not ret:
                break
            
            try:
                results = self.yolo_model(frame, verbose=False)
                
                # 找到最大的检测框
                max_area = 0
                best_box = None
                
                for r in results:
                    if len(r.boxes) > 0:
                        for i, box in enumerate(r.boxes.xyxy):
                            conf = float(r.boxes.conf[i])
                            if conf < self.confidence_threshold:
                                continue
                                
                            x1, y1, x2, y2 = map(int, box[:4])
                            area = (x2 - x1) * (y2 - y1)
                            
                            if area > max_area:
                                max_area = area
                                best_box = [x1, y1, x2, y2]
                
                if best_box is not None:
                    boxes.append(best_box)
                    
            except Exception as e:
                print(f"⚠️ 检测时间 {current_time:.2f}s 时出错: {e}")
            
            current_time += sample_interval
        
        cap.release()
        return boxes

    def cluster_boxes(self, boxes, eps=20, min_samples=3):
        """对检测框进行聚类，返回主要区域"""
        if not boxes:
            return None
            
        if len(boxes) < min_samples:
            # 框太少，返回联合边界框
            x1 = min(b[0] for b in boxes)
            y1 = min(b[1] for b in boxes)
            x2 = max(b[2] for b in boxes)
            y2 = max(b[3] for b in boxes)
            return [x1, y1, x2, y2]
        
        # 计算中心点
        centers = np.array([[(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] for box in boxes])
        
        # 聚类
        db = DBSCAN(eps=eps, min_samples=min_samples).fit(centers)
        labels = db.labels_
        
        # 找到最大的聚类
        valid_indices = [i for i, label in enumerate(labels) if label != -1]
        if not valid_indices:
            # 没有有效聚类，返回所有框的联合边界框
            x1 = min(b[0] for b in boxes)
            y1 = min(b[1] for b in boxes)
            x2 = max(b[2] for b in boxes)
            y2 = max(b[3] for b in boxes)
            return [x1, y1, x2, y2]
        
        # 选择最大聚类
        unique_labels, counts = np.unique([labels[i] for i in valid_indices], return_counts=True)
        best_cluster = unique_labels[np.argmax(counts)]
        cluster_boxes = [boxes[i] for i in range(len(boxes)) if labels[i] == best_cluster]
        
        # 返回聚类的联合边界框
        x1 = min(b[0] for b in cluster_boxes)
        y1 = min(b[1] for b in cluster_boxes)
        x2 = max(b[2] for b in cluster_boxes)
        y2 = max(b[3] for b in cluster_boxes)
        
        return [x1, y1, x2, y2]

    def smooth_crop_regions(self, crop_regions, video_info):
        """
        平滑裁剪区域，避免剧烈跳跃
        
        Args:
            crop_regions: 每段的裁剪区域列表
            video_info: 视频信息
        """
        if not crop_regions:
            return []
        
        smoothed = []
        width, height = video_info['width'], video_info['height']
        
        for i, region in enumerate(crop_regions):
            if region is None:
                # 使用前一个区域或默认区域
                if smoothed:
                    smoothed.append(smoothed[-1])
                else:
                    smoothed.append([0, 0, width, height])
                continue
            
            x1, y1, x2, y2 = region
            
            # 边界检查
            x1 = max(0, min(x1, width - 1))
            x2 = max(x1 + 1, min(x2, width))
            y1 = max(0, min(y1, height - 1))
            y2 = max(y1 + 1, min(y2, height))
            
            if smoothed:
                # 与前一个区域进行平滑
                prev_x1, prev_y1, prev_x2, prev_y2 = smoothed[-1]
                
                # 使用加权平均进行平滑
                alpha = 0.7  # 当前帧权重
                x1 = int(alpha * x1 + (1 - alpha) * prev_x1)
                y1 = int(alpha * y1 + (1 - alpha) * prev_y1)
                x2 = int(alpha * x2 + (1 - alpha) * prev_x2)
                y2 = int(alpha * y2 + (1 - alpha) * prev_y2)
            
            smoothed.append([x1, y1, x2, y2])
        
        return smoothed

    def extract_audio(self, input_video, output_audio):
        """使用 ffmpeg 提取视频中的音频"""
        cmd = [
            'ffmpeg', '-y',
            '-loglevel', 'error',
            '-i', input_video,
            '-vn',
            '-acodec', 'copy',
            output_audio
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"提取音频失败: {e}")
            return False
        except FileNotFoundError:
            print("❌ ffmpeg不可用，无法提取音频")
            return False

    def merge_audio_video(self, input_video, temp_video, output_video):
        """合并音频和视频"""
        cmd = [
            'ffmpeg', '-y',
            '-loglevel', 'error',
            '-i', temp_video,
            '-i', input_video,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-map', '0:v:0',
            '-map', '1:a:0',
            output_video
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except Exception as e:
            print(f"音频合并失败: {e}")
            return False

    def process_video_segments(self, input_path, output_path):
        """
        分段处理视频 - 每段使用不同的裁剪区域
        
        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
        """
        print(f"🎬 开始分段YOLO处理: {input_path}")
        
        # 如果YOLO不可用，直接复制原视频
        if not self.yolo_available:
            print("⚠️ YOLO不可用，直接复制原视频")
            import shutil
            shutil.copy2(input_path, output_path)
            return True
        
        # 获取视频信息
        video_info = self.get_video_info(input_path)
        duration = video_info['duration']
        fps = video_info['fps']
        
        print(f"📹 视频信息: {duration:.2f}秒, {fps:.1f}fps, {video_info['width']}x{video_info['height']}")
        
        # 计算分段数量
        num_segments = int(np.ceil(duration / self.segment_length))
        print(f"📊 将处理 {num_segments} 个{self.segment_length}秒段")
        
        # 第一阶段：为每个段检测最佳裁剪区域
        print("🔍 第一阶段：检测每段的最佳裁剪区域...")
        crop_regions = []
        
        for i in range(num_segments):
            start_time = i * self.segment_length
            end_time = min((i + 1) * self.segment_length, duration)
            
            print(f"  段 {i+1}/{num_segments}: {start_time:.1f}s - {end_time:.1f}s")
            
            # 检测这个时间段的目标框
            boxes = self.detect_segment_boxes(input_path, start_time, end_time)
            
            # 计算最佳裁剪区域
            crop_region = self.cluster_boxes(boxes) if boxes else None
            crop_regions.append(crop_region)
            
            if crop_region:
                x1, y1, x2, y2 = crop_region
                print(f"    裁剪区域: [{x1}, {y1}, {x2}, {y2}] 尺寸: {x2-x1}x{y2-y1}")
            else:
                print(f"    未检测到目标，将使用默认区域")
        
        # 平滑裁剪区域
        print("🔧 平滑裁剪区域...")
        crop_regions = self.smooth_crop_regions(crop_regions, video_info)
        
        # 第二阶段：按分段裁剪视频
        print("✂️ 第二阶段：分段裁剪视频...")
        
        # 创建临时文件
        temp_video_path = output_path.replace('.mp4', '_temp_nosound.mp4')
        
        # 处理视频
        success = self._crop_video_segments(input_path, temp_video_path, crop_regions, video_info)
        
        if not success:
            print("❌ 视频裁剪失败")
            return False
        
        # 第三阶段：添加音频
        print("🎵 第三阶段：添加音频...")
        temp_audio_path = output_path.replace('.mp4', '_temp_audio.aac')
        
        if self.extract_audio(input_path, temp_audio_path):
            if self.merge_audio_video(input_path, temp_video_path, output_path):
                print("✅ 分段YOLO处理完成")
                success = True
            else:
                print("⚠️ 音频合并失败，使用无音频版本")
                import shutil
                shutil.move(temp_video_path, output_path)
                success = True
        else:
            print("⚠️ 音频提取失败，使用无音频版本")
            import shutil
            shutil.move(temp_video_path, output_path)
            success = True
        
        # 清理临时文件
        for temp_file in [temp_video_path, temp_audio_path]:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
        
        return success

    def _crop_video_segments(self, input_path, output_path, crop_regions, video_info):
        """裁剪视频段"""
        try:
            cap = cv2.VideoCapture(input_path)
            fps = video_info['fps']
            
            # 计算输出视频的尺寸（使用第一个有效裁剪区域的尺寸）
            valid_region = None
            for region in crop_regions:
                if region is not None:
                    valid_region = region
                    break
            
            if valid_region is None:
                print("❌ 没有有效的裁剪区域")
                cap.release()
                return False
            
            x1, y1, x2, y2 = valid_region
            crop_w, crop_h = x2 - x1, y2 - y1
            
            # 创建视频写入器
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (crop_w, crop_h))
            
            current_segment = 0
            frame_count = 0
            total_frames = video_info['total_frames']
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # 计算当前帧属于哪个段
                current_time = frame_count / fps
                segment_index = min(int(current_time / self.segment_length), len(crop_regions) - 1)
                
                # 获取当前段的裁剪区域
                crop_region = crop_regions[segment_index]
                if crop_region is None:
                    crop_region = [0, 0, video_info['width'], video_info['height']]
                
                x1, y1, x2, y2 = crop_region
                
                # 裁剪帧
                h, w = frame.shape[:2]
                x1_c = max(0, min(x1, w - 1))
                x2_c = max(x1_c + 1, min(x2, w))
                y1_c = max(0, min(y1, h - 1))
                y2_c = max(y1_c + 1, min(y2, h))
                
                cropped = frame[y1_c:y2_c, x1_c:x2_c]
                
                # 确保尺寸一致
                if cropped.shape[1] != crop_w or cropped.shape[0] != crop_h:
                    cropped = cv2.resize(cropped, (crop_w, crop_h))
                
                out.write(cropped)
                
                frame_count += 1
                if frame_count % 1000 == 0:
                    progress = frame_count / total_frames * 100
                    print(f"  裁剪进度: {progress:.1f}%")
            
            cap.release()
            out.release()
            
            print(f"✅ 视频裁剪完成，共处理 {frame_count} 帧")
            return True
            
        except Exception as e:
            print(f"❌ 视频裁剪失败: {e}")
            if 'cap' in locals():
                cap.release()
            if 'out' in locals():
                out.release()
            return False

# 新增：情绪推理功能
class VideoEmotionInference:
    def __init__(self, segment_length=4.0):
        """
        视频情绪推理器
        
        Args:
            segment_length: 分段长度（秒）
        """
        self.segment_length = segment_length
    
    def analyze_video_emotion(self, video_path, output_file):
        """
        分析视频的情绪变化
        
        Args:
            video_path: 输入视频路径
            output_file: 输出JSON文件路径
        """
        print(f"🎭 开始视频情绪分析: {video_path}")
        
        try:
            # 获取视频信息
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            cap.release()
            
            print(f"📹 视频信息: {duration:.2f}秒, {fps:.1f}fps")
            
            # 计算分段数量
            num_segments = int(np.ceil(duration / self.segment_length))
            print(f"📊 将分析 {num_segments} 个{self.segment_length}秒段")
            
            # 分析每个时间段
            emotion_data = []
            
            for i in range(num_segments):
                start_time = i * self.segment_length
                end_time = min((i + 1) * self.segment_length, duration)
                
                # 模拟情绪分析（这里可以替换为实际的情绪推理模型）
                emotion_score = self._mock_emotion_analysis(video_path, start_time, end_time)
                
                segment_data = {
                    "start": start_time,
                    "end": end_time,
                    "emotion_score": emotion_score,
                    "emotion_type": self._classify_emotion(emotion_score),
                    "segment_index": i
                }
                
                emotion_data.append(segment_data)
                print(f"  段 {i+1}/{num_segments}: {start_time:.1f}s-{end_time:.1f}s 情绪分数: {emotion_score:.3f}")
            
            # 保存结果
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(emotion_data, f, ensure_ascii=False, indent=2)
            
            print(f"✅ 情绪分析完成，结果保存到: {output_file}")
            return True
            
        except Exception as e:
            print(f"❌ 情绪分析失败: {e}")
            # 创建空的结果文件
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump([], f)
            return False
    
    def _mock_emotion_analysis(self, video_path, start_time, end_time):
        """
        模拟情绪分析（可以替换为实际的模型推理）
        
        Args:
            video_path: 视频路径
            start_time: 开始时间
            end_time: 结束时间
        
        Returns:
            emotion_score: 情绪分数 (0.0-1.0)
        """
        # 这里是一个简单的模拟实现
        # 实际应用中可以替换为深度学习模型，如：
        # - 面部表情识别
        # - 动作识别
        # - 音频情绪识别等
        
        try:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            
            # 跳转到指定时间
            start_frame = int(start_time * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            
            # 采样几帧进行分析
            sample_frames = []
            current_time = start_time
            
            while current_time < end_time and len(sample_frames) < 5:
                ret, frame = cap.read()
                if not ret:
                    break
                sample_frames.append(frame)
                # 跳过一些帧
                for _ in range(int(fps * 0.5)):  # 每0.5秒采样一帧
                    cap.read()
                    current_time += 0.5
            
            cap.release()
            
            if not sample_frames:
                return 0.5  # 默认中性情绪
            
            # 简单的图像特征分析（可以替换为实际的模型）
            emotion_score = 0.0
            for frame in sample_frames:
                # 计算图像的亮度变化作为简单的情绪指标
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                brightness = np.mean(gray) / 255.0
                contrast = np.std(gray) / 255.0
                
                # 简单的情绪评分算法（实际应用中应使用训练好的模型）
                frame_emotion = (brightness * 0.6 + contrast * 0.4)
                emotion_score += frame_emotion
            
            emotion_score = emotion_score / len(sample_frames)
            return min(max(emotion_score, 0.0), 1.0)  # 限制在0-1范围内
            
        except Exception as e:
            print(f"⚠️ 分析段 {start_time:.1f}s-{end_time:.1f}s 时出错: {e}")
            return 0.5  # 返回中性情绪分数
    
    def _classify_emotion(self, emotion_score):
        """
        根据情绪分数分类情绪类型
        
        Args:
            emotion_score: 情绪分数 (0.0-1.0)
        
        Returns:
            emotion_type: 情绪类型字符串
        """
        if emotion_score < 0.2:
            return "very_low"
        elif emotion_score < 0.4:
            return "low"
        elif emotion_score < 0.6:
            return "neutral"
        elif emotion_score < 0.8:
            return "high"
        else:
            return "very_high"

# 主要的运行函数，供主程序调用
def run(video_path, output_file, args=None):
    """
    运行视频情绪推理
    
    Args:
        video_path: 输入视频路径
        output_file: 输出JSON文件路径
        args: 参数对象（兼容原有接口）
    """
    try:
        # 从args获取参数，如果没有则使用默认值
        segment_length = getattr(args, 'segment_length', 4.0) if args else 4.0
        
        # 创建情绪推理器
        emotion_analyzer = VideoEmotionInference(segment_length=segment_length)
        
        # 执行分析
        success = emotion_analyzer.analyze_video_emotion(video_path, output_file)
        
        if success:
            print(f"🎉 视频情绪推理完成: {output_file}")
        else:
            print(f"❌ 视频情绪推理失败")
            
        return success
        
    except Exception as e:
        print(f"❌ 视频情绪推理出错: {e}")
        # 确保输出文件存在，即使是空的
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump([], f)
        except:
            pass
        return False

# 便捷函数
def process_video_with_segmented_yolo(input_path, output_path, yolo_weights="best.pt", segment_length=4.0):
    """
    使用分段YOLO处理视频
    
    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        yolo_weights: YOLO权重文件
        segment_length: 分段长度（秒）
    """
    processor = SegmentedYOLOProcessor(
        yolo_weights=yolo_weights,
        segment_length=segment_length
    )
    
    return processor.process_video_segments(input_path, output_path)

if __name__ == "__main__":
    print("🎬 视频情绪推理模块")
    print("使用方法: python video_emotion_infer.py <视频路径> <输出文件>")
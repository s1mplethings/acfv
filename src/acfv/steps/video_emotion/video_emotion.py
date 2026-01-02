import os
import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision.transforms as T
from PIL import Image
from acfv import config

##############################################
# 数据预处理：前景 mask 提取与平滑处理
##############################################
class AddForegroundMask(object):
    def __init__(self, threshold=50, fixed_green=(0, 255, 0)):
        self.threshold = threshold
        self.fixed_green = np.array(fixed_green, dtype=np.int32)
    
    def __call__(self, img):
        np_img = np.array(img)
        diff = np.abs(np_img.astype(np.int32) - self.fixed_green)
        mask = (diff.sum(axis=-1) > self.threshold).astype(np.float32)
        mask_uint8 = (mask * 255).astype(np.uint8)
        smooth_mask = cv2.GaussianBlur(mask_uint8, (5, 5), sigmaX=0)
        smooth_mask = smooth_mask.astype(np.float32) / 255.0
        img_tensor = T.ToTensor()(img)
        mask_tensor = torch.from_numpy(smooth_mask).unsqueeze(0)
        return torch.cat([img_tensor, mask_tensor], dim=0)

class MultiChannelNormalize(object):
    def __init__(self, means, stds):
        self.means = means
        self.stds = stds
        
    def __call__(self, tensor):
        for i in range(3):
            tensor[i] = (tensor[i] - self.means[i]) / self.stds[i]
        return tensor

transform_rgb = T.Compose([
    AddForegroundMask(threshold=50, fixed_green=(0, 255, 0)),
    MultiChannelNormalize(means=[0.485, 0.456, 0.406],
                            stds=[0.229, 0.224, 0.225])
])

##############################################
# 数据增强（训练时使用，推理时不用）
##############################################
data_augmentation = T.Compose([
    T.RandomHorizontalFlip(),
    T.RandomRotation(10),
    T.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.1),
    T.RandomResizedCrop(224, scale=(0.8, 1.0))
])

##############################################
# 模型部分：多分支 deformable transformer 模型
##############################################
class DeformableDETRModule(nn.Module):
    def __init__(self, in_channels, d_model, kernel_size):
        super(DeformableDETRModule, self).__init__()
        self.conv = nn.Conv2d(in_channels, d_model, kernel_size=kernel_size, padding=kernel_size//2)
        self.bn = nn.BatchNorm2d(d_model)
        self.relu = nn.ReLU(inplace=True)
    
    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        return self.relu(x)

class CNNHead(nn.Module):
    def __init__(self, in_channels, d_model):
        super(CNNHead, self).__init__()
        self.features = nn.Sequential(
            nn.Conv2d(in_channels, d_model//2, kernel_size=3, padding=1),
            nn.BatchNorm2d(d_model//2),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(d_model//2, d_model, kernel_size=3, padding=1),
            nn.BatchNorm2d(d_model),
            nn.ReLU(inplace=True)
        )
    
    def forward(self, x):
        return self.features(x)

class MultiBranchDeformableTransformerModel(nn.Module):
    def __init__(self, in_channels, seq_len=30, d_model=128, temporal_layers=6, nhead=8, dropout=0.1):
        super(MultiBranchDeformableTransformerModel, self).__init__()
        self.branch1 = DeformableDETRModule(in_channels, d_model, kernel_size=7)
        self.branch2 = DeformableDETRModule(in_channels, d_model, kernel_size=5)
        self.branch3 = DeformableDETRModule(in_channels, d_model, kernel_size=3)
        self.branch4 = CNNHead(in_channels, d_model)
        self.branch5 = CNNHead(in_channels, d_model)
        self.gate1 = nn.Linear(d_model, 1)
        self.gate2 = nn.Linear(d_model, 1)
        self.gate3 = nn.Linear(d_model, 1)
        self.gate4 = nn.Linear(d_model, 1)
        self.gate5 = nn.Linear(d_model, 1)
        self.pool = nn.AdaptiveAvgPool2d((1, 1))
        encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=nhead, dropout=dropout, batch_first=True)
        self.temporal_encoder = nn.TransformerEncoder(encoder_layer, num_layers=temporal_layers)
        self.classifier = nn.Linear(d_model, 1)  # 情绪强度回归
        self.regressor = nn.Linear(d_model, 1)   # 情绪值回归
    
    def forward(self, x):
        # 输入 x: [B, seq_len, 1, 4, H, W]
        B, seq_len, C, H, W = x.shape
        
        # 多分支处理
        branch1_out = self.branch1(x.view(-1, C, H, W)).view(B, seq_len, -1, H, W)
        branch2_out = self.branch2(x.view(-1, C, H, W)).view(B, seq_len, -1, H, W)
        branch3_out = self.branch3(x.view(-1, C, H, W)).view(B, seq_len, -1, H, W)
        branch4_out = self.branch4(x.view(-1, C, H, W)).view(B, seq_len, -1, H, W)
        branch5_out = self.branch5(x.view(-1, C, H, W)).view(B, seq_len, -1, H, W)
        
        # 注意力门控
        gate1 = torch.sigmoid(self.gate1(branch1_out.view(B, seq_len, -1)))
        gate2 = torch.sigmoid(self.gate2(branch2_out.view(B, seq_len, -1)))
        gate3 = torch.sigmoid(self.gate3(branch3_out.view(B, seq_len, -1)))
        gate4 = torch.sigmoid(self.gate4(branch4_out.view(B, seq_len, -1)))
        gate5 = torch.sigmoid(self.gate5(branch5_out.view(B, seq_len, -1)))
        
        # 加权融合
        fused = (gate1 * branch1_out + gate2 * branch2_out + gate3 * branch3_out + 
                gate4 * branch4_out + gate5 * branch5_out) / 5.0
        
        # 全局池化
        pooled = self.pool(fused.view(B * seq_len, -1, H, W)).view(B, seq_len, -1)
        
        # 时序编码
        encoded = self.temporal_encoder(pooled)
        
        # 分类和回归
        class_logits = self.classifier(encoded.mean(dim=1))
        reg_value = self.regressor(encoded.mean(dim=1))
        
        return class_logits, reg_value

##############################################
# 加载视频情绪识别模型
##############################################
def load_video_emotion_model(device):
    in_channels = 4
    model = MultiBranchDeformableTransformerModel(in_channels, seq_len=30, d_model=128, temporal_layers=6, nhead=8, dropout=0.1)
    if os.path.isfile(config.VIDEO_EMOTION_MODEL_PATH):
        checkpoint = torch.load(config.VIDEO_EMOTION_MODEL_PATH, map_location=device)
        model.load_state_dict(checkpoint["model_state_dict"])
        print(f"Loaded video emotion model from {config.VIDEO_EMOTION_MODEL_PATH}")
    else:
        print(f"Warning: Video emotion model checkpoint not found at {config.VIDEO_EMOTION_MODEL_PATH}")
    model.to(device)
    model.eval()
    return model

##############################################
# 根据视频文件和时间段计算视频情绪强度
##############################################
def compute_video_emotion_strength(video_file, start, end, model, device):
    cap = cv2.VideoCapture(video_file)
    
    if not cap.isOpened():
        print(f"Warning: Cannot open video {video_file}")
        cap.release()
        return 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or config.VIDEO_FPS
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    start_frame = int(start * fps)
    end_frame = int(end * fps)
    frames = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    for frame_idx in range(start_frame, min(end_frame, total_frames)):
        ret, frame = cap.read()
        if not ret:
            break
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_resized = cv2.resize(frame_rgb, (224, 224))
        frame_pil = Image.fromarray(frame_resized)
        frame_tensor = transform_rgb(frame_pil)  # 4通道
        frames.append(frame_tensor.unsqueeze(0))
    cap.release()
    if len(frames) == 0:
        return 0.0
    frames_tensor = torch.stack(frames, dim=0)  # [num_frames, 1, 4, H, W]
    seq_len = 30
    if frames_tensor.shape[0] < seq_len:
        while frames_tensor.shape[0] < seq_len:
            frames_tensor = torch.cat([frames_tensor, frames_tensor[-1:].clone()], dim=0)
        frames_tensor = frames_tensor[:seq_len]
    else:
        indices = np.linspace(0, frames_tensor.shape[0]-1, num=seq_len).astype(int)
        frames_tensor = frames_tensor[indices]
    frames_tensor = frames_tensor.unsqueeze(0).to(device)  # [1, seq_len, 1, 4, H, W]
    with torch.no_grad():
        _, reg_value = model(frames_tensor)
    video_emotion_score = reg_value.item()
    print(f"Video emotion score for segment {start}-{end}: {video_emotion_score}")
    return video_emotion_score 
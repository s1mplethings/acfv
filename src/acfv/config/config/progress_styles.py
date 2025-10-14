#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
进度条美化样式集合 - 多种现代化设计方案
"""

# 🎨 方案1: 现代渐变风格
MODERN_GRADIENT_STYLE = """
QProgressBar {
    border: 2px solid #34495e;
    border-radius: 15px;
    text-align: center;
    font-weight: bold;
    font-size: 14px;
    background-color: #ecf0f1;
    color: #2c3e50;
    min-height: 35px;
    max-height: 35px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #667eea, stop:0.3 #764ba2, stop:0.7 #f093fb, stop:1 #f5576c);
    border-radius: 12px;
    margin: 1px;
}

QProgressBar:chunk:disabled {
    background: #bdc3c7;
}
"""

# 🎨 方案2: 苹果风格
APPLE_STYLE = """
QProgressBar {
    border: none;
    border-radius: 8px;
    text-align: center;
    font-weight: 600;
    font-size: 13px;
    background-color: rgba(0, 0, 0, 0.1);
    color: #333333;
    min-height: 20px;
    max-height: 20px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #007AFF, stop:1 #0051D0);
    border-radius: 8px;
    margin: 1px;
}
"""

# 🎨 方案3: 霓虹发光效果
NEON_GLOW_STYLE = """
QProgressBar {
    border: 2px solid #1a1a2e;
    border-radius: 12px;
    text-align: center;
    font-weight: bold;
    font-size: 14px;
    background-color: #16213e;
    color: #00d4aa;
    min-height: 30px;
    padding: 2px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00d4aa, stop:0.5 #7209b7, stop:1 #1a1a2e);
    border-radius: 8px;
    margin: 1px;
    border: 1px solid #00d4aa;
}

QProgressBar:hover {
    border: 2px solid #00d4aa;
    background-color: #1e3a5f;
}
"""

# 🎨 方案4: 微软Fluent设计
FLUENT_DESIGN_STYLE = """
QProgressBar {
    border: 1px solid #e1e5e9;
    border-radius: 4px;
    text-align: center;
    font-weight: 400;
    font-size: 13px;
    background-color: #f3f4f6;
    color: #323130;
    min-height: 24px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0078d4, stop:1 #106ebe);
    border-radius: 2px;
    margin: 1px;
}

QProgressBar:disabled {
    background-color: #f8f9fa;
    color: #a19f9d;
}
"""

# 🎨 方案5: 游戏风格 (RPG血条)
GAMING_STYLE = """
QProgressBar {
    border: 3px solid #8b4513;
    border-radius: 8px;
    text-align: center;
    font-weight: bold;
    font-size: 14px;
    font-family: 'Consolas', 'Monaco', monospace;
    background-color: #2c1810;
    color: #ffd700;
    min-height: 32px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ff6b35, stop:0.4 #ff8c42, stop:0.6 #ffa726, stop:1 #ffb74d);
    border-radius: 4px;
    margin: 2px;
    border: 1px solid #ff8c42;
}
"""

# 🎨 方案6: 简约黑白风
MINIMAL_BW_STYLE = """
QProgressBar {
    border: 1px solid #d1d5db;
    border-radius: 6px;
    text-align: center;
    font-weight: 500;
    font-size: 12px;
    background-color: #ffffff;
    color: #374151;
    min-height: 26px;
}

QProgressBar::chunk {
    background-color: #111827;
    border-radius: 4px;
    margin: 1px;
}

QProgressBar:hover {
    border: 1px solid #9ca3af;
}
"""

# 🎨 方案7: 彩虹渐变
RAINBOW_STYLE = """
QProgressBar {
    border: 2px solid #34495e;
    border-radius: 16px;
    text-align: center;
    font-weight: bold;
    font-size: 14px;
    background-color: #ecf0f1;
    color: #2c3e50;
    min-height: 32px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff0080, stop:0.15 #ff8c00, stop:0.3 #40e0d0, 
        stop:0.45 #90ee90, stop:0.6 #ffd700, stop:0.75 #ff69b4, stop:1 #8a2be2);
    border-radius: 12px;
    margin: 2px;
}
"""

# 💎 高级样式配置
ADVANCED_STYLES = {
    "labels": {
        # 阶段标签样式
        "stage_label": """
            QLabel {
                font-size: 18px;
                font-weight: 700;
                color: #2563eb;
                padding: 8px 12px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f8fafc, stop:1 #e2e8f0);
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin: 4px 0;
            }
        """,
        
        # 时间预测标签样式
        "eta_label": """
            QLabel {
                font-size: 14px;
                font-weight: 600;
                color: #059669;
                padding: 6px 10px;
                background-color: #f0fdf4;
                border: 1px solid #bbf7d0;
                border-radius: 6px;
                margin: 2px 0;
            }
        """,
        
        # 详细进度标签样式
        "detail_label": """
            QLabel {
                font-size: 13px;
                color: #64748b;
                padding: 4px 8px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #f1f5f9);
                border: 1px solid #e2e8f0;
                border-radius: 4px;
                margin: 2px 0;
            }
        """
    },
    
    "animations": {
        # 动画效果配置
        "fade_duration": 300,
        "slide_duration": 250,
        "bounce_duration": 400
    }
}

# 🌈 子阶段指示器样式
SUBSTAGE_INDICATOR_STYLES = {
    "completed": """
        QPushButton {
            background-color: #10b981;
            border: 2px solid #065f46;
            border-radius: 8px;
            color: white;
            font-weight: bold;
            padding: 4px 8px;
            margin: 2px;
            min-width: 60px;
        }
    """,
    
    "current": """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b82f6, stop:1 #1d4ed8);
            border: 2px solid #1e40af;
            border-radius: 8px;
            color: white;
            font-weight: bold;
            padding: 4px 8px;
            margin: 2px;
            min-width: 60px;
            animation: pulse 2s infinite;
        }
        
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #2563eb, stop:1 #1e40af);
        }
    """,
    
    "pending": """
        QPushButton {
            background-color: #e5e7eb;
            border: 2px solid #d1d5db;
            border-radius: 8px;
            color: #6b7280;
            font-weight: normal;
            padding: 4px 8px;
            margin: 2px;
            min-width: 60px;
        }
    """
}

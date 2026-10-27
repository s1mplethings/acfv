# 自定义输出文件夹名称 - 避免 _internal 文件夹

## 问题说明

PyInstaller 默认会创建一个名为 `_internal` 的文件夹来存放所有依赖文件。这个名称可能不够友好，我们可以通过自定义输出名称来改变它。

## 使用方法

### 1. 基本用法

```bash
# 使用默认名称 InterestRating
python build_with_pyinstaller.py

# 自定义名称，例如 MyApp
python build_with_pyinstaller.py --name MyApp

# 自定义名称，例如 VideoProcessor
python build_with_pyinstaller.py --name VideoProcessor
```

### 2. 其他选项

```bash
# 仅创建spec文件
python build_with_pyinstaller.py --spec-only --name MyApp

# 仅清理构建目录
python build_with_pyinstaller.py --clean --name MyApp

# 检查依赖
python build_with_pyinstaller.py --check-deps

# 检查文件
python build_with_pyinstaller.py --check-files
```

## 输出结构

使用 `--name MyApp` 后，输出结构将变为：

```
dist/
└── MyApp/                    # 而不是 InterestRating/
    ├── MyApp.exe            # 主程序
    ├── 启动程序.bat         # 启动脚本
    ├── README.txt           # 说明文档
    ├── config.txt           # 配置文件
    ├── pr_style.qss        # 样式文件
    ├── icon.png            # 图标文件
    ├── data/               # 数据目录
    ├── cache/              # 缓存目录
    ├── modules/            # 模块目录
    ├── processing/         # 处理目录
    └── ...                 # 其他依赖文件
```

## 优势

1. **避免 _internal 名称**：输出文件夹使用您指定的名称
2. **更友好的命名**：可以使用有意义的名称，如 `VideoProcessor`、`ChatAnalyzer` 等
3. **保持一致性**：exe文件名和文件夹名称保持一致
4. **易于分发**：最终用户看到的文件夹名称更加直观

## 注意事项

1. 名称不能包含特殊字符（如 `\ / : * ? " < > |`）
2. 建议使用英文名称，避免中文字符可能导致的编码问题
3. 名称长度建议不超过50个字符
4. 如果名称包含空格，建议用下划线或连字符替代

## 示例

```bash
# 创建一个名为 VideoProcessor 的应用
python build_with_pyinstaller.py --name VideoProcessor

# 创建一个名为 ChatAnalyzer 的应用
python build_with_pyinstaller.py --name ChatAnalyzer

# 创建一个名为 StreamProcessor 的应用
python build_with_pyinstaller.py --name StreamProcessor
```

这样，您就可以完全避免 `_internal` 文件夹名称，使用更加友好和直观的文件夹名称！

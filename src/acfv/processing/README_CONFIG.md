# 说话人分离模块配置说明

## 配置 HuggingFace Token

为了使用说话人分离功能，您需要配置 HuggingFace Token。

### 步骤：

1. **获取 HuggingFace Token**
   - 访问 https://huggingface.co/settings/tokens
   - 创建一个新的访问令牌（Access Token）
   - 确保令牌有读取权限

2. **配置 Token**
   - 复制 `config.json.example` 文件为 `config.json`
   - 在 `config.json` 中将 `your_huggingface_token_here` 替换为您的实际token

   ```bash
   cp config.json.example config.json
   ```

   然后编辑 `config.json`：
   ```json
   {
     "huggingface_token": "hf_your_actual_token_here"
   }
   ```

3. **验证配置**
   您可以运行以下命令来测试配置是否正确：
   ```bash
   python config_manager.py
   ```

## 重要提示

- ⚠️ **不要将 `config.json` 文件提交到版本控制系统**
- ✅ `config.json` 已被添加到 `.gitignore` 文件中
- ✅ 只提交 `config.json.example` 作为模板
- 🔒 请妥善保管您的 HuggingFace Token

## 使用

配置完成后，您可以正常使用说话人分离功能：

```python
from speaker_separation_integration import SpeakerSeparationIntegration
from speaker_diarization_module import process_video_with_speaker_diarization

# 代码会自动从 config.json 读取 token
```

## 故障排除

如果遇到 token 相关错误：

1. 确认 `config.json` 文件存在且格式正确
2. 确认 token 是有效的 HuggingFace token
3. 确认 token 有足够的权限访问所需模型
4. 检查网络连接是否正常
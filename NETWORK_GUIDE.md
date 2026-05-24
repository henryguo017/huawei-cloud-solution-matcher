# 国内网络使用指南

## 🔧 问题原因

系统需要以下两个外部资源：

1. **向量模型下载**：`BAAI/bge-small-zh-v1.5`（约100MB）
   - 托管在 HuggingFace，国内访问困难
   - 已配置国内镜像：`hf-mirror.com`

2. **DeepSeek API**：`https://api.deepseek.com/v1`
   - 国内公司，理论上国内可访问
   - 网络不稳定时可能需要重试

---

## ✅ 已优化的配置

### 1. HuggingFace 镜像配置

代码已自动配置国内镜像：
```python
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
```

**首次运行时会自动下载模型**，使用国内镜像源。

### 2. DeepSeek API

您已配置 DeepSeek API：
```
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-521ad10aad5a44b181881461ab7e941b
```

DeepSeek 是国内公司，API 应该可以在国内访问。

---

## 🚀 使用步骤

### 步骤 1: 首次运行（需要网络）

```bash
# 启动API服务
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

**首次运行会看到：**
```
⏳ 首次运行，正在下载向量模型（约100MB）...
💡 使用国内镜像源: hf-mirror.com
```

**等待下载完成：**
```
✅ 向量模型下载完成！
```

### 步骤 2: 后续运行（无需网络）

模型下载后会缓存在本地，后续运行**不需要再下载**，无需VPN。

---

## 🔍 如果仍然无法访问

### 方案 A: 使用预下载模型

1. **手动下载模型**：
   - 访问：https://hf-mirror.com/BAAI/bge-small-zh-v1.5
   - 下载所有文件到 `data/embedding_model/` 目录

2. **目录结构**：
   ```
   data/
   └── embedding_model/
       ├── config.json
       ├── pytorch_model.bin
       ├── tokenizer.json
       └── ...
   ```

3. **重新启动服务**：
   ```
   ✅ 使用本地向量模型: data/embedding_model
   ```

### 方案 B: 使用更小的模型

修改 `app/models/llm.py`，使用更小的模型：
```python
# 原模型（约100MB）
_local_embedding_model = SentenceTransformer('BAAI/bge-small-zh-v1.5')

# 更小的模型（约30MB，但效果略差）
_local_embedding_model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
```

### 方案 C: 禁用向量模型（不推荐）

如果实在无法下载，可以暂时禁用向量功能（但会影响匹配准确率）。

---

## 🌐 DeepSeek API 问题排查

### 测试 API 连接

```python
# 测试脚本
import requests

url = "https://api.deepseek.com/v1/chat/completions"
headers = {
    "Authorization": "Bearer sk-521ad10aad5a44b181881461ab7e941b",
    "Content-Type": "application/json"
}
data = {
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "你好"}],
    "temperature": 0.1
}

try:
    response = requests.post(url, headers=headers, json=data, timeout=10)
    print("✅ DeepSeek API 连接成功")
    print("响应:", response.json()["choices"][0]["message"]["content"])
except Exception as e:
    print("❌ 连接失败:", e)
```

### 如果 API 无法访问

1. **检查网络**：确保能访问 `api.deepseek.com`
2. **检查密钥**：确认 API Key 正确
3. **添加重试**：代码中添加重试机制
4. **使用代理**：如果网络环境特殊，配置系统代理

---

## 📊 性能优化

### 1. 模型缓存位置

默认缓存位置：
- Windows: `C:\Users\用户名\.cache\huggingface\`
- Linux/Mac: `~/.cache/huggingface/`

可以设置自定义位置：
```python
os.environ['TRANSFORMERS_CACHE'] = './data/model_cache'
```

### 2. 网络超时设置

为 API 请求添加超时：
```python
response = requests.post(url, headers=headers, json=data, timeout=30)
```

---

## ✅ 验证是否正常工作

### 启动服务后检查

1. **控制台输出**：
   ```
   ✅ 使用本地向量模型: ...
   或
   ✅ 向量模型下载完成！
   ```

2. **访问健康检查**：
   ```
   http://localhost:8000/api/health
   ```

3. **测试匹配功能**：
   - 输入需求
   - 点击"开始匹配"
   - 查看是否返回结果

---

## 🆘 常见问题

### Q1: 模型下载很慢怎么办？
A: 使用国内镜像已优化，如果还是慢，可以手动下载后放到本地目录。

### Q2: 提示"向量模型加载失败"？
A: 检查网络连接，或使用预下载模型方案。

### Q3: DeepSeek API 超时？
A: 增加超时时间，或检查网络环境。

### Q4: 能否完全离线使用？
A: 首次运行需要网络下载模型，之后可以离线使用（但需要 DeepSeek API）。

### Q5: 有没有其他向量模型选择？
A: 可以使用其他支持中文的模型：
- `BAAI/bge-base-zh-v1.5`（更大更准确，约400MB）
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`（更小更快，约30MB）

---

## 📞 技术支持

如果以上方案都无法解决，请提供：
1. 错误信息截图
2. 网络环境描述
3. Python 版本和依赖列表

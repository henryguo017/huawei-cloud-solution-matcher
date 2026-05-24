# 快速启动指南

## 🚀 立即开始使用

### 修复说明

✅ **已修复的问题：**
1. 下拉选项文字不可见 → 已修复为高对比度样式
2. 输入验证过于严格 → 已放宽到最少1个字符
3. 知识库为空时无法匹配 → AI现在可以基于通用知识给出建议

### 启动步骤

#### 1. 启动 API 服务

**Windows:**
```bash
.\start_api.bat

#或者手动执行：python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Linux/Mac:**
```bash
source venv/bin/activate
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 2. 配置 API 密钥

确保 `.env` 文件中配置了正确的 API 密钥：

```env
# OpenAI API（推荐）
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL_NAME=gpt-3.5-turbo-16k

# 或使用 DeepSeek API
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

#### 3. 访问应用

浏览器打开: http://localhost:8000

## 💡 功能特点

### 1. 解决方案智能匹配

**无需知识库也可使用！**

即使知识库为空，AI 也会基于华为云产品体系给出建议：
- 分析客户需求
- 推荐解决方案方向
- 列出适用的华为云产品
- 给出行动建议

**示例输入：**
- "我们是家小公司"
- "制造业企业，想做设备预测性维护"
- "教育机构，需要在线教学平台"

### 2. 竞争对手分析

**无需知识库也可使用！**

即使知识库为空，AI 也会给出竞争分析：
- 竞争对手的卖点分析
- 竞争对手的劣势分析
- 华为云的核心优势
- 销售应对建议

### 3. 知识库管理

**后续优化：**

当您准备好华为云白皮书等资料后：
1. 将文档放入 `data/sample_solutions/行业名称/` 目录
2. 在知识库管理页面点击"重建知识库"
3. AI 将基于具体资料给出更精准的建议

## 📂 准备知识库文档

### 文档格式
- 支持 PDF 和 TXT 格式
- 每个行业一个文件夹

### 文件夹结构
```
data/sample_solutions/
├── 智慧农业/
│   ├── 华为云智慧农业解决方案.pdf
│   └── 智慧农业案例集.txt
├── 工业互联网/
│   └── 工业互联网白皮书.pdf
├── 智慧园区/
├── 智慧教育/
└── ...
```

### 重建知识库

1. 前端界面：知识库管理 → 重建知识库
2. 或调用 API：
```bash
curl -X POST http://localhost:8000/api/knowledge/rebuild
```

## 🔍 测试示例

### 测试解决方案匹配
```bash
curl -X POST http://localhost:8000/api/match \
  -H "Content-Type: application/json" \
  -d '{"demand": "我们是家小公司"}'
```

### 测试竞争对手分析
```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"competitor": "阿里云", "industry": "智慧农业"}'
```

## ⚠️ 注意事项

1. **API 密钥必填**：确保配置了 OpenAI 或 DeepSeek API 密钥
2. **网络连接**：确保能访问 OpenAI/DeepSeek API
3. **首次启动**：首次调用 API 可能需要几秒钟初始化

## 🐛 故障排查

### 问题：API 启动失败
- 检查 Python 版本是否 3.8+
- 检查依赖是否安装：`pip install -r requirements.txt`
- 检查 `.env` 文件是否存在

### 问题：匹配失败
- 检查 API 密钥是否正确
- 检查网络连接
- 查看控制台日志

### 问题：下拉选项不可见
- 已修复！请刷新浏览器页面
- 按 Ctrl+F5 强制刷新

---

**现在就可以开始使用了！** 🎉

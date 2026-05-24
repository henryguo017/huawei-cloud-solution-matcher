# 国内网络环境适配 - 编码任务规划

## 1. 配置模块扩展

### 1.1 扩展配置文件（app/config.py）
- [ ] 添加阿里云百炼LLM配置项
  - 在 `app/config.py` 中添加 `ALIYUN_API_KEY`、`ALIYUN_MODEL_NAME`、`ALIYUN_BASE_URL`、`ALIYUN_TEMPERATURE` 配置项
  - 从环境变量读取配置，设置合理的默认值
  - API端点默认值：`https://dashscope.aliyuncs.com/api/v1`
  - 模型默认值：`qwen-turbo`

- [ ] 添加百度文心LLM配置项
  - 在 `app/config.py` 中添加 `BAIDU_API_KEY`、`BAIDU_SECRET_KEY`、`BAIDU_MODEL_NAME`、`BAIDU_BASE_URL`、`BAIDU_TEMPERATURE` 配置项
  - 百度文心需要两个密钥：API_KEY 和 SECRET_KEY
  - API端点默认值：`https://aip.baidubce.com/rpc/2.0/ai_custom/v1`
  - 模型默认值：`ernie-bot`

- [ ] 添加向量模型镜像配置项
  - 添加 `EMBEDDING_MODEL_NAME`（默认：`BAAI/bge-small-zh-v1.5`）
  - 添加 `EMBEDDING_MODEL_LOCAL_PATH`（默认：`./data/embedding_model`）
  - 添加 `HF_ENDPOINT`（默认：`https://hf-mirror.com`）用于国内镜像加速

- [ ] 添加网络环境配置项
  - 添加 `OFFLINE_MODE` 配置开关（默认：`false`）
  - 添加 `REQUEST_TIMEOUT`（默认：`30`秒）
  - 添加 `MAX_RETRIES`（默认：`3`次）
  - 添加 `RETRY_INTERVAL`（默认：`2`秒）
  - 添加 `DETECTION_TIMEOUT`（默认：`5`秒）用于网络检测

- [ ] 添加配置验证函数
  - 创建 `validate_config()` 函数
  - 验证当前选择的LLM提供商对应的API密钥是否已配置
  - 验证配置值范围（如temperature在[0, 2]之间）
  - 验证失败时抛出清晰的错误信息，指导用户如何配置

**验证方法**：
- 在Python交互环境中导入 `app.config`，确认所有新增配置项正常加载
- 调用 `validate_config()` 验证配置完整性
- 测试配置缺失时的错误提示是否清晰友好

---

## 2. LLM服务重构

### 2.1 实现LLM提供商抽象基类
- [ ] 创建LLM提供商抽象基类
  - 在 `app/models/llm.py` 中定义 `LLMProvider` 抽象基类
  - 定义抽象方法：`chat(prompt: str, temperature: float) -> str`
  - 定义抽象方法：`test_connection() -> bool`
  - 定义公共方法：`_retry_request()` 实现重试机制包装器

### 2.2 实现LLM工厂模式
- [ ] 创建LLM工厂类
  - 在 `app/models/llm.py` 中创建 `LLMFactory` 类
  - 实现提供商注册表：`_providers = {"deepseek": DeepSeekProvider, "aliyun": AliyunProvider, ...}`
  - 实现 `create(provider_name, config)` 方法，根据配置创建对应提供商实例
  - 实现配置验证逻辑，确保必需的配置项存在

- [ ] 重构现有LLM调用接口
  - 修改 `get_llm(provider, temperature)` 函数，使用工厂模式创建实例
  - 保持 `get_llm_response(prompt)` 接口不变，确保向后兼容
  - 添加新接口 `test_llm_connection(provider)` 用于测试连接

### 2.3 实现DeepSeek适配器
- [ ] 创建DeepSeek提供商适配器类
  - 在 `app/models/llm.py` 中创建 `DeepSeekProvider` 类，继承 `LLMProvider`
  - 实现与现有DeepSeek调用逻辑相同的 `chat()` 方法
  - 实现 `test_connection()` 方法，发送测试请求验证API可用性
  - 使用配置中的 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_API_KEY`
  - 实现重试机制：失败时自动重试最多3次，间隔2秒

**验证方法**：
- 配置有效的DEEPSEEK_API_KEY，调用 `test_llm_connection("deepseek")` 确认返回True
- 调用 `get_llm(provider="deepseek")` 获取LLM函数，发送测试对话
- 模拟API密钥错误，验证错误信息清晰友好

### 2.4 实现阿里云百炼适配器
- [ ] 创建阿里云百炼提供商适配器类
  - 在 `app/models/llm.py` 中创建 `AliyunProvider` 类，继承 `LLMProvider`
  - 实现 `chat()` 方法，调用阿里云百炼API（通义千问）
  - 阿里云API格式：POST请求到 `https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation`
  - 请求头：`Authorization: Bearer {API_KEY}`
  - 请求体：包含model、input.prompt、parameters.temperature
  - 实现 `test_connection()` 方法

- [ ] 处理阿里云API响应格式
  - 解析阿里云百炼特有的响应格式
  - 提取生成文本：`response.json()["output"]["text"]`
  - 处理阿里云特有的错误码和错误信息

**验证方法**：
- 配置有效的ALIYUN_API_KEY，测试连接和对话功能
- 验证响应解析正确，能提取出生成的文本内容

### 2.5 实现百度文心适配器
- [ ] 创建百度文心提供商适配器类
  - 在 `app/models/llm.py` 中创建 `BaiduProvider` 类，继承 `LLMProvider`
  - 百度文心需要先获取access_token：使用API_KEY和SECRET_KEY调用OAuth接口
  - 实现 `chat()` 方法，调用百度文心API
  - 请求格式：POST到 `{BASE_URL}/wenxin/chat?access_token={token}`
  - 实现 `test_connection()` 方法

- [ ] 实现百度文心access_token管理
  - 实现 `get_access_token()` 方法，调用百度OAuth接口获取token
  - 缓存access_token，避免频繁请求（百度token有效期30天）
  - token过期时自动刷新

**验证方法**：
- 配置有效的BAIDU_API_KEY和BAIDU_SECRET_KEY
- 测试access_token获取、缓存和刷新逻辑
- 测试对话功能，验证响应解析正确

### 2.6 实现OpenAI适配器（VPN环境）
- [ ] 重构现有OpenAI调用逻辑为适配器模式
  - 在 `app/models/llm.py` 中创建 `OpenAIProvider` 类，继承 `LLMProvider`
  - 将现有OpenAI调用代码迁移到适配器中
  - 实现 `chat()` 和 `test_connection()` 方法
  - 保持与原有功能完全兼容

**验证方法**：
- 在VPN环境下测试OpenAI适配器的连接和对话功能
- 确认与原有OpenAI调用行为一致

---

## 3. 向量模型加载优化

### 3.1 实现向量模型智能加载策略
- [ ] 创建向量模型加载器类
  - 在 `app/models/llm.py` 中创建 `EmbeddingModelLoader` 类
  - 实现三级加载策略：本地缓存 > 国内镜像 > 官核方源

- [ ] 实现本地模型检测和加载
  - 实现 `_check_local_model(path)` 方法，检查本地模型文件是否存在
  - 检查关键文件：`config.json`、`pytorch_model.bin`、`tokenizer.json`
  - 实现 `_load_from_local(path)` 方法，从本地加载模型

- [ ] 实现镜像源下载逻辑
  - 在下载前设置环境变量：`os.environ['HF_ENDPOINT'] = HF_ENDPOINT`
  - 使用配置中的镜像URL（默认：`https://hf-mirror.com`）
  - 下载后自动缓存到 `EMBEDDING_MODEL_LOCAL_PATH` 目录

- [ ] 实现离线模式处理
  - 检查 `OFFLINE_MODE` 配置，离线模式下禁止联网下载
  - 离线模式下，如果本地模型不存在，抛出明确的错误提示
  - 提示用户手动下载模型或关闭离线模式

- [ ] 重构现有向量模型加载代码
  - 修改现有的 `SentenceTransformer` 加载代码，使用新的加载器
  - 保持 `get_embedding_vector()` 和 `LocalEmbeddings` 接口不变
  - 添加详细的加载日志，显示加载策略和路径

**验证方法**：
- 删除本地模型，测试从镜像下载功能
- 测试本地模型存在时直接加载功能
- 测试离线模式下缺少模型时的错误提示

---

## 4. 网络环境检测工具

### 4.1 创建网络检测工具模块
- [ ] 创建 `app/utils/network_checker.py` 文件
  - 创建 `NetworkChecker` 类
  - 定义检测目标配置：DeepSeek API、阿里云百炼API、百度文心API、HuggingFace镜像、PyPI镜像
  - 每个目标包含：url、timeout、description

### 4.2 实现端点连通性检测
- [ ] 实现 `test_endpoint(url, timeout)` 方法
  - 使用requests库发送HEAD或GET请求测试连通性
  - 记录响应时间（毫秒）
  - 捕获异常，返回连接状态和错误信息
  - 超时时间使用配置中的 `DETECTION_TIMEOUT`

- [ ] 实现 `detect_all()` 方法
  - 并发检测所有预定义的端点（使用ThreadPoolExecutor）
  - 返回每个端点的状态：accessible、response_time、error_message
  - 记录总检测时间

### 4.3 实现配置建议生成
- [ ] 实现 `generate_suggestions(results)` 方法
  - 根据检测结果生成智能配置建议
  - 如果DeepSeek API可达，建议使用DeepSeek作为LLM提供商
  - 如果HuggingFace镜像不可达，提示配置问题
  - 如果所有国内LLM API不可达，建议检查网络或使用VPN
  - 返回建议列表，每条建议清晰易懂

### 4.4 实现网络检测报告数据结构
- [ ] 定义 `EndpointStatus` 数据类
  - 字段：name、url、accessible、response_time、error_message
  - 使用 `@dataclass` 装饰器

- [ ] 定义 `NetworkReport` 数据类
  - 字段：deepseek_api、aliyun_api、baidu_api、huggingface_mirror、pypi_mirror、suggestions、timestamp
  - 实现 `is_usable()` 方法：判断至少有一个LLM API可达且HuggingFace镜像可达
  - 实现 `get_available_providers()` 方法：返回可用的LLM提供商列表

### 4.5 实现命令行检测接口
- [ ] 实现 `detect_network_environment()` 函数
  - 封装 `NetworkChecker` 的使用
  - 返回 `NetworkReport` 对象
  - 可在命令行直接调用：`python -m app.utils.network_checker`

- [ ] 实现检测报告格式化输出
  - 实现 `print_report(report)` 函数
  - 以表格形式显示各端点状态
  - 使用✅和❌图标直观显示连通性
  - 打印配置建议列表

**验证方法**：
- 在国内网络环境下运行检测，确认DeepSeek API和HuggingFace镜像可达
- 模拟网络异常，验证检测超时和错误处理
- 验证配置建议的准确性和可读性

---

## 5. 模型下载辅助工具

### 5.1 创建模型下载工具模块
- [ ] 创建 `app/utils/model_downloader.py` 文件
  - 创建 `ModelDownloader` 类
  - 支持下载sentence-transformers向量模型

### 5.2 实现模型下载功能
- [ ] 实现 `download_embedding_model(model_name, save_path, mirror_url)` 方法
  - 设置HuggingFace镜像源环境变量
  - 使用 `sentence_transformers.SentenceTransformer` 下载模型
  - 自动保存到指定目录
  - 显示下载进度和预计时间

- [ ] 实现 `download_with_progress()` 方法
  - 显示下载进度条（使用tqdm库）
  - 显示下载速度和剩余时间
  - 支持断点续传（如果已部分下载）

### 5.3 实现模型验证功能
- [ ] 实现 `validate_model_files(model_path)` 方法
  - 检查模型目录结构完整性
  - 验证必需文件：`config.json`、`pytorch_model.bin`、`tokenizer.json`、`vocab.txt`等
  - 计算并验证文件大小是否合理
  - 返回验证结果和缺失文件列表

### 5.4 实现命令行下载接口
- [ ] 实现 `download_default_model()` 函数
  - 下载默认向量模型：`BAAI/bge-small-zh-v1.5`
  - 保存到默认路径：`./data/embedding_model`
  - 使用默认镜像：`https://hf-mirror.com`

- [ ] 添加命令行参数支持
  - 支持通过命令行指定模型名称、保存路径、镜像源
  - 例如：`python -m app.utils.model_downloader --model BAAI/bge-small-zh-v1.5 --mirror https://hf-mirror.com`

**验证方法**：
- 运行模型下载工具，确认模型能成功下载到指定目录
- 验证下载的模型文件完整性
- 测试模型加载功能，确认下载的模型可正常使用

---

## 6. 启动脚本和部署辅助

### 6.1 创建Windows启动脚本
- [ ] 创建 `start_domestic.bat` 文件
  - 添加注释说明：用于国内网络环境启动系统
  - 设置PyPI镜像源：`pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple`
  - 设置HuggingFace镜像环境变量：`set HF_ENDPOINT=https://hf-mirror.com`
  - 检查Python环境是否存在
  - 检查虚拟环境，如不存在则创建
  - 安装依赖：`pip install -r requirements.txt`
  - 启动应用：`python app/main.py`（或正确的启动命令）

- [ ] 添加网络环境自动检测
  - 在启动前运行网络检测工具
  - 如果检测失败，显示警告和配置建议
  - 提供选项：继续启动 / 取消启动 / 查看详细报告

### 6.2 创建Linux/Mac启动脚本
- [ ] 创建 `start_domestic.sh` 文件
  - 功能与Windows版本相同
  - 使用bash脚本语法
  - 设置环境变量：`export HF_ENDPOINT=https://hf-mirror.com`
  - 添加执行权限说明

### 6.3 创建离线模式启动脚本
- [ ] 创建 `start_offline.bat` 和 `start_offline.sh` 文件
  - 设置 `OFFLINE_MODE=true` 环境变量
  - 启动前检查本地模型文件是否存在
  - 如果模型文件缺失，显示错误和手动下载指引
  - 启动应用

**验证方法**：
- 在Windows环境下运行 `start_domestic.bat`，确认能正常启动
- 验证环境变量设置生效
- 测试网络自动检测功能

---

## 7. 配置文件更新

### 7.1 更新 .env.example 文件
- [ ] 添加LLM提供商选择说明
  - 添加配置项：`LLM_PROVIDER=deepseek`
  - 添加注释说明可选值：deepseek / aliyun / baidu / openai

- [ ] 添加DeepSeek配置示例
  - 添加 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL_NAME`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_TEMPERATURE`
  - 提供默认值和获取API Key的链接

- [ ] 添加阿里云百炼配置示例
  - 添加 `ALIYUN_API_KEY`、`ALIYUN_MODEL_NAME`、`ALIYUN_BASE_URL`、`ALIYUN_TEMPERATURE`
  - 添加注释说明如何获取阿里云百炼API Key

- [ ] 添加百度文心配置示例
  - 添加 `BAIDU_API_KEY`、`BAIDU_SECRET_KEY`、`BAIDU_MODEL_NAME`、`BAIDU_BASE_URL`、`BAIDU_TEMPERATURE`
  - 添加注释说明如何获取百度文心API Key和Secret Key

- [ ] 添加向量模型配置示例
  - 添加 `EMBEDDING_MODEL_NAME`、`EMBEDDING_MODEL_LOCAL_PATH`、`HF_ENDPOINT`
  - 说明HuggingFace镜像的作用和使用场景

- [ ] 添加网络环境配置示例
  - 添加 `OFFLINE_MODE`、`REQUEST_TIMEOUT`、`MAX_RETRIES`、`RETRY_INTERVAL`
  - 说明离线模式的使用场景和前提条件

**验证方法**：
- 复制 `.env.example` 为 `.env`，填写真实API Key
- 启动应用，确认配置加载成功
- 验证配置项的注释清晰易懂

---

## 8. 文档更新

### 8.1 创建国内网络安装指南
- [ ] 创建 `docs/installation_cn.md` 文件
  - 编写国内网络环境安装步骤
  - 说明PyPI镜像配置方法（清华源、阿里源等）
  - 说明HuggingFace镜像配置方法
  - 说明各LLM提供商的API Key获取方法
  - 提供常见问题FAQ

- [ ] 编写配置说明章节
  - 详细说明 `.env` 文件配置方法
  - 说明各配置项的含义和作用
  - 提供配置示例和最佳实践

- [ ] 编写离线模式使用指南
  - 说明离线模式的适用场景
  - 说明如何预先下载模型文件
  - 说明离线模式下的功能限制

### 8.2 更新 README.md
- [ ] 添加国内网络适配说明章节
  - 在README中添加新章节：国内网络环境适配
  - 说明系统支持国内网络环境运行
  - 提供快速开始指引，链接到详细文档

- [ ] 更新功能特性列表
  - 添加：支持DeepSeek、阿里云百炼、百度文心等国内LLM
  - 添加：支持HuggingFace国内镜像加速
  - 添加：支持离线运行模式
  - 添加：网络环境自动检测功能

**验证方法**：
- 按照安装指南在新环境重新安装，确认步骤准确无误
- 请团队成员review文档，确认表述清晰易懂

---

## 9. 单元测试

### 9.1 编写LLM适配器测试
- [ ] 创建 `tests/test_llm_providers.py` 文件
  - 测试各LLM提供商适配器的创建
  - 测试配置验证逻辑
  - 测试重试机制
  - 使用mock模拟API响应，避免真实API调用

### 9.2 编写配置验证测试
- [ ] 创建 `tests/test_config.py` 文件
  - 测试配置加载和验证
  - 测试配置缺失时的错误提示
  - 测试配置值范围验证

### 9.3 编写网络检测工具测试
- [ ] 创建 `tests/test_network_checker.py` 文件
  - 测试端点连通性检测
  - 测试配置建议生成逻辑
  - 使用mock模拟网络请求

### 9.4 编写向量模型加载测试
- [ ] 创建 `tests/test_embedding_loader.py` 文件
  - 测试本地模型检测
  - 测试加载策略选择
  - 测试离线模式处理

**验证方法**：
- 运行所有单元测试，确认测试覆盖率>80%
- 使用pytest生成测试报告

---

## 10. 集成测试和验证

### 10.1 功能集成测试
- [ ] 测试DeepSeek LLM完整调用流程
  - 配置DeepSeek API Key
  - 启动应用
  - 执行解决方案匹配功能
  - 验证LLM响应正确

- [ ] 测试阿里云百炼完整调用流程
  - 配置阿里云百炼 API Key
  - 切换LLM提供商为阿里云
  - 执行解决方案匹配功能
  - 验证LLM响应正确

- [ ] 测试百度文心完整调用流程
  - 配置百度文心 API Key 和 Secret Key
  - 切换LLM提供商为百度
  - 执行解决方案匹配功能
  - 验证LLM响应正确

### 10.2 向量模型加载测试
- [ ] 测试首次运行模型下载
  - 清空本地模型目录
  - 启动应用
  - 观察模型从镜像下载过程
  - 验证模型加载成功

- [ ] 测试本地模型加载
  - 确认本地模型已存在
  - 启动应用
  - 验证直接使用本地模型，不发起网络请求

- [ ] 测试离线模式
  - 设置 `OFFLINE_MODE=true`
  - 确认本地模型存在
  - 启动应用，验证正常运行
  - 删除本地模型，验证启动失败并提示明确错误

### 10.3 网络检测功能测试
- [ ] 测试网络检测命令
  - 运行网络检测工具：`python -m app.utils.network_checker`
  - 在国内网络环境下，验证检测结果显示DeepSeek API可达
  - 验证HuggingFace镜像可达
  - 验证配置建议合理

### 10.4 启动脚本测试
- [ ] 测试Windows启动脚本
  - 在Windows环境下运行 `start_domestic.bat`
  - 验证环境变量设置生效
  - 验证应用正常启动

- [ ] 测试Linux启动脚本
  - 在Linux/Mac环境下运行 `start_domestic.sh`
  - 验证脚本权限和执行
  - 验证应用正常启动

### 10.5 向后兼容性验证
- [ ] 验证原有配置仍可正常工作
  - 使用原有的 `.env` 配置（仅配置OpenAI）
  - 在VPN环境下启动应用
  - 验证所有功能正常，无breaking changes

- [ ] 验证现有业务代码无需修改
  - 检查所有调用 `get_llm_response()` 的代码
  - 确认无需修改即可正常工作
  - 检查向量数据库相关代码，确认兼容性

---

## 11. 性能和稳定性测试

### 11.1 API响应时间测试
- [ ] 测试各LLM API响应时间
  - 测试DeepSeek API平均响应时间，应<10秒
  - 测试阿里云百炼API平均响应时间
  - 测试百度文心API平均响应时间
  - 记录并对比各提供商的性能

### 11.2 重试机制测试
- [ ] 模拟API失败场景
  - 使用错误的API Key，验证重试机制触发
  - 验证最多重试3次
  - 验证重试间隔为2秒
  - 验证失败后的错误信息清晰

### 11.3 并发请求测试
- [ ] 测试并发LLM请求处理
  - 模拟多个并发对话请求
  - 验证系统稳定性
  - 验证无资源泄漏

### 11.4 长时间运行稳定性测试
- [ ] 执行持续运行测试
  - 连续运行系统1小时
  - 定期发送对话请求
  - 监控内存和CPU使用情况
  - 验证无内存泄漏

---

## 12. 最终交付验证

### 12.1 验收标准检查
- [ ] 检查所有需求规格中的功能是否实现
  - 对照 `spec.md` 中的核心能力清单
  - 逐一验证功能实现
  - 记录未完成项（如有）

- [ ] 检查所有DFX约束是否满足
  - 验证性能约束：配置加载<5秒，API响应<10秒，模型下载<5分钟
  - 验证可靠性约束：重试机制、错误提示
  - 验证安全性约束：API密钥不明文存储、不输出到日志
  - 验证可维护性约束：诊断日志、网络检测功能
  - 验证兼容性约束：保持向后兼容

### 12.2 文档完整性检查
- [ ] 检查所有文档是否完整
  - 确认 `installation_cn.md` 内容完整准确
  - 确认 `README.md` 已更新
  - 确认 `.env.example` 配置项完整
  - 确认代码注释充分

### 12.3 代码质量检查
- [ ] 运行代码质量检查工具
  - 运行pylint或flake8检查代码风格
  - 运行black格式化代码
  - 确认无严重代码质量问题

- [ ] 检查类型注解
  - 确认关键函数有类型注解
  - 使用mypy检查类型一致性

### 12.4 交付物清单确认
- [ ] 确认所有修改文件已提交
  - `app/config.py` - 扩展配置
  - `app/models/llm.py` - LLM工厂和适配器
  - `app/utils/network_checker.py` - 网络检测工具（新增）
  - `app/utils/model_downloader.py` - 模型下载工具（新增）
  - `.env.example` - 配置示例更新
  - `start_domestic.bat` - 启动脚本（新增）
  - `start_domestic.sh` - 启动脚本（新增）
  - `docs/installation_cn.md` - 安装文档（新增）
  - `README.md` - 文档更新

---

## 任务依赖关系图

```
配置模块扩展 (1)
    ├─→ LLM服务重构 (2)
    │       ├─→ DeepSeek适配器 (2.3)
    │       ├─→ 阿里云适配器 (2.4)
    │       ├─→ 百度适配器 (2.5)
    │       └─→ OpenAI适配器 (2.6)
    │
    ├─→ 向量模型加载优化 (3)
    │
    ├─→ 网络检测工具 (4)
    │
    └─→ 模型下载工具 (5)

启动脚本 (6) ─→ 依赖 (1, 4, 5)
配置文件更新 (7) ─→ 依赖 (1)
文档更新 (8) ─→ 依赖 (1-7)

单元测试 (9) ─→ 依赖 (1-5)
集成测试 (10) ─→ 依赖 (1-8)
性能测试 (11) ─→ 依赖 (1-10)
最终验证 (12) ─→ 依赖 (1-11)
```

---

## 预计工时汇总

| 任务组 | 预计工时 |
|--------|---------|
| 1. 配置模块扩展 | 0.5小时 |
| 2. LLM服务重构 | 4.5小时 |
| 3. 向量模型加载优化 | 1小时 |
| 4. 网络检测工具 | 1.5小时 |
| 5. 模型下载工具 | 1小时 |
| 6. 启动脚本 | 0.5小时 |
| 7. 配置文件更新 | 0.5小时 |
| 8. 文档更新 | 1小时 |
| 9. 单元测试 | 2小时 |
| 10. 集成测试 | 2小时 |
| 11. 性能测试 | 1小时 |
| 12. 最终验证 | 0.5小时 |
| **总计** | **16小时** |

---

## 注意事项

1. **优先级说明**：
   - P0（必须完成）：任务1、2、3、7、10 - 核心功能，确保基本可用
   - P1（重要）：任务4、5、6、8 - 提升易用性
   - P2（可选）：任务9、11 - 质量保障，视时间安排

2. **风险提示**：
   - 阿里云百炼和百度文心的API接口可能与文档有差异，需要实际测试验证
   - 向量模型下载可能因网络问题失败，需要提供手动下载方案
   - 离线模式需要预先准备所有资源，文档需要详细说明

3. **测试环境**：
   - 需要准备DeepSeek、阿里云百炼、百度文心的测试账号和API Key
   - 需要在纯国内网络环境（无VPN）下测试
   - 需要在离线环境下测试离线模式

4. **验收标准**：
   - 所有P0任务必须完成
   - 核心功能测试通过率100%
   - 文档完整、准确、易懂
   - 代码质量检查无严重问题

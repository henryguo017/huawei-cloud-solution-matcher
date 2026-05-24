# 登录系统实现任务清单

## 1. 环境配置与依赖准备

### 1.1 后端依赖安装
- [ ] 在 `requirements.txt` 中添加认证相关依赖包：
  - `PyJWT>=2.8.0` - JWT Token生成与验证
  - `passlib[bcrypt]>=1.7.4` - 密码加密（bcrypt算法）
  - `Pillow>=10.0.0` - 图形验证码生成
  - `python-multipart>=0.0.6` - 表单数据处理
- [ ] 执行 `pip install -r requirements.txt` 安装新增依赖
- [ ] 验证所有依赖包安装成功，无版本冲突
- [ ] 验收标准：所有依赖包成功安装，import测试通过
- [ ] 优先级：P0（最高）
- [ ] 估算工时：0.5小时

### 1.2 配置文件扩展
- [ ] 在 `app/config.py` 中添加JWT配置项：
  - JWT_SECRET_KEY（密钥）
  - JWT_ALGORITHM（算法，默认HS256）
  - JWT_ACCESS_TOKEN_EXPIRE_MINUTES（过期时间，默认1440分钟）
- [ ] 添加验证码配置项：
  - CAPTCHA_LENGTH（验证码长度，默认4）
  - CAPTCHA_EXPIRE_MINUTES（有效期，默认5分钟）
- [ ] 添加登录安全配置项：
  - MAX_LOGIN_ATTEMPTS（最大失败次数，默认5）
  - LOCK_DURATION_MINUTES（锁定时长，默认15分钟）
- [ ] 添加密码强度配置项：
  - MIN_PASSWORD_LENGTH（最小长度，默认6）
  - MAX_PASSWORD_LENGTH（最大长度，默认50）
  - BCRYPT_ROUNDS（加密轮数，默认12）
- [ ] 添加用户限制配置项：
  - MAX_FAVORITES_PER_USER（最大收藏数，默认100）
- [ ] 添加数据库配置项：
  - DATABASE_URL（数据库连接字符串）
- [ ] 在 `.env` 文件中添加对应环境变量（生产环境需修改JWT密钥）
- [ ] 验收标准：所有配置项可正常读取，配置验证通过
- [ ] 优先级：P0
- [ ] 估算工时：1小时
- [ ] 依赖：任务1.1

---

## 2. 数据层实现

### 2.1 数据库初始化
- [ ] 创建目录 `app/utils/`（如不存在）
- [ ] 创建数据库初始化脚本 `app/utils/db_init.py`：
  - 创建用户表（users）及约束、索引
  - 创建历史记录表（history）及外键约束、索引
  - 创建收藏表（favorites）及唯一约束、索引
  - 创建用户偏好设置表（user_preferences）及索引
  - 创建验证码表（captchas）及索引
  - 创建登录日志表（login_logs）及索引
  - 添加CHECK约束确保数据有效性
- [ ] 实现数据库表结构创建函数 `init_database()`
- [ ] 在 `app/main.py` 启动时调用数据库初始化
- [ ] 验证数据库文件 `data/users.db` 正确生成
- [ ] 验收标准：所有表结构创建成功，索引正常，外键约束生效
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务1.2

### 2.2 默认管理员账户初始化
- [ ] 创建管理员初始化脚本 `app/utils/admin_init.py`：
  - 检查是否存在管理员账户
  - 如不存在则创建默认管理员（username: admin, password: admin123）
  - 使用bcrypt加密默认密码
  - 记录创建时间戳
- [ ] 在数据库初始化后自动调用管理员初始化
- [ ] 添加生产环境警告提示（提醒修改默认密码）
- [ ] 验收标准：默认管理员账户创建成功，可正常登录
- [ ] 优先级：P0
- [ ] 估算工时：1小时
- [ ] 依赖：任务2.1

### 2.3 数据模型定义
- [ ] 创建目录 `app/models/`（如不存在）
- [ ] 创建 `app/models/__init__.py` 导出所有模型
- [ ] 创建用户模型 `app/models/user.py`：
  - 定义User SQLAlchemy模型类，映射users表
  - 定义UserCreate Pydantic模型（注册请求）
  - 定义UserLogin Pydantic模型（登录请求）
  - 定义UserResponse Pydantic模型（用户信息响应）
  - 定义UserUpdate Pydantic模型（用户更新请求）
- [ ] 创建历史记录模型 `app/models/history.py`：
  - 定义History SQLAlchemy模型类
  - 定义HistoryCreate Pydantic模型
  - 定义HistoryResponse Pydantic模型
- [ ] 创建收藏模型 `app/models/favorite.py`：
  - 定义Favorite SQLAlchemy模型类
  - 定义FavoriteCreate Pydantic模型
  - 定义FavoriteResponse Pydantic模型
- [ ] 创建认证模型 `app/models/auth.py`：
  - 定义Token Pydantic模型（Token响应）
  - 定义TokenData Pydantic模型（Token载荷）
  - 定义Captcha Pydantic模型（验证码响应）
  - 定义LoginLog SQLAlchemy模型类
- [ ] 验收标准：所有模型类定义完整，Pydantic验证正常，SQLAlchemy映射正确
- [ ] 优先级：P0
- [ ] 估算工时：3小时
- [ ] 依赖：任务2.1

### 2.4 数据仓储层实现
- [ ] 创建目录 `app/repositories/`（如不存在）
- [ ] 创建 `app/repositories/__init__.py` 导出所有仓储
- [ ] 创建用户仓储 `app/repositories/user_repository.py`：
  - 实现用户插入 `insert(user_data)`
  - 实现按ID查询 `find_by_id(user_id)`
  - 实现按用户名查询 `find_by_username(username)`
  - 实现按邮箱查询 `find_by_email(email)`
  - 实现用户更新 `update(user_id, update_data)`
  - 实现用户状态更新 `update_status(user_id, status)`
  - 实现失败计数更新 `update_failed_count(user_id, count)`
  - 实现锁定时间更新 `update_locked_until(user_id, locked_until)`
  - 实现最后登录时间更新 `update_last_login(user_id)`
  - 实现用户列表查询 `find_all(page, page_size, status)`
- [ ] 创建历史记录仓储 `app/repositories/history_repository.py`：
  - 实现历史记录插入 `insert(history_data)`
  - 实现按用户ID查询 `find_by_user_id(user_id, page, page_size, query_type)`
  - 实现按ID删除 `delete(history_id)`
  - 实现按用户ID统计 `count_by_user_id(user_id)`
- [ ] 创建收藏仓储 `app/repositories/favorite_repository.py`：
  - 实现收藏插入 `insert(favorite_data)`
  - 实现按用户ID查询 `find_by_user_id(user_id, page, page_size)`
  - 实现按ID删除 `delete(favorite_id)`
  - 实现按用户ID和方案ID查询 `find_by_user_and_solution(user_id, solution_id)`
  - 实现按用户ID统计 `count_by_user_id(user_id)`
- [ ] 验收标准：所有仓储方法实现完整，数据库操作正常，异常处理完善
- [ ] 优先级：P0
- [ ] 估算工时：4小时
- [ ] 依赖：任务2.3

---

## 3. 业务层实现

### 3.1 密码加密工具
- [ ] 创建 `app/utils/password_encoder.py`：
  - 实现密码加密方法 `encode(password: str) -> str`
  - 实现密码验证方法 `verify(password: str, hashed: str) -> bool`
  - 使用passlib库的bcrypt算法
  - 配置加密轮数（从config读取BCRYPT_ROUNDS）
- [ ] 编写单元测试验证加密和验证功能
- [ ] 验收标准：密码加密后为bcrypt哈希值，验证功能正常
- [ ] 优先级：P0
- [ ] 估算工时：1小时
- [ ] 依赖：任务1.2

### 3.2 验证码生成工具
- [ ] 创建 `app/utils/captcha_generator.py`：
  - 实现验证码生成方法 `generate_captcha(length: int) -> tuple[str, str]`
  - 使用Pillow库生成图形验证码（包含随机字符、干扰线、噪点）
  - 生成随机4位验证码文本
  - 生成PNG格式的验证码图片（Base64编码）
  - 返回验证码文本和Base64图片数据
- [ ] 优化验证码图片可读性（调整字体大小、干扰线密度）
- [ ] 编写单元测试验证生成功能
- [ ] 验收标准：验证码图片清晰可辨，Base64编码正确
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务1.2

### 3.3 日志工具配置
- [ ] 创建 `app/utils/logger.py`（如不存在）：
  - 配置Loguru日志记录器
  - 设置日志格式（时间、级别、模块、消息）
  - 设置日志输出路径（data/logs/目录）
  - 设置日志轮转策略（按大小或时间）
- [ ] 在所有服务和仓储中集成日志记录
- [ ] 验收标准：日志正常输出到文件，格式清晰，包含关键信息
- [ ] 优先级：P1
- [ ] 估算工时：1小时
- [ ] 依赖：无

### 3.4 JWT服务实现
- [ ] 创建目录 `app/services/`（如不存在）
- [ ] 创建 `app/services/jwt_service.py`：
  - 实现Token生成方法 `generate_token(user_id: str, role: str) -> str`
  - 实现Token验证方法 `verify_token(token: str) -> TokenData`
  - 实现Token解码方法 `decode_token(token: str) -> dict`
  - 实现Token刷新方法 `refresh_token(token: str) -> str`
  - 使用PyJWT库，配置HS256算法
  - 设置Token过期时间（从config读取）
  - 设置Token载荷（user_id, role, exp, iat）
  - 异常处理：Token过期、Token无效、Token被篡改
- [ ] 编写单元测试验证Token生成和验证功能
- [ ] 验收标准：Token生成正确，验证功能正常，异常处理完善
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务1.2, 任务2.3

### 3.5 验证码服务实现
- [ ] 创建 `app/services/captcha_service.py`：
  - 实现验证码生成方法 `generate_captcha() -> CaptchaResponse`
  - 实现验证码验证方法 `validate_captcha(captcha_id: str, captcha_text: str) -> bool`
  - 使用验证码生成工具生成验证码
  - 将验证码保存到数据库（captchas表）
  - 验证时检查验证码是否过期（5分钟有效期）
  - 验证后标记验证码为已使用
  - 实现过期验证码清理方法 `clean_expired_captchas()`
- [ ] 编写单元测试验证验证码生成和验证功能
- [ ] 验收标准：验证码生成正确，验证逻辑正常，过期处理正确
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务3.2, 任务2.4

### 3.6 用户服务实现
- [ ] 创建 `app/services/user_service.py`：
  - 实现用户创建方法 `create_user(user_data: UserCreate) -> UserResponse`
  - 实现用户查询方法 `get_user_by_id(user_id: str) -> UserResponse`
  - 实现用户查询方法 `get_user_by_username(username: str) -> User`
  - 实现用户更新方法 `update_user(user_id: str, update_data: UserUpdate) -> UserResponse`
  - 实现密码重置方法 `reset_password(email: str, new_password: str) -> bool`
  - 实现用户状态更新方法 `update_user_status(user_id: str, status: str) -> bool`
  - 实现用户角色更新方法 `update_user_role(user_id: str, role: str) -> bool`
  - 用户名唯一性校验
  - 邮箱唯一性校验
  - 密码强度校验
  - 用户名格式校验
  - 邮箱格式校验
- [ ] 编写单元测试验证所有用户管理功能
- [ ] 验收标准：用户CRUD操作正常，所有校验逻辑正确
- [ ] 优先级：P0
- [ ] 估算工时：3小时
- [ ] 依赖：任务2.4, 任务3.1, 任务3.3

### 3.7 认证服务实现
- [ ] 创建 `app/services/auth_service.py`：
  - 实现用户登录方法 `login(username, password, captcha_id, captcha_text) -> Token`
  - 实现用户注册方法 `register(user_data: UserCreate) -> UserResponse`
  - 实现用户登出方法 `logout(user_id: str) -> bool`
  - 实现Token刷新方法 `refresh_token(token: str) -> Token`
  - 登录流程：
    - 验证验证码
    - 检查账户锁定状态
    - 验证用户名存在性
    - 验证密码正确性
    - 更新失败计数
    - 检查是否达到锁定阈值
    - 生成JWT Token
    - 清空失败计数
    - 记录登录日志
  - 注册流程：
    - 用户名唯一性校验
    - 格式校验（用户名、密码、邮箱）
    - 密码加密
    - 创建用户记录
    - 分配默认角色（user）
  - 异常处理：验证码错误、账户锁定、密码错误、用户名不存在
- [ ] 编写单元测试验证登录、注册、登出功能
- [ ] 验收标准：登录流程完整，注册流程完整，异常处理正确
- [ ] 优先级：P0
- [ ] 估算工时：4小时
- [ ] 依赖：任务3.4, 任务3.5, 任务3.6

### 3.8 权限服务实现
- [ ] 创建 `app/services/permission_service.py`：
  - 实现权限校验方法 `check_permission(user_id: str, required_role: str) -> bool`
  - 实现用户角色查询方法 `get_user_role(user_id: str) -> str`
  - 实现管理员判断方法 `is_admin(user_id: str) -> bool`
  - 实现用户状态检查方法 `is_user_active(user_id: str) -> bool`
  - 实现接口权限装饰器 `require_auth(role: str)`
- [ ] 编写单元测试验证权限校验功能
- [ ] 验收标准：权限校验逻辑正确，角色判断准确
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务2.4, 任务3.4

### 3.9 历史记录服务实现
- [ ] 创建 `app/services/history_service.py`：
  - 实现历史记录保存方法 `save_history(user_id: str, history_data: HistoryCreate) -> HistoryResponse`
  - 实现历史记录查询方法 `get_history(user_id: str, page: int, page_size: int, query_type: str) -> List[HistoryResponse]`
  - 实现历史记录删除方法 `delete_history(user_id: str, history_id: str) -> bool`
  - 实现历史记录统计方法 `count_history(user_id: str) -> int`
  - 数据归属校验（确保用户只能访问自己的历史记录）
- [ ] 编写单元测试验证历史记录管理功能
- [ ] 验收标准：历史记录CRUD操作正常，数据隔离正确
- [ ] 优先级：P1
- [ ] 估算工时：2小时
- [ ] 依赖：任务2.4, 任务3.3

### 3.10 收藏服务实现
- [ ] 创建 `app/services/favorite_service.py`：
  - 实现收藏添加方法 `add_favorite(user_id: str, favorite_data: FavoriteCreate) -> FavoriteResponse`
  - 实现收藏查询方法 `get_favorites(user_id: str, page: int, page_size: int) -> List[FavoriteResponse]`
  - 实现收藏删除方法 `delete_favorite(user_id: str, favorite_id: str) -> bool`
  - 实现收藏统计方法 `count_favorites(user_id: str) -> int`
  - 收藏数量限制检查（不超过100个）
  - 重复收藏检查
  - 数据归属校验
- [ ] 编写单元测试验证收藏管理功能
- [ ] 验收标准：收藏CRUD操作正常，限制检查正确
- [ ] 优先级：P1
- [ ] 估算工时：2小时
- [ ] 依赖：任务2.4, 任务3.3

---

## 4. API层实现

### 4.1 FastAPI依赖注入配置
- [ ] 创建目录 `app/dependencies/`（如不存在）
- [ ] 创建 `app/dependencies/auth.py`：
  - 实现获取当前用户依赖 `get_current_user(token: str = Depends(oauth2_scheme)) -> User`
  - 实现获取当前活跃用户依赖 `get_current_active_user(user: User = Depends(get_current_user)) -> User`
  - 实现管理员权限依赖 `get_current_admin_user(user: User = Depends(get_current_active_user)) -> User`
  - 配置OAuth2密码流方案
  - Token提取和验证
  - 异常处理：Token无效、用户不存在、用户被禁用
- [ ] 验收标准：依赖注入正确，用户提取正常
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务3.4, 任务3.8

### 4.2 认证中间件实现
- [ ] 创建目录 `app/middlewares/`（如不存在）
- [ ] 创建 `app/middlewares/auth_middleware.py`：
  - 实现认证中间件类 `AuthMiddleware`
  - 拦截所有需要认证的请求
  - 提取并验证JWT Token
  - 注入用户上下文到请求
  - 记录请求日志
  - 异常处理和错误响应
- [ ] 在 `app/main.py` 中注册中间件
- [ ] 验收标准：中间件正确拦截请求，Token验证正常
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务3.4

### 4.3 认证API路由实现
- [ ] 创建目录 `app/api/`（如不存在）
- [ ] 创建 `app/api/auth.py`：
  - 实现注册接口 `POST /api/auth/register`
  - 实现登录接口 `POST /api/auth/login`
  - 实现获取验证码接口 `GET /api/auth/captcha`
  - 实现登出接口 `POST /api/auth/logout`
  - 实现Token刷新接口 `POST /api/auth/refresh`
  - 统一响应格式封装
  - 参数校验（使用Pydantic模型）
  - 异常处理和错误码返回
  - OpenAPI文档注解（描述、参数、响应示例）
- [ ] 在 `app/main.py` 中注册认证路由
- [ ] 验收标准：所有认证接口正常工作，响应格式正确
- [ ] 优先级：P0
- [ ] 估算工时：3小时
- [ ] 依赖：任务3.7, 任务3.5, 任务4.1

### 4.4 用户API路由实现
- [ ] 创建 `app/api/users.py`：
  - 实现获取当前用户信息接口 `GET /api/users/me`
  - 实现更新当前用户信息接口 `PUT /api/users/me`
  - 实现密码重置接口 `POST /api/users/me/password/reset`
  - 使用依赖注入获取当前用户
  - 参数校验和响应封装
  - OpenAPI文档注解
- [ ] 在 `app/main.py` 中注册用户路由
- [ ] 验收标准：用户接口正常工作，权限控制正确
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务3.6, 任务4.1

### 4.5 历史记录API路由实现
- [ ] 创建 `app/api/history.py`：
  - 实现获取历史记录列表接口 `GET /api/history`
  - 实现删除历史记录接口 `DELETE /api/history/{history_id}`
  - 支持分页参数（page, page_size）
  - 支持查询类型过滤（query_type）
  - 使用依赖注入获取当前用户
  - OpenAPI文档注解
- [ ] 在 `app/main.py` 中注册历史记录路由
- [ ] 验收标准：历史记录接口正常，数据隔离正确
- [ ] 优先级：P1
- [ ] 估算工时：1.5小时
- [ ] 依赖：任务3.9, 任务4.1

### 4.6 收藏API路由实现
- [ ] 创建 `app/api/favorites.py`：
  - 实现获取收藏列表接口 `GET /api/favorites`
  - 实现添加收藏接口 `POST /api/favorites`
  - 实现删除收藏接口 `DELETE /api/favorites/{favorite_id}`
  - 支持分页参数
  - 收藏数量限制检查
  - OpenAPI文档注解
- [ ] 在 `app/main.py` 中注册收藏路由
- [ ] 验收标准：收藏接口正常，限制检查正确
- [ ] 优先级：P1
- [ ] 估算工时：1.5小时
- [ ] 依赖：任务3.10, 任务4.1

### 4.7 管理员API路由实现
- [ ] 创建 `app/api/admin.py`：
  - 实现获取用户列表接口 `GET /api/admin/users`
  - 实现更新用户状态接口 `PUT /api/admin/users/{user_id}/status`
  - 实现更新用户角色接口 `PUT /api/admin/users/{user_id}/role`
  - 使用管理员权限依赖注入
  - 权限校验（仅管理员可访问）
  - 禁止删除最后一个管理员检查
  - OpenAPI文档注解
- [ ] 在 `app/main.py` 中注册管理员路由
- [ ] 验收标准：管理员接口正常，权限控制严格
- [ ] 优先级：P1
- [ ] 估算工时：2小时
- [ ] 依赖：任务3.6, 任务3.8, 任务4.1

### 4.8 现有业务接口改造
- [ ] 改造解决方案匹配接口 `POST /api/match`：
  - 在请求处理前检查Token（可选）
  - 如果Token有效，提取用户ID
  - 执行原有匹配逻辑
  - 如果用户已登录，保存历史记录到数据库
- [ ] 改造竞争对手分析接口 `POST /api/analyze`：
  - 同上改造逻辑
- [ ] 确保改造不影响匿名用户使用
- [ ] 验收标准：业务接口改造后功能正常，历史记录自动保存
- [ ] 优先级：P1
- [ ] 估算工时：2小时
- [ ] 依赖：任务3.9, 任务4.1

---

## 5. 前端实现

### 5.1 登录页面实现
- [ ] 创建 `frontend/login.html`：
  - 设计登录表单（用户名、密码、验证码输入框）
  - 验证码图片显示区域（可点击刷新）
  - 登录按钮
  - 注册链接
  - 响应式布局（适配移动端）
  - 现代科技风格设计（参考华为云/阿里云风格）
- [ ] 创建 `frontend/auth.js`（认证相关脚本）：
  - 实现获取验证码函数 `getCaptcha()`
  - 实现登录函数 `login()`
  - 表单校验（必填项、格式校验）
  - Token存储（localStorage）
  - 错误提示显示
  - 登录成功跳转到主页
- [ ] 验收标准：登录页面显示正常，交互流畅，样式美观
- [ ] 优先级：P0
- [ ] 估算工时：3小时
- [ ] 依赖：任务4.3

### 5.2 注册页面实现
- [ ] 创建 `frontend/register.html`：
  - 设计注册表单（用户名、密码、确认密码、邮箱输入框）
  - 注册按钮
  - 登录链接
  - 密码强度提示
  - 响应式布局
  - 现代科技风格设计
- [ ] 在 `frontend/auth.js` 中添加：
  - 实现注册函数 `register()`
  - 用户名格式校验（3-20字符，字母数字下划线）
  - 密码强度校验（6-50字符）
  - 邮箱格式校验
  - 密码一致性校验
  - 注册成功跳转到登录页
- [ ] 验收标准：注册页面显示正常，校验逻辑正确
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务4.3

### 5.3 个人中心页面实现
- [ ] 创建 `frontend/profile.html`：
  - 用户信息展示区域（用户名、邮箱、角色）
  - 用户信息编辑表单
  - 密码修改表单
  - 历史记录列表展示区域
  - 收藏列表展示区域
  - 退出登录按钮
  - 响应式布局
- [ ] 创建 `frontend/profile.js`：
  - 实现获取用户信息函数 `getUserInfo()`
  - 实现更新用户信息函数 `updateUserInfo()`
  - 实现修改密码函数 `changePassword()`
  - 实现获取历史记录函数 `getHistory()`
  - 实现获取收藏列表函数 `getFavorites()`
  - 实现删除历史记录函数 `deleteHistory()`
  - 实现删除收藏函数 `deleteFavorite()`
  - Token过期处理（跳转登录页）
- [ ] 验收标准：个人中心功能完整，数据展示正确
- [ ] 优先级：P1
- [ ] 估算工时：4小时
- [ ] 依赖：任务4.4, 任务4.5, 任务4.6

### 5.4 管理员页面实现
- [ ] 创建 `frontend/admin.html`：
  - 用户列表表格展示区域
  - 用户搜索和筛选功能
  - 用户状态启用/禁用按钮
  - 用户角色修改功能
  - 分页控件
  - 响应式布局
- [ ] 在 `frontend/profile.js` 中添加管理员功能：
  - 实现获取用户列表函数 `getUserList()`
  - 实现更新用户状态函数 `updateUserStatus()`
  - 实现更新用户角色函数 `updateUserRole()`
  - 权限校验（仅管理员可访问）
- [ ] 验收标准：管理员页面功能完整，权限控制正确
- [ ] 优先级：P1
- [ ] 估算工时：3小时
- [ ] 依赖：任务4.7

### 5.5 主页改造
- [ ] 改造 `frontend/index.html`：
  - 添加导航栏（顶部）
  - 导航栏包含：Logo、主页、历史记录、收藏、个人中心、登录/注册、退出登录
  - 未登录状态显示：登录、注册按钮
  - 已登录状态显示：用户名、个人中心、退出登录
  - 集成认证状态检查
- [ ] 改造 `frontend/script.js`：
  - 实现认证状态检查函数 `checkAuthStatus()`
  - 实现退出登录函数 `logout()`
  - 根据登录状态动态更新导航栏
  - 在匹配和分析操作后自动保存历史记录（如已登录）
- [ ] 验收标准：主页导航栏显示正确，认证状态检查正常
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务5.1, 任务4.8

### 5.6 样式文件扩展
- [ ] 扩展 `frontend/style.css`：
  - 添加登录/注册页面样式
  - 添加个人中心页面样式
  - 添加管理员页面样式
  - 添加导航栏样式
  - 添加表单样式（输入框、按钮、提示）
  - 添加表格样式（用户列表、历史记录列表）
  - 添加响应式样式（移动端适配）
  - 现代科技风格设计（渐变色、阴影、圆角）
- [ ] 验收标准：所有页面样式统一美观，响应式布局正常
- [ ] 优先级：P1
- [ ] 估算工时：3小时
- [ ] 依赖：任务5.1, 任务5.2, 任务5.3, 任务5.4

---

## 6. 系统集成与测试

### 6.1 集成测试
- [ ] 编写登录流程集成测试：
  - 获取验证码 → 登录 → Token验证
- [ ] 编写注册流程集成测试：
  - 注册 → 登录 → Token验证
- [ ] 编写权限控制集成测试：
  - 普通用户访问管理员接口（应拒绝）
  - 管理员访问管理员接口（应允许）
- [ ] 编写历史记录集成测试：
  - 登录用户执行匹配 → 历史记录自动保存 → 查询历史记录
- [ ] 编写收藏功能集成测试：
  - 添加收藏 → 查询收藏 → 删除收藏
- [ ] 验收标准：所有集成测试通过
- [ ] 优先级：P0
- [ ] 估算工时：4小时
- [ ] 依赖：任务4.3, 任务4.4, 任务4.5, 任务4.6, 任务4.7

### 6.2 安全测试
- [ ] 测试密码加密：
  - 验证数据库中密码为bcrypt哈希值，非明文
- [ ] 测试SQL注入防护：
  - 尝试在用户名、密码中注入SQL语句
  - 验证系统正确处理或拒绝
- [ ] 测试XSS防护：
  - 尝试在输入中注入XSS脚本
  - 验证系统正确转义或拒绝
- [ ] 测试暴力破解防护：
  - 连续5次错误登录
  - 验证账户被锁定15分钟
- [ ] 测试Token安全：
  - 验证Token有效期（24小时）
  - 验证Token签名（伪造Token应被拒绝）
  - 验证Token过期后无法访问
- [ ] 测试权限隔离：
  - 验证用户只能访问自己的数据
  - 验证普通用户无法访问管理员功能
- [ ] 验收标准：所有安全测试通过
- [ ] 优先级：P0
- [ ] 估算工时：3小时
- [ ] 依赖：任务6.1

### 6.3 性能测试
- [ ] 测试登录响应时间：
  - 正常登录响应时间 < 2秒
- [ ] 测试Token验证时间：
  - Token验证响应时间 < 100毫秒
- [ ] 测试验证码生成时间：
  - 验证码生成时间 < 500毫秒
- [ ] 测试并发登录：
  - 模拟100个并发登录请求
  - 验证系统稳定性和数据一致性
- [ ] 测试数据库查询性能：
  - 用户查询时间 < 50毫秒（有索引）
- [ ] 验收标准：所有性能指标达标
- [ ] 优先级：P1
- [ ] 估算工时：2小时
- [ ] 依赖：任务6.1

### 6.4 前端测试
- [ ] 测试登录页面：
  - 表单校验正常
  - 验证码显示和刷新正常
  - 登录成功跳转正确
  - 错误提示显示正确
- [ ] 测试注册页面：
  - 表单校验正常
  - 注册成功跳转正确
- [ ] 测试个人中心：
  - 用户信息显示正确
  - 信息修改正常
  - 历史记录和收藏显示正确
- [ ] 测试管理员页面：
  - 用户列表显示正确
  - 状态和角色修改正常
- [ ] 测试浏览器兼容性：
  - Chrome、Firefox、Edge、Safari最新3个版本
- [ ] 测试移动端适配：
  - 响应式布局正常
- [ ] 验收标准：前端功能正常，兼容性良好
- [ ] 优先级：P1
- [ ] 估算工时：3小时
- [ ] 依赖：任务5.1, 任务5.2, 任务5.3, 任务5.4, 任务5.5

---

## 7. 文档与部署准备

### 7.1 API文档生成
- [ ] 利用FastAPI自动生成OpenAPI文档
- [ ] 访问 `/docs` 验证Swagger UI文档正确
- [ ] 访问 `/redoc` 验证ReDoc文档正确
- [ ] 检查所有接口文档注解完整（描述、参数、响应示例）
- [ ] 导出OpenAPI规范文档 `openapi.json`
- [ ] 验收标准：API文档完整准确，所有接口有详细说明
- [ ] 优先级：P1
- [ ] 估算工时：1小时
- [ ] 依赖：任务4.3, 任务4.4, 任务4.5, 任务4.6, 任务4.7

### 7.2 部署文档编写
- [ ] 创建部署文档 `DEPLOYMENT.md`：
  - 环境要求（Python版本、依赖包）
  - 配置说明（环境变量、配置文件）
  - 数据库初始化步骤
  - 默认管理员账户说明
  - 生产环境安全配置（修改JWT密钥、修改默认密码）
  - 启动命令（uvicorn）
  - HTTPS配置说明
- [ ] 验收标准：部署文档清晰完整，按文档可成功部署
- [ ] 优先级：P1
- [ ] 估算工时：1.5小时
- [ ] 依赖：无

### 7.3 用户手册编写
- [ ] 创建用户手册 `USER_GUIDE.md`：
  - 功能介绍（登录、注册、个人中心、管理员功能）
  - 操作指南（配图说明）
  - 常见问题FAQ
  - 错误码说明
- [ ] 验收标准：用户手册清晰易懂，覆盖所有功能
- [ ] 优先级：P2
- [ ] 估算工时：2小时
- [ ] 依赖：无

### 7.4 README更新
- [ ] 更新项目根目录 `README.md`：
  - 添加登录系统功能说明
  - 更新项目结构说明
  - 更新安装和运行说明
  - 添加截图或演示链接
- [ ] 验收标准：README内容完整，说明清晰
- [ ] 优先级：P2
- [ ] 估算工时：1小时
- [ ] 依赖：无

---

## 8. 最终验证与交付

### 8.1 系统整体验证
- [ ] 启动后端服务，验证所有API接口可访问
- [ ] 访问前端页面，验证所有页面正常显示
- [ ] 执行完整用户流程测试：
  - 访客访问主页 → 注册 → 登录 → 执行匹配 → 查看历史 → 收藏方案 → 个人中心修改信息 → 退出登录
- [ ] 执行管理员流程测试：
  - 管理员登录 → 查看用户列表 → 禁用用户 → 修改用户角色 → 验证权限生效
- [ ] 验证数据库数据一致性
- [ ] 验证日志记录完整
- [ ] 验收标准：系统整体运行正常，所有功能可用
- [ ] 优先级：P0
- [ ] 估算工时：2小时
- [ ] 依赖：任务6.1, 任务6.2, 任务6.3, 任务6.4

### 8.2 代码审查与优化
- [ ] 代码规范检查：
  - 代码格式符合PEP8规范
  - 命名规范统一
  - 注释和文档字符串完整
- [ ] 代码质量检查：
  - 避免硬编码
  - 异常处理完善
  - 日志记录充分
- [ ] 性能优化：
  - 数据库查询优化
  - 缓存策略考虑（验证码、Token）
- [ ] 安全检查：
  - 敏感信息不硬编码
  - 配置文件安全
- [ ] 验收标准：代码质量高，符合规范
- [ ] 优先级：P1
- [ ] 估算工时：2小时
- [ ] 依赖：任务8.1

### 8.3 交付准备
- [ ] 准备交付清单：
  - 源代码完整
  - 数据库初始化脚本
  - 配置文件模板
  - 文档完整（API文档、部署文档、用户手册）
  - 测试报告
- [ ] 准备演示环境：
  - 部署演示系统
  - 准备演示数据
  - 录制演示视频（可选）
- [ ] 验收标准：交付物完整，演示环境可用
- [ ] 优先级：P0
- [ ] 估算工时：1.5小时
- [ ] 依赖：任务7.1, 任务7.2, 任务7.3, 任务7.4, 任务8.1

---

## 任务统计总览

**总任务数**：84个子任务

**主要任务组**：
1. 环境配置与依赖准备：2个任务
2. 数据层实现：4个任务
3. 业务层实现：10个任务
4. API层实现：8个任务
5. 前端实现：6个任务
6. 系统集成与测试：4个任务
7. 文档与部署准备：4个任务
8. 最终验证与交付：3个任务

**优先级分布**：
- P0（最高优先级）：26个任务
- P1（中等优先级）：20个任务
- P2（低优先级）：3个任务

**估算总工时**：约82小时（约10个工作日）

**关键路径**：
环境配置 → 数据库初始化 → 数据模型 → 业务服务 → API路由 → 前端页面 → 集成测试 → 最终验证

**风险提示**：
1. JWT密钥安全性：生产环境必须修改默认密钥
2. 默认管理员密码：生产环境必须修改默认密码
3. HTTPS配置：生产环境必须使用HTTPS
4. 数据库备份：定期备份SQLite数据库文件

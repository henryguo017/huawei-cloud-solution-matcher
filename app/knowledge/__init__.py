"""知识库 ingestion 策略族包（ruoyi-ai 学习项 #2 可插拔 loader/splitter）。

对外保持 `app.utils.document_loader` 的 `DocumentLoader` / `load_documents_from_directory`
接口不变；新增格式只需实现 BaseLoader / BaseSplitter 并注册进 Registry，零侵入。
"""

import os
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from app.config import CHUNK_SIZE, CHUNK_OVERLAP

class DocumentLoader:
    """文档加载工具类，支持PDF和TXT格式"""
    
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
            is_separator_regex=False
        )
    
    def load_single_file(self, file_path):
        """加载单个文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == ".pdf":
            loader = PyPDFLoader(file_path)
            documents = loader.load()
        elif file_ext == ".txt":
            loader = TextLoader(file_path, encoding="utf-8")
            documents = loader.load()
        else:
            raise ValueError(f"不支持的文件格式: {file_ext}")
        
        # 添加元数据
        file_name = os.path.basename(file_path)
        industry = os.path.basename(os.path.dirname(file_path))
        
        for doc in documents:
            doc.metadata["source"] = file_name
            doc.metadata["industry"] = industry
        
        return documents
    
    def load_directory(self, directory_path):
        """加载整个目录下的所有支持的文件"""
        if not os.path.exists(directory_path):
            raise FileNotFoundError(f"目录不存在: {directory_path}")
        
        all_documents = []
        
        for root, dirs, files in os.walk(directory_path):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                file_ext = os.path.splitext(file_name)[1].lower()
                
                if file_ext in [".pdf", ".txt"]:
                    try:
                        documents = self.load_single_file(file_path)
                        all_documents.extend(documents)
                        print(f"成功加载: {file_path}")
                    except Exception as e:
                        print(f"加载失败: {file_path}, 错误: {e}")
        
        return all_documents
    
    def split_documents(self, documents):
        """分割文档为小块"""
        return self.text_splitter.split_documents(documents)


def load_documents_from_directory(directory, chunk_size=1000, chunk_overlap=200):
    """模块级函数：加载目录文档并分割为chunk，供知识库重建调用"""
    if not os.path.exists(directory):
        raise FileNotFoundError(f"目录不存在: {directory}")

    loader = DocumentLoader()
    # 按传入参数重建 splitter（覆盖类构造函数中的默认值）
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    loader.text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False
    )

    raw_docs = loader.load_directory(directory)
    if not raw_docs:
        print(f"[WARN] 目录 {directory} 下未找到任何支持的文件(.txt/.pdf)")
        return []

    chunks = loader.split_documents(raw_docs)
    print(f"[OK] 加载 {len(raw_docs)} 个原始文档 → 分割为 {len(chunks)} 个chunk (chunk_size={chunk_size}, overlap={chunk_overlap})")
    return chunks


# 测试代码
if __name__ == "__main__":
    try:
        loader = DocumentLoader()
        
        # 创建测试文件
        test_dir = "./test_docs/智慧农业"
        os.makedirs(test_dir, exist_ok=True)
        
        test_file_path = os.path.join(test_dir, "test.txt")
        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write("华为云智慧植物方舱解决方案通过传感器实时监测温湿度、光照、CO2等环境参数，利用AI大模型构建植物生长模型，实现环境的精准控制和植物生长的数字化管理。该方案可以帮助农业企业提高产量30%以上，降低人工成本50%以上。")
        
        # 加载并分割文档
        documents = loader.load_directory("./test_docs")
        splits = loader.split_documents(documents)
        
        print("文档加载工具测试成功！")
        print(f"加载文档数: {len(documents)}")
        print(f"分割后块数: {len(splits)}")
        print(f"第一个块内容: {splits[0].page_content}")
        print(f"第一个块元数据: {splits[0].metadata}")
        
        # 清理测试文件
        import shutil
        shutil.rmtree("./test_docs")
        
    except Exception as e:
        print(f"文档加载工具测试失败: {e}")
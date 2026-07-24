# -*- coding: utf-8 -*-
"""扫描知识库文档，统计华为云产品提及频次（一次性分析脚本）"""
import os, re, json
from collections import Counter

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample_solutions")

# 华为云产品关键词 -> 规范名（同义词合并）
PRODUCTS = {
    "ECS": ["ECS", "弹性云服务器"],
    "RDS": ["RDS", "云数据库 MySQL", "云数据库MySQL"],
    "GaussDB": ["GaussDB"],
    "OBS": ["OBS", "对象存储服务", "对象存储"],
    "EVS": ["EVS", "云硬盘"],
    "SFS": ["SFS", "弹性文件服务"],
    "EIP": ["EIP", "弹性公网IP", "弹性公网 IP"],
    "ELB": ["ELB", "弹性负载均衡"],
    "VPC": ["VPC", "虚拟私有云"],
    "CDN": ["CDN", "内容分发网络"],
    "NAT": ["NAT网关", "NAT 网关"],
    "VPN": ["VPN"],
    "云专线DC": ["云专线", "Direct Connect"],
    "CCE": ["CCE", "云容器引擎"],
    "CCI": ["CCI", "云容器实例"],
    "SWR": ["SWR", "容器镜像服务"],
    "FunctionGraph": ["FunctionGraph", "函数工作流"],
    "ModelArts": ["ModelArts"],
    "盘古大模型": ["盘古大模型", "盘古"],
    "DLI": ["DLI", "数据湖探索"],
    "MRS": ["MRS", "MapReduce服务", "MapReduce 服务"],
    "DWS": ["DWS", "数据仓库服务", "GaussDB(DWS)"],
    "DataArts": ["DataArts", "数据治理中心", "DAYU"],
    "CSS": ["云搜索服务", "CSS集群", "Elasticsearch"],
    "IoTDA": ["IoTDA", "设备接入", "物联网平台", "IoT平台", "IoT 平台"],
    "IoT边缘": ["IoT Edge", "边缘计算", "IEF", "智能边缘"],
    "DIS": ["DIS", "数据接入服务"],
    "Kafka": ["Kafka", "分布式消息服务"],
    "RocketMQ": ["RocketMQ"],
    "DCS": ["DCS", "分布式缓存", "Redis"],
    "DDS": ["DDS", "文档数据库"],
    "TaurusDB": ["TaurusDB", "GaussDB(for MySQL)"],
    "WAF": ["WAF", "Web应用防火墙", "Web 应用防火墙"],
    "HSS": ["HSS", "企业主机安全", "主机安全"],
    "DBSS": ["DBSS", "数据库安全"],
    "DDoS防护": ["DDoS", "Anti-DDoS"],
    "SSL证书": ["SSL证书", "云证书"],
    "态势感知": ["态势感知", "SecMaster", "安全云脑"],
    "KMS": ["KMS", "数据加密服务", "DEW"],
    "云堡垒机": ["堡垒机", "CBH"],
    "视频直播Live": ["视频直播", "Live"],
    "媒体处理MPC": ["媒体处理", "MPC"],
    "视频点播VOD": ["视频点播", "VOD"],
    "CPH云手机": ["云手机", "CPH"],
    "SMS短信": ["消息&短信", "短信服务"],
    "APM": ["APM", "应用性能管理"],
    "AOM": ["AOM", "应用运维管理"],
    "LTS": ["LTS", "云日志服务"],
    "CES": ["CES", "云监控"],
    "ROMA": ["ROMA"],
    "API网关": ["API网关", "APIG", "API 网关"],
    "华为云Stack": ["华为云Stack", "HCS", "华为云 Stack"],
    "IdeaHub": ["IdeaHub"],
    "WeLink": ["WeLink"],
    "CodeArts": ["CodeArts", "DevCloud", "软件开发生产线"],
    "OCR": ["OCR", "文字识别"],
    "图像识别": ["图像识别", "Image"],
    "人脸识别": ["人脸识别", "FRS"],
    "语音服务": ["语音交互", "SIS", "语音识别"],
    "内容审核": ["内容审核", "Moderation"],
    "数字人": ["数字人", "MetaStudio"],
    "KooSearch": ["KooSearch"],
    "CloudTable": ["CloudTable", "表格存储"],
    "GES图引擎": ["图引擎", "GES"],
    "BCS区块链": ["区块链", "BCS"],
    "IEC智能边缘云": ["智能边缘云", "IEC"],
    "SDRS容灾": ["容灾", "SDRS", "CBR", "云备份"],
    "DRS迁移": ["DRS", "数据复制服务", "数据库迁移"],
    "SMS迁移": ["主机迁移", "SMS服务"],
    "MAS": ["MAS", "多活高可用"],
    "GeminiDB": ["GeminiDB", "Influx", "Cassandra"],
    "CloudIDE": ["CloudIDE"],
    "KooMessage": ["KooMessage"],
    "云桌面Workspace": ["云桌面", "Workspace"],
    "裸金属BMS": ["裸金属", "BMS"],
    "专属主机DeH": ["专属主机", "DeH"],
    "GPU加速云服务器": ["GPU服务器", "GPU云服务器", "GPU 云服务器", "P系列", "GPU实例"],
    "昇腾AI云服务": ["昇腾", "Ascend", "AI算力"],
}

file_hits = Counter()   # 产品出现在多少个文档里
total_hits = Counter()  # 总提及次数
n_files = 0

for root, dirs, files in os.walk(BASE):
    for fn in files:
        if not fn.endswith((".md", ".txt")):
            continue
        n_files += 1
        path = os.path.join(root, fn)
        try:
            text = open(path, encoding="utf-8").read()
        except UnicodeDecodeError:
            text = open(path, encoding="gbk", errors="ignore").read()
        for prod, kws in PRODUCTS.items():
            cnt = sum(text.count(k) for k in kws)
            if cnt > 0:
                file_hits[prod] += 1
                total_hits[prod] += cnt

print(f"扫描文档数: {n_files}\n")
print(f"{'产品':<18}{'覆盖文档数':>8}{'总提及次数':>10}")
print("-" * 40)
for prod, fc in file_hits.most_common():
    print(f"{prod:<18}{fc:>8}{total_hits[prod]:>10}")

# 输出 JSON 供后续使用
out = [{"product": p, "files": file_hits[p], "mentions": total_hits[p]} for p, _ in file_hits.most_common()]
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "product_scan_result.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 data/pricing_reference.json（成本参考功能的结构化价目表）。

数据来源：华为云官网公开页面（产品页 / 官方帮助中心「资源和成本规划」），
采集自 docs/pricing-reference-draft.md 已核实价。全程未编造数字：
- 标 verified=False 的为⚠待官网复核项；
- business_only=True 的为商务定价（盘古/华为云Stack），前端不出数字。

运行：python scripts/gen_pricing_reference.py
输出：data/pricing_reference.json
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "pricing_reference.json")

COLLECTED_AT = "2026-07"
REGION = "华北-北京四"
# 年付折扣系数：年费 = 月费 × 12 × ANNUAL_DISCOUNT（模拟年付优惠，前端「月/年」切换用）
ANNUAL_DISCOUNT = 0.85
DISCLAIMER = (
    "本结果为参考估算，基于公开价目表策展常见规格区间，不含折扣与实时波动，"
    "实际价格以华为云官网价格计算器 / 销售报价为准。"
)

# ---------- 产品库（已核实价的明细项）----------
# tier: 低成本/均衡/高可靠 三档的 {qty, unit_price}
ITEMS = {
    "ECS": {
        "product": "ECS 弹性云服务器", "spec": "s6.large.2（2核4G）", "billing": "按需",
        "unit_label": "月/台", "ref_price": 274.0, "qty": 2,
        "tier": {"low": {"qty": 1, "unit_price": 274.0},
                 "mid": {"qty": 2, "unit_price": 274.0},
                 "high": {"qty": 4, "unit_price": 274.0}},
        "source_url": "https://support.huaweicloud.com/topic/560654-5-B",
        "verified": True,
        "note": "按需连续运行价≈¥0.38/时；包月约¥166–220/月（⚠待官网复核），高可靠建议升主备/集群"
    },
    "OBS": {
        "product": "OBS 对象存储", "spec": "标准存储·单AZ", "billing": "按量",
        "unit_label": "月/GB", "ref_price": 0.099, "qty": 2000,
        "tier": {"low": {"qty": 500, "unit_price": 0.099},
                 "mid": {"qty": 2000, "unit_price": 0.099},
                 "high": {"qty": 10000, "unit_price": 0.099}},
        "source_url": "https://www.huaweicloud.com/product/obs.html",
        "verified": True,
        "note": "多AZ ¥0.139/GB·月、低频 ¥0.08、归档 ¥0.033；公网流出 ¥0.25–0.50/GB"
    },
    "RDS": {
        "product": "RDS for MySQL", "spec": "主备·2核4G·40G SSD", "billing": "包月",
        "unit_label": "月/实例", "ref_price": 470.0, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 470.0},
                 "mid": {"qty": 1, "unit_price": 470.0},
                 "high": {"qty": 2, "unit_price": 470.0}},
        "source_url": "https://www.huaweicloud.com/product/mysql.html",
        "verified": True,
        "note": "主备版；单机¥196/月起、集群版¥729/月起"
    },
    "CCE": {
        "product": "CCE 云容器引擎", "spec": "Standard/Turbo·50节点集群管理费（节点ECS另计）", "billing": "包月",
        "unit_label": "月/集群", "ref_price": 420.80, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 420.80},
                 "mid": {"qty": 1, "unit_price": 420.80},
                 "high": {"qty": 2, "unit_price": 420.80}},
        "source_url": "https://www.huaweicloud.com/guide/page-2908",
        "verified": True,
        "note": "集群管理费；工作节点 ECS 费用另计"
    },
    "EIP": {
        "product": "EIP 弹性公网IP", "spec": "按带宽·5Mbit/s·动态BGP", "billing": "按需",
        "unit_label": "月/个", "ref_price": 245.0, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 245.0},
                 "mid": {"qty": 2, "unit_price": 245.0},
                 "high": {"qty": 4, "unit_price": 245.0}},
        "source_url": "https://support.huaweicloud.com/topic/1235594-2-Y",
        "verified": True,
        "note": "5M按需≈¥0.34/时；按流量计费¥0.80/GB（波动流量更划算）"
    },
    "HSS": {
        "product": "HSS 企业主机安全", "spec": "企业版", "billing": "包月",
        "unit_label": "月/台", "ref_price": 90.0, "qty": 5,
        "tier": {"low": {"qty": 2, "unit_price": 90.0},
                 "mid": {"qty": 5, "unit_price": 90.0},
                 "high": {"qty": 10, "unit_price": 90.0}},
        "source_url": "https://www.huaweicloud.com/guide/page-2908",
        "verified": True,
        "note": "企业版¥90/月/台"
    },
    "CDN": {
        "product": "CDN", "spec": "中国大陆·流量计费", "billing": "按量",
        "unit_label": "月/GB流量", "ref_price": 0.20, "qty": 5000,
        "tier": {"low": {"qty": 1000, "unit_price": 0.20},
                 "mid": {"qty": 5000, "unit_price": 0.20},
                 "high": {"qty": 20000, "unit_price": 0.20}},
        "source_url": "https://www.huaweicloud.com/special/pro-cdn-hwyjf.html",
        "verified": True,
        "note": "流量计费¥0.20/GB起；500GB流量包=¥88更划算"
    },
    "IoTDA": {
        "product": "IoTDA 设备接入", "spec": "基础版·消息数", "billing": "按量",
        "unit_label": "月/百万条", "ref_price": 3.6, "qty": 5,
        "tier": {"low": {"qty": 1, "unit_price": 3.6},
                 "mid": {"qty": 5, "unit_price": 3.6},
                 "high": {"qty": 20, "unit_price": 3.6}},
        "source_url": "https://www.huaweicloud.com/guide/productsdesc-bms_2bc4d1e395cba49399742e176762c108support0",
        "verified": True,
        "note": "前100万条/月免费；标准版S0免费单元(1000在线设备)"
    },
    "ModelArts": {
        "product": "ModelArts", "spec": "昇腾AI加速型(B1) 1卡·推理·公共资源池", "billing": "按需",
        "unit_label": "月/卡(连续)", "ref_price": 15636.0, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 15636.0},
                 "mid": {"qty": 1, "unit_price": 15636.0},
                 "high": {"qty": 2, "unit_price": 15636.0}},
        "source_url": "https://www.huaweicloud.com/guide/productsdesc-bms_961bd6cfc3b893e19abed7aea0d09a1dsupport0",
        "verified": True,
        "note": "昇腾B1推理≈¥21.72/时；910 8卡训练≈¥155.98/时；训练/推理按需"
    },
    "DCS": {
        "product": "DCS 分布式缓存(Redis)", "spec": "基础版·单机·24GB", "billing": "包月",
        "unit_label": "月/实例", "ref_price": 1012.80, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 1012.80},
                 "mid": {"qty": 1, "unit_price": 1012.80},
                 "high": {"qty": 2, "unit_price": 1012.80}},
        "source_url": "https://www.huaweicloud.com/guide/page-2908",
        "verified": True,
        "note": "基础版24GB；高可靠建议主备/集群版"
    },
    "WAF": {
        "product": "WAF Web应用防火墙", "spec": "标准版（云模式）", "billing": "包月",
        "unit_label": "月/实例", "ref_price": 3880.0, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 3880.0},
                 "mid": {"qty": 1, "unit_price": 3880.0},
                 "high": {"qty": 1, "unit_price": 3880.0}},
        "source_url": "https://www.huaweicloud.com/guide/page-2908",
        "verified": False,
        "note": "⚠数值偏高，疑似专业版价，待官网价格计算器复核"
    },
    # ---- 以下为 2026-07 补齐的公开价（原 no_price 项，均取华为云官网/帮助中心公开价）----
    "EVS": {
        "product": "EVS 云硬盘", "spec": "块存储（按类型/容量计费）", "billing": "按量",
        "unit_label": "月/GB", "ref_price": 0.70, "qty": 1000,
        "tier": {"low": {"qty": 500, "unit_price": 0.35},
                 "mid": {"qty": 1000, "unit_price": 0.70},
                 "high": {"qty": 2000, "unit_price": 1.00}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/evs",
        "verified": True,
        "note": "高IO ¥0.35/GiB·月、通用型SSD ¥0.70、超高IO ¥1.00、极速型SSD ¥2.00、通用型SSD V2 ¥0.50"
    },
    "OCR": {
        "product": "OCR 文字识别", "spec": "通用文字识别（资源包）", "billing": "按量",
        "unit_label": "月/千次", "ref_price": 15.0, "qty": 50,
        "tier": {"low": {"qty": 10, "unit_price": 15.0},
                 "mid": {"qty": 50, "unit_price": 15.0},
                 "high": {"qty": 200, "unit_price": 15.0}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/ocr",
        "verified": True,
        "note": "资源包¥15/千次(1000次)；按需 网络图片¥0.05/次、增值税发票¥0.18/次、发票验真¥0.23/次"
    },
    "内容审核": {
        "product": "内容审核 Moderation", "spec": "图像审核（按调用量）", "billing": "按量",
        "unit_label": "月/千次", "ref_price": 0.35, "qty": 200,
        "tier": {"low": {"qty": 50, "unit_price": 0.35},
                 "mid": {"qty": 200, "unit_price": 0.35},
                 "high": {"qty": 1000, "unit_price": 0.35}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/moderation",
        "verified": True,
        "note": "图像¥0.35/千次、文本¥0.16/千次、视频¥0.048/分钟"
    },
    "MRS": {
        "product": "MRS MapReduce服务", "spec": "分析集群 5节点 ac7.4xlarge.4（LTS）", "billing": "包月",
        "unit_label": "月/集群", "ref_price": 16321.60, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 16321.60},
                 "mid": {"qty": 1, "unit_price": 16321.60},
                 "high": {"qty": 2, "unit_price": 16321.60}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/mrs",
        "verified": True,
        "note": "包月¥16,321.60；按需≈¥30.31/小时（5节点 ac7.4xlarge.4）"
    },
    "DLI": {
        "product": "DLI 数据湖探索", "spec": "套餐包 4000 CU时", "billing": "套餐包",
        "unit_label": "月/套餐包", "ref_price": 1360.0, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 1360.0},
                 "mid": {"qty": 2, "unit_price": 1360.0},
                 "high": {"qty": 4, "unit_price": 1360.0}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/dli",
        "verified": True,
        "note": "套餐包4000CU时¥1360；弹性资源池¥0.4/CU·小时，16CU队列≈¥6.4/小时"
    },
    "DWS": {
        "product": "DWS 数据仓库", "spec": "dwsx2.h.2xlarge.4.c7 · 3节点", "billing": "包月",
        "unit_label": "月/集群", "ref_price": 7653.60, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 7653.60},
                 "mid": {"qty": 1, "unit_price": 7653.60},
                 "high": {"qty": 2, "unit_price": 7653.60}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/dws",
        "verified": True,
        "note": "包月¥7,653.6；按需≈¥10.63/小时（3节点 dwsx2.h.2xlarge.4.c7）"
    },
    "GaussDB": {
        "product": "GaussDB", "spec": "分布式 / 主备（按部署形态）", "billing": "包月",
        "unit_label": "月/实例", "ref_price": 4428.0, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 1327.33},
                 "mid": {"qty": 1, "unit_price": 4428.0},
                 "high": {"qty": 1, "unit_price": 30576.0}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/gaussdb",
        "verified": True,
        "note": "for MySQL 4核16G 2节点≈¥1,327/月(年付¥15,928)；分布式入门≈¥6.15/小时(≈¥4,428/月)；分布式高可用≈¥30,576/月"
    },
    "BCS": {
        "product": "BCS 区块链服务", "spec": "专业版 / 企业版（含Peer）", "billing": "包月",
        "unit_label": "月/实例", "ref_price": 5000.0, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 5000.0},
                 "mid": {"qty": 1, "unit_price": 10000.0},
                 "high": {"qty": 1, "unit_price": 60000.0}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/bcs",
        "verified": True,
        "note": "专业版¥5,000/月(含2 Peer,¥8/小时)；企业版¥10,000/月(¥17/小时)；铂金版¥60,000/月；增购Peer专业版¥2,000/个"
    },
    "DataArts": {
        "product": "DataArts Studio 数据治理", "spec": "初级版 cdm.medium 4核8G", "billing": "包月",
        "unit_label": "月/实例", "ref_price": 2000.0, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 2000.0},
                 "mid": {"qty": 1, "unit_price": 2000.0},
                 "high": {"qty": 2, "unit_price": 2000.0}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/dataartsstudio",
        "verified": True,
        "note": "初级版¥2,000/月(cdm.medium)；CDM数据集成 cdm.large 8核16G ≈¥2.25/小时(≈¥1,620/月)"
    },
    "ROMA": {
        "product": "ROMA Connect 集成平台", "spec": "新版按 RCU 计费", "billing": "按量",
        "unit_label": "月/RCU", "ref_price": 1987.2, "qty": 5,
        "tier": {"low": {"qty": 2, "unit_price": 1987.2},
                 "mid": {"qty": 5, "unit_price": 1987.2},
                 "high": {"qty": 15, "unit_price": 1987.2}},
        "source_url": "https://www.huaweicloud.com/pricing.html?tab=detail#/roma",
        "verified": True,
        "note": "新版¥3/RCU·小时；套餐包低至¥2.76/RCU·小时(≈¥1,987/RCU·月连续运行)；15 RCU实例≈¥45/小时"
    },
    "WeLink": {
        "product": "WeLink 智能协同办公", "spec": "标准版 / 旗舰版（按人/月）", "billing": "包月",
        "unit_label": "月/人", "ref_price": 20.0, "qty": 100,
        "tier": {"low": {"qty": 50, "unit_price": 20.0},
                 "mid": {"qty": 100, "unit_price": 20.0},
                 "high": {"qty": 200, "unit_price": 40.0}},
        "source_url": "https://www.huaweicloud.com/product/welink.html",
        "verified": True,
        "note": "标准版¥20/人/月、旗舰版¥40/人/月；免费版≤100成员"
    },
    "数字人": {
        "product": "数字人 MetaStudio", "spec": "分身数字人智能交互（并发路）", "billing": "包月",
        "unit_label": "月/路", "ref_price": 1800.0, "qty": 1,
        "tier": {"low": {"qty": 1, "unit_price": 1800.0},
                 "mid": {"qty": 1, "unit_price": 1800.0},
                 "high": {"qty": 2, "unit_price": 1800.0}},
        "source_url": "https://support.huaweicloud.com/productdesc-metastudio/metastudio_01_0006.html",
        "verified": True,
        "note": "智能交互¥1,800/路·月；视频制作¥10/分钟、视频直播¥23/小时、形象制作¥5,999/个"
    },
    "视频直播": {
        "product": "视频直播 Live", "spec": "标准直播·下行流量计费", "billing": "按量",
        "unit_label": "月/GB流量", "ref_price": 0.225, "qty": 5000,
        "tier": {"low": {"qty": 1000, "unit_price": 0.225},
                 "mid": {"qty": 5000, "unit_price": 0.225},
                 "high": {"qty": 20000, "unit_price": 0.225}},
        "source_url": "https://support.huaweicloud.com/price-live/live-price-pdf.pdf",
        "verified": True,
        "note": "标准直播下行流量¥0.225/GB；云直播录制¥30/路·月；新开用户仅支持华北-北京四"
    },
}

# 商务定价（不出数字，仅提示咨询销售）
BUSINESS_ONLY = {
    "盘古大模型": "按 token / 专属算力商务报价，请咨询华为云销售",
    "华为云Stack": "私有化项目制报价，请咨询华为云销售",
}

# 暂无可靠公开价的产品（不编造数字，仅作「参考价待补充」占位，不参与合计）
# 2026-07：原 13 项均已在官网/帮助中心检索到公开价，全部移入 ITEMS，此处清空。
NO_PRICE_ITEMS = {}


def biz_item(name):
    return {"product": name, "business_only": True, "note": BUSINESS_ONLY[name]}


def no_price_item(name):
    d = NO_PRICE_ITEMS[name]
    return {"product": d["product"], "spec": d["spec"], "no_price": True, "note": d["note"]}


# ---------- 行业成本参考骨架（profiles）----------
BASE = ["ECS", "OBS", "RDS", "CCE", "EIP", "HSS", "CDN"]

PROFILE_DEFS = {
    "通用": {"items": BASE + ["EVS", "WeLink"], "biz": [], "noprice": [],
             "desc": "通用云底座（计算/存储/数据库/容器/网络/安全/CDN），适用于绝大多数方案的成本量级参考。"},
    "智慧城市": {"items": BASE + ["IoTDA", "ModelArts", "WAF", "DataArts", "ROMA", "MRS", "OCR", "内容审核", "视频直播"],
                 "biz": [], "noprice": [],
                 "desc": "城市物联感知 + AI 推理 + Web 安全防护 + 数据治理 / 大数据 / 音视频。"},
    "工业互联网": {"items": BASE + ["IoTDA", "DCS", "ModelArts", "DataArts", "ROMA", "MRS", "DLI"],
                  "biz": [], "noprice": [],
                  "desc": "设备接入 + 缓存加速 + AI 质检/预测 + 数据集成 / 大数据分析。"},
    "智慧医疗": {"items": BASE + ["WAF", "GaussDB", "OCR", "数字人"], "biz": ["盘古大模型"], "noprice": [],
                 "desc": "医疗影像/病历 AI 辅助（盘古为商务报价）+ Web 安全 + 高可用数据库 + OCR / 数字人。"},
    "政务": {"items": BASE + ["WAF", "DataArts", "GaussDB", "BCS"], "biz": ["华为云Stack"], "noprice": [],
             "desc": "政务云安全合规（华为云Stack 为私有化项目制报价）+ 数据治理 / 高可用库 / 区块链存证。"},
    "制造": {"items": BASE + ["IoTDA", "DCS", "DWS", "GaussDB"], "biz": [], "noprice": [],
             "desc": "产线设备接入 + 缓存加速 + 数据仓库 / 高可用数据库。"},
    "矿山": {"items": BASE + ["ModelArts", "IoTDA", "MRS", "内容审核"], "biz": ["华为云Stack"], "noprice": [],
             "desc": "AI 视觉（巡检/作业识别）+ 设备接入 + 大数据 / 内容审核（华为云Stack 私有化报价）。"},
}


def build_profiles():
    profiles = {}
    for name, cfg in PROFILE_DEFS.items():
        items = [dict(ITEMS[k]) for k in cfg["items"]]
        for b in cfg["biz"]:
            items.append(biz_item(b))
        for n in cfg.get("noprice", []):
            items.append(no_price_item(n))
        profiles[name] = {"description": cfg["desc"], "items": items}
    return profiles


def main():
    data = {
        "collected_at": COLLECTED_AT,
        "region": REGION,
        "annual_discount": ANNUAL_DISCOUNT,
        "disclaimer": DISCLAIMER,
        "default_profile": "通用",
        "profiles": build_profiles(),
        "business_only_products": list(BUSINESS_ONLY.keys()),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 统计
    n_profiles = len(data["profiles"])
    n_items = sum(len(p["items"]) for p in data["profiles"].values())
    print(f"已生成 {OUT}")
    print(f"行业骨架数={n_profiles}, 含产品条目合计={n_items}, 商务定价产品={len(BUSINESS_ONLY)}")


if __name__ == "__main__":
    main()

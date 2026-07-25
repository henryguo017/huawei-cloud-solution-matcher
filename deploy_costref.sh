#!/usr/bin/env bash
# 产品价格图谱覆盖补齐部署脚本（2026-07-25 价目覆盖补齐）
# 在服务器 47.96.109.234 上以 root 执行。遵循项目部署铁律①-⑤。
set -e

VER="20260725g"

# 1) 拉取最新代码包（重推 commit 后必须重下 main.zip）
cd /tmp
rm -rf huawei-cloud-solution-matcher-main main.zip
wget -O main.zip https://github.com/henryguo017/huawei-cloud-solution-matcher/archive/refs/heads/main.zip
python3 -c "import zipfile; zipfile.ZipFile('main.zip').extractall('/tmp')"

# 2) 覆盖代码（铁律①：目录名必须 huawei，勿手改勿加粗；仅覆盖代码不碰 DB）
cp -r /tmp/huawei-cloud-solution-matcher-main/* /var/www/huawei-cloud-solution-matcher/

# 3) 重建价目表（铁律④：data/pricing_reference.json 实际被 git 跟踪会随 cp 一同覆盖，
#    但重建可从 gen_pricing_reference.py 重新生成，确保与脚本逻辑一致，作为安全网保留）
cd /var/www/huawei-cloud-solution-matcher
venv/bin/python scripts/gen_pricing_reference.py

# 4) 重启服务
systemctl restart huawei-cloud-api

# 5) 部署后验证（铁律⑤：真 curl 确认生效，勿信版本号/截图）
echo "--- 验证前端版本号生效 ---"
curl -s https://www.cloudsol.cn/index.html | grep -o "style.css?v=${VER}"
curl -s https://www.cloudsol.cn/index.html | grep -o "script.js?v=${VER}"
echo "--- 验证价目 all_items 全量（应为 40）---"
curl -s https://www.cloudsol.cn/api/pricing/products | python3 -c "import sys,json; d=json.load(sys.stdin); print('items=', len(d.get('items', [])))"
echo "--- 验证来源文案改为'正式下单，待官网核查' ---"
curl -s https://www.cloudsol.cn/script.js?v=${VER} | grep -o "正式下单，待官网核查" | head -1

echo "部署完成。"

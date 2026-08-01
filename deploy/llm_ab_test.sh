#!/usr/bin/env bash
# ============================================================
# DeepSeek V4 thinking 开/关 A/B 对比脚本
# 用途：同一段需求，分别以 thinking=enabled / disabled 调用，
#       对比耗时与输出质量，验证"关闭思考"对方案质量无实质影响。
# 适用：V4-Flash-0731 正式版起 thinking 默认开启（匹配 140-170s），
#       项目默认关闭（~12s）。本脚本用于打消质量顾虑或做回归。
# 用法：在项目根目录执行：
#         bash deploy/llm_ab_test.sh
#       可选：传自定义需求描述（注意避免双引号）：
#         bash deploy/llm_ab_test.sh "用一段话介绍智慧园区安防方案"
# 输出：/tmp/ab_think_enabled.txt  /tmp/ab_think_disabled.txt
# ============================================================
set -e
cd "$(dirname "$0")/.."

KEY=$(grep '^DEEPSEEK_API_KEY=' .env | cut -d= -f2-)
if [ -z "$KEY" ]; then echo "❌ 未在 .env 找到 DEEPSEEK_API_KEY"; exit 1; fi

PROMPT="${1:-用一段话介绍制造企业设备预测性维护的华为云解决方案，包含架构要点与价值主张}"

for MODE in enabled disabled; do
  echo "========== thinking=$MODE =========="
  # 只打印耗时与统计
  time curl -s https://api.deepseek.com/v1/chat/completions \
    -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d "{\"model\":\"deepseek-v4-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}],\"temperature\":0.1,\"max_tokens\":8000,\"thinking\":{\"type\":\"$MODE\"}}" \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
m = d['choices'][0]['message']
print('响应字段      :', list(m.keys()))
print('reasoning长度 :', len(m.get('reasoning_content','')), '| 正文长度:', len(m.get('content','')))
print('usage        :', d.get('usage'))
"
  # 完整正文落盘，方便 diff
  curl -s https://api.deepseek.com/v1/chat/completions \
    -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d "{\"model\":\"deepseek-v4-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}],\"temperature\":0.1,\"max_tokens\":8000,\"thinking\":{\"type\":\"$MODE\"}}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['choices'][0]['message'].get('content',''))" > "/tmp/ab_think_${MODE}.txt"
  echo "正文已存: /tmp/ab_think_${MODE}.txt"
  echo
done

echo "对比正文差异:  diff /tmp/ab_think_enabled.txt /tmp/ab_think_disabled.txt"
echo "（无实质差异=关闭思考不影响质量；差异集中在结构措辞=正常）"

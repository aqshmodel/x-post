---
description: 投稿の分析データを取得し、改善提案を行う
---

# 分析・改善提案ワークフロー

## 手順

1. アカウントの分析サマリを取得する
```bash
curl -s http://localhost:8000/api/analytics/{account_name} | python3 -m json.tool
```

2. 投稿履歴をレビューする
```bash
curl -s "http://localhost:8000/api/posts/posted?account={account_name}" | python3 -m json.tool
```

3. コスト履歴を確認する
```bash
curl -s http://localhost:8000/api/cost-history/{account_name} | python3 -m json.tool
```

4. 分析データを手動更新する（最新データ取得）
```bash
curl -s -X POST http://localhost:8000/api/analytics/{account_name}/fetch | python3 -m json.tool
```

5. 以下の観点でインサイトを導出し、ユーザーに提案する:
   - **最適な投稿時間帯**: posted_at × impressions の相関
   - **ウケるテーマ**: テキスト内容 × engagement_rate
   - **投稿頻度の効果**: 日別投稿数 × 平均engagement_rate
   - **画像の効果**: 画像あり/なし × engagement_rate 比較
   - **曜日別傾向**: 曜日 × impressions 集計

6. 改善提案をまとめてユーザーに報告する

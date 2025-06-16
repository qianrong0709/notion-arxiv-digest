
import os
import requests
import arxiv

# ✅ 从 GitHub Actions 或本地环境变量读取密钥
notion_token = os.getenv("NOTION_TOKEN")
notion_page_id = os.getenv("NOTION_PAGE_ID")
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")

# 🔍 关键词设置
search_keywords = [
    "molecular generation",                       # 分子生成
    "structure-based molecular generation",       # 基于结构的分子生成
    "AI drug discovery",                          # AI 药物发现
    "protein-ligand generation",                  # 蛋白-配体生成
    "3D molecule generation",                     # 3D 分子生成
    "binding pocket generation",                  # 结合口袋建模
    "protein-ligand interaction prediction",      # 蛋白配体相互作用预测
    "target prediction using deep learning",      # 靶点预测（AI）
    "protein structure modeling with AI",         # AI蛋白质结构建模
    "drug-target interaction prediction",         # 药物-靶点相互作用预测
    "AI for binding affinity prediction",         # 结合亲和力预测（AI）
    "multi-objective optimization in drug design",# 药物设计中的多目标优化
    "deep learning for ADMET prediction",         # ADMET 预测（AI）
    "deep generative models for drug discovery"   # 深度生成模型用于药物设计
]

papers_per_keyword = 2

def summarize_with_deepseek(prompt):
    headers = {
        "Authorization": f"Bearer {deepseek_api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 300
    }

    response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers=headers,
        json=payload
    )

    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return f"❗ Error from DeepSeek API: {response.text}"

def fetch_and_summarize_papers():
    summaries = []
    for keyword in search_keywords:
        search = arxiv.Search(
            query=keyword,
            max_results=papers_per_keyword,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        for result in search.results():
            title = result.title
            abstract = result.summary
            url = result.entry_id

            prompt = f"Summarize the following abstract in 3 concise bullet points:\nTitle: {title}\nAbstract: {abstract}"
            summary_text = summarize_with_deepseek(prompt)

            summaries.append({"title": title, "url": url, "summary": summary_text})
    return summaries

def push_to_notion(paper_summaries):
    for paper in paper_summaries:
        payload = {
            "parent": {"page_id": notion_page_id},
            "properties": {
                "title": {
                    "title": [{"text": {"content": paper["title"]}}]
                }
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": paper["summary"]}}]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "📎 View on arXiv",
                                    "link": {"url": paper["url"]}
                                }
                            }
                        ]
                    }
                }
            ]
        }

        headers = {
            "Authorization": f"Bearer {notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }

        requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)

if __name__ == "__main__":
    papers = fetch_and_summarize_papers()
    push_to_notion(papers)

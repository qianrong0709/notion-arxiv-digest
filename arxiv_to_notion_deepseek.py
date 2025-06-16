
import os
import requests
import arxiv

# 从 GitHub Secrets 或本地环境读取密钥
notion_token = os.getenv("NOTION_TOKEN")
notion_page_id = os.getenv("NOTION_PAGE_ID")
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")

# 扩展关键词列表（覆盖 AI 药物发现多个维度）
search_keywords = [
    "molecular generation",
    "structure-based molecular generation",
    "AI drug discovery",
    "protein-ligand generation",
    "3D molecule generation",
    "binding pocket generation",
    "protein-ligand interaction prediction",
    "target prediction using deep learning",
    "protein structure modeling with AI",
    "drug-target interaction prediction",
    "AI for binding affinity prediction",
    "multi-objective optimization in drug design",
    "deep learning for ADMET prediction",
    "deep generative models for drug discovery"
]

papers_per_keyword = 5  # 每个关键词抓取几篇论文

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
    seen_titles = set()
    summaries = []

    for keyword in search_keywords:
        search = arxiv.Search(
            query=keyword,
            max_results=papers_per_keyword,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        for result in search.results():
            title = result.title.strip()

            # 去重：跳过已经见过的标题
            if title in seen_titles:
                continue
            seen_titles.add(title)

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

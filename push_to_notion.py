
import os
import requests

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID")

def push_to_notion(papers):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    for paper in papers:
        data = {
            "parent": {"page_id": NOTION_PAGE_ID},
            "properties": {
                "title": [{"text": {"content": paper["title"]}}],
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {"type": "text", "text": {"content": paper["summary"][:1000]}}
                        ]
                    },
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": f"📎 View on {paper['source']}",
                                    "link": {"url": paper["url"]},
                                },
                            }
                        ]
                    },
                },
            ],
        }

        requests.post("https://api.notion.com/v1/pages", headers=headers, json=data)

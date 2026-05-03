import feedparser
import os
import datetime
import pytz
import re
import hashlib
from urllib.parse import urlparse, urlunparse

from openai import OpenAI
from notion_client import Client


# ================= 配置区域 =================

RSS_FEEDS = {
    "ArXiv (q-bio.BM)": "http://export.arxiv.org/rss/q-bio.BM",
    "ArXiv (CS.LG - Machine Learning)": "https://rss.arxiv.org/rss/cs.LG",
    "ArXiv (CS.AI - Artificial Intelligence)": "http://rss.arxiv.org/rss/cs.AI",
    "ArXiv (Chem-Phys)": "http://export.arxiv.org/rss/physics.chem-ph",
    "ArXiv(multi)": "https://rss.arxiv.org/rss/cs.ai+q-bio.NC",
    "Nature MI": "https://www.nature.com/natmachintell.rss",
    "Nature Communi": "https://www.nature.com/ncomms.rss",
    "Nature Biotech": "https://www.nature.com/nbt.rss",
    "Nature Comp Sci": "https://www.nature.com/natcomputsci.rss",
    "Nature Methods": "https://www.nature.com/nmeth.rss",
    "JCIM": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jcisd8",
    "JMC": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jmcmar",
    "Chemical Science": "http://feeds.rsc.org/rss/sc",
    "Digital Discovery": "http://feeds.rsc.org/rss/dd",
    "Science Advances": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",
    "Science": "https://www.science.org/action/showFeed?type=etoc&feed=rss&journalCode=science",
}

KEYWORDS = [
    "diffusion",
    "generative",
    "docking",
    "molecular dynamics",
    "BFN",
    "GNN",
    "transformer",
    "drug design",
    "molecular generation",
    "electron density",
    "structure-based",
    "ligand-based",
    "de novo design",
    "geometric deep learning",
    "equivariant",
    "SE(3)",
    "binding affinity",
    "protein generation",
    "protein design",
    "drug discovery",
    "molecule generation",
    "molecular design",
]

MAX_ENTRIES_PER_FEED = 10


# ================= 初始化客户端 =================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")

if not DEEPSEEK_API_KEY:
    raise RuntimeError("❌ 缺少环境变量 DEEPSEEK_API_KEY")

if not NOTION_TOKEN:
    raise RuntimeError("❌ 缺少环境变量 NOTION_TOKEN")

if not DATABASE_ID:
    raise RuntimeError("❌ 缺少环境变量 DATABASE_ID")

deepseek_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
)

notion = Client(auth=NOTION_TOKEN)


# ================= 论文 ID 规范化函数 =================

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)

ARXIV_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:|oai:arXiv\.org:)?"
    r"([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
    re.I,
)


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonicalize_url(url):
    """
    规范化 URL：
    - http/https 统一成 https
    - 去掉 query 和 fragment
    - 去掉 www
    - arXiv pdf 链接统一成 abs 链接
    """
    if not url:
        return ""

    parsed = urlparse(url)
    netloc = parsed.netloc.lower()

    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path.rstrip("/")

    if "arxiv.org" in netloc:
        path = path.replace("/pdf/", "/abs/")
        if path.endswith(".pdf"):
            path = path[:-4]

    return urlunparse(("https", netloc, path, "", "", ""))


def normalize_title(title):
    if not title:
        return ""

    title = title.lower().strip()
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff ]", "", title)
    return title


def get_entry_field(entry, key, default=""):
    try:
        return entry.get(key, default)
    except Exception:
        return getattr(entry, key, default)


def get_paper_id(entry):
    """
    为每篇文章生成稳定 InternalID。

    优先级：
    1. DOI
    2. arXiv ID
    3. 规范化 URL
    4. 标题 hash
    """
    title = get_entry_field(entry, "title", "") or ""
    link = get_entry_field(entry, "link", "") or ""
    summary = get_entry_field(entry, "summary", "") or ""
    entry_id = get_entry_field(entry, "id", "") or ""

    possible_fields = [
        title,
        link,
        summary,
        entry_id,
        str(get_entry_field(entry, "dc_identifier", "")),
        str(get_entry_field(entry, "prism_doi", "")),
        str(get_entry_field(entry, "doi", "")),
    ]

    text = " ".join(possible_fields)

    doi_match = DOI_RE.search(text)
    if doi_match:
        doi = doi_match.group(0).lower().rstrip(".")
        return f"doi:{doi}"

    arxiv_text = " ".join([link, entry_id])
    arxiv_match = ARXIV_RE.search(arxiv_text)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1).lower()
        return f"arxiv:{arxiv_id}"

    if link:
        return f"url:{canonicalize_url(link)}"

    clean_title = normalize_title(title)
    title_hash = hashlib.sha1(clean_title.encode("utf-8")).hexdigest()[:16]
    return f"title:{title_hash}"


# ================= Notion 相关函数 =================

def check_if_exists(paper_id, canonical_url, raw_url, title):
    """
    三层查重：
    1. InternalID 查重：新数据最稳
    2. URL 查重：兼容旧数据
    3. Title 查重：兜底兼容旧数据
    """
    filters = [
        {
            "property": "InternalID",
            "rich_text": {
                "equals": paper_id
            }
        },
        {
            "property": "URL",
            "url": {
                "equals": canonical_url
            }
        },
        {
            "property": "Title",
            "title": {
                "equals": title
            }
        },
    ]

    if raw_url and raw_url != canonical_url:
        filters.append(
            {
                "property": "URL",
                "url": {
                    "equals": raw_url
                }
            }
        )

    response = notion.databases.query(
        database_id=DATABASE_ID,
        filter={
            "or": filters
        },
        page_size=1,
    )

    return len(response.get("results", [])) > 0


def push_to_notion(title, url, summary, source, date_str, paper_id):
    """
    写入 Notion 数据库。

    Notion 字段要求：
    - Title      : title
    - URL        : url
    - Summary    : rich_text
    - Source     : select
    - Date       : date
    - Status     : status
    - InternalID : rich_text，隐藏即可
    """
    notion.pages.create(
        parent={"database_id": DATABASE_ID},
        properties={
            "Title": {
                "title": [
                    {
                        "text": {
                            "content": title[:2000]
                        }
                    }
                ]
            },
            "URL": {
                "url": url
            },
            "Summary": {
                "rich_text": [
                    {
                        "text": {
                            "content": summary[:2000]
                        }
                    }
                ]
            },
            "Source": {
                "select": {
                    "name": source
                }
            },
            "Date": {
                "date": {
                    "start": date_str
                }
            },
            "Status": {
                "status": {
                    "name": "Inbox"
                }
            },
            "InternalID": {
                "rich_text": [
                    {
                        "text": {
                            "content": paper_id[:2000]
                        }
                    }
                ]
            },
        },
    )

    print(f"✅ 已入库: {title[:60]}... [{paper_id}]")


# ================= DeepSeek 总结函数 =================

def summarize_paper(title, abstract):
    """用 DeepSeek 生成克制、客观的论文摘要"""
    print(f"🤖 正在总结: {title[:60]}...")

    prompt = f"""
你是 AI 药物发现、计算化学和机器学习方向的博士生。请根据下面论文的标题和摘要，写一段中文摘要，供 Notion 文献数据库快速浏览使用。

写作要求：
1. 只基于标题和摘要，不要补充摘要中没有的信息。
2. 不要写成推荐语，不要使用“兄弟们”“太顶了”“值得一看”“重磅”“颠覆”“突破性”“厉害”等口语化或营销化表达。
3. 不要夸大论文贡献，不要替作者下过强结论。
4. 优先说明三点：研究问题、方法思路、主要结果或潜在用途。
5. 如果摘要信息不足，就明确写“摘要中未提供具体实验细节”或“摘要中未说明具体性能提升”。
6. 语言保持科研笔记风格，客观、克制、清楚。
7. 控制在 80–120 字。

标题：
{title}

摘要：
{abstract}

请直接输出摘要正文，不要加标题，不要分点。
"""

    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": "你是一个严谨的科研文献摘要助手，输出必须客观、克制、避免宣传语。"
                },
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=0.2,
            max_tokens=220,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"❌ LLM Error: {e}")
        return "AI 总结失败，请人工查看。"


# ================= 主程序 =================

def run():
    print("🚀 开始抓取每日论文...")

    tz = pytz.timezone("Asia/Shanghai")
    today = datetime.datetime.now(tz).strftime("%Y-%m-%d")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
    }

    seen_paper_ids = set()

    total_new = 0
    total_skipped_existing = 0
    total_skipped_keyword = 0
    total_skipped_error = 0
    total_feed_error = 0

    for source_name, feed_url in RSS_FEEDS.items():
        print(f"\n📡 正在扫描: {source_name} ...", end="")

        try:
            feed = feedparser.parse(feed_url, request_headers=headers)

            status = getattr(feed, "status", 200)
            if status != 200:
                print(f" [❌ 失败: 状态码 {status}]")
                total_feed_error += 1
                continue

            entries = getattr(feed, "entries", [])
            entry_count = len(entries)

            print(f" [✅ 连接成功，发现 {entry_count} 篇文章]")

            if entry_count == 0:
                print("   ⚠️ 源是通的，但没有解析到文章，可能今天没更新或 RSS 格式变化")
                continue

            for entry in entries[:MAX_ENTRIES_PER_FEED]:
                try:
                    title = get_entry_field(entry, "title", "").strip()
                    raw_url = get_entry_field(entry, "link", "").strip()
                    abstract = strip_html(get_entry_field(entry, "summary", "No Abstract"))

                    if not title:
                        print("   ⚠️ 跳过一条无标题记录")
                        total_skipped_error += 1
                        continue

                    if not raw_url:
                        print(f"   ⚠️ 跳过无 URL 记录: {title[:60]}...")
                        total_skipped_error += 1
                        continue

                    canonical_url = canonicalize_url(raw_url)
                    paper_id = get_paper_id(entry)

                    text_content = f"{title} {abstract}".lower()

                    if KEYWORDS and not any(keyword.lower() in text_content for keyword in KEYWORDS):
                        total_skipped_keyword += 1
                        continue

                    if paper_id in seen_paper_ids:
                        print(f"   💨 本次运行已见过: {title[:60]}... [{paper_id}]")
                        total_skipped_existing += 1
                        continue

                    seen_paper_ids.add(paper_id)

                    exists = check_if_exists(
                        paper_id=paper_id,
                        canonical_url=canonical_url,
                        raw_url=raw_url,
                        title=title,
                    )

                    if exists:
                        print(f"   💨 已存在: {title[:60]}... [{paper_id}]")
                        total_skipped_existing += 1
                        continue

                    summary = summarize_paper(title, abstract)

                    push_to_notion(
                        title=title,
                        url=canonical_url,
                        summary=summary,
                        source=source_name,
                        date_str=today,
                        paper_id=paper_id,
                    )

                    total_new += 1

                except Exception as e:
                    print(f"   ❌ 单篇处理失败: {title[:60] if 'title' in locals() else '未知标题'}")
                    print(f"      错误: {e}")
                    total_skipped_error += 1
                    continue

        except Exception as e:
            print(f"\n⚠️ RSS 源解析出错: {source_name}, 错误: {e}")
            total_feed_error += 1
            continue

    print("\n================= 今日抓取完成 =================")
    print(f"✅ 新增论文: {total_new}")
    print(f"💨 已存在 / 重复跳过: {total_skipped_existing}")
    print(f"🔎 关键词不匹配跳过: {total_skipped_keyword}")
    print(f"⚠️ 单篇错误跳过: {total_skipped_error}")
    print(f"📡 RSS 源错误: {total_feed_error}")
    print("================================================")


if __name__ == "__main__":
    run()

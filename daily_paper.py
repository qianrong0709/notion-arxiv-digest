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

# 1. RSS 订阅源
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

# 2. 关键词过滤
# 如果想看所有文章，就改成 KEYWORDS = []
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

# 每个 RSS 源最多检查最新多少篇
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
    """简单去掉 RSS summary 里的 HTML 标签"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonicalize_url(url):
    """
    规范化 URL：
    - http/https 统一
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
    """标题兜底用：减少大小写、空格、标点差异"""
    if not title:
        return ""

    title = title.lower().strip()
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff ]", "", title)
    return title


def get_entry_field(entry, key, default=""):
    """feedparser 的 entry 有时像 dict，有时像对象，这里统一读取"""
    try:
        return entry.get(key, default)
    except Exception:
        return getattr(entry, key, default)


def get_paper_id(entry):
    """
    为每篇文章生成稳定 PaperID。

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

    # 有些 RSS 会把 DOI 放在其他字段里
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

    # 1. DOI
    doi_match = DOI_RE.search(text)
    if doi_match:
        doi = doi_match.group(0).lower().rstrip(".")
        return f"doi:{doi}"

    # 2. arXiv ID
    # 只从 link 和 entry_id 中找，避免从摘要里误识别普通数字
    arxiv_text = " ".join([link, entry_id])
    arxiv_match = ARXIV_RE.search(arxiv_text)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1).lower()
        return f"arxiv:{arxiv_id}"

    # 3. 规范化 URL
    if link:
        return f"url:{canonicalize_url(link)}"

    # 4. 标题 hash 兜底
    clean_title = normalize_title(title)
    title_hash = hashlib.sha1(clean_title.encode("utf-8")).hexdigest()[:16]
    return f"title:{title_hash}"


# ================= Notion 相关函数 =================

def check_if_exists(paper_id):
    """
    根据 PaperID 查重。

    返回：
    True  = 已存在
    False = 不存在
    None  = 查重失败，主程序应跳过该论文，避免重复入库
    """
    try:
        response = notion.databases.query(
            database_id=DATABASE_ID,
            filter={
                "property": "PaperID",
                "rich_text": {
                    "equals": paper_id
                }
            },
            page_size=1,
        )
        return len(response.get("results", [])) > 0

    except Exception as e:
        print(f"⚠️ 查重出错，跳过本篇，避免重复入库: {e}")
        return None


def push_to_notion(title, url, summary, source, date_str, paper_id):
    """写入 Notion 数据库"""
    try:
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
                "PaperID": {
                    "rich_text": [
                        {
                            "text": {
                                "content": paper_id
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
            },
        )

        print(f"✅ 已入库: {title[:30]}...")

    except Exception as e:
        print(f"❌ Notion Error: {e}")


# ================= DeepSeek 总结函数 =================

def summarize_paper(title, abstract):
    """用 DeepSeek 总结论文"""
    print(f"🤖 正在总结: {title[:40]}...")

    prompt = f"""
你是 AIDD，也就是 AI 药物发现领域的博士生。请阅读下面这篇论文的标题和摘要，用中文写一段简短的“推荐语”。

要求：
1. 第一句直接说明这篇文章解决什么问题，或者核心创新点是什么。
2. 语言自然，像科研师兄给组里同学推荐论文，不要翻译腔。
3. 不要夸大，不要说“颠覆”“革命性”等过强表述。
4. 100 字以内。

标题：
{title}

摘要：
{abstract}
"""

    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=0.5,
            max_tokens=300,
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

    # 本次运行内去重，防止同一篇文章从多个 RSS 源同时出现
    seen_paper_ids = set()

    total_new = 0
    total_skipped_existing = 0
    total_skipped_keyword = 0
    total_skipped_error = 0

    for source_name, feed_url in RSS_FEEDS.items():
        print(f"\n📡 正在扫描: {source_name} ...", end="")

        try:
            feed = feedparser.parse(feed_url, request_headers=headers)

            status = getattr(feed, "status", 200)
            if status != 200:
                print(f" [❌ 失败: 状态码 {status}]")
                continue

            entries = getattr(feed, "entries", [])
            entry_count = len(entries)

            print(f" [✅ 连接成功，发现 {entry_count} 篇文章]")

            if entry_count == 0:
                print("   ⚠️ 源是通的，但没有解析到文章，可能今天没更新或 RSS 格式变化")
                continue

            for entry in entries[:MAX_ENTRIES_PER_FEED]:
                title = get_entry_field(entry, "title", "").strip()
                link = get_entry_field(entry, "link", "").strip()
                abstract = strip_html(get_entry_field(entry, "summary", "No Abstract"))

                if not title:
                    print("   ⚠️ 跳过一条无标题记录")
                    total_skipped_error += 1
                    continue

                # 1. 关键词过滤
                text_content = f"{title} {abstract}".lower()

                if KEYWORDS and not any(keyword.lower() in text_content for keyword in KEYWORDS):
                    total_skipped_keyword += 1
                    continue

                # 2. 生成稳定 PaperID
                paper_id = get_paper_id(entry)

                # 3. 本次运行内查重
                if paper_id in seen_paper_ids:
                    print(f"   💨 本次运行已见过: {title[:30]}... [{paper_id}]")
                    total_skipped_existing += 1
                    continue

                seen_paper_ids.add(paper_id)

                # 4. Notion 数据库查重
                exists = check_if_exists(paper_id)

                if exists is None:
                    print(f"   ⚠️ 查重失败，已跳过: {title[:30]}...")
                    total_skipped_error += 1
                    continue

                if exists:
                    print(f"   💨 已存在: {title[:30]}... [{paper_id}]")
                    total_skipped_existing += 1
                    continue

                # 5. 总结并入库
                summary = summarize_paper(title, abstract)

                push_to_notion(
                    title=title,
                    url=link,
                    summary=summary,
                    source=source_name,
                    date_str=today,
                    paper_id=paper_id,
                )

                total_new += 1

        except Exception as e:
            print(f"\n⚠️ 解析出错: {source_name}, 错误: {e}")
            total_skipped_error += 1

    print("\n================= 今日抓取完成 =================")
    print(f"✅ 新增论文: {total_new}")
    print(f"💨 已存在 / 重复跳过: {total_skipped_existing}")
    print(f"🔎 关键词不匹配跳过: {total_skipped_keyword}")
    print(f"⚠️ 错误跳过: {total_skipped_error}")
    print("================================================")


if __name__ == "__main__":
    run()

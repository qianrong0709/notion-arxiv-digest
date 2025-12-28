import feedparser
import os
import datetime
import pytz
from openai import OpenAI
from notion_client import Client

# ================= 配置区域 =================

# 1. 你的 RSS 订阅源 (AIDD 方向)
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
    "Digital Discovery (专门做AI化学的)": "http://feeds.rsc.org/rss/dd",
    "science advances": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",
    "Science (Main)": "https://www.science.org/action/showFeed?type=etoc&feed=rss&journalCode=science"
}

# 2. 关键词过滤 (只保留相关的)
# 如果想看所有文章，就把下面改成: KEYWORDS = []
KEYWORDS = ["diffusion", "generative", "docking", "molecular dynamics", "BFN", "GNN", "transformer", "drug design", "molecular generation", "electron density",
            "drug design", "structure-based", "ligand-based", "de novo design", "geometric deep learning", "equivariant", "SE(3)","binding affinity", "protein generation"]

# ================= 初始化客户端 =================

# 这里会自动读取 GitHub Secrets 里的配置，不用改
deepseek_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"), 
    base_url="https://api.deepseek.com"  # DeepSeek 官方接口地址
)

notion = Client(auth=os.environ.get("NOTION_TOKEN"))
database_id = os.environ.get("DATABASE_ID")

# ================= 核心函数 =================

def check_if_exists(url):
    """检查这篇文章是不是已经存过了，避免重复"""
    try:
        response = notion.databases.query(
            database_id=database_id,
            filter={
                "property": "URL",
                "url": {
                    "equals": url
                }
            }
        )
        return len(response["results"]) > 0
    except Exception as e:
        print(f"⚠️ 查重出错: {e}")
        return False

def summarize_paper(title, abstract):
    """用 DeepSeek 总结"""
    print(f"🤖 正在思考: {title[:30]}...")
    prompt = f"""
    你是AIDD(AI药物发现)领域的博士生。请阅读这篇论文摘要，用中文写一段简短的“推荐语”。
    要求：
    1. 第一句直击痛点或核心创新点。
    2. 口语化，类似“师兄笔记”的风格，不要翻译腔。
    3. 100字以内。
    
    标题: {title}
    摘要: {abstract}
    """
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat", 
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ LLM Error: {e}")
        return "AI 总结失败，请人工查看。"

def push_to_notion(title, url, summary, source, date_str):
    """写入 Notion 数据库"""
    try:
        notion.pages.create(
            parent={"database_id": database_id},
            properties={
                "Title": {"title": [{"text": {"content": title}}]},
                "URL": {"url": url},
                "Summary": {"rich_text": [{"text": {"content": summary}}]},
                "Source": {"select": {"name": source}},
                "Date": {"date": {"start": date_str}},
                "Status": {"status": {"name": "Inbox"}} 
            }
        )
        print(f"✅ 已入库: {title[:20]}")
    except Exception as e:
        print(f"❌ Notion Error: {e}")

# ================= 主程序 =================

# ================= 主程序 (修复版) =================

def run():
    print("🚀 开始抓取每日论文...")
    tz = pytz.timezone('Asia/Shanghai')
    today = datetime.datetime.now(tz).strftime("%Y-%m-%d")
    
    # --- 关键修改：伪装成浏览器 ---
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    }

    for source_name, feed_url in RSS_FEEDS.items():
        print(f"\n📡 正在扫描: {source_name} ...", end="")
        
        try:
            # --- 关键修改：传入 request_headers ---
            # 这一步是骗过 ACS 和 ArXiv 的关键
            feed = feedparser.parse(feed_url, request_headers=HEADERS)
            
            # 🔍 调试信息：看看服务器返回了什么状态码
            status = getattr(feed, 'status', 200) # 有些源可能没返回 status，默认 200
            if status != 200:
                print(f" [❌ 失败: 状态码 {status}]")
                continue # 如果被墙了 (403/429)，就跳过
            
            entry_count = len(feed.entries)
            print(f" [✅ 连接成功，发现 {entry_count} 篇文章]")

            if entry_count == 0:
                print("   (⚠️ 注意: 源是通的，但没有解析到文章，可能是XML格式问题或今天没更新)")
                continue

            # 每次只看最新的 10 篇
            for entry in feed.entries[:10]: 
                title = entry.title
                link = entry.link
                abstract = getattr(entry, 'summary', 'No Abstract')
                
                # 1. 关键词过滤
                text_content = (title + abstract).lower()
                if KEYWORDS and not any(k.lower() in text_content for k in KEYWORDS):
                    # print(f"   [过滤] {title[:20]}...") # 调试时可以取消注释
                    continue 

                # 2. 查重
                if check_if_exists(link):
                    print(f"   💨 已存在: {title[:15]}...")
                    continue
                
                # 3. 总结 & 入库
                summary = summarize_paper(title, abstract)
                push_to_notion(title, link, summary, source_name, today)
                
        except Exception as e:
            print(f"\n⚠️ 解析出错: {source_name}, 错误: {e}")

if __name__ == "__main__":
    run()

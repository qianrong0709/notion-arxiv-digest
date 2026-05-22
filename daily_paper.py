import feedparser
import os
import datetime
import pytz
import re
import hashlib
import html
import json
import time
from urllib.parse import urlparse, urlunparse, urlencode
from urllib.request import Request, urlopen

from openai import OpenAI
from notion_client import Client


# ============================================================
# 配置区域
# ============================================================

TIMEZONE = "Asia/Shanghai"

# 日常精选模式：不要太高，否则 arXiv 每天会进太多。
# 如果某天想高召回，可以临时改成 25 或 50。
MAX_ENTRIES_PER_FEED = 15
MAX_ENTRIES_PER_API_SOURCE = 15

# 默认跳过博客源，避免 OpenAI / DeepMind / HF 等动态把 Notion 塞满。
EXCLUDED_FEED_TAGS = {"blog"}

# 默认关闭的一些 arXiv 边缘源。
# 这些源目前没有放进 RSS_FEEDS；保留此项是为了以后重新加入时可直接控制。
EXCLUDED_FEED_NAMES = {
    "ArXiv q-bio.MN - Molecular Networks",
    "ArXiv cond-mat.soft - Soft Matter",
    "ArXiv cs.NE - Neural and Evolutionary Computing",
    "ArXiv eess.IV - Image and Video Processing",
    "ArXiv cs.RO - Robotics",
    "ArXiv cs.HC - Human-Computer Interaction",
}

# 如果 Notion 数据库里有这些字段，就填字段名；没有就保持 None。
# 字段类型必须对应，否则 Notion API 会报错。
NOTION_TAG_PROPERTY = None              # 例："Tags"，multi_select
NOTION_TOPIC_PROPERTY = None            # 例："Topics"，multi_select
NOTION_SCORE_PROPERTY = None            # 例："Score"，number
NOTION_ENTRY_TYPE_PROPERTY = None       # 例："Type"，select


# ============================================================
# RSS 源
# 结构说明：
#   key: 你想在 Notion Source 字段里显示的来源名
#   url: RSS 地址
#   tag: 来源大类：aidd / ml / nlp / cv / agent / general / blog / custom
#   type: paper / blog / news
# ============================================================

RSS_FEEDS = {
    # ================= arXiv：AIDD / 计算化学 / 生物分子 =================
    "ArXiv q-bio.BM - Biomolecules": {
        "url": "https://rss.arxiv.org/rss/q-bio.BM",
        "tag": "aidd",
        "type": "paper",
    },
    "ArXiv q-bio.QM - Quantitative Methods": {
        "url": "https://rss.arxiv.org/rss/q-bio.QM",
        "tag": "aidd",
        "type": "paper",
    },
    "ArXiv physics.chem-ph - Chemical Physics": {
        "url": "https://rss.arxiv.org/rss/physics.chem-ph",
        "tag": "aidd",
        "type": "paper",
    },

    # ================= arXiv：核心 AI / ML =================
    "ArXiv cs.LG - Machine Learning": {
        "url": "https://rss.arxiv.org/rss/cs.LG",
        "tag": "ml",
        "type": "paper",
    },
    "ArXiv cs.AI - Artificial Intelligence": {
        "url": "https://rss.arxiv.org/rss/cs.AI",
        "tag": "ml",
        "type": "paper",
    },
    "ArXiv stat.ML - Statistical ML": {
        "url": "https://rss.arxiv.org/rss/stat.ML",
        "tag": "ml",
        "type": "paper",
    },

    # ================= arXiv：NLP / CV / Agent 核心源 =================
    "ArXiv cs.CL - NLP": {
        "url": "https://rss.arxiv.org/rss/cs.CL",
        "tag": "nlp",
        "type": "paper",
    },
    "ArXiv cs.CV - Computer Vision": {
        "url": "https://rss.arxiv.org/rss/cs.CV",
        "tag": "cv",
        "type": "paper",
    },
    "ArXiv cs.MA - Multiagent Systems": {
        "url": "https://rss.arxiv.org/rss/cs.MA",
        "tag": "agent",
        "type": "paper",
    },

    # ================= AIDD / 计算化学 / 药物化学期刊 =================
    "JCIM": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jcisd8",
        "tag": "aidd",
        "type": "paper",
    },
    "JMC": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jmcmar",
        "tag": "aidd",
        "type": "paper",
    },
    "JCTC": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jctcce",
        "tag": "aidd",
        "type": "paper",
    },
    "ACS Central Science": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=acscii",
        "tag": "aidd",
        "type": "paper",
    },
    "ACS Medicinal Chemistry Letters": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=amclct",
        "tag": "aidd",
        "type": "paper",
    },
    "ACS Chemical Biology": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=acbcct",
        "tag": "aidd",
        "type": "paper",
    },
    "Chemical Reviews": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=chreay",
        "tag": "aidd",
        "type": "paper",
    },
    "Chemical Science": {
        "url": "https://feeds.rsc.org/rss/sc",
        "tag": "aidd",
        "type": "paper",
    },
    "Digital Discovery": {
        "url": "https://feeds.rsc.org/rss/dd",
        "tag": "aidd",
        "type": "paper",
    },
    "Chemical Society Reviews": {
        "url": "https://feeds.rsc.org/rss/cs",
        "tag": "aidd",
        "type": "paper",
    },
    "RSC Medicinal Chemistry": {
        "url": "https://feeds.rsc.org/rss/md",
        "tag": "aidd",
        "type": "paper",
    },
    "Journal of Cheminformatics": {
        "url": "https://link.springer.com/search.rss?facet-journal-id=13321&channel-name=Journal%20of%20Cheminformatics",
        "tag": "aidd",
        "type": "paper",
    },

    # ================= Nature / Science / Cell / PNAS =================
    "Nature Machine Intelligence": {
        "url": "https://www.nature.com/natmachintell.rss",
        "tag": "ml",
        "type": "paper",
    },
    "Nature Computational Science": {
        "url": "https://www.nature.com/natcomputsci.rss",
        "tag": "ml",
        "type": "paper",
    },
    "Nature Chemistry": {
        "url": "https://www.nature.com/nchem.rss",
        "tag": "aidd",
        "type": "paper",
    },
    "Nature Chemical Biology": {
        "url": "https://www.nature.com/nchembio.rss",
        "tag": "aidd",
        "type": "paper",
    },
    "Nature Structural & Molecular Biology": {
        "url": "https://www.nature.com/nsmb.rss",
        "tag": "aidd",
        "type": "paper",
    },
    "Nature Reviews Drug Discovery": {
        "url": "https://www.nature.com/nrd.rss",
        "tag": "aidd",
        "type": "paper",
    },
    "Nature Reviews Chemistry": {
        "url": "https://www.nature.com/natrevchem/current_issue/rss",
        "tag": "aidd",
        "type": "paper",
    },
    "Nature Medicine": {
        "url": "https://www.nature.com/nm/current_issue/rss",
        "tag": "general",
        "type": "paper",
    },
    "Nature Methods": {
        "url": "https://www.nature.com/nmeth.rss",
        "tag": "general",
        "type": "paper",
    },
    "Nature Biotechnology": {
        "url": "https://www.nature.com/nbt.rss",
        "tag": "general",
        "type": "paper",
    },
    "Nature Communications": {
        "url": "https://www.nature.com/ncomms.rss",
        "tag": "general",
        "type": "paper",
    },
    "Science": {
        "url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&journalCode=science",
        "tag": "general",
        "type": "paper",
    },
    "Science Advances": {
        "url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",
        "tag": "general",
        "type": "paper",
    },
    "Science Translational Medicine": {
        "url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&journalCode=stm",
        "tag": "general",
        "type": "paper",
    },
    "PNAS": {
        "url": "https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=pnas",
        "tag": "general",
        "type": "paper",
    },
    "Cell Systems": {
        "url": "https://www.cell.com/cell-systems/rss",
        "tag": "general",
        "type": "paper",
    },
    "Patterns": {
        "url": "https://www.cell.com/patterns/rss",
        "tag": "general",
        "type": "paper",
    },
    "Cell Chemical Biology": {
        "url": "https://www.cell.com/cell-chemical-biology/rss",
        "tag": "aidd",
        "type": "paper",
    },
    "Cell Reports Medicine": {
        "url": "https://www.cell.com/cell-reports-medicine/rss",
        "tag": "general",
        "type": "paper",
    },

    # ================= Bioinformatics / Computational Biology =================
    "Bioinformatics": {
        "url": "https://academic.oup.com/rss/site_5127/3091.xml",
        "tag": "aidd",
        "type": "paper",
    },
    "Briefings in Bioinformatics": {
        "url": "https://academic.oup.com/rss/site_5260/3091.xml",
        "tag": "aidd",
        "type": "paper",
    },
    "Nucleic Acids Research": {
        "url": "https://academic.oup.com/rss/site_5153/3127.xml",
        "tag": "aidd",
        "type": "paper",
    },

    # ================= 工业界 / 实验室博客 =================
    # 默认会被 EXCLUDED_FEED_TAGS = {"blog"} 跳过。
    "Google Research Blog": {
        "url": "https://research.google/blog/rss/",
        "tag": "blog",
        "type": "blog",
    },
    "DeepMind Blog": {
        "url": "https://deepmind.google/blog/rss.xml",
        "tag": "blog",
        "type": "blog",
    },
    "OpenAI Blog": {
        "url": "https://openai.com/news/rss.xml",
        "tag": "blog",
        "type": "blog",
    },
    "Anthropic News": {
        "url": "https://www.anthropic.com/news/rss.xml",
        "tag": "blog",
        "type": "blog",
    },
    "Hugging Face Blog": {
        "url": "https://huggingface.co/blog/feed.xml",
        "tag": "blog",
        "type": "blog",
    },
}


# ============================================================
# 你后续新增期刊 RSS 地址就放这里
# ============================================================

USER_CUSTOM_RSS_FEEDS = {
    # "期刊或来源名称": {
    #     "url": "https://example.com/rss.xml",
    #     "tag": "aidd",
    #     "type": "paper",
    # },
}

RSS_FEEDS.update(USER_CUSTOM_RSS_FEEDS)


# ============================================================
# API 源：bioRxiv / ChemRxiv
# 这些不是 RSS_FEEDS，不能用 feedparser 直接解析。
# ============================================================

API_SOURCES = {
    # ================= bioRxiv =================
    # 建议只抓最近 3 天，并按 category 限制，否则数量会很多。
    "bioRxiv Bioinformatics": {
        "provider": "biorxiv",
        "server": "biorxiv",
        "category": "bioinformatics",
        "days": 3,
        "tag": "preprint",
        "type": "paper",
    },
    "bioRxiv Biophysics": {
        "provider": "biorxiv",
        "server": "biorxiv",
        "category": "biophysics",
        "days": 3,
        "tag": "preprint",
        "type": "paper",
    },
    "bioRxiv Molecular Biology": {
        "provider": "biorxiv",
        "server": "biorxiv",
        "category": "molecular biology",
        "days": 3,
        "tag": "preprint",
        "type": "paper",
    },
    "bioRxiv Biochemistry": {
        "provider": "biorxiv",
        "server": "biorxiv",
        "category": "biochemistry",
        "days": 3,
        "tag": "preprint",
        "type": "paper",
    },
    "bioRxiv Synthetic Biology": {
        "provider": "biorxiv",
        "server": "biorxiv",
        "category": "synthetic biology",
        "days": 3,
        "tag": "preprint",
        "type": "paper",
    },

    # ================= ChemRxiv =================
    # 只保留与你更相关的分类；仍会经过关键词筛选。
    "ChemRxiv AIDD / Computational Chemistry": {
        "provider": "chemrxiv",
        "url": "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items",
        "days": 7,
        "allowed_categories": {
            "Biological and Medicinal Chemistry",
            "Theoretical and Computational Chemistry",
            "Computational Chemistry",
            "Cheminformatics",
            "Artificial Intelligence",
            "Pharmaceutical Industry",
        },
        "tag": "preprint",
        "type": "paper",
    },
}


# ============================================================
# 关键词分组
# 逻辑：
#   - 先判断命中哪些主题组
#   - 再计算相关性分数
#   - general/blog 源要求至少命中强关键词，避免噪声过大
# ============================================================

KEYWORD_GROUPS = {
    "AIDD / Drug Design": [
        "drug discovery", "drug design", "ai drug discovery", "AIDD",
        "molecular generation", "molecule generation", "molecular design",
        "de novo design", "de novo drug design",
        "structure-based drug design", "structure based drug design", "SBDD",
        "ligand-based", "ligand based", "binding pocket", "binding site",
        "protein-ligand", "protein ligand", "protein–ligand",
        "binding affinity", "docking", "molecular docking", "virtual screening",
        "molecular dynamics", "free energy", "FEP", "ADMET", "QSAR",
        "lead optimization", "hit discovery", "small molecule",
        "fragment-based", "fragment based", "pharmacophore",
        "interaction fingerprint", "molecular property prediction",
        "activity prediction", "retrosynthesis", "reaction prediction",
        "scoring function", "force field", "PROTAC",
        "medicinal chemistry", "chemical biology", "cheminformatics",
    ],

    "3D Molecular / Generative Modeling": [
        "3D molecule", "3D molecular", "conformation generation",
        "conformer generation", "geometric deep learning", "equivariant",
        "E(3)", "SE(3)", "SO(3)", "diffusion model", "diffusion",
        "flow matching", "rectified flow", "score-based", "score based",
        "Bayesian flow network", "BFN", "graph neural network", "GNN",
        "message passing", "graph transformer", "molecular graph",
        "molecular foundation model", "molecular representation",
        "pocket-conditioned", "pocket conditioned",
    ],

    "Protein / Structural Biology": [
        "protein design", "protein generation", "protein language model",
        "protein structure prediction", "protein folding", "protein-protein interaction",
        "protein protein interaction", "PPI", "antibody design", "enzyme design",
        "binder design", "peptide design", "inverse folding", "AlphaFold",
        "RFdiffusion", "RoseTTAFold", "ESM", "Boltz", "Chai",
        "structure prediction", "cryo-EM", "electron density", "density map",
        "X-ray crystallography", "binding site", "protein-ligand complex",
    ],

    "LLM / NLP": [
        "large language model", "LLM", "language model", "foundation model",
        "instruction tuning", "alignment", "RLHF", "DPO",
        "preference optimization", "reasoning", "chain-of-thought",
        "chain of thought", "in-context learning", "in context learning",
        "retrieval augmented generation", "retrieval-augmented", "RAG",
        "long context", "context window", "fine-tuning", "LoRA", "PEFT",
        "mixture of experts", "MoE", "tokenizer", "text generation",
        "code generation", "program synthesis", "scientific discovery",
        "AI scientist",
    ],

    "Agent / Autonomous AI": [
        "agent", "AI agent", "LLM agent", "autonomous agent",
        "multi-agent", "multiagent", "tool use", "tool learning",
        "tool-using agent", "function calling", "planning", "task planning",
        "reflection", "ReAct", "agentic",
        "web agent", "browser agent", "computer use", "GUI agent",
        "code agent", "workflow agent", "agent benchmark", "MCP",
        "scientific agent", "research agent", "chemistry agent", "biology agent",
        "laboratory automation", "lab automation", "self-driving lab",
        "closed-loop discovery", "active learning",
    ],

    "CV / Multimodal": [
        "computer vision", "vision-language", "vision language", "multimodal",
        "multimodal large language model", "MLLM", "VLM", "image generation",
        "text-to-image", "video generation", "segmentation", "object detection",
        "detection", "visual reasoning", "diffusion transformer", "DiT",
        "image understanding", "medical image", "3D vision", "point cloud",
        "scene understanding",
    ],

    "AI Infrastructure / General ML": [
        "pretraining", "pre-training", "scaling law", "benchmark", "evaluation",
        "synthetic data", "dataset", "transformer", "generative", "foundation model",
        "model compression", "distillation", "efficient training", "inference",
    ],
}


# ============================================================
# 关键词匹配强弱设置
# ============================================================

STRICT_MATCH_KEYWORDS = {
    "BFN", "GNN", "LLM", "VLM", "MLLM", "RAG", "MoE", "LoRA", "PEFT",
    "DPO", "RLHF", "MCP", "FEP", "QSAR", "ADMET", "PROTAC", "SE(3)",
    "E(3)", "SO(3)", "ESM", "PPI", "DiT", "AI", "agent", "ReAct",
}
STRICT_MATCH_KEYWORDS_LOWER = {kw.lower() for kw in STRICT_MATCH_KEYWORDS}

# 弱关键词不能单独让 general/blog 源入库。
WEAK_KEYWORDS = {
    "benchmark", "evaluation", "pretraining", "pre-training", "synthetic data",
    "dataset", "transformer", "generative", "representation learning",
    "self-supervised", "contrastive learning", "model compression",
    "distillation", "efficient training", "inference", "planning",
}
WEAK_KEYWORDS_LOWER = {kw.lower() for kw in WEAK_KEYWORDS}

# 高优先级关键词：命中后相关性加权更高。
HIGH_PRIORITY_KEYWORDS = {
    "structure-based drug design", "molecular generation", "de novo drug design",
    "protein-ligand", "binding pocket", "virtual screening", "ADMET",
    "molecular docking", "protein design", "protein language model",
    "electron density", "large language model", "LLM", "AI agent",
    "multi-agent", "tool use", "RAG", "reasoning", "vision-language",
    "multimodal", "foundation model", "diffusion", "flow matching",
    "rectified flow", "graph transformer", "equivariant",
    "cheminformatics", "medicinal chemistry", "chemical biology",
}
HIGH_PRIORITY_KEYWORDS_LOWER = {kw.lower() for kw in HIGH_PRIORITY_KEYWORDS}


# ============================================================
# 不同来源的最低入库分数
# ============================================================

MIN_SCORE_BY_TAG = {
    "aidd": 4,
    "ml": 7,
    "nlp": 7,
    "cv": 7,
    "agent": 7,
    "general": 8,
    "blog": 8,
    "preprint": 4,
    "custom": 5,
    None: 5,
}


# ============================================================
# 初始化客户端
# ============================================================

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


# ============================================================
# 论文 ID 规范化函数
# ============================================================

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)

ARXIV_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:|oai:arXiv\.org:)?"
    r"([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
    re.I,
)


def strip_html(text):
    if not text:
        return ""
    text = html.unescape(str(text))
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


# ============================================================
# 关键词匹配与相关性评分
# ============================================================


def keyword_hit(text: str, kw: str) -> bool:
    """
    严格匹配：用于 LLM/RAG/agent 这类短词，要求左右不是字母数字，避免误命中。
    普通匹配：大小写不敏感子串匹配。
    """
    text = text or ""
    kw = kw or ""
    kw_lower = kw.lower()

    if kw_lower in STRICT_MATCH_KEYWORDS_LOWER:
        pattern = rf"(?<![A-Za-z0-9]){re.escape(kw)}(?![A-Za-z0-9])"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None

    return kw_lower in text.lower()


def match_keyword_groups(text: str):
    """
    返回：
    - matched_groups: 命中的主题组
    - matched_keywords: 所有命中的关键词
    - strong_keywords: 非弱关键词
    """
    matched_groups = []
    matched_keywords = []

    for group_name, keywords in KEYWORD_GROUPS.items():
        group_hits = []
        for kw in keywords:
            if keyword_hit(text, kw):
                group_hits.append(kw)

        if group_hits:
            matched_groups.append(group_name)
            matched_keywords.extend(group_hits)

    # 去重但保留顺序
    seen = set()
    unique_keywords = []
    for kw in matched_keywords:
        key = kw.lower()
        if key not in seen:
            unique_keywords.append(kw)
            seen.add(key)

    strong_keywords = [
        kw for kw in unique_keywords
        if kw.lower() not in WEAK_KEYWORDS_LOWER
    ]

    return matched_groups, unique_keywords, strong_keywords


def relevance_score(matched_keywords, strong_keywords):
    """
    简单可解释打分：
    - 弱关键词：+1
    - 强关键词：+2
    - 高优先级关键词：额外 +2
    """
    score = 0

    for kw in matched_keywords:
        kw_lower = kw.lower()
        if kw_lower in WEAK_KEYWORDS_LOWER:
            score += 1
        else:
            score += 2

        if kw_lower in HIGH_PRIORITY_KEYWORDS_LOWER:
            score += 2

    return score


def should_keep_entry(text, feed_tag):
    matched_groups, matched_keywords, strong_keywords = match_keyword_groups(text)
    score = relevance_score(matched_keywords, strong_keywords)
    min_score = MIN_SCORE_BY_TAG.get(feed_tag, MIN_SCORE_BY_TAG.get(None, 5))

    if not matched_keywords:
        return False, matched_groups, matched_keywords, strong_keywords, score

    # 综合大刊和博客噪声较大：必须有强关键词，不能只靠 benchmark/evaluation/generative 这种泛词入库。
    if feed_tag in {"general", "blog"} and not strong_keywords:
        return False, matched_groups, matched_keywords, strong_keywords, score

    keep = score >= min_score
    return keep, matched_groups, matched_keywords, strong_keywords, score


# ============================================================
# Notion 相关函数
# ============================================================


def check_if_exists(paper_id, canonical_url, raw_url, title):
    """
    三层查重：
    1. InternalID 查重：新数据最稳
    2. URL 查重：兼容旧数据
    3. Title 查重：兜底兼容旧数据
    """
    filters = [
        {"property": "InternalID", "rich_text": {"equals": paper_id}},
        {"property": "URL", "url": {"equals": canonical_url}},
        {"property": "Title", "title": {"equals": title}},
    ]

    if raw_url and raw_url != canonical_url:
        filters.append({"property": "URL", "url": {"equals": raw_url}})

    response = notion.databases.query(
        database_id=DATABASE_ID,
        filter={"or": filters},
        page_size=1,
    )

    return len(response.get("results", [])) > 0


def push_to_notion(
    title,
    url,
    summary,
    source,
    date_str,
    paper_id,
    feed_tag=None,
    entry_type="paper",
    matched_groups=None,
    score=None,
):
    """
    Notion 必需字段：
    - Title      : title
    - URL        : url
    - Summary    : rich_text
    - Source     : select
    - Date       : date
    - Status     : status
    - InternalID : rich_text

    可选字段：
    - NOTION_TAG_PROPERTY        : multi_select
    - NOTION_TOPIC_PROPERTY      : multi_select
    - NOTION_SCORE_PROPERTY      : number
    - NOTION_ENTRY_TYPE_PROPERTY : select
    """
    properties = {
        "Title": {"title": [{"text": {"content": title[:2000]}}]},
        "URL": {"url": url},
        "Summary": {"rich_text": [{"text": {"content": summary[:2000]}}]},
        "Source": {"select": {"name": source}},
        "Date": {"date": {"start": date_str}},
        "Status": {"status": {"name": "Inbox"}},
        "InternalID": {"rich_text": [{"text": {"content": paper_id[:2000]}}]},
    }

    if NOTION_TAG_PROPERTY and feed_tag:
        properties[NOTION_TAG_PROPERTY] = {
            "multi_select": [{"name": str(feed_tag)}]
        }

    if NOTION_TOPIC_PROPERTY and matched_groups:
        properties[NOTION_TOPIC_PROPERTY] = {
            "multi_select": [{"name": group[:100]} for group in matched_groups]
        }

    if NOTION_SCORE_PROPERTY and score is not None:
        properties[NOTION_SCORE_PROPERTY] = {"number": float(score)}

    if NOTION_ENTRY_TYPE_PROPERTY and entry_type:
        properties[NOTION_ENTRY_TYPE_PROPERTY] = {"select": {"name": entry_type}}

    notion.pages.create(
        parent={"database_id": DATABASE_ID},
        properties=properties,
    )

    print(f"✅ 已入库: {title[:60]}... [{paper_id}] score={score}")


# ============================================================
# API 源抓取：bioRxiv / ChemRxiv
# ============================================================


def fetch_json(url, headers=None):
    req = Request(
        url,
        headers=headers or {
            "User-Agent": "Mozilla/5.0 (compatible; AIDD-Daily-Bot/1.0)",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_iso_date(date_text):
    if not date_text:
        return None

    date_text = str(date_text).replace("Z", "+00:00")

    try:
        return datetime.datetime.fromisoformat(date_text)
    except Exception:
        pass

    try:
        return datetime.datetime.strptime(str(date_text)[:10], "%Y-%m-%d")
    except Exception:
        return None


def fetch_biorxiv_entries(source_info, today_dt):
    days = int(source_info.get("days", 3))
    server = source_info.get("server", "biorxiv")
    category = source_info.get("category")

    start_date = (today_dt - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = today_dt.strftime("%Y-%m-%d")

    base_url = f"https://api.biorxiv.org/details/{server}/{start_date}/{end_date}/0"

    if category:
        base_url += "?" + urlencode({"category": category})

    data = fetch_json(base_url)
    collection = data.get("collection", [])

    entries = []
    for item in collection:
        doi = item.get("doi", "")
        title = item.get("title", "")
        abstract = item.get("abstract", "")
        category_name = item.get("category", "")
        date_text = item.get("date", "")

        if not title or not doi:
            continue

        entries.append({
            "title": title,
            "link": f"https://www.biorxiv.org/content/{doi}",
            "summary": abstract,
            "id": doi,
            "doi": doi,
            "date": date_text,
            "source_category": category_name,
        })

    return entries


def fetch_chemrxiv_entries(source_info, today_dt):
    url = source_info["url"]
    allowed_categories = set(source_info.get("allowed_categories", set()))
    days = int(source_info.get("days", 7))
    cutoff_dt = today_dt - datetime.timedelta(days=days)

    data = fetch_json(url)
    hits = data.get("itemHits", [])

    entries = []
    for hit in hits:
        item = hit.get("item", {})
        if not item:
            continue

        categories = {
            c.get("name", "")
            for c in item.get("categories", [])
            if c.get("name")
        }

        if allowed_categories and not (categories & allowed_categories):
            continue

        published_date = item.get("publishedDate") or item.get("approvedDate") or item.get("submittedDate")
        parsed_date = parse_iso_date(published_date)
        if parsed_date is not None:
            # 去掉时区，方便和 today_dt 比较。
            parsed_naive = parsed_date.replace(tzinfo=None)
            today_naive = today_dt.replace(tzinfo=None)
            cutoff_naive = cutoff_dt.replace(tzinfo=None)
            if parsed_naive < cutoff_naive or parsed_naive > today_naive + datetime.timedelta(days=1):
                continue

        item_id = item.get("id", "")
        doi = item.get("doi", "")
        title = item.get("title", "")
        abstract = item.get("abstract", "")

        if not title or not item_id:
            continue

        entries.append({
            "title": title,
            "link": f"https://chemrxiv.org/engage/chemrxiv/article-details/{item_id}",
            "summary": abstract,
            "id": doi or item_id,
            "doi": doi,
            "date": published_date,
            "source_category": "; ".join(sorted(categories)),
        })

    return entries


def fetch_api_entries(source_info, today_dt):
    provider = source_info.get("provider")

    if provider == "biorxiv":
        return fetch_biorxiv_entries(source_info, today_dt)

    if provider == "chemrxiv":
        return fetch_chemrxiv_entries(source_info, today_dt)

    return []


# ============================================================
# DeepSeek 总结函数
# ============================================================


def summarize_paper(title, abstract, matched_groups=None, score=None):
    """用 DeepSeek 生成克制、客观的论文摘要。"""
    print(f"🤖 正在总结论文: {title[:60]}...")

    topics = ", ".join(matched_groups or [])

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

命中主题：
{topics}

相关性分数：
{score}

标题：
{title}

摘要：
{abstract}

请直接输出摘要正文，不要加标题，不要分点。
"""

    return call_deepseek(prompt)


def summarize_blog_or_news(title, abstract, matched_groups=None, score=None):
    """用于博客、新闻和工业界动态，不强行写成论文摘要。"""
    print(f"🤖 正在总结动态: {title[:60]}...")

    topics = ", ".join(matched_groups or [])

    prompt = f"""
你是 AI 药物发现、人工智能和大模型方向的博士生。请根据下面的标题和摘要/简介，写一段中文摘要，供 Notion 每日科研动态数据库快速浏览使用。

写作要求：
1. 只基于标题和简介，不要补充原文中没有的信息。
2. 不要写成营销文案，不要使用“重磅”“颠覆”“炸裂”“太强了”等夸张表达。
3. 优先说明：这是什么动态、涉及什么技术方向、对 AI 药物发现 / NLP / CV / 智能体是否可能有参考价值。
4. 如果信息不足，就明确写“简介中未提供技术细节”。
5. 控制在 70–110 字。

命中主题：
{topics}

相关性分数：
{score}

标题：
{title}

简介：
{abstract}

请直接输出摘要正文，不要加标题，不要分点。
"""

    return call_deepseek(prompt)


def call_deepseek(prompt):
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": "你是一个严谨的科研文献摘要助手，输出必须客观、克制、避免宣传语。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=260,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"❌ LLM Error: {e}")
        return "AI 总结失败，请人工查看。"


# ============================================================
# 单条记录处理函数
# ============================================================


def process_entry(
    entry,
    source_name,
    feed_tag,
    entry_type,
    today,
    seen_paper_ids,
    counters,
):
    title = ""

    try:
        title = strip_html(get_entry_field(entry, "title", "")).strip()
        raw_url = str(get_entry_field(entry, "link", "")).strip()
        abstract = strip_html(get_entry_field(entry, "summary", "No Abstract"))

        if not title:
            print("   ⚠️ 跳过一条无标题记录")
            counters["skipped_error"] += 1
            return

        if not raw_url:
            print(f"   ⚠️ 跳过无 URL 记录: {title[:60]}...")
            counters["skipped_error"] += 1
            return

        canonical_url = canonicalize_url(raw_url)
        paper_id = get_paper_id(entry)

        text_content = f"{title} {abstract}"
        keep, matched_groups, matched_keywords, strong_keywords, score = should_keep_entry(
            text=text_content,
            feed_tag=feed_tag,
        )

        if not keep:
            counters["skipped_keyword"] += 1
            return

        if paper_id in seen_paper_ids:
            print(f"   💨 本次运行已见过: {title[:60]}... [{paper_id}]")
            counters["skipped_existing"] += 1
            return

        seen_paper_ids.add(paper_id)

        exists = check_if_exists(
            paper_id=paper_id,
            canonical_url=canonical_url,
            raw_url=raw_url,
            title=title,
        )

        if exists:
            print(f"   💨 已存在: {title[:60]}... [{paper_id}]")
            counters["skipped_existing"] += 1
            return

        if entry_type in {"blog", "news"}:
            summary = summarize_blog_or_news(
                title=title,
                abstract=abstract,
                matched_groups=matched_groups,
                score=score,
            )
        else:
            summary = summarize_paper(
                title=title,
                abstract=abstract,
                matched_groups=matched_groups,
                score=score,
            )

        push_to_notion(
            title=title,
            url=canonical_url,
            summary=summary,
            source=source_name,
            date_str=today,
            paper_id=paper_id,
            feed_tag=feed_tag,
            entry_type=entry_type,
            matched_groups=matched_groups,
            score=score,
        )

        print(
            f"   🔎 topics={matched_groups}; "
            f"strong={strong_keywords[:5]}; score={score}"
        )

        counters["new"] += 1

    except Exception as e:
        print(f"   ❌ 单篇处理失败: {title[:60] if title else '未知标题'}")
        print(f"      错误: {e}")
        counters["skipped_error"] += 1


# ============================================================
# 主程序
# ============================================================


def run():
    print("🚀 开始抓取每日论文 / 科研动态...")

    tz = pytz.timezone(TIMEZONE)
    today_dt = datetime.datetime.now(tz)
    today = today_dt.strftime("%Y-%m-%d")

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

    counters = {
        "new": 0,
        "skipped_existing": 0,
        "skipped_keyword": 0,
        "skipped_error": 0,
        "feed_error": 0,
    }

    # ================= RSS 源 =================

    for source_name, feed_info in RSS_FEEDS.items():
        if source_name in EXCLUDED_FEED_NAMES:
            print("\n⏭️ 跳过来源: {}，如需启用请从 EXCLUDED_FEED_NAMES 中移除".format(source_name))
            continue

        # 兼容旧格式：若值是字符串则当作纯 URL
        if isinstance(feed_info, str):
            feed_url = feed_info
            feed_tag = None
            entry_type = "paper"
        else:
            feed_url = feed_info["url"]
            feed_tag = feed_info.get("tag")
            entry_type = feed_info.get("type", "paper")

        if feed_tag in EXCLUDED_FEED_TAGS:
            print("\n⏭️ 跳过来源: {} [{}]，如需启用请修改 EXCLUDED_FEED_TAGS".format(source_name, feed_tag))
            continue

        print("\n📡 正在扫描: {} [{} / {}] ...".format(source_name, feed_tag or "-", entry_type), end="")

        try:
            feed = feedparser.parse(feed_url, request_headers=headers)

            status = getattr(feed, "status", 200)
            if status not in {200, 301, 302, 304}:
                print(f" [❌ 失败: 状态码 {status}]")
                counters["feed_error"] += 1
                continue

            entries = getattr(feed, "entries", [])
            entry_count = len(entries)

            print(f" [✅ 连接成功，发现 {entry_count} 条记录]")

            if entry_count == 0:
                print("   ⚠️ 源是通的，但没有解析到记录，可能今天没更新或 RSS 格式变化")
                continue

            for entry in entries[:MAX_ENTRIES_PER_FEED]:
                process_entry(
                    entry=entry,
                    source_name=source_name,
                    feed_tag=feed_tag,
                    entry_type=entry_type,
                    today=today,
                    seen_paper_ids=seen_paper_ids,
                    counters=counters,
                )

        except Exception as e:
            print(f"\n⚠️ RSS 源解析出错: {source_name}, 错误: {e}")
            counters["feed_error"] += 1
            continue

    # ================= API 源：bioRxiv / ChemRxiv =================

    for source_name, source_info in API_SOURCES.items():
        feed_tag = source_info.get("tag", "preprint")
        entry_type = source_info.get("type", "paper")

        if source_name in EXCLUDED_FEED_NAMES:
            print("\n⏭️ 跳过 API 来源: {}，如需启用请从 EXCLUDED_FEED_NAMES 中移除".format(source_name))
            continue

        if feed_tag in EXCLUDED_FEED_TAGS:
            print("\n⏭️ 跳过 API 来源: {} [{}]".format(source_name, feed_tag))
            continue

        print("\n📡 正在扫描 API 来源: {} [{} / {}] ...".format(source_name, feed_tag, entry_type), end="")

        try:
            api_entries = fetch_api_entries(source_info, today_dt)
            print(f" [✅ 获取成功，发现 {len(api_entries)} 条记录]")

            for entry in api_entries[:MAX_ENTRIES_PER_API_SOURCE]:
                process_entry(
                    entry=entry,
                    source_name=source_name,
                    feed_tag=feed_tag,
                    entry_type=entry_type,
                    today=today,
                    seen_paper_ids=seen_paper_ids,
                    counters=counters,
                )

            # 避免连续请求 preprint API 过快。
            time.sleep(0.5)

        except Exception as e:
            print(f"\n⚠️ API 源解析出错: {source_name}, 错误: {e}")
            counters["feed_error"] += 1
            continue

    print("\n================= 今日抓取完成 =================")
    print(f"✅ 新增论文 / 动态: {counters['new']}")
    print(f"💨 已存在 / 重复跳过: {counters['skipped_existing']}")
    print(f"🔎 关键词不匹配跳过: {counters['skipped_keyword']}")
    print(f"⚠️ 单篇错误跳过: {counters['skipped_error']}")
    print(f"📡 RSS/API 源错误: {counters['feed_error']}")
    print("================================================")


if __name__ == "__main__":
    run()

import feedparser
import os
import datetime
import pytz
import re
import hashlib
import html
from urllib.parse import urlparse, urlunparse

from openai import OpenAI
from notion_client import Client


# ============================================================
# 配置区域
# ============================================================

TIMEZONE = "Asia/Shanghai"  # 如果你更想按日本时间入库，可改成 "Asia/Tokyo"
MAX_ENTRIES_PER_FEED = 50

# 如果 Notion 数据库里有这些字段，就填字段名；没有就保持 None。
# 注意：字段类型必须对应，否则 Notion API 会报错。
NOTION_TAG_PROPERTY = None              # 例："Tags"，multi_select，用于写入来源分组 aidd/ml/nlp/cv/agent/general/blog/custom
NOTION_TOPIC_PROPERTY = None            # 例："Topics"，multi_select，用于写入关键词命中的主题组
NOTION_SCORE_PROPERTY = None            # 例："Score"，number，用于写入相关性分数
NOTION_ENTRY_TYPE_PROPERTY = None       # 例："Type"，select，用于写入 paper/blog/news


# ============================================================
# RSS 源
# 结构说明：
#   key: 你想在 Notion Source 字段里显示的来源名
#   url: RSS 地址
#   tag: 来源大类，用于筛选策略与可选 Notion 标签
#   type: paper / blog / news
# ============================================================

RSS_FEEDS = {
    # ================= AIDD / 计算化学 / 结构生物 =================
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
    "ArXiv q-bio.MN - Molecular Networks": {
        "url": "https://rss.arxiv.org/rss/q-bio.MN",
        "tag": "aidd",
        "type": "paper",
    },
    "ArXiv physics.chem-ph - Chemical Physics": {
        "url": "https://rss.arxiv.org/rss/physics.chem-ph",
        "tag": "aidd",
        "type": "paper",
    },
    "ArXiv cond-mat.soft - Soft Matter": {
        "url": "https://rss.arxiv.org/rss/cond-mat.soft",
        "tag": "aidd",
        "type": "paper",
    },
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

    # ================= ML / 通用 AI =================
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
    "ArXiv cs.NE - Neural and Evolutionary Computing": {
        "url": "https://rss.arxiv.org/rss/cs.NE",
        "tag": "ml",
        "type": "paper",
    },
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
    "JMLR": {
        "url": "https://jmlr.org/jmlr.xml",
        "tag": "ml",
        "type": "paper",
    },

    # ================= NLP / LLM =================
    "ArXiv cs.CL - NLP": {
        "url": "https://rss.arxiv.org/rss/cs.CL",
        "tag": "nlp",
        "type": "paper",
    },
    "ArXiv cs.IR - Information Retrieval / RAG": {
        "url": "https://rss.arxiv.org/rss/cs.IR",
        "tag": "nlp",
        "type": "paper",
    },

    # ================= CV / 多模态 =================
    "ArXiv cs.CV - Computer Vision": {
        "url": "https://rss.arxiv.org/rss/cs.CV",
        "tag": "cv",
        "type": "paper",
    },
    "ArXiv eess.IV - Image and Video Processing": {
        "url": "https://rss.arxiv.org/rss/eess.IV",
        "tag": "cv",
        "type": "paper",
    },

    # ================= 智能体 / 机器人 / 人机交互 =================
    "ArXiv cs.MA - Multiagent Systems": {
        "url": "https://rss.arxiv.org/rss/cs.MA",
        "tag": "agent",
        "type": "paper",
    },
    "ArXiv cs.RO - Robotics": {
        "url": "https://rss.arxiv.org/rss/cs.RO",
        "tag": "agent",
        "type": "paper",
    },
    "ArXiv cs.HC - Human-Computer Interaction": {
        "url": "https://rss.arxiv.org/rss/cs.HC",
        "tag": "agent",
        "type": "paper",
    },

    # ================= 综合性顶刊 =================
    "Nature Communications": {
        "url": "https://www.nature.com/ncomms.rss",
        "tag": "general",
        "type": "paper",
    },
    "Nature Biotechnology": {
        "url": "https://www.nature.com/nbt.rss",
        "tag": "general",
        "type": "paper",
    },
    "Nature Methods": {
        "url": "https://www.nature.com/nmeth.rss",
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
    "Cell Reports Physical Science": {
        "url": "https://www.cell.com/cell-reports-physical-science/inpress.rss",
        "tag": "general",
        "type": "paper",
    },

    # ================= 工业界 / 实验室博客 =================
    # 这些不是论文源，但适合追热点。脚本会用 blog/news prompt 摘要。
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
    "BAIR Blog": {
        "url": "https://bair.berkeley.edu/blog/feed.xml",
        "tag": "blog",
        "type": "blog",
    },
    "Hugging Face Blog": {
        "url": "https://huggingface.co/blog/feed.xml",
        "tag": "blog",
        "type": "blog",
    },
    "Distill": {
        "url": "https://distill.pub/rss.xml",
        "tag": "blog",
        "type": "blog",
    },
}


# ============================================================
# 你后续新增期刊 RSS 地址就放这里
# 格式照抄下面模板即可。
# tag 建议：aidd / ml / nlp / cv / agent / general / blog / custom
# type 建议：paper / blog / news
# ============================================================


USER_CUSTOM_RSS_FEEDS = {
    # ============================================================
    # Nature Reviews / Nature 系列：建议保留 AOP + current issue
    # ============================================================

    "Nature Reviews Chemistry": {
        "url": "https://www.nature.com/natrevchem/current_issue/rss",
        "tag": "aidd",
        "type": "paper",
    },
    "Nature Reviews Chemistry AOP": {
        "url": "https://www.nature.com/natrevchem/journal/vaop/ncurrent/rss.rdf",
        "tag": "aidd",
        "type": "paper",
    },

    "Nature Medicine": {
        "url": "https://www.nature.com/nm/current_issue/rss",
        "tag": "general",
        "type": "paper",
    },
    "Nature Medicine AOP": {
        "url": "https://www.nature.com/nm/journal/vaop/ncurrent/rss.rdf",
        "tag": "general",
        "type": "paper",
    },

    # 如果你想显式覆盖/补充 Nature Methods，也可以放这里；
    # 但我之前给你的主 RSS_FEEDS 里已经有 Nature Methods。
    "Nature Methods AOP": {
        "url": "https://www.nature.com/nmeth/journal/vaop/ncurrent/rss.rdf",
        "tag": "general",
        "type": "paper",
    },

    # ============================================================
    # ACS：化学、药物化学、计算化学
    # ============================================================

    "Chemical Reviews": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=chreay",
        "tag": "aidd",
        "type": "paper",
    },
    "ACS Chemical Biology": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=acbcct",
        "tag": "aidd",
        "type": "paper",
    },
    "Biochemistry": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=bichaw",
        "tag": "aidd",
        "type": "paper",
    },

    # JACS 很强，但非常宽。建议 tag 用 general，靠关键词过滤。
    "JACS": {
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jacsat",
        "tag": "general",
        "type": "paper",
    },

    # ============================================================
    # PNAS
    # ============================================================

    # 你主脚本里已经有 PNAS。这里给的是官方 eTOC feed 的等价写法。
    "PNAS eTOC": {
        "url": "https://www.pnas.org/action/showFeed?feed=rss&jc=PNAS&type=etoc",
        "tag": "general",
        "type": "paper",
    },

    # ============================================================
    # RSC：综述 / 药物化学
    # ============================================================

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

    # ============================================================
    # Cell Press：化学生物 / 系统生物 / AI for biology 相关
    # ============================================================

    "Cell Chemical Biology": {
        "url": "https://www.cell.com/cell-chemical-biology/rss",
        "tag": "aidd",
        "type": "paper",
    },
    "Cell Genomics": {
        "url": "https://www.cell.com/cell-genomics/rss",
        "tag": "general",
        "type": "paper",
    },
    "Cell Reports Medicine": {
        "url": "https://www.cell.com/cell-reports-medicine/rss",
        "tag": "general",
        "type": "paper",
    },

    # ============================================================
    # Bioinformatics / computational biology
    # ============================================================

    "Nucleic Acids Research": {
        "url": "https://academic.oup.com/rss/site_5153/3127.xml",
        "tag": "aidd",
        "type": "paper",
    },

    # Journal of Cheminformatics 的 Springer/BMC RSS 地址有时不稳定；
    # 这个地址建议你先跑一次脚本测试 feedparser 是否能解析。
    "Journal of Cheminformatics": {
        "url": "https://link.springer.com/search.rss?facet-journal-id=13321&channel-name=Journal%20of%20Cheminformatics",
        "tag": "aidd",
        "type": "paper",
    },
}



RSS_FEEDS.update(USER_CUSTOM_RSS_FEEDS)


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
        "reflection", "ReAct", "agentic", "embodied agent",
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
        "scene understanding", "self-supervised", "contrastive learning",
        "representation learning", "world model",
    ],

    "AI Infrastructure / General ML": [
        "pretraining", "pre-training", "scaling law", "benchmark", "evaluation",
        "synthetic data", "dataset", "transformer", "generative", "foundation model",
        "model compression", "distillation", "efficient training", "inference",
    ],
}

# 这些短词或容易误命中的词必须使用边界匹配。
# 例如 agent 如果不用边界匹配，会误命中 reagent。
STRICT_MATCH_KEYWORDS = {
    "BFN", "GNN", "LLM", "VLM", "MLLM", "RAG", "MoE", "LoRA", "PEFT",
    "DPO", "RLHF", "MCP", "FEP", "QSAR", "ADMET", "PROTAC", "SE(3)",
    "E(3)", "SO(3)", "ESM", "PPI", "DiT", "AI", "agent", "ReAct",
}
STRICT_MATCH_KEYWORDS_LOWER = {kw.lower() for kw in STRICT_MATCH_KEYWORDS}

# 弱关键词不能单独让 general/blog 源入库，否则综合顶刊和博客噪声会很大。
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
}
HIGH_PRIORITY_KEYWORDS_LOWER = {kw.lower() for kw in HIGH_PRIORITY_KEYWORDS}

# 不同来源类型的最低分。
# general/blog 源阈值更高，是为了减少综合大刊和博客的噪声。
MIN_SCORE_BY_TAG = {
    "aidd": 1,
    "ml": 1,
    "nlp": 1,
    "cv": 1,
    "agent": 1,
    "general": 3,
    "blog": 3,
    "custom": 1,
    None: 1,
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

    # 命中多个主题组本身也说明文章可能有交叉价值，但避免分数膨胀，只加少量。
    return score


def should_keep_entry(text, feed_tag):
    matched_groups, matched_keywords, strong_keywords = match_keyword_groups(text)
    score = relevance_score(matched_keywords, strong_keywords)
    min_score = MIN_SCORE_BY_TAG.get(feed_tag, 1)

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
# 主程序
# ============================================================


def run():
    print("🚀 开始抓取每日论文 / 科研动态...")

    tz = pytz.timezone(TIMEZONE)
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

    for source_name, feed_info in RSS_FEEDS.items():
        # 兼容旧格式：若值是字符串则当作纯 URL
        if isinstance(feed_info, str):
            feed_url = feed_info
            feed_tag = None
            entry_type = "paper"
        else:
            feed_url = feed_info["url"]
            feed_tag = feed_info.get("tag")
            entry_type = feed_info.get("type", "paper")

        print(f"\n📡 正在扫描: {source_name} [{feed_tag or '-'} / {entry_type}] ...", end="")

        try:
            feed = feedparser.parse(feed_url, request_headers=headers)

            status = getattr(feed, "status", 200)
            if status not in {200, 301, 302, 304}:
                print(f" [❌ 失败: 状态码 {status}]")
                total_feed_error += 1
                continue

            entries = getattr(feed, "entries", [])
            entry_count = len(entries)

            print(f" [✅ 连接成功，发现 {entry_count} 条记录]")

            if entry_count == 0:
                print("   ⚠️ 源是通的，但没有解析到记录，可能今天没更新或 RSS 格式变化")
                continue

            for entry in entries[:MAX_ENTRIES_PER_FEED]:
                title = ""
                try:
                    title = strip_html(get_entry_field(entry, "title", "")).strip()
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

                    text_content = f"{title} {abstract}"
                    keep, matched_groups, matched_keywords, strong_keywords, score = should_keep_entry(
                        text=text_content,
                        feed_tag=feed_tag,
                    )

                    if not keep:
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

                    total_new += 1

                except Exception as e:
                    print(f"   ❌ 单篇处理失败: {title[:60] if title else '未知标题'}")
                    print(f"      错误: {e}")
                    total_skipped_error += 1
                    continue

        except Exception as e:
            print(f"\n⚠️ RSS 源解析出错: {source_name}, 错误: {e}")
            total_feed_error += 1
            continue

    print("\n================= 今日抓取完成 =================")
    print(f"✅ 新增论文 / 动态: {total_new}")
    print(f"💨 已存在 / 重复跳过: {total_skipped_existing}")
    print(f"🔎 关键词不匹配跳过: {total_skipped_keyword}")
    print(f"⚠️ 单篇错误跳过: {total_skipped_error}")
    print(f"📡 RSS 源错误: {total_feed_error}")
    print("================================================")


if __name__ == "__main__":
    run()

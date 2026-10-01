#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AIDD Daily Paper Bot
====================

设计目标：
1. 只抓取固定白名单期刊、bioRxiv 和 ChemRxiv；
2. 正式期刊统一通过 Crossref API 按 ISSN 获取最近注册的文章，
   因而不依赖各出版社不稳定的 RSS/ASAP 页面结构；
3. 核心候选词命中后按任务与上下文筛选；
4. 使用明确任务规则与有条件的弱词；不使用打分；
5. DOI / URL / 标题查重后，用 DeepSeek 生成中文摘要并写入 Notion；
6. DIAGNOSE_ONLY=1 时只诊断，不调用 DeepSeek、不查询或写入 Notion。

Notion 数据库需要以下字段：
- Title      : title
- URL        : url
- Summary    : rich_text
- Source     : select
- Date       : date
- Status     : status
- InternalID : rich_text
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

import pytz
from notion_client import Client
from openai import OpenAI


# ============================================================
# 基础配置
# ============================================================

TIMEZONE = "Asia/Shanghai"

# 每天回看最近几天。依靠 DOI/URL/标题查重，重复抓取不会重复入库。
LOOKBACK_DAYS = 4

# Crossref 单个 ISSN 一次最多返回多少条。日期窗口较短，通常远低于该值。
CROSSREF_ROWS = 500

# Crossref 建议在 User-Agent 中提供联系方式。
# GitHub Actions 中可选设置 CROSSREF_MAILTO；不设置也能运行。
CROSSREF_MAILTO = os.environ.get("CROSSREF_MAILTO", "").strip()

# Crossref 没有摘要且标题不命中关键词时，尝试从文章页面的 meta 标签补摘要。
FETCH_MISSING_ABSTRACT_FROM_PAGE = True
MAX_PAGE_ABSTRACT_FETCHES_PER_JOURNAL = 12

# bioRxiv 最近几天全部扫描，但每天最多新增若干篇，避免预印本淹没正刊。
MAX_BIORXIV_PER_RUN = 5
MAX_BIORXIV_PAGES = 25  # 每页通常 100 条

# ChemRxiv 同样只保留关键词相关内容，并限制每天新增数量。
MAX_CHEMRXIV_PER_RUN = 5
MAX_CHEMRXIV_PAGES = 20  # 官方 API 每页最多 50 条

# 网络配置
HTTP_TIMEOUT = 35
REQUEST_SLEEP_SECONDS = 0.12

# 诊断模式：
# DIAGNOSE_ONLY=1 python daily_paper.py
DIAGNOSE_ONLY = os.environ.get("DIAGNOSE_ONLY", "0").lower() in {
    "1", "true", "yes", "y"
}

# 可选 Notion 字段；数据库中没有就保持 None。
NOTION_KEYWORDS_PROPERTY = None       # 例："Keywords"，multi_select
NOTION_ENTRY_TYPE_PROPERTY = None     # 例："Type"，select


# ============================================================
# 期刊白名单
# ============================================================

# 使用印刷版和电子版 ISSN 双重查询，再按 DOI 去重。
# Crossref 会覆盖 DOI 正式注册的 online-first / ASAP / early-view 文章。
JOURNALS: dict[str, tuple[str, ...]] = {
    # ACS
    "Chemical Reviews": ("0009-2665", "1520-6890"),
    "Journal of Medicinal Chemistry": ("0022-2623", "1520-4804"),
    "Journal of Chemical Information and Modeling": ("1549-9596", "1549-960X"),
    "Journal of the American Chemical Society": ("0002-7863", "1520-5126"),

    # Nature Portfolio
    "Nature": ("0028-0836", "1476-4687"),
    "Nature Reviews Drug Discovery": ("1474-1776", "1474-1784"),
    "Nature Reviews Chemistry": ("2397-3358",),
    "Nature Machine Intelligence": ("2522-5839",),
    "Nature Computational Science": ("2662-8457",),
    "Nature Communications": ("2041-1723",),
    "Nature Medicine": ("1078-8956", "1546-170X"),
    "Nature Biotechnology": ("1087-0156", "1546-1696"),
    "Nature Methods": ("1548-7091", "1548-7105"),

    # Science / PNAS / Wiley / RSC
    "Science": ("0036-8075", "1095-9203"),
    "Science Advances": ("2375-2548",),
    "Advanced Science": ("2198-3844",),
    "Proceedings of the National Academy of Sciences": ("0027-8424", "1091-6490"),
    #"Angewandte Chemie International Edition": ("1433-7851", "1521-3773"),
    "Chemical Science": ("2041-6520", "2041-6539"),
    "Chemical Society Reviews": ("0306-0012", "1460-4744"),

    # Cheminformatics / Bioinformatics
    "Journal of Cheminformatics": ("1758-2946",),
    "Bioinformatics": ("1367-4803", "1460-2059"),
}


# ============================================================
# 核心关键词
# ============================================================

# 候选召回词；最终入库由 match_core_keywords 的任务条件决定。
CORE_KEYWORDS = [
    # AIDD / 计算机辅助药物设计
    "drug discovery",
    "drug design",
    "ai drug discovery",
    "ai-driven drug discovery",
    "artificial intelligence for drug discovery",
    "machine learning for drug discovery",
    "deep learning for drug discovery",
    "AIDD",
    "computer-aided drug design",
    "computer aided drug design",
    "CADD",
    "structure-based drug design",
    "structure based drug design",
    "SBDD",
    "ligand-based drug design",
    "ligand based drug design",
    "in silico drug design",
    "molecular design",
    "molecule design",
    "small-molecule design",
    "small molecule design",
    "de novo drug design",
    "de novo molecular design",
    "lead optimization",
    "hit discovery",
    "medicinal chemistry",
    "cheminformatics",

    # 分子生成与优化
    "molecular generation",
    "molecule generation",
    "molecular generative",
    "generative molecular",
    "de novo molecule generation",
    "de novo molecular generation",
    "3d molecular generation",
    "3d molecule generation",
    "structure-based molecular generation",
    "structure based molecular generation",
    "pocket-conditioned",
    "pocket conditioned",
    "molecular optimization",
    "molecule optimization",
    "molecular foundation model",

    # 蛋白–配体、口袋与虚拟筛选
    "protein-ligand",
    "protein ligand",
    "protein–ligand",
    "ligand-protein",
    "ligand protein",
    "protein–small molecule",
    "protein-small molecule",
    "protein small molecule",
    "protein-ligand complex",
    "protein ligand complex",
    "binding pocket",
    "binding site",
    "binding affinity",
    "binding mode",
    "molecular docking",
    "docking",
    "virtual screening",
    "structure-based virtual screening",
    "structure based virtual screening",
    "scoring function",
    "interaction fingerprint",
    "pharmacophore",

    # 计算化学与性质预测
    "molecular dynamics",
    "binding free energy",
    "free energy perturbation",
    "alchemical free energy",
    "FEP",
    "ADMET",
    "QSAR",
    "molecular property prediction",
    "activity prediction",
    "force field",
    "conformation generation",
    "conformer generation",
    "molecular representation learning",

    # 三维与几何学习
    "3d molecule",
    "3d molecular",
    "geometric deep learning",
    "equivariant neural network",
    "equivariant graph",
    "SE(3)",
    "E(3)",
    "molecular diffusion model",
    "diffusion model for molecular generation",
    "flow matching for molecular",
    "molecular flow matching",
    "Bayesian flow network",
    "BFN",
    "molecular graph neural network",
    "molecular graph transformer",

    # 蛋白设计与结构生物学
    "protein design",
    "protein generation",
    "protein language model",
    "protein foundation model",
    "protein structure prediction",
    "protein folding",
    "inverse folding",
    "AlphaFold",
    "RFdiffusion",
    "RoseTTAFold",
    "ESM",
    "Boltz",
    "Chai",
    "cryo-EM",
    "electron density",
    "electron cloud",
    "density map",
    "X-ray crystallography",
    "X ray crystallography",
    "macromolecular crystallography",

    # AI 多肽设计：入库还要求标题任务或句内方法与设计对象关联。
    "AI peptide design",
]

# 复合词的候选匹配；最终入库仍须满足 match_core_keywords 的任务条件。
COMPOUND_KEYWORD_PATTERNS = {
    "ai peptide design": (
        r"\bpeptides?\b",
        r"\b(?:design(?:s|ed|ing)?|generat(?:e[sd]?|ing|ion|ive)|"
        r"optimi[sz](?:e[sd]?|ing|ation))\b",
        r"\b(?:ai|artificial intelligence|(?:machine|deep|reinforcement)[ -]learning|"
        r"generative|(?:large )?language models?|"
        r"diffusion(?: models?|[- ](?:based|guided|driven))|flow matching|"
        r"neural[- ]networks?|transformers?)\b",
    ),
}

STRICT_KEYWORDS = {
    "AIDD", "CADD", "SBDD", "FEP", "ADMET", "QSAR",
    "SE(3)", "E(3)", "BFN", "ESM",
}
STRICT_KEYWORDS_LOWER = {word.lower() for word in STRICT_KEYWORDS}

# 不入库的内容类型。
EXCLUDED_TITLE_PREFIXES = (
    "correction:",
    "correction to ",
    "correction ",
    "erratum ",
    "publisher correction:",
    "author correction:",
    "erratum:",
    "retraction:",
    "expression of concern:",
)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Article:
    title: str
    abstract: str
    url: str
    doi: str
    published_date: str
    source: str
    entry_type: str = "journal"
    matched_keywords: list[str] = field(default_factory=list)

    @property
    def internal_id(self) -> str:
        if self.doi:
            return f"doi:{normalize_doi(self.doi)}"
        if self.url:
            return f"url:{canonicalize_url(self.url)}"
        digest = hashlib.sha1(normalize_title(self.title).encode("utf-8")).hexdigest()[:20]
        return f"title:{digest}"


@dataclass
class SourceStats:
    fetched: int = 0
    keyword_matched: int = 0
    page_abstract_fetched: int = 0
    duplicate_in_run: int = 0
    already_in_notion: int = 0
    inserted: int = 0
    would_insert: int = 0
    errors: int = 0


# ============================================================
# 文本和日期工具
# ============================================================

def strip_html(text: Any) -> str:
    if not text:
        return ""
    value = html.unescape(str(text))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_search_text(text: str) -> str:
    value = html.unescape(text or "")
    value = value.replace("–", "-").replace("—", "-").replace("−", "-")
    value = re.sub(r"\s+", " ", value)
    return value.lower().strip()


def normalize_doi(doi: str) -> str:
    value = (doi or "").strip().lower()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value.rstrip(".,; ")


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return urlunparse(("https", netloc, path, "", "", ""))


def normalize_title(title: str) -> str:
    value = normalize_search_text(title)
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff ]", "", value)
    return re.sub(r"\s+", " ", value).strip()


# 候选词必须同时满足研究对象与计算任务条件。
def normalize_filter_text(text: str) -> str:
    value = normalize_search_text(text)
    value = value.replace("‐", "-").replace("‑", "-")
    return re.sub(r"\s+", " ", value)


def keyword_hit(text: str, keyword: str) -> bool:
    text, keyword = normalize_filter_text(text), normalize_filter_text(keyword)
    if keyword in COMPOUND_KEYWORD_PATTERNS:
        return all(re.search(p, text) for p in COMPOUND_KEYWORD_PATTERNS[keyword])
    # Model version suffixes are explicit; Chai must never match chain.
    model_patterns = {
        "alphafold": r"\balphafold(?:[ -]?\d+|[ -]?multimer)?\b",
        "boltz": r"\bboltz(?:[ -]?\d+)?\b",
        "chai": r"\bchai(?:[ -]?\d+)?\b",
        "esm": r"\besm(?:[ -]?\d+|fold)?\b",
        "rfdiffusion": r"\brfdiffusion(?:aa|[ -]?\d+)?\b",
    }
    if keyword in model_patterns:
        return re.search(model_patterns[keyword], text) is not None
    pattern = re.escape(keyword).replace(r"\ ", r"[ -]+")
    if keyword.endswith((" model", "network", "map", "pocket", "site")):
        pattern += "s?"
    return re.search(r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])", text) is not None


def match_core_keywords(title: str, abstract: str) -> list[str]:
    title_text = normalize_filter_text(title)
    text = normalize_filter_text(f"{title} {abstract}")
    matched = [k for k in CORE_KEYWORDS if k != "AI peptide design" and keyword_hit(text, k)]
    # Auxiliary evidence may rescue papers missed by the old recall vocabulary.
    bio = re.search(r"\b(?:proteins?|peptides?|ligands?|receptors?|enzymes?|"
                    r"drugs?|drug-like|therapeutic|bioactivity|admet|qsar|"
                    r"binding pockets?|binding sites?|inhibitors?|lytac)\b", text)
    ai = re.search(r"\b(?:ai|artificial intelligence|machine[ -]learning|"
                   r"deep[ -]learning|reinforcement[ -]learning|flow matching|neural[ -]networks?|language models?|"
                   r"generative|diffusion|transformer|proteinmpnn|rfdiffusion)\b", text)
    biological_design_title = re.search(
        r"\b(?:protein|peptide|drug)[ -](?:design|generation)\b|"
        r"\b(?:design|generat)\w*\b.{0,60}\b(?:proteins?|peptides?)\b", title_text)
    if not biological_design_title and re.search(r"\b(?:zeolite|electrolytes?|batter(?:y|ies)|photocurrent|"
                 r"carbon capture|singlet fission|taste|odor|flavor|"
                 r"nanopore translocation)\b", title_text):
        return []
    # Explicit generation/representation/prediction tasks; not generic drug discovery.
    strong = (
        "molecular generation", "molecule generation", "molecular generative",
        "generative molecular", "pocket-conditioned", "molecular optimization",
        "molecular representation learning", "molecular property prediction",
        "molecular foundation model", "protein language model",
        "protein foundation model", "inverse folding", "QSAR", "ADMET",
    )
    property_method = keyword_hit(title_text, "molecular property prediction") and ai
    if (bio or property_method) and any(keyword_hit(text, k) for k in strong):
        return matched or ["task: molecular/protein modeling"]
    # Design + AI must refer to a biological object, not AI materials chemistry.
    object_design = re.search(
        r"\b(?:protein|peptide|molecular|molecule|drug)[ -](?:design|generation|optimi[sz]ation)\b|"
        r"\b(?:design|generat|optimi[sz])\w*\b.{0,70}\b(?:proteins?|peptides?|drug-like molecules)\b|"
        r"\b(?:proteinmpnn|rfdiffusion(?:aa|[ -]?\d+)?)\b", text)
    units = [title_text] + re.split(r"[.!?;]\s+", normalize_filter_text(abstract))
    design_in_ai_unit = any(
        re.search(r"\b(?:ai|artificial intelligence|machine[ -]learning|"
                  r"deep[ -]learning|language models?|generative|diffusion|neural|proteinmpnn|rfdiffusion)\b", u)
        and re.search(r"\b(?:protein|peptide|molecular|molecule|drug)[ -]"
                      r"(?:design|generation|optimi[sz]ation)\b|"
                      r"\b(?:design|generat|optimi[sz])\w*\b.{0,70}"
                      r"\b(?:proteins?|peptides?|drug-like molecules|lytac)\b|"
                      r"\b(?:proteinmpnn|rfdiffusion(?:aa|[ -]?\d+)?)\b", u)
        for u in units)
    peptide_task_title = re.search(
        r"\bpeptide[ -](?:design|generation|optimi[sz]ation)\b|"
        r"\b(?:design|generat|optimi[sz])\w*\b.{0,60}\bpeptides?\b|"
        r"\bpeptides?\b.{0,20}\b(?:design|generat|optimi[sz])\w*\b", title_text)
    if bio and ai and peptide_task_title:
        return matched + ["AI peptide design"]
    if bio and ai and object_design and design_in_ai_unit:
        if re.search(r"\bpeptides?\b", text):
            return matched + ["AI peptide design"]
        return matched or ["task: AI biological design"]
    if bio and keyword_hit(text, "RFdiffusion") and re.search(
            r"\b(?:protein design|binder design|design of.*proteins?)\b", title_text):
        return matched or ["task: AI protein design"]
    if bio and re.search(r"\bai[ -]designed\b", title_text) and re.search(
            r"\b(?:proteins?|peptides?|lytac|binders?)\b", title_text):
        return matched or ["task: AI biological design (title)"]
    # Named co-folding models must be tied to the modeling task.
    models = any(keyword_hit(text, k) for k in ("Boltz", "Chai", "AlphaFold", "ESM"))
    model_task_title = re.search(
        r"\b(?:co[ -]?folding|fine[ -]?tun\w*|prediction|benchmark\w*|"
        r"structural errors|structural prioritization)\b", title_text)
    if bio and models and model_task_title and re.search(
            r"\b(?:co[ -]?folding|fine[ -]?tun\w*|structure prediction|"
            r"binding pose|affinity prediction|benchmark\w*|structural errors)\b", text):
        return matched or ["task: structure model"]
    # CADD: keep as adjacent coverage, not as evidence that the paper uses AI.
    if bio and any(keyword_hit(text, k) for k in (
            "computer-aided drug design", "CADD", "SBDD", "in silico drug design")):
        return matched or ["task: CADD"]
    if bio and re.search(
            r"\b(?:contrastive learning|multimodal ai|generative|"
            r"machine[ -]learning|deep[ -]learning)\b", title_text) and re.search(
            r"\b(?:drug design|drug discovery|molecular design)\b", title_text):
        return matched or ["task: AI drug design"]
    if bio and ai and re.search(r"\btoxicity\b", title_text):
        return matched or ["task: toxicity modeling"]
    if bio and ai and re.search(
            r"\b(?:artificial intelligence|learning|language models?)\b", title_text) and re.search(
            r"\b(?:antioxidant|thermostability|selectivity|activity|adme)\b", title_text):
        return matched or ["task: biomolecular property modeling"]
    # Method contribution in the title prevents an incidental docking mention
    # in a mechanism paper from becoming an admission criterion.
    method_title = re.search(
        r"\b(?:framework|platform|workflow|pipeline|benchmark\w*|database|"
        r"prediction|modeling|modelling|mapping|discovery|refinement|"
        r"generation|sampling|training|evaluation|generalizability|design|analysis|tool|paths|elaboration)\b", title_text)
    experiment_title = re.search(
        r"\b(?:alleviates?|attenuates?|suppresses?|protects?|"
        r"mechanisms?|specimen preparation|ice thickness|"
        r"structures? of|reveals?|responses? to|biological evaluation)\b", title_text)
    if not bio or not method_title or experiment_title:
        return []
    # Pocket/ligand methods, affinity data, and synthesis-aware elaboration.
    ligand_method = any(keyword_hit(text, k) for k in (
        "binding pocket", "binding site", "protein-ligand", "binding affinity",
        "molecular docking", "docking", "virtual screening"))
    computational = re.search(
        r"\b(?:computational|algorithm\w*|automated|open-source|software|"
        r"markov state|conformational ensemble|fragment elaboration|"
        r"databases?|neural\w*|machine[ -]learning|benchmark\w*|ai system)\b", text)
    if re.search(r"\bfragment elaboration\b", title_text) and ligand_method:
        return matched or ["task: synthesis-aware ligand design"]
    if re.search(r"\bmatched (?:molecule|molecular) pair\b", title_text) and bio:
        return matched or ["task: cheminformatics"]
    if ligand_method and computational:
        return matched or ["task: ligand/pocket method"]
    # Computational reconstruction/refinement is allowed even without AI.
    structural = any(keyword_hit(text, k) for k in (
        "cryo-EM", "electron density", "density map", "X-ray crystallography"))
    if structural and re.search(
            r"\b(?:reconstruction|refinement|modeling|modelling)\b", title_text):
        return matched or ["task: structural modeling"]
    # Biomolecular force-field/sampling methods, not all MD applications.
    if any(keyword_hit(text, k) for k in ("force field", "molecular dynamics")) and re.search(
            r"\b(?:force[ -]field|sampling|water model)\b", title_text):
        return matched or ["task: biomolecular simulation method"]
    return []

def should_skip_title(title: str) -> bool:
    normalized = normalize_search_text(title)
    return any(normalized.startswith(prefix) for prefix in EXCLUDED_TITLE_PREFIXES)


def crossref_date_to_iso(item: dict[str, Any]) -> str:
    for field_name in (
        "published-online",
        "published",
        "published-print",
        "issued",
        "created",
    ):
        value = item.get(field_name)
        if not isinstance(value, dict):
            continue

        date_parts = value.get("date-parts")
        if date_parts and isinstance(date_parts, list) and date_parts[0]:
            parts = date_parts[0]
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            day = int(parts[2]) if len(parts) > 2 else 1
            try:
                return dt.date(year, month, day).isoformat()
            except ValueError:
                continue

        date_time = value.get("date-time")
        if date_time:
            try:
                return dt.datetime.fromisoformat(
                    str(date_time).replace("Z", "+00:00")
                ).date().isoformat()
            except ValueError:
                continue

    return dt.date.today().isoformat()


# ============================================================
# HTTP 工具
# ============================================================

def user_agent() -> str:
    base = "AIDD-Daily-Paper-Bot/2.0"
    if CROSSREF_MAILTO:
        return f"{base} (mailto:{CROSSREF_MAILTO})"
    return base


def fetch_json(url: str, *, retries: int = 3) -> dict[str, Any]:
    headers = {
        "User-Agent": user_agent(),
        "Accept": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return json.loads(response.read().decode(charset))
        except HTTPError as exc:
            last_error = exc
            # 429 / 5xx 可重试；其他错误直接抛出。
            if exc.code != 429 and exc.code < 500:
                raise
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc

        time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"请求失败: {url}; last_error={last_error}")


class MetaDescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return

        attr_map = {
            (key or "").lower(): (value or "")
            for key, value in attrs
        }
        key = (
            attr_map.get("name")
            or attr_map.get("property")
            or attr_map.get("itemprop")
        ).lower()
        content = attr_map.get("content", "").strip()
        if key and content and key not in self.values:
            self.values[key] = content


def fetch_page_abstract(url: str) -> str:
    if not url:
        return ""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=HTTP_TIMEOUT) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(2_500_000).decode(charset, errors="replace")
    except Exception:
        return ""

    parser = MetaDescriptionParser()
    try:
        parser.feed(body)
    except Exception:
        return ""

    keys = (
        "citation_abstract",
        "dc.description",
        "dcterms.description",
        "description",
        "og:description",
        "twitter:description",
    )
    for key in keys:
        value = strip_html(parser.values.get(key, ""))
        if len(value) >= 40:
            return value

    return ""


# ============================================================
# Crossref：正式期刊抓取
# ============================================================

def build_crossref_url(issn: str, start_date: str, end_date: str) -> str:
    filters = ",".join(
        [
            f"from-created-date:{start_date}",
            f"until-created-date:{end_date}",
            "type:journal-article",
        ]
    )
    params = {
        "filter": filters,
        "rows": str(CROSSREF_ROWS),
        "sort": "created",
        "order": "desc",
    }
    if CROSSREF_MAILTO:
        params["mailto"] = CROSSREF_MAILTO

    return f"https://api.crossref.org/journals/{issn}/works?{urlencode(params)}"


def crossref_item_to_article(item: dict[str, Any], source: str) -> Article | None:
    title_values = item.get("title") or []
    title = strip_html(title_values[0] if title_values else "")
    if not title or should_skip_title(title):
        return None

    doi = normalize_doi(str(item.get("DOI", "")))
    url = str(item.get("URL", "") or "").strip()
    if not url and doi:
        url = f"https://doi.org/{doi}"

    if not url:
        return None

    abstract = strip_html(item.get("abstract", ""))
    published_date = crossref_date_to_iso(item)

    return Article(
        title=title,
        abstract=abstract,
        url=url,
        doi=doi,
        published_date=published_date,
        source=source,
        entry_type="journal",
    )


def fetch_journal_articles(
    source: str,
    issns: tuple[str, ...],
    start_date: str,
    end_date: str,
) -> tuple[list[Article], int]:
    by_id: dict[str, Article] = {}
    errors = 0

    for issn in issns:
        url = build_crossref_url(issn, start_date, end_date)
        try:
            payload = fetch_json(url)
            items = payload.get("message", {}).get("items", [])
        except Exception as exc:
            errors += 1
            print(f"   ⚠️ Crossref 请求失败: {source} / ISSN {issn}: {exc}")
            continue

        for item in items:
            article = crossref_item_to_article(item, source)
            if article is None:
                continue
            by_id[article.internal_id] = article

        time.sleep(REQUEST_SLEEP_SECONDS)

    articles = sorted(
        by_id.values(),
        key=lambda article: (article.published_date, article.title),
        reverse=True,
    )
    return articles, errors


# ============================================================
# bioRxiv 抓取
# ============================================================

def fetch_biorxiv_articles(start_date: str, end_date: str) -> tuple[list[Article], int]:
    by_id: dict[str, Article] = {}
    errors = 0

    for page_index in range(MAX_BIORXIV_PAGES):
        cursor = page_index * 100
        url = (
            "https://api.biorxiv.org/details/"
            f"biorxiv/{start_date}/{end_date}/{cursor}"
        )

        try:
            payload = fetch_json(url)
        except Exception as exc:
            errors += 1
            print(f"   ⚠️ bioRxiv API 请求失败 cursor={cursor}: {exc}")
            break

        collection = payload.get("collection", [])
        if not collection:
            break

        for item in collection:
            title = strip_html(item.get("title", ""))
            doi = normalize_doi(str(item.get("doi", "")))
            if not title or not doi or should_skip_title(title):
                continue

            abstract = strip_html(item.get("abstract", ""))
            date_text = str(item.get("date", "") or end_date)[:10]
            article = Article(
                title=title,
                abstract=abstract,
                url=f"https://www.biorxiv.org/content/{doi}",
                doi=doi,
                published_date=date_text,
                source="bioRxiv",
                entry_type="preprint",
            )

            # 同一 DOI 多个版本只保留 API 后返回/日期更新的一条。
            by_id[article.internal_id] = article

        if len(collection) < 100:
            break

        time.sleep(REQUEST_SLEEP_SECONDS)

    articles = sorted(
        by_id.values(),
        key=lambda article: (article.published_date, article.title),
        reverse=True,
    )
    return articles, errors



# ============================================================
# ChemRxiv 抓取
# ============================================================

CHEMRXIV_API_URL = "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items"


def chemrxiv_date_to_iso(item: dict[str, Any], fallback: str) -> str:
    """
    ChemRxiv 元数据中的日期字段在不同版本中可能略有差异。
    优先使用 publishedDate，其次 approvedDate / submittedDate。
    """
    for field_name in ("publishedDate", "approvedDate", "submittedDate", "createdDate"):
        value = item.get(field_name)
        if not value:
            continue

        text = str(value).strip()
        if len(text) >= 10:
            candidate = text[:10]
            try:
                dt.date.fromisoformat(candidate)
                return candidate
            except ValueError:
                pass

    return fallback


def fetch_chemrxiv_articles(start_date: str, end_date: str) -> tuple[list[Article], int]:
    """
    使用 ChemRxiv 官方 Open Engage Public API 抓取最近日期窗口内的预印本。

    API:
      /public-api/v1/items
    主要参数:
      searchDateFrom / searchDateTo / skip / limit / sort

    返回结果在不同 API 版本中可能使用 itemHits / items / results，
    因此这里做兼容解析。
    """
    by_id: dict[str, Article] = {}
    errors = 0
    page_size = 50

    for page_index in range(MAX_CHEMRXIV_PAGES):
        skip = page_index * page_size
        params = {
            "searchDateFrom": start_date,
            "searchDateTo": end_date,
            "sort": "PUBLISHED_DATE_DESC",
            "skip": str(skip),
            "limit": str(page_size),
        }
        url = f"{CHEMRXIV_API_URL}?{urlencode(params)}"

        try:
            payload = fetch_json(url)
        except Exception as exc:
            errors += 1
            print(f"   ⚠️ ChemRxiv API 请求失败 skip={skip}: {exc}")
            break

        hits = (
            payload.get("itemHits")
            or payload.get("items")
            or payload.get("results")
            or []
        )

        if not isinstance(hits, list) or not hits:
            break

        parsed_count = 0

        for hit in hits:
            if not isinstance(hit, dict):
                continue

            item = hit.get("item", hit)
            if not isinstance(item, dict):
                continue

            title = strip_html(item.get("title", ""))
            if not title or should_skip_title(title):
                continue

            abstract = strip_html(item.get("abstract", ""))
            doi = normalize_doi(str(item.get("doi", "") or ""))
            item_id = str(item.get("id", "") or item.get("_id", "") or "").strip()

            url_value = ""
            for key in ("url", "itemUrl", "landingPageUrl"):
                value = str(item.get(key, "") or "").strip()
                if value:
                    url_value = value
                    break

            if not url_value and item_id:
                url_value = (
                    "https://chemrxiv.org/engage/chemrxiv/"
                    f"article-details/{item_id}"
                )

            if not url_value and doi:
                url_value = f"https://doi.org/{doi}"

            if not url_value:
                continue

            article = Article(
                title=title,
                abstract=abstract,
                url=url_value,
                doi=doi,
                published_date=chemrxiv_date_to_iso(item, end_date),
                source="ChemRxiv",
                entry_type="preprint",
            )

            by_id[article.internal_id] = article
            parsed_count += 1

        # 如果 API 本页不足 page_size，说明已经到最后一页。
        if len(hits) < page_size:
            break

        # 即使返回 50 条但一条都无法解析，也不继续死循环。
        if parsed_count == 0:
            break

        time.sleep(REQUEST_SLEEP_SECONDS)

    articles = sorted(
        by_id.values(),
        key=lambda article: (article.published_date, article.title),
        reverse=True,
    )
    return articles, errors


# ============================================================
# Notion 与 DeepSeek
# ============================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
DATABASE_ID = os.environ.get("DATABASE_ID", "")

if DIAGNOSE_ONLY:
    deepseek_client: OpenAI | None = None
    notion: Client | None = None
else:
    missing = [
        name
        for name, value in {
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
            "NOTION_TOKEN": NOTION_TOKEN,
            "DATABASE_ID": DATABASE_ID,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"❌ 缺少环境变量: {', '.join(missing)}")

    deepseek_client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    notion = Client(auth=NOTION_TOKEN)


def check_if_exists(article: Article) -> bool:
    if notion is None:
        return False

    filters: list[dict[str, Any]] = [
        {
            "property": "InternalID",
            "rich_text": {"equals": article.internal_id},
        },
        {
            "property": "URL",
            "url": {"equals": canonicalize_url(article.url)},
        },
        {
            "property": "Title",
            "title": {"equals": article.title},
        },
    ]

    if article.url != canonicalize_url(article.url):
        filters.append(
            {
                "property": "URL",
                "url": {"equals": article.url},
            }
        )

    response = notion.databases.query(
        database_id=DATABASE_ID,
        filter={"or": filters},
        page_size=1,
    )
    return bool(response.get("results"))


def call_deepseek(article: Article) -> str:
    if deepseek_client is None:
        raise RuntimeError("DeepSeek 客户端未初始化")

    abstract = article.abstract or "摘要未提供。"
    keywords = ", ".join(article.matched_keywords)

    prompt = f"""
你是 AI 药物发现、计算化学和结构生物学方向的博士生。请仅根据论文标题和摘要写一段中文科研笔记摘要。

要求：
1. 只基于提供的标题和摘要，不补充未出现的信息。
2. 依次说明研究问题、方法思路、主要结果或潜在用途。
3. 如果没有摘要，明确写“当前元数据未提供摘要，具体方法和结果需查看原文”。
4. 不使用“重磅、颠覆、突破性、值得一看”等营销化措辞。
5. 语言客观、克制、清楚，控制在 90–140 字。
6. 直接输出摘要正文，不要加标题或分点。

期刊/来源：{article.source}
发表日期：{article.published_date}
命中关键词：{keywords}

标题：
{article.title}

摘要：
{abstract}
""".strip()

    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": "你是严谨的 AIDD 科研文献摘要助手。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=320,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        print(f"   ⚠️ DeepSeek 总结失败: {exc}")
        return "AI 总结失败，请查看原文。"


def push_to_notion(article: Article, summary: str) -> None:
    if notion is None:
        raise RuntimeError("Notion 客户端未初始化")

    properties: dict[str, Any] = {
        "Title": {
            "title": [{"text": {"content": article.title[:2000]}}],
        },
        "URL": {
            "url": canonicalize_url(article.url),
        },
        "Summary": {
            "rich_text": [{"text": {"content": summary[:2000]}}],
        },
        "Source": {
            "select": {"name": article.source[:100]},
        },
        "Date": {
            "date": {"start": article.published_date},
        },
        "Status": {
            "status": {"name": "Inbox"},
        },
        "InternalID": {
            "rich_text": [{"text": {"content": article.internal_id[:2000]}}],
        },
    }

    if NOTION_KEYWORDS_PROPERTY and article.matched_keywords:
        properties[NOTION_KEYWORDS_PROPERTY] = {
            "multi_select": [
                {"name": keyword[:100]}
                for keyword in article.matched_keywords[:20]
            ]
        }

    if NOTION_ENTRY_TYPE_PROPERTY:
        properties[NOTION_ENTRY_TYPE_PROPERTY] = {
            "select": {"name": article.entry_type}
        }

    notion.pages.create(
        parent={"database_id": DATABASE_ID},
        properties=properties,
    )


# ============================================================
# 统一处理逻辑
# ============================================================

def process_source_articles(
    source: str,
    articles: list[Article],
    stats: SourceStats,
    seen_ids: set[str],
    *,
    max_insertions: int | None = None,
) -> None:
    page_fallback_count = 0

    for article in articles:
        stats.fetched += 1

        matched = match_core_keywords(article.title, article.abstract)

        # Crossref 没有摘要、标题也没命中时，从文章页面 meta 信息补一次摘要。
        if (
            not matched
            and not article.abstract
            and FETCH_MISSING_ABSTRACT_FROM_PAGE
            and page_fallback_count < MAX_PAGE_ABSTRACT_FETCHES_PER_JOURNAL
        ):
            page_fallback_count += 1
            page_abstract = fetch_page_abstract(article.url)
            if page_abstract:
                article.abstract = page_abstract
                stats.page_abstract_fetched += 1
                matched = match_core_keywords(article.title, article.abstract)

        if not matched:
            continue

        article.matched_keywords = matched
        stats.keyword_matched += 1

        if article.internal_id in seen_ids:
            stats.duplicate_in_run += 1
            continue
        seen_ids.add(article.internal_id)

        if DIAGNOSE_ONLY:
            stats.would_insert += 1
            print(
                f"   🟢 WOULD_INSERT | {article.published_date} | "
                f"{article.title[:110]} | keywords={matched[:8]}"
            )
            if max_insertions is not None and stats.would_insert >= max_insertions:
                break
            continue

        try:
            if check_if_exists(article):
                stats.already_in_notion += 1
                continue

            summary = call_deepseek(article)
            push_to_notion(article, summary)
            stats.inserted += 1
            print(
                f"   ✅ 已入库 | {article.published_date} | "
                f"{article.title[:100]} | keywords={matched[:8]}"
            )

            if max_insertions is not None and stats.inserted >= max_insertions:
                break

        except Exception as exc:
            stats.errors += 1
            print(f"   ❌ 处理失败: {article.title[:90]} | {exc}")


def print_source_stats(source: str, stats: SourceStats) -> None:
    print(
        f"📊 {source}: "
        f"抓取={stats.fetched}, "
        f"关键词命中={stats.keyword_matched}, "
        f"页面补摘要={stats.page_abstract_fetched}, "
        f"本轮重复={stats.duplicate_in_run}, "
        f"Notion已存在={stats.already_in_notion}, "
        f"新增={stats.inserted}, "
        f"诊断应入库={stats.would_insert}, "
        f"错误={stats.errors}"
    )


# ============================================================
# 主程序
# ============================================================

def run() -> None:
    tz = pytz.timezone(TIMEZONE)
    now = dt.datetime.now(tz)
    end_date = now.date()
    start_date = end_date - dt.timedelta(days=LOOKBACK_DAYS)

    start_text = start_date.isoformat()
    end_text = end_date.isoformat()

    print("=" * 76)
    print("🚀 AIDD Daily Paper Bot")
    print(f"日期窗口: {start_text} 至 {end_text}")
    print("筛选规则: 明确任务或候选词 + 生物分子计算上下文")
    print(f"诊断模式: {DIAGNOSE_ONLY}")
    print("=" * 76)

    seen_ids: set[str] = set()
    all_stats: dict[str, SourceStats] = {}

    # 1. 正式期刊
    for source, issns in JOURNALS.items():
        print(f"\n📚 正在抓取: {source}")
        stats = SourceStats()
        all_stats[source] = stats

        articles, fetch_errors = fetch_journal_articles(
            source=source,
            issns=issns,
            start_date=start_text,
            end_date=end_text,
        )
        stats.errors += fetch_errors

        process_source_articles(
            source=source,
            articles=articles,
            stats=stats,
            seen_ids=seen_ids,
        )
        print_source_stats(source, stats)

    # 2. bioRxiv
    source = "bioRxiv"
    print(f"\n🧪 正在抓取: {source}")
    stats = SourceStats()
    all_stats[source] = stats

    articles, fetch_errors = fetch_biorxiv_articles(start_text, end_text)
    stats.errors += fetch_errors

    process_source_articles(
        source=source,
        articles=articles,
        stats=stats,
        seen_ids=seen_ids,
        max_insertions=MAX_BIORXIV_PER_RUN,
    )
    print_source_stats(source, stats)

    # 3. ChemRxiv
    source = "ChemRxiv"
    print(f"\n🧪 正在抓取: {source}")
    stats = SourceStats()
    all_stats[source] = stats

    articles, fetch_errors = fetch_chemrxiv_articles(start_text, end_text)
    stats.errors += fetch_errors

    process_source_articles(
        source=source,
        articles=articles,
        stats=stats,
        seen_ids=seen_ids,
        max_insertions=MAX_CHEMRXIV_PER_RUN,
    )
    print_source_stats(source, stats)

    # 4. 总结
    totals = SourceStats()
    for stats in all_stats.values():
        totals.fetched += stats.fetched
        totals.keyword_matched += stats.keyword_matched
        totals.page_abstract_fetched += stats.page_abstract_fetched
        totals.duplicate_in_run += stats.duplicate_in_run
        totals.already_in_notion += stats.already_in_notion
        totals.inserted += stats.inserted
        totals.would_insert += stats.would_insert
        totals.errors += stats.errors

    print("\n" + "=" * 76)
    print("今日抓取完成")
    print_source_stats("TOTAL", totals)
    print("=" * 76)


if __name__ == "__main__":
    run()

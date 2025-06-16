
import arxiv

def fetch_arxiv():
    search_keywords = [
        "structure-based molecular generation",
        "structure-guided molecule generation",
        "pocket-based drug design",
        "AI-based molecule generation",
        "protein-ligand binding generation",
        "target-specific molecular design",
        "3D molecule generation AND drug discovery",
        "binding site conditioned generation",
        "deep generative models for drug design",
        "structure-function driven drug discovery",
        "fragment-based drug design with AI",
        "protein-ligand interaction prediction AND generation",
        "molecular generation for PARP1 inhibitor"
    ]

    papers_per_keyword = 2
    seen_titles = set()
    results = []

    for keyword in search_keywords:
        search = arxiv.Search(
            query=keyword,
            max_results=papers_per_keyword,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        for result in search.results():
            title = result.title.strip()
            summary = result.summary.strip()
            lower_title = title.lower()
            lower_summary = summary.lower()

            relevance_keywords = ["generation", "pocket", "binding", "ligand", "protein", "drug"]
            match_title = any(kw in lower_title for kw in relevance_keywords)
            match_summary = any(kw in lower_summary for kw in relevance_keywords)

            if title not in seen_titles and (match_title or match_summary):
                seen_titles.add(title)
                results.append({
                    "title": title,
                    "summary": summary,
                    "url": result.entry_id,
                    "source": "arXiv"
                })
    return results

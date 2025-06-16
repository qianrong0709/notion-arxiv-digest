
from fetch_arxiv import fetch_arxiv
from fetch_biorxiv import fetch_biorxiv
from fetch_medrxiv import fetch_medrxiv
from fetch_pubmed import fetch_pubmed
from push_to_notion import push_to_notion

def summarize(text):
    return text if len(text) < 500 else text[:500] + "..."

def fetch_and_merge_all():
    seen = set()
    all_papers = []

    for fetcher in [
        fetch_arxiv,
        fetch_biorxiv,
        fetch_medrxiv,
        lambda: fetch_pubmed("AI-based molecular generation", 10)
    ]:
        for paper in fetcher():
            if paper["title"] not in seen:
                seen.add(paper["title"])
                paper["summary"] = summarize(paper["summary"])
                all_papers.append(paper)

    return all_papers

if __name__ == "__main__":
    papers = fetch_and_merge_all()
    push_to_notion(papers)

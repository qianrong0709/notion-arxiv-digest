
from Bio import Entrez

Entrez.email = "your_email@example.com"

def fetch_pubmed(keyword="AI drug discovery", max_results=10):
    handle = Entrez.esearch(db="pubmed", term=keyword, retmax=max_results, sort="pub+date")
    record = Entrez.read(handle)
    handle.close()

    ids = record["IdList"]
    if not ids:
        return []

    handle = Entrez.efetch(db="pubmed", id=",".join(ids), rettype="medline", retmode="xml")
    papers = Entrez.read(handle)["PubmedArticle"]
    handle.close()

    results = []
    for paper in papers:
        try:
            title = paper["MedlineCitation"]["Article"]["ArticleTitle"]
            abstract = paper["MedlineCitation"]["Article"]["Abstract"]["AbstractText"][0]
            pmid = paper["MedlineCitation"]["PMID"]
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            if any(kw in title.lower() for kw in ["drug", "target", "binding", "ligand", "protein"]):
                results.append({
                    "title": title,
                    "summary": abstract,
                    "url": url,
                    "source": "PubMed"
                })
        except Exception:
            continue
    return results

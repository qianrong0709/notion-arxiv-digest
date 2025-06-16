
import feedparser

def fetch_medrxiv():
    url = "https://www.medrxiv.org/rss/subject/pharmacology-toxicology"
    feed = feedparser.parse(url)
    entries = []
    for entry in feed.entries[:10]:
        if any(kw in entry.title.lower() for kw in ["drug", "target", "generation", "binding", "ai"]):
            entries.append({
                "title": entry.title,
                "summary": entry.summary,
                "url": entry.link,
                "source": "medRxiv"
            })
    return entries

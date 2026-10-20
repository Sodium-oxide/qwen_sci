"""Resolve scholarly identifiers and read identity-checked repository XML."""
from __future__ import annotations

from collections.abc import Mapping
import re
from urllib.parse import urlencode
from xml.etree import ElementTree

from .anysearch import normalize_doi, source_identifiers, text


EUROPE_PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def biomedical_identity(paper):
    ids = source_identifiers(paper)
    return {"pmid": ids["pmid"], "pmcid": ids["pmcid"],
            "doi": normalize_doi(paper.get("doi") or (paper.get("externalIds") or {}).get("DOI"))}


def matching_biomedical_identity(expected, actual):
    shared = [key for key in expected if expected.get(key) and actual.get(key)]
    return bool(shared) and all(expected[key] == actual[key] for key in shared)


def resolve_biomedical_metadata(paper, fetch_json):
    expected = biomedical_identity(paper)
    if expected["pmid"]:
        query = f'EXT_ID:{expected["pmid"]} AND SRC:MED'
    elif expected["pmcid"]:
        query = expected["pmcid"]
    elif expected["doi"]:
        query = f'DOI:"{expected["doi"]}"'
    else:
        return {}
    url = EUROPE_PMC_API + "/search?" + urlencode({"query": query, "format": "json", "resultType": "core", "pageSize": 10})
    payload = fetch_json(url)
    rows = payload.get("resultList", {}).get("result", [])
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        pmid = str(row.get("pmid") or (row.get("id") if row.get("source") == "MED" else "") or "")
        pmcid = str(row.get("pmcid") or (row.get("id") if row.get("source") == "PMC" else "") or "")
        external = {key: value for key, value in {"PubMed": pmid, "PMCID": pmcid, "DOI": row.get("doi")}.items() if value}
        actual = biomedical_identity({"externalIds": external})
        if not matching_biomedical_identity(expected, actual):
            continue
        from bs4 import BeautifulSoup
        locations = []
        for location in (row.get("fullTextUrlList") or {}).get("fullTextUrl", []):
            if not isinstance(location, Mapping) or location.get("availabilityCode") not in {"OA", "F"}:
                continue
            location_url = text(location.get("url"))
            if location_url:
                locations.append({"source": "europepmc.fulltext", "oa_evidence": "europepmc." + location["availabilityCode"],
                                  "pdf_url": location_url if str(location.get("documentStyle", "")).lower() == "pdf" else "",
                                  "landing_page_url": location_url})
        authors = [{"name": author["fullName"]} for author in (row.get("authorList") or {}).get("author", [])
                   if isinstance(author, Mapping) and author.get("fullName")]
        result = {"title": text(row.get("title")), "doi": actual["doi"], "pmid": actual["pmid"], "pmcid": actual["pmcid"],
                  "externalIds": external, "authors": authors, "year": row.get("pubYear"),
                  "venue": (row.get("journalInfo") or {}).get("journal", {}).get("title", ""),
                  "abstract": BeautifulSoup(text(row.get("abstractText")), "html.parser").get_text(" ", strip=True),
                  "openalex_oa_locations": locations, "metadata_identity_status": "identifier_exact_match",
                  "identity_provenance": [{"provider": "europe_pmc", "url": url, "identifiers": actual}]}
        return result
    raise ValueError("No metadata record matches the supplied scholarly identifiers")


def parse_repository_jats(body, paper):
    if re.search(r"<!\s*ENTITY\b", body, re.I):
        raise ValueError("Repository XML contains unsupported declarations")
    root = ElementTree.fromstring(body)
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    if root.tag != "article":
        raise ValueError("Repository response is not a JATS article")
    ids = {}
    for node in root.findall(".//article-meta/article-id"):
        kind = node.get("pub-id-type", "").lower()
        value = "".join(node.itertext()).strip()
        if kind == "doi":
            ids["DOI"] = value
        elif kind in {"pmc", "pmcid"}:
            ids["PMCID"] = value
        elif kind == "pmid":
            ids["PubMed"] = value
    actual = biomedical_identity({"externalIds": ids})
    if not matching_biomedical_identity(biomedical_identity(paper), actual):
        raise ValueError("Repository XML identifiers do not match the requested paper")
    article_body = root.find("body")
    if article_body is None or not "".join(article_body.itertext()).strip():
        raise ValueError("Repository XML has no article body")
    parts = [root.find(".//article-meta/title-group"), root.find(".//article-meta/abstract"), article_body]
    content = "\n\n".join(" ".join(part.itertext()).strip() for part in parts if part is not None)
    return {"content": content, "identity": actual, "article_type": root.get("article-type", "")}

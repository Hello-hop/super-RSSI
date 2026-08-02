#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collecteur d'offres — tourne dans GitHub Actions, sans dépendance externe.

Il interroge les sources, note chaque offre selon les mots-clés du profil,
dédoublonne sur l'URL et écrit docs/data/offres.json que lit l'application.

Tout ce qui se règle est dans le bloc CONFIGURATION ci-dessous.
Test en local :  python3 scripts/veille.py
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html import unescape
from xml.etree import ElementTree

# ─────────────────────────── CONFIGURATION ───────────────────────────

# type : "freework" (page de résultats Free-Work) ou "rss" (n'importe quel flux,
# y compris une Google Alert livrée en RSS — c'est la façon d'ajouter un site
# qui ne publie pas de flux.)
SOURCES = [
    {"nom": "FW ISO 27001",       "type": "freework",
     "url": "https://www.free-work.com/fr/tech-it/jobs/iso-27001"},
    {"nom": "FW Cyber Toulouse",  "type": "freework",
     "url": "https://www.free-work.com/fr/tech-it/jobs/cybersecurite/toulouse"},
    {"nom": "FW Sécu Toulouse",   "type": "freework",
     "url": "https://www.free-work.com/fr/tech-it/jobs/securite-informatique/toulouse"},
    {"nom": "FW Consultant cyber", "type": "freework",
     "url": "https://www.free-work.com/fr/tech-it/jobs/consultant-cyber-securite/toulouse"},
]

# Mots-clés pondérés : l'ADN de la recherche. Ajuste les points sur du réel.
MOTS_CLES = [
    (r"iso ?2700[15]|27005|ebios|smsi", 3),
    (r"grc|gouvernance|conformit[ée]", 2),
    (r"rssi|ciso", 2),
    (r"analyse de risque|pssi|audit", 2),
    (r"nis ?2|dora|rgpd|hds", 1),
    (r"toulouse|occitanie", 2),
    (r"t[ée]l[ée]travail|remote", 1),
    (r"sant[ée]|h[ôo]pital|chu|laboratoire|collectivit[ée]|territorial", 2),
    (r"senior|lead|expert", 1),
]

EXCLUSIONS = [
    "alternance", "stage", "stagiaire", "apprenti", "pentest", "soc analyst",
    "développeur", "developpeur", "commercial", "business developer", "recruteur",
]

# Détection du lieu, appliquée au texte complet de l'annonce (pas seulement au titre).
RE_TOULOUSE = re.compile(r"toulouse|haute[- ]garonne|\b31\d{3}\b", re.I)

SORTIE = os.path.join("docs", "data", "offres.json")
MAX_OFFRES = 600          # on garde un historique glissant
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

# ──────────────────────────── COLLECTE ────────────────────────────


def telecharger(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "fr-FR,fr;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def nettoyer(s: str) -> str:
    s = re.sub(r"<!--.*?-->", "", s or "", flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    return unescape(re.sub(r"\s+", " ", s)).strip()


RE_FREEWORK = re.compile(
    r'href="(/fr/tech-it/job-mission/[^"]+)"[^>]*>\s*<span[^>]*>(.*?)</span>', re.S)


def lire_freework(url: str):
    """Renvoie titre, lien, extrait et contexte (tags + description) de chaque carte.

    Le contexte sert au scoring : le titre seul ne dit ni le lieu, ni le
    référentiel, ni le secteur — la carte, si.
    """
    html_src = telecharger(url)
    vus, out = set(), []
    for m in RE_FREEWORK.finditer(html_src):
        lien = "https://www.free-work.com" + m.group(1)
        titre = nettoyer(m.group(2))
        if not titre or lien in vus:
            continue
        vus.add(lien)

        bloc = html_src[m.end():m.end() + 9000]
        coupe = bloc.find("/fr/tech-it/job-mission/")   # ne pas déborder sur la carte suivante
        if coupe > 0:
            bloc = bloc[:coupe]
        contexte = nettoyer(bloc)
        # la description utile commence après la date de publication de l'annonce
        date_pub = re.search(r"\d{2}/\d{2}/\d{4}", contexte)
        extrait = contexte[date_pub.end():].strip()[:200] if date_pub else contexte[:200]

        out.append({"titre": titre, "lien": lien, "extrait": extrait,
                    "contexte": (titre + " " + contexte)[:4000]})
    return out


def lire_rss(url: str):
    racine = ElementTree.fromstring(telecharger(url))
    out = []
    canal = racine.find("channel")
    if canal is not None:                                   # RSS 2.0
        for item in canal.findall("item"):
            out.append({"titre": nettoyer(item.findtext("title", "")),
                        "lien": (item.findtext("link") or "").strip(),
                        "extrait": nettoyer(item.findtext("description", ""))[:200],
                        "contexte": nettoyer(item.findtext("title", "") + " " + (item.findtext("description") or ""))[:4000]})
        return out
    ns = {"a": "http://www.w3.org/2005/Atom"}               # Atom / Google Alerts
    for e in racine.findall("a:entry", ns):
        lien = e.find("a:link", ns)
        resume = nettoyer(e.findtext("a:content", "", ns) or e.findtext("a:summary", "", ns))
        titre = nettoyer(e.findtext("a:title", "", ns))
        out.append({"titre": titre,
                    "lien": lien.get("href") if lien is not None else "",
                    "extrait": resume[:200],
                    "contexte": (titre + " " + resume)[:4000]})
    return out


# ──────────────────────────── NOTATION ────────────────────────────


def scorer(texte: str) -> int:
    """Note /5. Le titre pèse via le contexte complet de l'annonce."""
    t = (texte or "").lower()
    pts = sum(p for motif, p in MOTS_CLES if re.search(motif, t))
    return min(5, round(pts / 3))


def exclu(titre: str) -> bool:
    t = (titre or "").lower()
    return any(x in t for x in EXCLUSIONS)


# ────────────────────────────── MAIN ──────────────────────────────


def main() -> int:
    os.makedirs(os.path.dirname(SORTIE), exist_ok=True)
    try:
        with open(SORTIE, encoding="utf-8") as f:
            connues = json.load(f).get("offres", [])
    except (FileNotFoundError, json.JSONDecodeError):
        connues = []

    index = {o["lien"] for o in connues}
    aujourdhui = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    nouvelles, incidents = [], []

    for src in SOURCES:
        try:
            brutes = lire_rss(src["url"]) if src["type"] == "rss" else lire_freework(src["url"])
        except (urllib.error.URLError, urllib.error.HTTPError, ElementTree.ParseError, OSError) as e:
            incidents.append(f"{src['nom']} : {e}")
            print(f"  ⚠ {src['nom']} injoignable — {e}", file=sys.stderr)
            continue

        retenues = 0
        for o in brutes:
            if not o["lien"] or o["lien"] in index or exclu(o["titre"]):
                continue
            index.add(o["lien"])
            nouvelles.append({
                "date": aujourdhui,
                "source": src["nom"],
                "titre": o["titre"],
                "lien": o["lien"],
                "extrait": o.get("extrait", ""),
                "toulouse": bool(RE_TOULOUSE.search(o.get("contexte") or o["titre"])),
                "score": scorer(o.get("contexte") or o["titre"]),
            })
            retenues += 1
        print(f"  {src['nom']} : {len(brutes)} lues, {retenues} nouvelles")

    toutes = (nouvelles + connues)[:MAX_OFFRES]
    with open(SORTIE, "w", encoding="utf-8") as f:
        json.dump({
            "scan": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "incidents": incidents,
            "offres": toutes,
        }, f, ensure_ascii=False, indent=1)

    print(f"→ {len(nouvelles)} nouvelle(s), {len(toutes)} au total dans {SORTIE}")
    # Une source morte ne doit pas casser le workflow : on sort en succès.
    return 0


if __name__ == "__main__":
    sys.exit(main())

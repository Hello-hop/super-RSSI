#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collecteur d'offres — tourne dans GitHub Actions, sans dépendance externe.

Il interroge les sources, note chaque offre selon les mots-clés du profil,
dédoublonne sur l'URL et écrit docs/data/offres.json que lit l'application.

Pour Free-Work, chaque NOUVELLE offre est enrichie en visitant sa fiche
détail : le lieu, la fourchette de TJM, la durée, le télétravail et la
description complète en sont extraits. Le listing seul ne suffit pas à noter
correctement — un extrait tronqué à 200 caractères rate souvent le
référentiel exact ou la ville. Comme la déduplication ne rejoue jamais une
offre déjà connue, ce coût supplémentaire ne pèse que sur les vraies
nouveautés du jour, pas sur l'ensemble du catalogue à chaque scan.

Tout ce qui se règle est dans le bloc CONFIGURATION ci-dessous.
Test en local :  python3 scripts/veille.py
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html import unescape
from xml.etree import ElementTree

# ─────────────────────────── CONFIGURATION ───────────────────────────

# type : "freework" (scraping + fiche détail) ou "rss" (n'importe quel flux,
# y compris une Google Alert livrée en RSS — c'est la façon d'ajouter un site
# qui ne publie pas de flux, ou qui bloque le scraping comme Malt).
SOURCES = [
    {"nom": "FW ISO 27001",        "type": "freework",
     "url": "https://www.free-work.com/fr/tech-it/jobs/iso-27001"},
    {"nom": "FW Cyber Toulouse",   "type": "freework",
     "url": "https://www.free-work.com/fr/tech-it/jobs/cybersecurite/toulouse"},
    {"nom": "FW Sécu Toulouse",    "type": "freework",
     "url": "https://www.free-work.com/fr/tech-it/jobs/securite-informatique/toulouse"},
    {"nom": "FW Consultant cyber", "type": "freework",
     "url": "https://www.free-work.com/fr/tech-it/jobs/consultant-cyber-securite/toulouse"},

    # Hellowork republie ses offres en JSON-LD (schema.org JobPosting), le
    # format que Google lit pour l'indexation — un simple téléchargement de
    # page suffit, pas besoin de JavaScript. Chaque offre y est complètement
    # structurée : lieu (avec code postal, donc détection Toulouse fiable à
    # 100 %), salaire estimé, compétences, description complète.
    {"nom": "HW RSSI Occitanie",     "type": "hellowork",
     "url": "https://www.hellowork.com/fr-fr/emploi/metier_responsable-securite-des-systemes-informatiques-region_occitanie.html"},
    {"nom": "HW Conformité Occitanie", "type": "hellowork",
     "url": "https://www.hellowork.com/fr-fr/emploi/metier_responsable-conformite-region_occitanie.html"},
    {"nom": "HW RSSI national",      "type": "hellowork",
     "url": "https://www.hellowork.com/fr-fr/emploi/metier_responsable-securite-des-systemes-informatiques.html"},

    # Malt : ni scraping (Cloudflare bloque tout, y compris un navigateur
    # simulé) ni Google Alert (Google n'indexe que les profils freelances de
    # Malt, jamais les missions elles-mêmes — réservées aux comptes connectés).
    # Pas de contournement automatisable ici. Solution : l'alerte email native
    # de Malt (Rechercher des missions > sauvegarder la recherche > 🔔),
    # à filtrer dans Gmail vers le même libellé que les autres sources.
]

# Mots-clés pondérés : l'ADN de la recherche. Le total est divisé par 3,
# plafonné à 5. Calibré sur une vraie offre (consultant analyse de risques
# SSI, ISO 27005/EBIOS, collectivité) : 4/5 hors Toulouse, 5/5 à Toulouse —
# c'est l'écart que "toulouse" doit produire à lui seul.
MOTS_CLES = [
    (r"iso ?2700[15]|27005|ebios|smsi",                4),
    (r"grc|gouvernance|conformit[ée]",                 2),
    (r"rssi|ciso",                                     2),
    (r"analyse de risque|pssi|audit",                  3),
    (r"nis ?2|dora|rgpd|hds",                          1),
    (r"toulouse|occitanie",                            3),
    (r"t[ée]l[ée]travail|remote",                      1),
    (r"sant[ée]|h[ôo]pital|chu|laboratoire|collectivit[ée]|territorial", 2),
    (r"senior|lead|expert",                            1),
]

EXCLUSIONS = [
    "alternance", "stage", "stagiaire", "apprenti", "pentest", "soc analyst",
    "développeur", "developpeur", "commercial", "business developer", "recruteur",
]

# Détection du lieu, appliquée au texte complet de l'annonce (pas seulement au titre).
RE_TOULOUSE = re.compile(r"toulouse|haute[- ]garonne|\b31\d{3}\b", re.I)

SORTIE = os.path.join("docs", "data", "offres.json")
MAX_OFFRES = 600           # on garde un historique glissant
MAX_ENRICHISSEMENTS = 80   # garde-fou : plafond de fiches détail visitées par scan,
                            # partagé entre Free-Work et Hellowork
DELAI_ENRICHISSEMENT = 0.4  # secondes entre deux fiches — politesse envers le site
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

# ──────────────────────────── COLLECTE ────────────────────────────


def telecharger(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "fr-FR,fr;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def nettoyer(s: str) -> str:
    s = re.sub(r"<!--.*?-->", "", s or "", flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return unescape(re.sub(r"\s+", " ", s)).strip()


RE_FREEWORK_CARTE = re.compile(
    r'href="(/fr/tech-it/job-mission/[^"]+)"[^>]*>\s*<span[^>]*>(.*?)</span>', re.S)
RE_FREEWORK_LIEU = re.compile(r"<h1>.*?</h1><h2>([^<]+)</h2>", re.S)
RE_FREEWORK_FICHE = re.compile(r'class="w-full text-sm line-clamp-2">([^<]+)</span>')


def lister_freework(url: str):
    """Liste légère : titre + lien de chaque carte. Un seul appel réseau."""
    html_src = telecharger(url)
    vus, out = set(), []
    for m in RE_FREEWORK_CARTE.finditer(html_src):
        lien = "https://www.free-work.com" + m.group(1)
        titre = nettoyer(m.group(2))
        if titre and lien not in vus:
            vus.add(lien)
            out.append({"titre": titre, "lien": lien})
    return out


def enrichir_freework(lien: str):
    """Visite la fiche détail : lieu fiable, TJM/durée/télétravail, texte complet.

    Renvoie None si la structure de page attendue n'est pas trouvée (mise à
    jour du site, page retirée) — l'appelant retombe alors sur le titre seul.
    """
    html_src = telecharger(lien)

    m_lieu = RE_FREEWORK_LIEU.search(html_src)
    lieu = nettoyer(m_lieu.group(1)) if m_lieu else ""

    i1_marqueur = html_src.find("html-renderer prose-content")
    i1 = html_src.find(">", i1_marqueur) + 1 if i1_marqueur != -1 else -1
    i2 = html_src.find("Postulez à cette offre", i1) if i1 > 0 else -1
    corps = nettoyer(html_src[i1:i2]) if i1 > 0 and i2 != -1 else ""
    if not corps:
        return None

    i3 = html_src.find(">Le poste<")
    faits = RE_FREEWORK_FICHE.findall(html_src[i3:i3 + 7000]) if i3 != -1 else []
    fiche = " · ".join(nettoyer(f) for f in faits)  # ex. "18 mois · 210-500 €/j · Télétravail partiel"

    apercu = corps[:180]
    extrait = (fiche + " — " + apercu) if fiche else apercu

    contexte = " ".join([lieu, fiche, corps])
    return {
        "lieu": lieu,
        "extrait": extrait[:260],
        "contexte": contexte[:6000],
        "toulouse": bool(RE_TOULOUSE.search(lieu) or RE_TOULOUSE.search(contexte)),
    }


RE_JSON_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def extraire_json_ld(html_src: str, type_recherche: str):
    """Cherche, parmi tous les blocs JSON-LD de la page, le premier du type donné."""
    for m in RE_JSON_LD.finditer(html_src):
        try:
            d = json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(d, dict) and d.get("@type") == type_recherche:
            return d
    return None


def lister_hellowork(url: str):
    """Liste des offres via le JSON-LD ItemList — un seul appel réseau.

    Ce format ne donne que l'URL de chaque offre (pas de titre) : Hellowork
    charge ses cartes de résultats en JavaScript, mais republie la liste
    complète en JSON-LD pour l'indexation Google. On s'appuie sur ce second
    canal, stable et sans JavaScript à exécuter.
    """
    d = extraire_json_ld(telecharger(url), "ItemList")
    if not d:
        return []
    return [{"lien": it.get("url")} for it in d.get("itemListElement", []) if it.get("url")]


def enrichir_hellowork(lien: str):
    """Visite la fiche détail et lit son JSON-LD JobPosting (schema.org) :
    titre, description complète, lieu avec code postal, salaire estimé,
    compétences — tout structuré, sans scraping HTML fragile.

    Renvoie None si le bloc JobPosting est absent (offre retirée, format
    changé) — l'appelant l'ignore alors simplement.
    """
    d = extraire_json_ld(telecharger(lien), "JobPosting")
    if not d:
        return None

    titre = nettoyer(d.get("title", ""))
    if not titre:
        return None
    description = nettoyer(d.get("description", ""))

    lieu_obj = d.get("jobLocation")
    if isinstance(lieu_obj, list):
        lieu_obj = lieu_obj[0] if lieu_obj else {}
    adresse = (lieu_obj or {}).get("address", {}) if isinstance(lieu_obj, dict) else {}
    ville = adresse.get("addressLocality", "") if isinstance(adresse, dict) else ""
    cp = (adresse.get("postalCode") or "") if isinstance(adresse, dict) else ""
    region = adresse.get("addressRegion", "") if isinstance(adresse, dict) else ""
    lieu = ", ".join(x for x in [ville, region] if x)

    organisation = ""
    hiring = d.get("hiringOrganization")
    if isinstance(hiring, dict):
        organisation = hiring.get("name", "")

    salaire = ""
    est = d.get("estimatedSalary")
    if isinstance(est, dict) and est.get("median"):
        salaire = f"~{int(est['median'] / 1000)}k€/an estimé"
    elif isinstance(est, list) and est:
        m = est[0].get("median") if isinstance(est[0], dict) else None
        if m:
            salaire = f"~{int(m / 1000)}k€/an estimé"

    competences = d.get("skills")
    tags = ", ".join(competences) if isinstance(competences, list) else ""

    fiche = " · ".join(x for x in [lieu, salaire] if x)
    apercu = description[:180]
    extrait = ((organisation + " — ") if organisation else "") + (fiche + " — " if fiche else "") + apercu

    contexte = " ".join([titre, lieu, organisation, tags, description])
    return {
        "titre": titre,
        "extrait": extrait[:260],
        "contexte": contexte[:6000],
        "toulouse": bool(RE_TOULOUSE.search(lieu) or cp.startswith("31")),
    }


def lire_rss(url: str):
    racine = ElementTree.fromstring(telecharger(url))
    out = []
    canal = racine.find("channel")
    if canal is not None:                                   # RSS 2.0
        for item in canal.findall("item"):
            titre = nettoyer(item.findtext("title", ""))
            resume = nettoyer(item.findtext("description", ""))
            out.append({"titre": titre, "lien": (item.findtext("link") or "").strip(),
                        "extrait": resume[:200], "contexte": (titre + " " + resume)[:4000]})
        return out
    ns = {"a": "http://www.w3.org/2005/Atom"}               # Atom / Google Alerts
    for e in racine.findall("a:entry", ns):
        lien = e.find("a:link", ns)
        titre = nettoyer(e.findtext("a:title", "", ns))
        resume = nettoyer(e.findtext("a:content", "", ns) or e.findtext("a:summary", "", ns))
        out.append({"titre": titre, "lien": lien.get("href") if lien is not None else "",
                    "extrait": resume[:200], "contexte": (titre + " " + resume)[:4000]})
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
    enrichissements_faits = 0

    for src in SOURCES:
        try:
            if src["type"] == "rss":
                cartes = lire_rss(src["url"])
            elif src["type"] == "hellowork":
                cartes = lister_hellowork(src["url"])
            else:
                cartes = lister_freework(src["url"])
        except (urllib.error.URLError, urllib.error.HTTPError, ElementTree.ParseError, OSError) as e:
            incidents.append(f"{src['nom']} : {e}")
            print(f"  ⚠ {src['nom']} injoignable — {e}", file=sys.stderr)
            continue

        retenues = 0
        for o in cartes:
            lien = o.get("lien")
            if not lien or lien in index:
                continue

            if src["type"] == "hellowork":
                # Hellowork ne donne aucun titre au niveau du listing : sans
                # budget d'enrichissement, impossible de savoir de quoi il
                # s'agit. On ne marque PAS l'offre comme connue, pour la
                # retenter au prochain scan plutôt que de la perdre.
                if enrichissements_faits >= MAX_ENRICHISSEMENTS:
                    continue
                try:
                    time.sleep(DELAI_ENRICHISSEMENT)
                    detail = enrichir_hellowork(lien)
                    enrichissements_faits += 1
                except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
                    print(f"    (fiche Hellowork indisponible — {e})", file=sys.stderr)
                    continue
                index.add(lien)
                if not detail or exclu(detail["titre"]):
                    continue
                titre, extrait, contexte, toulouse = (
                    detail["titre"], detail["extrait"], detail["contexte"], detail["toulouse"])

            else:
                titre = o.get("titre", "")
                if exclu(titre):
                    index.add(lien)
                    continue
                index.add(lien)

                detail = None
                if src["type"] == "freework" and enrichissements_faits < MAX_ENRICHISSEMENTS:
                    try:
                        time.sleep(DELAI_ENRICHISSEMENT)
                        detail = enrichir_freework(lien)
                        enrichissements_faits += 1
                    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
                        print(f"    (fiche détail indisponible pour {titre[:40]} — {e})", file=sys.stderr)

                if detail:
                    extrait = detail["extrait"]
                    contexte = titre + " " + detail["contexte"]
                    toulouse = detail["toulouse"]
                else:
                    extrait = o.get("extrait", "")
                    contexte = titre + " " + extrait
                    toulouse = bool(RE_TOULOUSE.search(contexte))

            nouvelles.append({
                "date": aujourdhui, "source": src["nom"], "titre": titre, "lien": lien,
                "extrait": extrait, "toulouse": toulouse, "score": scorer(contexte),
            })
            retenues += 1
        print(f"  {src['nom']} : {len(cartes)} lues, {retenues} nouvelles")

    toutes = (nouvelles + connues)[:MAX_OFFRES]
    with open(SORTIE, "w", encoding="utf-8") as f:
        json.dump({
            "scan": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "incidents": incidents,
            "offres": toutes,
        }, f, ensure_ascii=False, indent=1)

    print(f"→ {len(nouvelles)} nouvelle(s) ({enrichissements_faits} fiche(s) enrichie(s)), "
          f"{len(toutes)} au total dans {SORTIE}")
    return 0  # une source morte ne doit pas casser le workflow


if __name__ == "__main__":
    sys.exit(main())

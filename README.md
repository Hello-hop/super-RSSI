# Veille missions

Registre personnel d'opportunités : un robot interroge les plateformes chaque matin,
note les offres selon ton profil, et les pousse dans une application installable sur
l'écran d'accueil du téléphone.

- **Collecte** : GitHub Actions, une fois par jour, sans serveur à maintenir.
- **Application** : GitHub Pages, installable, consultable hors-ligne.
- **Suivi** : statuts et relances stockés dans le navigateur du téléphone — ils ne
  partent nulle part, même si le dépôt est public.

---

## Architecture

Trois briques qui ne se parlent qu'à travers un seul fichier JSON, sans serveur ni
base de données :

```
GitHub Actions (collecte)  →  docs/data/offres.json  →  GitHub Pages (app)
```

**Le collecteur** (`scripts/veille.py`) — Python pur, bibliothèque standard
uniquement. À chaque scan :
1. **Lit chaque source.** Free-Work est rendu côté serveur : une regex extrait les
   liens du listing, puis chaque offre *nouvelle* est enrichie via sa fiche détail
   (lieu, TJM, durée, description complète). Hellowork rend son contenu en
   JavaScript — invisible pour un simple téléchargement — mais republie un bloc
   **JSON-LD** (`schema.org/JobPosting`, celui que Google lit pour l'indexation) :
   c'est cette structure qu'on lit directement, sans avoir besoin d'exécuter de JS.
2. **Note chaque offre** : mots-clés pondérés cherchés dans le texte complet
   (`MOTS_CLES`), total divisé par 3 et plafonné à 5. Des **planchers** forcent une
   note minimale sur certains intitulés précis (`REGLES_PLANCHER`) — un titre de
   trois mots ne peut pas cumuler assez de catégories pour y arriver seul.
3. **Exclut le bruit** (`EXCLUSIONS`, en regex avec `\b` pour les motifs courts —
   "ot" ne doit jamais matcher dans "photo"), vérifié sur le titre *et* sur le texte
   complet après enrichissement.
4. **Dédoublonne** par similarité de titre + entreprise + statut Toulouse
   (`difflib`), même entre deux plateformes différentes.

**Le stockage** (`docs/data/offres.json`) — un tableau JSON relu et réécrit à
chaque scan, dédoublonné sur l'URL, plafonné à 600 entrées.

**L'automatisation** — `.github/workflows/veille.yml` déclenche le script tous les
jours à 5h UTC (`schedule`) ou à la demande (`workflow_dispatch`), puis commit et
pousse le JSON modifié.

**L'hébergement** — le dossier `docs/` est publié tel quel comme site statique,
sans build ni compilation.

**L'application** (`docs/index.html`) — HTML/CSS/JS vanilla, sans framework. Elle
charge `data/offres.json` au démarrage ; le suivi personnel (statuts, relances) vit
dans le `localStorage` du téléphone, pas dans le dépôt. Un service worker
(`sw.js`) met en cache la dernière version pour l'ouverture hors-ligne, et un
`manifest.webmanifest` la rend installable sur l'écran d'accueil.

Chaque brique ne connaît que le format du JSON, rien d'autre — la source de
collecte, le scoring ou l'interface peuvent évoluer indépendamment sans rien
casser ailleurs.

---

## Installation

### 1. Créer le dépôt

Dépôt **public** (GitHub Pages est gratuit sur les dépôts publics uniquement).
Seuls le code et les liens d'offres y sont visibles : ton pipeline personnel, lui,
ne quitte jamais ton téléphone.

Dépose les fichiers en respectant l'arborescence :

```
.github/workflows/veille.yml
scripts/veille.py
docs/index.html
docs/sw.js
docs/manifest.webmanifest
docs/icone.svg
docs/data/offres.json
```

### 2. Autoriser le robot à écrire

Settings → Actions → General → **Workflow permissions** → *Read and write permissions* → Save.
Sans ça, le workflow collecte mais ne peut pas publier.

### 3. Publier l'application

Settings → Pages → Source : *Deploy from a branch* → branche `main`, dossier **`/docs`** → Save.
L'URL apparaît après une minute : `https://<ton-compte>.github.io/<nom-du-depot>/`

### 4. Premier scan

Onglet Actions → *Veille missions* → **Run workflow**. Ce bouton fonctionne aussi
depuis le navigateur du téléphone : c'est ton scan à la demande.

### 5. Installer sur le téléphone

Ouvre l'URL → menu du navigateur → **Installer l'application** (Android) ou
**Sur l'écran d'accueil** (iOS). Icône, plein écran, ouverture hors-ligne.

---

## Réglage

Tout se règle dans `scripts/veille.py`, bloc `CONFIGURATION` :

- **`SOURCES`** — trois types possibles :
  - `"freework"` et `"hellowork"` sont déjà branchés avec plusieurs URLs chacun.
    Pour Hellowork, ce sont des pages métier (`metier_<slug>-region_<région>.html`
    ou `metier_<slug>.html` pour le national) — cherche le bon slug en visitant
    le site et en copiant l'URL d'une recherche par métier.
  - `"rss"` accepte n'importe quel flux. Pour un site sans flux : crée une alerte sur
    [google.com/alerts](https://www.google.com/alerts), choisis *Diffusion : flux RSS*,
    et colle l'URL obtenue. C'est la façon d'ajouter APEC, LinkedIn ou un site de
    collectivité. **Ça ne marche pas pour Malt** : Google n'indexe que les profils de
    freelances, jamais les missions (réservées aux comptes connectés) — une alerte
    ramènerait des concurrents, pas des offres. Pour Malt, utilise son alerte email
    native (Rechercher des missions → sauvegarder la recherche → 🔔), et filtre ces
    emails dans Gmail vers le même endroit que le reste — ça reste manuel, hors de l'app.
- **`MOTS_CLES`** — les pondérations. La note vaut `somme des points / 3`, plafonnée à 5.
  Pour Free-Work, chaque nouvelle offre est enrichie via sa fiche détail (lieu, TJM,
  durée, télétravail, description complète) avant d'être notée — pas seulement le
  titre. Pour un flux RSS, la note porte sur le titre et le résumé fournis par le flux.
- **`EXCLUSIONS`** — le bruit à écarter d'office.
- **`MAX_ENRICHISSEMENTS`** — plafond de fiches détail visitées par scan (40 par défaut).
  À la hausse seulement si tu élargis beaucoup les sources Free-Work.

Après modification : Actions → Run workflow pour voir l'effet tout de suite.

---

## Ce qu'il faut savoir

- **Les workflows planifiés s'endorment** après 60 jours sans activité sur le dépôt.
  Un commit, même minime, les réveille — et modifier tes mots-clés suffit.
- **L'heure du cron est en UTC** : `0 5 * * *` correspond à 7 h à Paris en été, 6 h en hiver.
- **Le suivi vit dans le navigateur.** Menu `⋯` → *Exporter le suivi* avant de changer
  de téléphone ou de vider le cache. C'est la seule sauvegarde.
- **Si une source cesse de répondre**, le workflow ne casse pas : l'incident est écrit
  dans `docs/data/offres.json`, champ `incidents`, et les autres sources continuent.
  Une plateforme qui bloque le scraping se rebranche en flux RSS via une Google Alert.

## Test en local

```bash
python3 scripts/veille.py          # écrit docs/data/offres.json
cd docs && python3 -m http.server  # puis http://localhost:8000
```

# Veille missions

Registre personnel d'opportunités : un robot interroge les plateformes chaque matin,
note les offres selon ton profil, et les pousse dans une application installable sur
l'écran d'accueil du téléphone.

- **Collecte** : GitHub Actions, une fois par jour, sans serveur à maintenir.
- **Application** : GitHub Pages, installable, consultable hors-ligne.
- **Suivi** : statuts et relances stockés dans le navigateur du téléphone — ils ne
  partent nulle part, même si le dépôt est public.

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

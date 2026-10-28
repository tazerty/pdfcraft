#!/usr/bin/env python3
"""Portes Evora sur le site web empaqueté (écrit pour le fork tazerty/pdfcraft, stdlib seule).

Sous-commandes :
  check PKG REPO REPORT      portes des marques (E1), des fichiers d'hébergement, des émojis (E10) et
                             des termes sensibles à l'affichage (E9) ; statut 1 si une porte échoue.
  csp PKG OUT                empreintes sha256-… des scripts inline d'index.html (CSP), une par ligne.
  compress PKG               fichiers .br (brotli -q 11) et .gz (gzip -9 -n) à côté de chaque ressource web.
  sizes PKG REPORT           tailles (.wasm brut, .br, .gz ; site complet).
  fonts CRAFT_DIR REPORT     polices craft-fonts embarquées dans le build web (E6, mesure).
  deny-config UPSTREAM EVORA OUT REPORT
                             configuration de la porte cargo-deny : deny.toml de l'amont, inchangé,
                             plus les exceptions d'avis nommées par Evora (EVORA ; preuve : chaque
                             crate concernée est absente du graphe web, cargo tree wasm32, vérifié
                             à chaque run) ; statut 1 si une exception est mal formée, déjà ignorée
                             par l'amont, ou si sa crate est dans le graphe web.
  masks-witness MAIN_LOG WITNESS_LOG [KIND]
                             témoins sabordés des masquages : la recette tests/evora_masks.rs, sous une
                             fonctionnalité CI qui coupe un filtre, doit rougir par les seuls contrôles
                             qui en dépendent, mêmes inventaires que la course normale ; statut 1 sinon.
                             KIND « enforce » (défaut, EVORA-COL-30) : garde `enforce` coupée (état posé
                             directement, automatisation, clic sur un champ de signature vide) ;
                             « palette-groups » (EVORA-COL-32) : filtre des groupes de la palette
                             rouvert (les groupes masqués proposés, et eux seuls, famille par famille).

Chaque mesure est écrite dans REPORT (Markdown, repris dans le résumé du job) et dans le journal.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata

# Marques ArtCraft (E1) : recherche insensible à la casse, octet par octet, .wasm compris.
# « discord » seul (depuis EVORA-COL-21) : le nom du serveur communautaire ArtCraft, même sans URL
# (une mesure de largeur « Discord » de la barre d'onglets survivait au retrait du bouton).
BRANDS = ("artcraft", "discord.gg", "getartcraft", "discord")
# Fichiers d'hébergement interdits dans l'artefact : l'hébergement est celui d'Evora.
HOSTING_NAMES = {".htaccess", "_headers", "_redirects", "web.config", ".user.ini"}
HOSTING_SUFFIXES = (".conf", ".php")
# Ressources servies au navigateur, précompressées.
WEB_SUFFIXES = (".wasm", ".js", ".html", ".css", ".svg", ".json", ".map")
# Dossier où les mentions de licence (dont « basé sur PdfCraft par l'équipe ArtCraft ») sont permises.
LICENCES_DIR = "LICENSES"

# Catalogues affichés (E10) : catalogues TSV et chaînes du code d'interface.
CATALOG_DIR = "crates/ui-egui/src/i18n"
# Termes sensibles renommés à l'affichage (E9, D-16), casse exacte.
SENSITIVE = ("Lumetri", "Lightroom", "Acrobat", "Premiere", "Adobe", "Cycore")
OVERRIDES = "crates/ui-egui/src/i18n/evora-overrides.txt"
# Chaînes anglaises affichées (par tl!/tr, ou brutes pour les messages du moteur).
E9_SOURCE_DIRS = (("crates/ui-egui/src", False), ("apps/pdfcraft-web/src", False), ("crates/engine/src", True))
STRING_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')
UI_SOURCE_DIRS = ("crates/ui-egui/src", "crates/engine/src", "apps/pdfcraft-web/src")
E10_BASELINE = ".github/evora/e10-baseline.txt"


def is_emoji_like(cp: int) -> bool:
    """Émojis et pictogrammes interdits par la directive « zéro émoji d'interface ».

    Blocs entiers : pictogrammes et émojis (U+1F000–1FAFF), symboles divers et dingbats
    (U+2600–27BF : ✓ ✔ ✕ ✖ ⚠ ★ ☆…), symboles et flèches divers (U+2B00–2BFF : ⭐ ⬛…),
    sélecteur de présentation émoji U+FE0F et cabochon U+20E3 ; plus les caractères isolés
    Extended_Pictographic hors de ces blocs. Les signes typographiques (… — · → ▸ ▾ ⌘ ⇧ ⌥ © ® ™)
    restent permis : ce ne sont pas des émojis.
    """
    if 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF:
        return True
    if cp in (0xFE0F, 0x20E3, 0x203C, 0x2049, 0x2139, 0x24C2, 0x231A, 0x231B, 0x2328, 0x23CF,
              0x25B6, 0x25C0, 0x2934, 0x2935, 0x3030, 0x303D, 0x3297, 0x3299):
        return True
    return 0x23E9 <= cp <= 0x23F3 or 0x23F8 <= cp <= 0x23FA or 0x25FB <= cp <= 0x25FE


def log(report, line=""):
    print(line)
    report.write(line + "\n")


def walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def check_brands(pkg, report):
    log(report, "### Porte des marques (E1, bloquante)")
    log(report)
    log(report, "| Fichier | " + " | ".join(f"{b} (casse ignorée)" for b in BRANDS) + " |")
    log(report, "|---|" + "---|" * len(BRANDS))
    site = {b: 0 for b in BRANDS}
    licences = 0
    for path in walk_files(pkg):
        r = rel(path, pkg)
        if r.endswith((".br", ".gz")):
            continue  # dérivés compressés : leur clair est déjà compté
        with open(path, "rb") as fh:
            data = fh.read().lower()
        counts = {b: data.count(b.encode()) for b in BRANDS}
        if any(counts.values()):
            log(report, f"| `{r}` | " + " | ".join(str(counts[b]) for b in BRANDS) + " |")
        if r.split("/", 1)[0] == LICENCES_DIR:
            licences += counts["artcraft"]
        else:
            for b in BRANDS:
                site[b] += counts[b]
    log(report)
    log(report, f"Hors {LICENCES_DIR}/ : " + ", ".join(f"{b} **{site[b]}**" for b in BRANDS)
                + f" (attendu : 0) ; dans {LICENCES_DIR}/ (permis) : artcraft {licences}")
    log(report)
    ok = not any(site.values())
    print("::notice::marques hors LICENSES : " + " ".join(f"{b}={site[b]}" for b in BRANDS)
          + f" ; LICENSES artcraft={licences}")
    if not ok:
        print("::error::marque ArtCraft présente dans le bundle (porte E1)")
    return ok


def check_hosting(pkg, report):
    log(report, "### Porte des fichiers d'hébergement (bloquante)")
    log(report)
    found = []
    for path in walk_files(pkg):
        name = os.path.basename(path)
        if name in HOSTING_NAMES or name.endswith(HOSTING_SUFFIXES):
            found.append(rel(path, pkg))
    log(report, f"Fichiers interdits ({', '.join(sorted(HOSTING_NAMES))}, *.conf, *.php) : **{len(found)}** (attendu : 0)")
    for r in found:
        log(report, f"- `{r}`")
    log(report)
    print(f"::notice::fichiers d'hébergement : {len(found)}")
    if found:
        print("::error::fichier d'hébergement dans l'artefact")
    return not found


def unescape_tsv(field):
    return field.replace("\\t", "\t").replace("\\n", "\n").replace("\\\\", "\\")


def scan_catalogs(repo):
    """{(fichier, caractère): occurrences} dans les catalogues TSV (source et traduction)."""
    hits = {}
    base = os.path.join(repo, CATALOG_DIR)
    for name in sorted(os.listdir(base)):
        if not name.endswith(".tsv"):
            continue
        with open(os.path.join(base, name), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                for field in parts[1:]:
                    for ch in unescape_tsv(field):
                        if is_emoji_like(ord(ch)):
                            key = (f"{CATALOG_DIR}/{name}", ch)
                            hits[key] = hits.get(key, 0) + 1
    return hits


CFG_TEST = re.compile(r"^(\s*)#\[cfg\(test\)\]\s*$")
MOD_OPEN = re.compile(r"^(\s*)(?:pub(?:\([^)]*\))?\s+)?mod\s+\w+\s*\{\s*$")


def test_module_lines(lines):
    """Index des lignes d'un module `#[cfg(test)] mod … {`, jamais compilé dans le build web.

    Format rustfmt (vérifié par la CI amont) : l'attribut, la ligne `mod nom {` au même retrait,
    puis une accolade fermante seule au même retrait. Un module dont la fermeture n'est pas trouvée
    n'est PAS exclu : la porte reste fermée par défaut.
    """
    skip = set()
    i = 0
    while i < len(lines):
        m = CFG_TEST.match(lines[i])
        if m:
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("#["):
                j += 1
            o = MOD_OPEN.match(lines[j]) if j < len(lines) else None
            if o and o.group(1) == m.group(1):
                close = o.group(1) + "}"
                k = j + 1
                while k < len(lines) and lines[k].rstrip("\n") != close:
                    k += 1
                if k < len(lines):
                    skip.update(range(i, k + 1))
                    i = k + 1
                    continue
        i += 1
    return skip


MOD_DECL = re.compile(r"^(\s*)(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;\s*$")


def test_module_files(paths):
    """Fichiers de module déclarés `#[cfg(test)] mod nom;` (module de test dans son propre fichier,
    jamais compilé dans le build web ; EVORA-COL-37, après EVORA-COL-20 pour les modules en ligne).

    Le fichier d'un tel module est `nom.rs` ou `nom/mod.rs` dans le dossier du module parent : celui du
    fichier pour lib.rs, main.rs et mod.rs, `parent/` pour un fichier `parent.rs`. Seul un fichier qui
    existe est exclu, et seulement s'il n'est déclaré nulle part sans `#[cfg(test)]` : la porte reste
    fermée par défaut.
    """
    tests, plain = set(), set()
    for path in paths:
        if not path.endswith(".rs"):
            continue
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        stem = os.path.splitext(os.path.basename(path))[0]
        base = os.path.dirname(path) if stem in ("lib", "main", "mod") else os.path.join(os.path.dirname(path), stem)
        for n, line in enumerate(lines):
            d = MOD_DECL.match(line)
            if not d:
                continue
            j = n - 1
            attrs = []
            while j >= 0 and lines[j].strip().startswith("#["):
                attrs.append(lines[j].strip())
                j -= 1
            for candidate in (os.path.join(base, d.group(2) + ".rs"), os.path.join(base, d.group(2), "mod.rs")):
                if os.path.exists(candidate):
                    (tests if "#[cfg(test)]" in attrs else plain).add(os.path.normpath(candidate))
    return tests - plain


def scan_sources(repo, ignored=None):
    """{(fichier, caractère): occurrences} dans le code d'interface, commentaires exclus.

    Le code des modules `#[cfg(test)]` n'est pas affiché : ses occurrences vont dans `ignored`
    (comptées et publiées à part), jamais dans le résultat.
    """
    hits = {}
    for d in UI_SOURCE_DIRS:
        paths = list(walk_files(os.path.join(repo, d)))
        test_files = test_module_files(paths)
        for path in paths:
            if not path.endswith((".rs", ".html")):
                continue
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
            if os.path.normpath(path) in test_files:
                skip = set(range(len(lines)))
            else:
                skip = test_module_lines(lines) if path.endswith(".rs") else set()
            for n, line in enumerate(lines):
                if line.lstrip().startswith("//"):
                    continue
                for ch in line:
                    if is_emoji_like(ord(ch)):
                        key = (rel(path, repo), ch)
                        target = ignored if (n in skip and ignored is not None) else hits
                        target[key] = target.get(key, 0) + 1
    return hits


def read_baseline(repo):
    path = os.path.join(repo, E10_BASELINE)
    base = {}
    if not os.path.exists(path):
        return base
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            f, cp, n = line.split("\t")
            base[(f, chr(int(cp.removeprefix("U+"), 16)))] = int(n)
    return base


def check_emoji(repo, report):
    log(report, "### Porte des émojis des catalogues affichés (E10, bloquante)")
    log(report)
    hits = scan_catalogs(repo)
    ignored = {}
    hits.update(scan_sources(repo, ignored))
    baseline = read_baseline(repo)
    total = sum(hits.values())
    over = []
    log(report, "| Fichier | Caractère | Occurrences | Ligne de base |")
    log(report, "|---|---|---|---|")
    for (f, ch), n in sorted(hits.items()):
        allowed = baseline.get((f, ch), 0)
        name = unicodedata.name(ch, "?")
        log(report, f"| `{f}` | U+{ord(ch):04X} {name} | {n} | {allowed} |")
        if n > allowed:
            over.append((f, ch, n, allowed))
    log(report)
    log(report, f"Occurrences : **{total}** ; ligne de base déclarée ({E10_BASELINE}) : {sum(baseline.values())} ; "
                f"dépassements : **{len(over)}** (attendu : 0)")
    if baseline:
        log(report, "La ligne de base ne fait que geler l'existant avant le patch E10 ; elle ne peut que décroître.")
    log(report)
    log(report, f"Code de test (`#[cfg(test)]`, hors build web), compté à part : **{sum(ignored.values())}**")
    for (f, ch), n in sorted(ignored.items()):
        log(report, f"- `{f}` : U+{ord(ch):04X} {unicodedata.name(ch, '?')} × {n}")
    log(report)
    print(f"::notice::émojis des catalogues : {total} occurrence(s), ligne de base {sum(baseline.values())}, "
          f"dépassements {len(over)} ; code de test ignoré : {sum(ignored.values())}")
    for f, ch, n, allowed in over:
        print(f"::error file={f}::U+{ord(ch):04X} {unicodedata.name(ch, '?')} : {n} occurrence(s), {allowed} permise(s)")
    return not over


def read_overrides(repo):
    rules = []
    with open(os.path.join(repo, OVERRIDES), encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) == 3 and cols[1]:
                rules.append(tuple(cols))
    return rules


def apply_overrides(rules, lang, text):
    """Même algorithme que i18n::evora_display (ui-egui) : règles de la langue et « * », dans l'ordre."""
    for rule_lang, src, dst in rules:
        if rule_lang in ("*", lang) and src in text:
            text = text.replace(src, dst)
    return text


def residual_terms(text):
    return [t for t in SENSITIVE if t in text]


def check_terms(repo, report):
    log(report, "### Porte des termes sensibles à l'affichage (E9, bloquante)")
    log(report)
    rules = read_overrides(repo)
    before = {t: 0 for t in SENSITIVE}
    after = {t: 0 for t in SENSITIVE}
    leftovers = []
    base = os.path.join(repo, CATALOG_DIR)
    for name in sorted(os.listdir(base)):
        if not name.endswith(".tsv"):
            continue
        lang = name[:-4]
        with open(os.path.join(base, name), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                shown = unescape_tsv(parts[2])
                for t in residual_terms(shown):
                    before[t] += 1
                left = residual_terms(apply_overrides(rules, lang, shown))
                for t in left:
                    after[t] += 1
                if left:
                    leftovers.append((f"{CATALOG_DIR}/{name}", shown[:100]))
    for d, raw_messages in E9_SOURCE_DIRS:
        for path in walk_files(os.path.join(repo, d)):
            if not path.endswith(".rs") or os.path.basename(path) == "tests.rs" or "/tests/" in path:
                continue
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if line.lstrip().startswith("//"):
                        continue
                    if "evora-gates: allow" in line:
                        continue  # liste de termes du détecteur au rendu lui-même
                    for lit in STRING_LITERAL.findall(line):
                        if not residual_terms(lit):
                            continue
                        for t in residual_terms(lit):
                            before[t] += 1
                        shown = [apply_overrides(rules, "en", lit)]
                        if raw_messages:
                            shown.append(apply_overrides(rules, "msg", lit))
                        left = sorted({t for s in shown for t in residual_terms(s)})
                        for t in left:
                            after[t] += 1
                        if left:
                            leftovers.append((rel(path, repo), lit[:100]))
    log(report, f"Règles de surcharge ({OVERRIDES}) : {len(rules)}")
    log(report)
    log(report, "| Terme | Occurrences dans les chaînes affichables | Après surcharge |")
    log(report, "|---|---|---|")
    for t in SENSITIVE:
        log(report, f"| {t} | {before[t]} | **{after[t]}** |")
    log(report)
    absent = [t for t in SENSITIVE if before[t] == 0]
    log(report, f"Termes absents de ce dépôt (sans objet, mesuré) : {', '.join(absent) if absent else 'aucun'}")
    for f, text in leftovers:
        log(report, f"- reste dans `{f}` : {text}")
    log(report)
    total = sum(after.values())
    print(f"::notice::termes sensibles affichés après surcharge : {total} (avant : {sum(before.values())})")
    if total:
        print("::error::terme sensible non couvert par le catalogue de surcharge (E9)")
    return total == 0


def bundle_terms(pkg, report):
    """Information, non bloquante : termes présents dans les octets du bundle (moteur, clés)."""
    counts = {t: 0 for t in SENSITIVE}
    for path in walk_files(pkg):
        r = rel(path, pkg)
        if r.endswith((".br", ".gz")) or r.split("/", 1)[0] == LICENCES_DIR:
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        for t in SENSITIVE:
            counts[t] += data.count(t.encode())
    log(report, "Information (non bloquante) : occurrences brutes dans le bundle hors LICENSES/, où restent les "
                "clés anglaises des catalogues, les règles de surcharge et les chaînes internes du moteur, "
                "non affichées ou affichées après surcharge : "
                + ", ".join(f"{t} {n}" for t, n in counts.items()))
    log(report)


def cmd_check(pkg, repo, report_path):
    with open(report_path, "a", encoding="utf-8") as report:
        results = [check_brands(pkg, report), check_hosting(pkg, report), check_emoji(repo, report),
                   check_terms(repo, report)]
        bundle_terms(pkg, report)
    return 0 if all(results) else 1


INLINE_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)


def cmd_csp(pkg, out_path):
    with open(os.path.join(pkg, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    hashes = []
    for attrs, body in INLINE_SCRIPT.findall(html):
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        hashes.append(f"sha256-{digest}")
    if not hashes:
        print("::error::aucun script inline dans index.html : chargeur Trunk inattendu")
        return 1
    with open(out_path, "w", encoding="utf-8") as fh:
        for h in hashes:
            fh.write(h + "\n")
    for h in hashes:
        print(f"::notice::CSP script-src '{h}'")
    return 0


def cmd_compress(pkg):
    n = 0
    for path in list(walk_files(pkg)):
        r = rel(path, pkg)
        if r.split("/", 1)[0] == LICENCES_DIR or not r.endswith(WEB_SUFFIXES):
            continue
        subprocess.run(["brotli", "-q", "11", "-f", "-o", path + ".br", path], check=True)
        with open(path + ".gz", "wb") as out:
            subprocess.run(["gzip", "-9", "-n", "-c", path], check=True, stdout=out)
        n += 1
    print(f"::notice::{n} ressource(s) précompressée(s) en .br et .gz")
    return 0 if n else 1


def cmd_sizes(pkg, report_path):
    with open(report_path, "a", encoding="utf-8") as report:
        log(report, "### Taille")
        log(report)
        log(report, "| Fichier | Brut (octets) | .br (brotli -q 11) | .gz (gzip -9) |")
        log(report, "|---|---|---|---|")
        for path in walk_files(pkg):
            if not path.endswith(".wasm"):
                continue
            raw = os.path.getsize(path)
            br = os.path.getsize(path + ".br") if os.path.exists(path + ".br") else "n/d"
            gz = os.path.getsize(path + ".gz") if os.path.exists(path + ".gz") else "n/d"
            log(report, f"| `{rel(path, pkg)}` | {raw} | {br} | {gz} |")
            print(f"::notice::{rel(path, pkg)} : {raw} octets bruts, {br} en .br, {gz} en .gz")
        files = list(walk_files(pkg))
        total = sum(os.path.getsize(p) for p in files)
        plain = sum(os.path.getsize(p) for p in files if not p.endswith((".br", ".gz")))
        log(report)
        log(report, f"Site : {plain} octets sans les précompressés, {total} avec ; fichiers : {len(files)}")
        log(report)
    return 0


# Même sélection que crates/fonts/build.rs (cible wasm32) : faces embarquées dans le .wasm.
BARRED_FAMILIES = ("Source Han", "Source Serif", "Source Sans", "Noto Sans CJK", "Noto Serif CJK")


def cmd_fonts(craft_dir, report_path):
    """E6 : polices craft-fonts embarquées dans le build web et polices laissées de côté (mesure)."""
    embedded, left, barred = [], [], []
    with open(os.path.join(craft_dir, "fonts", "manifest.txt"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cols = [c.strip() for c in line.split(" | ")]
            if len(cols) < 4:
                print(f"::error::ligne de manifeste craft-fonts illisible : {line}")
                return 1
            family, style, file, scripts = cols[:4]
            scripts = [x.strip() for x in scripts.split(",")]
            size = os.path.getsize(os.path.join(craft_dir, file)) if os.path.exists(os.path.join(craft_dir, file)) else 0
            row = (family, style, ",".join(scripts), size)
            if any(family.startswith(b) for b in BARRED_FAMILIES):
                barred.append(row)
            elif (family == "BIZ UDPGothic" and style == "Regular") or set(scripts) & {"Arab", "Telu", "Hebr", "Thai"}:
                embedded.append(row)
            else:
                left.append(row)
    with open(report_path, "a", encoding="utf-8") as report:
        log(report, "### Polices craft-fonts (E6, mesure)")
        log(report)
        log(report, "| Face embarquée dans le .wasm | Écritures | Octets |")
        log(report, "|---|---|---|")
        for family, style, scripts, size in embedded:
            log(report, f"| {family} {style} | {scripts} | {size} |")
        log(report)
        log(report, f"Embarquées : {len(embedded)} faces, {sum(r[3] for r in embedded)} octets ; laissées hors du build web par "
                    f"crates/fonts/build.rs : {len(left)} faces, {sum(r[3] for r in left)} octets ; écartées par AGENTS.md §1.1 "
                    f"de l'amont : {len(barred)} faces.")
        log(report)
    print(f"::notice::craft-fonts embarquées : {len(embedded)} faces, {sum(r[3] for r in embedded)} octets")
    return 0 if embedded else 1


def web_graph_packages():
    """Noms des paquets du graphe du build web (pdfcraft-web, cible wasm32, dépendances normales et de
    compilation, hôte compris), par `cargo tree`, hors ligne et verrou tenu."""
    out = subprocess.run(
        ["cargo", "tree", "--locked", "--offline", "-p", "pdfcraft-web", "--target", "wasm32-unknown-unknown",
         "-e", "normal,build", "--prefix", "none", "--format", "{p}"],
        check=True, capture_output=True, text=True).stdout
    return {line.split()[0] for line in out.splitlines() if line.strip()}


def advisory_ids(table):
    return [e["id"] if isinstance(e, dict) else e for e in table.get("advisories", {}).get("ignore", [])]


def cmd_deny_config(upstream, evora, out_path, report_path):
    """Porte cargo-deny : la politique de l'amont, plus les exceptions d'avis qu'Evora nomme une à une."""
    import tomllib
    with open(upstream, "rb") as fh:
        base = tomllib.load(fh)
    with open(evora, "rb") as fh:
        extra = tomllib.load(fh)
    added = extra.get("advisories", {}).get("ignore", [])
    base_ids = advisory_ids(base)
    graph = web_graph_packages()
    problems = []
    # Témoin de l'instrument : la crate web et egui sont dans le graphe, sinon il ne dit rien.
    for known in ("pdfcraft-web", "egui"):
        if known not in graph:
            problems.append(f"instrument : {known} absent du graphe web relevé par cargo tree ({len(graph)} paquets)")
    for e in added:
        ok = isinstance(e, dict) and re.fullmatch(r"RUSTSEC-\d{4}-\d{4}", str(e.get("id", ""))) \
            and e.get("crate") and e.get("reason") and e.get("evidence")
        if not ok:
            problems.append(f"exception mal formée (id, crate, reason, evidence) : {e!r}")
        elif e["id"] in base_ids:
            problems.append(f"{e['id']} : déjà ignoré par le deny.toml de l'amont, exception Evora à retirer")
        elif e["crate"] in graph:
            problems.append(f"{e['id']} : {e['crate']} est dans le graphe web, l'exception ne tient plus")
    with open(upstream, encoding="utf-8") as fh:
        lines = fh.readlines()
    section, at = None, None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
        elif section == "[advisories]" and re.fullmatch(r"ignore\s*=\s*\[", stripped):
            at = i
            break
    if at is None:
        problems.append("deny.toml de l'amont : pas de liste « ignore = [ » dans [advisories]")
        merged = "".join(lines)
    else:
        entries = "".join(
            f"    {{ id = {json.dumps(e['id'])}, reason = {json.dumps('Evora : ' + str(e.get('reason', '')), ensure_ascii=False)} }},\n"
            for e in added if isinstance(e, dict))
        merged = "".join(lines[:at + 1]) + "    # Evora (.github/evora/deny-exceptions.toml) : exceptions nommées.\n" + entries \
            + "".join(lines[at + 1:])
        ids = advisory_ids(tomllib.loads(merged))
        expected = [e["id"] for e in added if isinstance(e, dict)] + base_ids
        if ids != expected:
            problems.append(f"fusion : avis ignorés {ids}, attendus {expected}")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(merged)
    with open(report_path, "a", encoding="utf-8") as report:
        log(report, "### Politique cargo-deny : amont et exceptions Evora")
        log(report)
        log(report, f"Avis ignorés par le deny.toml de l'amont : {', '.join(base_ids) or 'aucun'} ; sources git admises : "
                    f"{', '.join(base.get('sources', {}).get('allow-git', [])) or 'aucune'} ; exceptions de licence : "
                    f"{', '.join(x.get('crate', '?') for x in base.get('licenses', {}).get('exceptions', [])) or 'aucune'}.")
        log(report)
        log(report, f"Graphe du build web (cargo tree, wasm32) : {len(graph)} paquets.")
        log(report)
        log(report, "| Avis ignoré par Evora | Crate | Dans le graphe web | Raison | Preuve |")
        log(report, "|---|---|---|---|---|")
        for e in added:
            if isinstance(e, dict):
                log(report, f"| {e.get('id')} | `{e.get('crate')}` | {'OUI' if e.get('crate') in graph else 'non'} | "
                            f"{e.get('reason')} | {e.get('evidence')} |")
        log(report)
        for p in problems:
            log(report, f"- ÉCHEC : {p}")
    for p in problems:
        print(f"::error::politique cargo-deny : {p}")
    print(f"::notice::politique cargo-deny : {len(base_ids)} avis ignoré(s) par l'amont, {len(added)} par Evora, "
          f"graphe web {len(graph)} paquets, {len(problems)} problème(s)")
    return 1 if problems else 0


# Témoins sabordés des masquages (fonctionnalités CI de pdfcraft-ui-egui, jamais dans le build web). Pour
# chacun : le début de libellé de ses seuls détecteurs dans tests/evora_masks.rs, les familles qui doivent
# rougir sous lui (toutes les autres restent vertes) et, quand ses détecteurs nomment un groupe d'outils,
# la liste exacte des groupes proposés attendue par famille (une faute par recherche).
MASK_WITNESSES = {
    # EVORA-COL-30 : garde `enforce` coupée.
    "enforce": {
        "title": "garde des masquages (enforce coupée)",
        "prefixes": ("clic sur le champ vide", "automatisation ", "dialogue ", "outil de page "),
        "red": ("signature", "caviardage", "ocr", "perimetre-q47"),
        "groups": None,
    },
    # EVORA-COL-32 : filtre des groupes de la palette rouvert (la palette liste tous les groupes du catalogue).
    "palette-groups": {
        "title": "filtre des groupes de la palette (groupes masqués rouverts)",
        "prefixes": ("groupe de palette ",),
        "red": ("caviardage", "ocr", "perimetre-q47"),
        "groups": {"caviardage": ["redact"], "ocr": ["actions", "scan"], "perimetre-q47": ["actions"]},
    },
}
# « vue-outils » (EVORA-COL-38) : vue « All tools » étendue de v0.14.0 ; verte sous les deux témoins.
MASK_FAMILIES = ("ids", "signature", "caviardage", "ocr", "perimetre-q47", "vue-outils", "temoins")
# Sans ancrage en début de ligne : le harnais de cargo test écrit « test <nom> ... » sans saut de ligne
# avant la sortie du test, qui commence donc au milieu de la ligne (run 39200498133).
MASK_COUNTS = re.compile(r"\[([a-z0-9-]+)\] (\d+) contrôle\(s\), (\d+) faute\(s\)$", re.M)
MASK_FAULT = re.compile(r"\[([a-z0-9-]+)\] FAUTE (.*)$", re.M)
# Faute d'un détecteur de groupe de la palette : le groupe masqué est proposé (seule cause admise).
PALETTE_GROUP_FAULT = re.compile(r"groupe de palette ([a-z_]+) : « [^»]+ » proposé \(\d+ nœud\(s\)\)$")


def mask_log(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = re.sub(r"\x1b\[[0-9;]*m", "", fh.read())
    counts = {m.group(1): (int(m.group(2)), int(m.group(3))) for m in MASK_COUNTS.finditer(text)}
    return counts, MASK_FAULT.findall(text)


def cmd_masks_witness(main_path, witness_path, kind="enforce"):
    """Témoin sabordé des masquages : rouge par ses seuls détecteurs, inventaires constants."""
    spec = MASK_WITNESSES.get(kind)
    if spec is None:
        print(f"::error::témoin des masquages : genre inconnu {kind!r}, attendus {sorted(MASK_WITNESSES)}")
        return 2
    main_counts, main_faults = mask_log(main_path)
    counts, faults = mask_log(witness_path)
    problems = []
    for name, got in (("course normale", main_counts), ("témoin", counts)):
        if sorted(got) != sorted(MASK_FAMILIES):
            problems.append(f"{name} : familles relevées {sorted(got)}, attendues {sorted(MASK_FAMILIES)}")
    if main_faults or any(f for _, f in main_counts.values()):
        problems.append(f"course normale rouge : {len(main_faults)} faute(s), le témoin ne se juge que sur un vert")
    for family in MASK_FAMILIES:
        if family in counts and family in main_counts and counts[family][0] != main_counts[family][0]:
            problems.append(f"{family} : {counts[family][0]} contrôles sous le témoin, {main_counts[family][0]} en course normale")
    for family in MASK_FAMILIES:
        if family in spec["red"]:
            if counts.get(family, (0, 0))[1] == 0:
                problems.append(f"{family} : vert sous le témoin, le filtre sabordé n'y est pas éprouvé")
        elif counts.get(family, (0, 1))[1] != 0:
            problems.append(f"{family} : rouge sous le témoin (une garde voisine ou l'instrument dépend du filtre sabordé)")
    stray = [(family, f) for family, f in faults if not f.startswith(spec["prefixes"])]
    if spec["groups"] is not None:
        proposed = {}
        for family, f in faults:
            m = PALETTE_GROUP_FAULT.match(f)
            if m:
                proposed.setdefault(family, []).append(m.group(1))
            elif (family, f) not in stray:
                stray.append((family, f))
        for family in MASK_FAMILIES:
            got, want = sorted(proposed.get(family, [])), sorted(spec["groups"].get(family, []))
            if got != want:
                problems.append(f"{family} : groupes proposés sous le témoin {got}, attendus {want}")
    for family, f in stray:
        problems.append(f"{family} : faute étrangère au filtre sabordé sous le témoin : {f}")
    lines = [f"### Témoin sabordé ({kind}) : {spec['title']}", "",
             "| Famille | Contrôles (normale / témoin) | Fautes sous le témoin |", "|---|---|---|"]
    for family in MASK_FAMILIES:
        n_main = main_counts.get(family, ("?", "?"))[0]
        n_w, f_w = counts.get(family, ("?", "?"))
        lines.append(f"| {family} | {n_main} / {n_w} | {f_w} |")
    lines.append("")
    lines.append(f"Fautes sous le témoin : {len(faults)}, toutes de ses détecteurs : {'oui' if not stray else 'NON'} ; "
                 f"verdict : {'témoin VALIDE' if not problems else 'témoin INVALIDE'} ({kind}).")
    lines.extend(f"- ÉCHEC : {p}" for p in problems)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    for p in problems:
        print(f"::error::témoin des masquages ({kind}) : {p}")
    return 1 if problems else 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "check" and len(argv) == 5:
        return cmd_check(argv[2], argv[3], argv[4])
    if len(argv) >= 2 and argv[1] == "csp" and len(argv) == 4:
        return cmd_csp(argv[2], argv[3])
    if len(argv) >= 2 and argv[1] == "compress" and len(argv) == 3:
        return cmd_compress(argv[2])
    if len(argv) >= 2 and argv[1] == "sizes" and len(argv) == 4:
        return cmd_sizes(argv[2], argv[3])
    if len(argv) >= 2 and argv[1] == "fonts" and len(argv) == 4:
        return cmd_fonts(argv[2], argv[3])
    if len(argv) >= 2 and argv[1] == "deny-config" and len(argv) == 6:
        return cmd_deny_config(argv[2], argv[3], argv[4], argv[5])
    if len(argv) >= 2 and argv[1] == "masks-witness" and len(argv) in (4, 5):
        return cmd_masks_witness(*argv[2:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""Portes Evora sur le site web empaqueté (écrit pour le fork tazerty/pdfcraft, stdlib seule).

Sous-commandes :
  check PKG REPO REPORT      porte des marques (E1), des fichiers d'hébergement et des émojis (E10) ;
                             statut 1 si une porte bloquante échoue.
  csp PKG OUT                empreintes sha256-… des scripts inline d'index.html (CSP), une par ligne.
  compress PKG               fichiers .br (brotli -q 11) et .gz (gzip -9 -n) à côté de chaque ressource web.
  sizes PKG REPORT           tailles (.wasm brut, .br, .gz ; site complet).

Chaque mesure est écrite dans REPORT (Markdown, repris dans le résumé du job) et dans le journal.
"""

import base64
import hashlib
import os
import re
import subprocess
import sys
import unicodedata

# Marques ArtCraft (E1) : recherche insensible à la casse, octet par octet, .wasm compris.
BRANDS = ("artcraft", "discord.gg", "getartcraft")
# Fichiers d'hébergement interdits dans l'artefact : l'hébergement est celui d'Evora.
HOSTING_NAMES = {".htaccess", "_headers", "_redirects", "web.config", ".user.ini"}
HOSTING_SUFFIXES = (".conf", ".php")
# Ressources servies au navigateur, précompressées.
WEB_SUFFIXES = (".wasm", ".js", ".html", ".css", ".svg", ".json", ".map")
# Dossier où les mentions de licence (dont « basé sur PdfCraft par l'équipe ArtCraft ») sont permises.
LICENCES_DIR = "LICENSES"

# Catalogues affichés (E10) : catalogues TSV et chaînes du code d'interface.
CATALOG_DIR = "crates/ui-egui/src/i18n"
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
    log(report, "| Fichier | artcraft (casse ignorée) | discord.gg | getartcraft (casse ignorée) |")
    log(report, "|---|---|---|---|")
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
            log(report, f"| `{r}` | {counts['artcraft']} | {counts['discord.gg']} | {counts['getartcraft']} |")
        if r.split("/", 1)[0] == LICENCES_DIR:
            licences += counts["artcraft"]
        else:
            for b in BRANDS:
                site[b] += counts[b]
    log(report)
    log(report, f"Hors {LICENCES_DIR}/ : artcraft **{site['artcraft']}**, discord.gg **{site['discord.gg']}**, "
                f"getartcraft **{site['getartcraft']}** (attendu : 0) ; dans {LICENCES_DIR}/ (permis) : artcraft {licences}")
    log(report)
    ok = not any(site.values())
    print(f"::notice::marques hors LICENSES : artcraft={site['artcraft']} discord.gg={site['discord.gg']} "
          f"getartcraft={site['getartcraft']} ; LICENSES artcraft={licences}")
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


def scan_sources(repo):
    """{(fichier, caractère): occurrences} dans le code d'interface, commentaires exclus."""
    hits = {}
    for d in UI_SOURCE_DIRS:
        for path in walk_files(os.path.join(repo, d)):
            if not path.endswith((".rs", ".html")):
                continue
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if line.lstrip().startswith("//"):
                        continue
                    for ch in line:
                        if is_emoji_like(ord(ch)):
                            key = (rel(path, repo), ch)
                            hits[key] = hits.get(key, 0) + 1
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
    hits.update(scan_sources(repo))
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
    print(f"::notice::émojis des catalogues : {total} occurrence(s), ligne de base {sum(baseline.values())}, dépassements {len(over)}")
    for f, ch, n, allowed in over:
        print(f"::error file={f}::U+{ord(ch):04X} {unicodedata.name(ch, '?')} : {n} occurrence(s), {allowed} permise(s)")
    return not over


def cmd_check(pkg, repo, report_path):
    with open(report_path, "a", encoding="utf-8") as report:
        results = [check_brands(pkg, report), check_hosting(pkg, report), check_emoji(repo, report)]
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


def main(argv):
    if len(argv) >= 2 and argv[1] == "check" and len(argv) == 5:
        return cmd_check(argv[2], argv[3], argv[4])
    if len(argv) >= 2 and argv[1] == "csp" and len(argv) == 4:
        return cmd_csp(argv[2], argv[3])
    if len(argv) >= 2 and argv[1] == "compress" and len(argv) == 3:
        return cmd_compress(argv[2])
    if len(argv) >= 2 and argv[1] == "sizes" and len(argv) == 4:
        return cmd_sizes(argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

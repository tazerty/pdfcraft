#!/usr/bin/env python3
"""Met en forme la sortie JSON de `cargo about generate --format json` (Evora, stdlib seule).

Usage : licenses.py ABOUT_JSON OUT_TXT
Écrit un fichier texte : synthèse (licence → crates), puis le texte intégral de chaque licence
avec la liste des crates qui l'utilisent. Statut 1 si le JSON ne contient aucune licence.
"""

import json
import sys


def crate_label(entry):
    c = entry.get("crate", entry) if isinstance(entry, dict) else {}
    return f"{c.get('name', '?')} {c.get('version', '')}".strip()


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
    licenses = data.get("licenses", [])
    crates = data.get("crates", [])
    print(f"cargo-about : clés {sorted(data)} ; {len(licenses)} texte(s) de licence ; {len(crates)} crate(s)")
    if not licenses:
        print("::error::cargo-about n'a produit aucune licence")
        return 1
    out = []
    out.append("Licences des dépendances Rust du build web (cible wasm32-unknown-unknown)")
    out.append("Générées par cargo-about lors du build Evora ; textes tels que fournis par chaque crate.")
    out.append("")
    out.append("Synthèse")
    out.append("--------")
    for lic in licenses:
        users = sorted({crate_label(u) for u in lic.get("used_by", [])})
        out.append(f"- {lic.get('name', lic.get('id', '?'))} ({lic.get('id', '?')}) : {len(users)} crate(s)")
    out.append("")
    out.append("Crates et expression de licence")
    out.append("-------------------------------")
    for c in sorted(crates, key=lambda x: (x.get("package", {}).get("name", ""), x.get("package", {}).get("version", ""))):
        pkg = c.get("package", {})
        out.append(f"- {pkg.get('name', '?')} {pkg.get('version', '')} : {c.get('license', pkg.get('license', '?'))}")
    out.append("")
    for lic in licenses:
        users = sorted({crate_label(u) for u in lic.get("used_by", [])})
        out.append("=" * 78)
        out.append(f"{lic.get('name', '?')} ({lic.get('id', '?')})")
        out.append("Utilisée par : " + ", ".join(users))
        out.append("-" * 78)
        out.append(lic.get("text", "").rstrip())
        out.append("")
    with open(argv[2], "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"::notice::LICENSES : {len(licenses)} texte(s) de licence pour {len(crates)} crate(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

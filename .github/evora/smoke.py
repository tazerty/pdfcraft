#!/usr/bin/env python3
"""Test de fumée Evora : le build web chargé dans une iframe servie par une AUTRE origine.

Écrit pour le fork tazerty/pdfcraft ; bibliothèque standard Python seule, aucune action tierce.
Chrome (préinstallé sur le runner) est piloté par le protocole DevTools sur tuyaux
(--remote-debugging-pipe : commandes JSON terminées par un octet nul sur les descripteurs 3 et 4).

  origine A (moteur)  : http://127.0.0.1:<port A>/  sert le site empaqueté ;
  origine B (parente) : http://localhost:<port B>/  sert une page qui encadre A dans une iframe.

Deux origines (hôtes et ports distincts, donc deux sites : la situation du mode B d'Evora).
Scénarios, chacun sur un profil Chrome vierge (démarrage à froid) :
  1. « sans CSP » ; 2. « CSP appliquée » : la CSP cible des documents moteur (ARCHITECTURE §3.6),
     avec les empreintes de csp-hashes.txt et frame-ancestors limité à l'origine B ;
  3. « fr-sombre » (E3) ; 4. « pont-ehp » (E4, E5) ; 5. « hors-pont » (E5, amont inchangé sans pont) ;
  6. « pont-ehp-temoin » : le scénario 4 sur un moteur SABORDÉ (removeItem sans effet, et un
     evora:dirty glissé depuis la fenêtre du moteur avant evora:open), qui DOIT être rouge, et rouge
     par les seuls détecteurs du stockage et de doc.dirty : la preuve que le banc sait rougir ;
  7. « pont-deux-instances » (E5 entre pages) : quatre moteurs encadrés par la même page, chacun
     isolant un chemin par lequel une autre page du moteur apprend un effacement :
     a) deux onglets du même compte (e1, e2) : une purge dans e1, puis une perte de focus dans e2
        (eframe enregistrerait) ; aucune clé ne doit reparaître, alors que la clé n'existait pas encore
        (seule la diffusion de la purge peut l'empêcher) ;
     b) un onglet du même compte ouvert après (e3), puis un AUTRE compte (e4) qui démarre : son
        evora:init efface les autres espaces, et e3 ne doit pas recréer le sien à sa perte de focus
        (clé encore absente : seule la diffusion de l'evora:init peut l'empêcher) ;
     c) e4 écrit sa clé, une autre fenêtre de l'origine l'efface, et une perte de focus ne doit pas
        la recréer (seul l'événement storage peut l'empêcher) ;
  8. « pont-deux-instances-temoin » : le scénario 7 avec BroadcastChannel inerte et sans écouteur
     storage dans les documents moteur, qui DOIT être rouge par ses trois seuls détecteurs ;
  9. « pont-accuse » (COL-08, COL-09) : demande d'enregistrement (evora:request-save) et accusé
     (doc.saved-ack), scénarios S-ACK-1, 2, 4, 5 et 6 de CONCEPTION-PROTOCOLE §4.1.8 ; S-ACK-3 relevé ;
 10. « pont-accuse-temoin » : le scénario 9 sans doc.saved-ack à evora:init (comportement amont) et
     avec une réouverture sous un autre docRef, qui DOIT être rouge par ses cinq seuls détecteurs.
 11. « masquages » (COL-05, COL-10, OCR, Q47 (a)) : au rendu, sur les surfaces du démarrage (Home et
     All tools), aucun libellé masqué n'est dessiné (MASKED_PROBES), et les témoins voisins le sont
     (KEPT_PROBES : sans eux, une surface non dessinée passerait pour un masquage). La recette
     complète, surface par surface, est tests/evora_masks.rs (job « masques »).
 12. « pont-robustesse » (COL-40, EVORA-COL-39) : deux moteurs dans la même page parente, un détecteur par
     défaut corrigé du pont : mémoire d'eframe d'une séance précédente jamais lue avant evora:init
     [rob-memoire-eframe] ; evora:init refusé quand sa purge n'est pas effective [rob-init-purge] ;
     evora:open acquitté après l'ouverture réelle, octets illisibles refusés [rob-open-ack] ; document
     de la coquille jamais retrouvé par son nom, un fichier local homonyme n'est pas envoyé sous son
     docRef [rob-docref-nom]. Ses quatre détecteurs, et eux seuls, rougissent sous le témoin groupé du
     lot COL-FK-B1 (défauts réintroduits dans le moteur, puis retirés). Correction 1 du lot (EVORA-COL-42) :
     un PDF chiffré ouvert par la coquille attend sa boîte de mot de passe, et un fichier local déposé
     pendant ce temps ne prend jamais son docRef [rob-chiffre-depot] ; le mot de passe saisi, le document
     de la coquille est acquitté et le fichier déposé s'ouvre ensuite [rob-chiffre-mdp]. Le premier, et lui
     seul, rougit sous le témoin de la correction (liaison au « plus récent document » et dépôt non retenu
     réintroduits, puis retirés : ROB_FIX_EXPECTED).
 13. « pont-finitions » (COL-42, COL-43, lot COL-FK-B2) : un moteur, un détecteur par finition : catalogue de
     commandes (evora:commands) conforme et en liste blanche par construction, réémis à chaque langue
     [fin-catalogue] ; commande hors catalogue refusée [fin-liste-blanche] ; paramètres, dont un chemin, refusés
     sans effet [fin-params] ; commande destructive refusée sans confirmed, exécutée avec [fin-destructive] ;
     exports vers la coquille (evora:export, type MIME du format), aucun téléchargement [fin-export] ; F6 rend le
     clavier (evora:focus-out) [fin-focus-out] ; signatures, paraphes et certificats jamais écrits dans le stockage
     [fin-signatures]. Ses sept détecteurs, et eux seuls, rougissent sous le témoin groupé du lot (FIN_EXPECTED). Le
     premier catalogue reçu est écrit dans le fichier nommé par EVORA_COMMANDS_OUT : le commands.json de l'artefact.
     Correction 1 du lot (EVORA-COL-49 et -50, avenant du 2026-10-27 §5) : toute commande de ce catalogue dont
     l'identifiant ou le libellé porte un marqueur de retrait est destructive, sauf exception justifiée une par une
     [fin-retraits] ; les destructives ajoutées (couper des pages, retirer la signature ou les initiales
     enregistrées, réinitialiser la disposition des panneaux) sont refusées sans confirmed, sans effet
     [fin-destructive]. Ces deux détecteurs, et eux seuls, rougissent sous le témoin de la correction
     (FIN_FIX_EXPECTED).

Le témoin « pont-ehp-temoin » (scénario 6) cache aussi au moteur, depuis EVORA-COL-39, les clés qu'il croit
avoir effacées (length, key()) : sa vérification passe, il ne refuse donc pas evora:init, et le banc garde
les mêmes détecteurs rouges.

doc.dirty (scénario 4, §7.1 étapes 7 et 8) : comme la coquille, qui lit le contenu du document entre
l'accusé d'evora:init et evora:open, la page parente n'ouvre le PDF qu'après des images du moteur
(prémisse vérifiée : compteur d'images de l'audit relevé à la réception de chaque message). Le moteur
ne doit émettre aucun evora:dirty avant l'accusé d'evora:open, puis un evora:dirty {dirty: false}
portant le docRef du document ouvert.

Le scénario « pont-ehp » ajoute deux documents à la page parente : un observateur servi par
l'origine A (même stockage que le moteur, il lit le localStorage à l'arrivée de chaque accusé
d'evora:init et d'evora:purge) et une page intruse d'une TROISIÈME origine (http://localhost:<port C>,
non admise par evora-host.json) qui envoie au moteur des messages EHP bien formés.

Succès d'un scénario : le canvas #pdfcraft existe et eframe l'a dimensionné (largeur = largeur CSS ×
devicePixelRatio, différente des 300 px par défaut), son contexte WebGL2 est vivant, et ni la page
parente ni l'iframe ne remontent d'exception, d'erreur de console ou d'erreur de journal
(chargement, CSP…). Le démarrage à froid mesuré va de la navigation de l'iframe au premier
dimensionnement du canvas (performance.now() de l'iframe).

Usage : smoke.py SITE_DIR CSP_HASHES_FILE OUT_DIR REPORT_MD
Statut 1 si un scénario échoue.
"""

import base64
import fcntl
import functools
import hashlib
import http.server
import json
import os
import re
import select
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.parse

PORT_A = 8801
PORT_B = 8802
PORT_C = 8803
ENGINE_ORIGIN = f"http://127.0.0.1:{PORT_A}"
PARENT_ORIGIN = f"http://localhost:{PORT_B}"
# Troisième origine, NON admise par evora-host.json : la page intruse du scénario « pont-ehp ».
INTRUDER_ORIGIN = f"http://localhost:{PORT_C}"
# E5 : espaces de noms (storageNs, 64 hexa) du compte courant et de deux autres comptes.
NS_OWN, NS_OTHER, NS_OTHER2 = "ab" * 32, "cd" * 32, "ef" * 32
NS_PREFIX = "evora.pdfcraft."
# Clés que le moteur écrit hors espace de noms sur son origine (amont, ancien nom, mémoire d'eframe).
LOOSE_KEYS = ("pdfcraft", "printcraft", "egui_memory_ron")
# Clé qui n'appartient pas au moteur (une autre app de l'origine, en mode A) : aucune purge n'y touche.
WITNESS_KEY = "evora-witness"
# Ids ULID des messages de la page intruse (préfixe distinct de ceux de la page parente).
INTRUDER_IDS = ["01J" + "Y" * 22 + c for c in "ABC"]
ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$")
CAPABILITY_NAMES = {"doc.open", "doc.save", "doc.saved-ack", "doc.dirty", "doc.multi", "doc.request-save",
                    "export.drive", "media.need", "media.ranges", "pick.drive", "command", "storage.ns",
                    "storage.memory", "storage.purge", "live.lang", "live.theme", "font.inject", "author",
                    # Plafond de la coquille d'Evora (host-schema.js, CAPABILITIES) : extensions de §9.1.
                    "ui.focus-out", "ui.activity", "drop.files", "prefs.sync", "command.catalog"}
# Charges utiles admises du moteur vers la coquille : (champs obligatoires, champs permis), §4.4-§4.5.
PAYLOAD_KEYS = {
    "evora:ready": ({"app", "version", "ehp", "capabilities"}, {"app", "version", "ehp", "capabilities"}),
    "evora:ack": ({"ok"}, {"ok", "code", "result"}),
    "evora:dirty": ({"dirty"}, {"dirty", "docRef"}),
    "evora:save": ({"docRef", "name", "saveAs", "bytes"}, {"docRef", "name", "saveAs", "bytes"}),
    "evora:failed": ({"code"}, {"code"}),
    # COL-42 et COL-43 (lot COL-FK-B2) : export vers Drive, sortie clavier, catalogue de commandes.
    "evora:export": ({"name", "mime", "bytes"}, {"docRef", "name", "mime", "bytes"}),
    "evora:focus-out": (set(), set()),
    "evora:commands": ({"lang", "count", "hash", "commands"}, {"lang", "count", "hash", "params", "commands"}),
}
IFRAME_W, IFRAME_H = 1280, 800
# Paramètres de l'URL du moteur dans l'iframe. Avant le pont EHP natif (E4), aucun : le pont amont
# ?host=parent ne parle qu'à sa propre origine et Chrome signalerait chaque envoi refusé.
ENGINE_QUERY = os.environ.get("EVORA_SMOKE_QUERY", "")
# Scénario « masquages » (EVORA-COL-25) : libellés anglais du catalogue qui ne doivent jamais être
# dessinés au démarrage (groupes Scan & OCR et Redact a PDF de All tools ; « Remove hidden
# information » sur la carte Protect a PDF de Home), et témoins des mêmes surfaces, qui doivent l'être.
# Écrits ici, indépendamment de crates/ui-egui/src/evora.rs.
MASKED_PROBES = ["Scan & OCR", "Redact a PDF", "Remove hidden information"]
KEPT_PROBES = ["Export a PDF", "Protect a PDF", "Protect with password"]
READY_TIMEOUT = 180.0
ERROR_GRACE = 30.0
SETTLE = 4.0

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".wasm": "application/wasm",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
}


def engine_csp(hashes):
    """CSP cible des documents moteur (ARCHITECTURE §3.6), frame-ancestors = origine parente."""
    script = " ".join(["'self'", "'wasm-unsafe-eval'"] + [f"'{h}'" for h in hashes])
    return ("default-src 'self'; "
            f"script-src {script}; "
            "worker-src 'self' blob:; connect-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
            f"frame-ancestors {PARENT_ORIGIN}; object-src 'none'; base-uri 'none'")


def minimal_pdf():
    """Un PDF d'une page, xref exacte : le document que la page parente ouvre par evora:open."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
    for o in offsets:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


# Coquille minimale (page parente du scénario « pont-ehp », HOST-PROTOCOL.md) : vérifie source et
# origine, journalise tout ce qui arrive (horodaté), attend que le banc ait semé le stockage du moteur
# (window.__evoraGo) pour envoyer un evora:init de version 2 (doit rester sans réponse) puis un
# evora:init valide, ouvre un PDF par evora:open quand le banc le lui dit (window.__evoraOpen, après
# l'accusé d'init et des images du moteur : la coquille lit d'abord le contenu, §7.1 étape 7), répond
# evora:saved à un evora:save, et fait lire le stockage du moteur par l'observateur à l'arrivée de
# chaque accusé d'evora:init et d'evora:purge. Le banc envoie le reste par window.__evoraSend.
HOST_HARNESS = """
const ENGINE = "%(engine)s";
const A = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
let n = 0;
const ulid = () => { n += 1; return "01JZZZZZZZZZZZZZZZZZZZZZ" + A[(n >> 5) %% 32] + A[n %% 32]; };
const PDF = "%(pdf)s";
const now = () => performance.timeOrigin + performance.now();
const ids = window.__evoraIds = {};
const log = window.__evoraLog = [];
const obs = window.__evoraObs = {};
const frame = document.getElementById("engine");
const observer = document.getElementById("observer");
const send = (key, m, transfer) => { ids[key] = m.id; frame.contentWindow.postMessage(m, ENGINE, transfer || []); };
const plainObject = (x) => x !== null && typeof x === "object" && Object.getPrototypeOf(x) === Object.prototype;
const binaries = (p) => {
  const out = {};
  if (plainObject(p)) for (const k of Object.keys(p)) {
    const x = p[k];
    if (x !== null && typeof x === "object" && !Array.isArray(x) && !plainObject(x))
      out[k] = {kind: Object.prototype.toString.call(x), byteLength: typeof x.byteLength === "number" ? x.byteLength : null};
  }
  return out;
};
addEventListener("message", (e) => {
  const t = now();
  const d = e.data;
  if (e.source === observer.contentWindow && e.origin === ENGINE) {
    if (plainObject(d) && typeof d.probe === "string") obs[d.probe] = {t, all: d.all, engine: d.engine};
    return;
  }
  const fromEngine = e.source === frame.contentWindow && e.origin === ENGINE;
  const plain = plainObject(d);
  log.push({t, origin: e.origin, fromEngine, plain, keys: plain ? Object.keys(d) : [], v: plain ? d.v : null,
            type: plain ? d.type : null, id: plain ? d.id : null, re: plain && "re" in d ? d.re : null,
            payloadPlain: plain && plainObject(d.payload),
            payload: plain && d.payload ? JSON.parse(JSON.stringify(d.payload,
              (k, v) => v instanceof ArrayBuffer ? {byteLength: v.byteLength} : v)) : null,
            binary: plain ? binaries(d.payload) : {}});
  if (!fromEngine || !plain || d.v !== 1) return;
  if (d.type === "evora:ready" && !ids.ready) {
    ids.ready = d.id;
    window.__evoraCaps = Array.isArray(d.payload && d.payload.capabilities) ? d.payload.capabilities : [];
  } else if (d.type === "evora:ack") {
    // L'observateur (même origine, même stockage que le moteur) lit le stockage dès l'accusé reçu.
    if ([ids.init, ids.purge, ids.purgeAll].includes(d.re)) observer.contentWindow.postMessage({probe: d.re}, ENGINE);
  } else if (d.type === "evora:save" && !ids.save) {
    ids.save = d.id;
    send("saved", {v: 1, type: "evora:saved", id: ulid(), re: d.id, payload: {ok: true, version: 1}});
  }
});
window.__evoraGo = () => {
  if (!ids.ready || ids.init) return false;
  send("bogus", {v: 2, type: "evora:init", id: ulid(), re: ids.ready, payload: {}});
  send("init", {v: 1, type: "evora:init", id: ulid(), re: ids.ready, payload: {
    lang: "fr", engineLang: "fr", theme: "dark", accent: "#4F46E5", readOnly: false,
    storageNs: "%(ns)s", displayName: "Compte Evora", capabilities: window.__evoraCaps,
    prefs: {}, limits: {maxDocumentBytes: 1048576, maxExportBytes: 1048576}}});
  return true;
};
window.__evoraOpen = () => {
  const initOk = log.some((m) => m.fromEngine && m.type === "evora:ack" && m.re === ids.init && m.payload && m.payload.ok === true);
  if (!ids.init || ids.open || !initOk) return false;
  const bytes = Uint8Array.from(atob(PDF), (c) => c.charCodeAt(0)).buffer;
  ids.docRef = ulid();
  send("open", {v: 1, type: "evora:open", id: ulid(), payload: {docRef: ids.docRef, name: "evora-smoke.pdf", bytes}}, [bytes]);
  return true;
};
window.__evoraSend = (key, type, payload) => { send(key, {v: 1, type, id: ulid(), payload}); return ids[key]; };
"""

# Observateur servi par l'origine du moteur (même stockage partitionné que le moteur : même origine,
# même page de premier niveau) : à chaque sonde de la page parente, il lit le localStorage aussitôt.
OBSERVER_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Evora smoke : observateur</title>
<script src="__evora-observer.js"></script></head><body></body></html>
"""
OBSERVER_JS = """"use strict";
const PARENT = "%(parent)s";
const PREFIX = "%(prefix)s";
const LOOSE = %(loose)s;
addEventListener("message", (e) => {
  if (e.origin !== PARENT || e.source !== window.parent) return;
  const d = e.data;
  if (d === null || typeof d !== "object" || typeof d.probe !== "string") return;
  // Scénario « pont-deux-instances » : une autre fenêtre de l'origine efface une clé du moteur.
  if (typeof d.remove === "string") localStorage.removeItem(d.remove);
  const all = Object.keys(localStorage).sort();
  window.parent.postMessage({probe: d.probe, all, engine: all.filter((k) => k.startsWith(PREFIX) || LOOSE.includes(k))}, PARENT);
});
"""

# Page intruse, d'une origine NON admise par evora-host.json (et d'une autre fenêtre que la parente) :
# elle envoie au moteur des messages EHP bien formés, dont un evora:purge {scope: "all"} ; le moteur
# ne doit ni répondre ni agir. Le témoin : les mêmes messages venus de la page parente admise ont un accusé.
INTRUDER_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Evora smoke : origine non admise</title></head><body>
<script>
const IDS = %(ids)s;
const MESSAGES = [["evora:purge", {scope: "all"}], ["evora:lang", {lang: "ja", engineLang: "ja"}],
                  ["evora:theme", {theme: "light", accent: "#4F46E5"}]];
window.__evoraIntrude = () => {
  const engine = window.parent.frames[0];
  MESSAGES.forEach(([type, payload], i) => engine.postMessage({v: 1, type, id: IDS[i], payload}, "*"));
  return JSON.stringify(IDS);
};
// S-ACK-5 : un evora:saved {ok: true} forgé pour un evora:save réel du moteur (re connu).
window.__evoraForge = (re, id) => {
  window.parent.frames[0].postMessage({v: 1, type: "evora:saved", id, re, payload: {ok: true, version: 9}}, "*");
  return id;
};
</script>
</body></html>
"""


def intruder_page():
    return (INTRUDER_PAGE % {"ids": json.dumps(INTRUDER_IDS)}).encode()


def parent_page(query, host=False, harness=None):
    harness = (harness or HOST_HARNESS) % {"engine": ENGINE_ORIGIN, "pdf": base64.b64encode(minimal_pdf()).decode(),
                                           "ns": NS_OWN} if host else ""
    # Ordre des cadres : le moteur d'abord (window.frames[0] pour la page intruse).
    extra = (f'<iframe id="observer" src="{ENGINE_ORIGIN}/__evora-observer.html" width="10" height="10" style="border:0"></iframe>\n'
             f'<iframe id="intruder" src="{INTRUDER_ORIGIN}/" width="10" height="10" style="border:0"></iframe>\n') if host else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><link rel="icon" href="data:,"><title>Evora smoke</title></head>
<body style="margin:0;background:#fff">
<iframe id="engine" src="{ENGINE_ORIGIN}/index.html{query}" width="{IFRAME_W}" height="{IFRAME_H}"
 style="border:0;display:block" sandbox="allow-scripts allow-same-origin"></iframe>
{extra}<script>
window.__evoraMessages = [];
addEventListener("message", (e) => {{
  const d = e.data;
  window.__evoraMessages.push({{origin: e.origin, type: (d && typeof d === "object" && typeof d.type === "string") ? d.type : null}});
}});
{harness}
</script>
</body></html>
""".encode()


# Scénario « pont-deux-instances » : quatre moteurs (e1 à e4 ; window.name evora-<id>) et
# l'observateur dans la même page parente. Le banc dit quand envoyer evora:init (__evoraInit) et
# evora:purge (__evoraSendTo) à chacun, et fait lire, ou effacer puis lire, le localStorage de
# l'origine moteur par l'observateur (__evoraProbe). Tout message d'une autre source est consigné.
INSTANCES = ("e1", "e2", "e3", "e4")
# Deux colonnes de moteurs de 640 × 400 px : tous dans la vue de la page parente (1320 × 840 px).
INSTANCE_W, INSTANCE_H = 640, 400
MULTI_HARNESS = """
const ENGINE = "%(engine)s";
const A = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
let n = 0;
const ulid = () => { n += 1; return "01JZZZZZZZZZZZZZZZZZZZZZ" + A[(n >> 5) %% 32] + A[n %% 32]; };
const plainObject = (x) => x !== null && typeof x === "object" && Object.getPrototypeOf(x) === Object.prototype;
const frames = {};
for (const id of %(ids)s) frames[id] = document.getElementById(id);
const observer = document.getElementById("observer");
const st = window.__evoraMulti = {ready: {}, caps: {}, log: [], acks: {}, obs: {}, stray: []};
addEventListener("message", (e) => {
  const d = e.data;
  if (e.source === observer.contentWindow && e.origin === ENGINE) {
    if (plainObject(d) && typeof d.probe === "string") st.obs[d.probe] = {all: d.all, engine: d.engine};
    return;
  }
  const from = Object.keys(frames).find((k) => frames[k].contentWindow === e.source) || null;
  if (from === null || e.origin !== ENGINE || !plainObject(d) || d.v !== 1) {
    st.stray.push({origin: e.origin, from, type: plainObject(d) ? d.type : null});
    return;
  }
  st.log.push({from, type: d.type, id: d.id, re: "re" in d ? d.re : null,
               payload: plainObject(d.payload) ? JSON.parse(JSON.stringify(d.payload)) : null});
  if (d.type === "evora:ready" && !st.ready[from]) {
    st.ready[from] = d.id;
    st.caps[from] = Array.isArray(d.payload && d.payload.capabilities) ? d.payload.capabilities : [];
  } else if (d.type === "evora:ack" && typeof d.re === "string") {
    st.acks[d.re] = {from, ok: plainObject(d.payload) && d.payload.ok === true, payload: d.payload};
  }
});
window.__evoraInit = (to, ns) => {
  if (!st.ready[to]) return null;
  const id = ulid();
  frames[to].contentWindow.postMessage({v: 1, type: "evora:init", id, re: st.ready[to], payload: {
    lang: "fr", engineLang: "fr", theme: "dark", accent: "#4F46E5", readOnly: false, storageNs: ns,
    displayName: "Compte Evora", capabilities: st.caps[to], prefs: {},
    limits: {maxDocumentBytes: 1048576, maxExportBytes: 1048576}}}, ENGINE);
  return id;
};
window.__evoraSendTo = (to, type, payload) => {
  const id = ulid();
  frames[to].contentWindow.postMessage({v: 1, type, id, payload}, ENGINE);
  return id;
};
window.__evoraProbe = (remove) => {
  const id = ulid();
  observer.contentWindow.postMessage(typeof remove === "string" ? {probe: id, remove} : {probe: id}, ENGINE);
  return id;
};
"""


def parent_page_multi(query):
    """Page parente du scénario « pont-deux-instances » : quatre moteurs en grille, tous visibles
    (une iframe d'une autre origine hors de la vue verrait ses images ralenties), et l'observateur."""
    harness = MULTI_HARNESS % {"engine": ENGINE_ORIGIN, "ids": json.dumps(list(INSTANCES))}
    engines = "".join(
        f'<iframe id="{i}" name="evora-{i}" src="{ENGINE_ORIGIN}/index.html{query}" width="{INSTANCE_W}" '
        f'height="{INSTANCE_H}"\n style="border:0;display:block" sandbox="allow-scripts allow-same-origin"></iframe>\n'
        for i in INSTANCES)
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><link rel="icon" href="data:,"><title>Evora smoke : deux instances</title></head>
<body style="margin:0;background:#fff">
<div style="display:grid;grid-template-columns:repeat(2,{INSTANCE_W}px);gap:0">
{engines}</div>
<iframe id="observer" src="{ENGINE_ORIGIN}/__evora-observer.html" width="10" height="10" style="border:0;display:block"></iframe>
<script>
window.__evoraMessages = [];
addEventListener("message", (e) => {{
  const d = e.data;
  window.__evoraMessages.push({{origin: e.origin, type: (d && typeof d === "object" && typeof d.type === "string") ? d.type : null}});
}});
{harness}
</script>
</body></html>
""".encode()


class Handler(http.server.SimpleHTTPRequestHandler):
    csp = None
    page = None
    served = None
    host_config = None

    def log_message(self, fmt, *args):  # journal sobre, consigné par le test
        if self.served is not None:
            self.served.append(f"{self.server.server_address[1]} {self.command} {self.path} -> {args[1] if len(args) > 1 else '?'}")

    def guess_type(self, path):
        return MIME.get(os.path.splitext(path)[1], "application/octet-stream")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.csp:
            self.send_header("Content-Security-Policy", self.csp)
        super().end_headers()

    def send_body(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if self.host_config is not None and path == "/evora-host.json":
            # Ce qu'écrit le provisionnement d'Evora à côté d'index.html (HOST-PROTOCOL §2.3).
            self.send_body(json.dumps(self.host_config).encode(), "application/json")
            return
        if self.host_config is not None and path == "/__evora-observer.html":
            # Observateur du banc (hors artefact), servi sous la même CSP que le moteur.
            self.send_body(OBSERVER_HTML.encode(), MIME[".html"])
            return
        if self.host_config is not None and path == "/__evora-observer.js":
            body = OBSERVER_JS % {"parent": PARENT_ORIGIN, "prefix": NS_PREFIX, "loose": json.dumps(list(LOOSE_KEYS))}
            self.send_body(body.encode(), MIME[".js"])
            return
        if self.page is not None:
            if self.path.split("?")[0] in ("/", "/index.html"):
                body = self.page
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)
            return
        super().do_GET()


class V6Server(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6


def start_server(port, host, directory=None, csp=None, page=None, served=None, host_config=None):
    handler = type("H", (Handler,), {"csp": csp, "page": page, "served": served, "host_config": host_config})
    if directory is not None:
        handler = functools.partial(handler, directory=directory)
    server_class = V6Server if ":" in host else http.server.ThreadingHTTPServer
    httpd = server_class((host, port), handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


class Chrome:
    """Chrome sans interface piloté par --remote-debugging-pipe (descripteurs 3 et 4)."""

    def __init__(self, binary, profile, log_path):
        cmd_r, self.cmd_w = os.pipe()
        self.res_r, res_w = os.pipe()
        # Descripteurs du fils déplacés au-delà de 4, pour que les dup2 vers 3 et 4 ne s'écrasent pas.
        hi_r = fcntl.fcntl(cmd_r, fcntl.F_DUPFD_CLOEXEC, 20)
        hi_w = fcntl.fcntl(res_w, fcntl.F_DUPFD_CLOEXEC, 20)
        os.close(cmd_r)
        os.close(res_w)
        self.log = open(log_path, "wb")
        args = [
            binary, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
            "--disable-background-networking", "--disable-component-update", "--disable-default-apps",
            "--mute-audio", "--no-sandbox", "--ignore-gpu-blocklist", "--enable-webgl",
            "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--window-size=1400,1000",
            "about:blank",
        ]
        actions = [
            (os.POSIX_SPAWN_OPEN, 0, "/dev/null", os.O_RDONLY, 0),
            (os.POSIX_SPAWN_DUP2, self.log.fileno(), 1),
            (os.POSIX_SPAWN_DUP2, self.log.fileno(), 2),
            (os.POSIX_SPAWN_DUP2, hi_r, 3),
            (os.POSIX_SPAWN_DUP2, hi_w, 4),
        ]
        self.pid = os.posix_spawn(binary, args, os.environ, file_actions=actions)
        os.close(hi_r)
        os.close(hi_w)
        self.buf = b""
        self.next_id = 0
        self.responses = {}
        self.events = []
        self.handlers = []

    def send(self, method, params=None, session=None):
        self.next_id += 1
        msg = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        os.write(self.cmd_w, json.dumps(msg).encode() + b"\0")
        return self.next_id

    def pump(self, timeout):
        r, _, _ = select.select([self.res_r], [], [], timeout)
        if not r:
            return
        chunk = os.read(self.res_r, 1 << 20)
        if not chunk:
            raise RuntimeError("Chrome a fermé le tuyau DevTools")
        self.buf += chunk
        while b"\0" in self.buf:
            raw, self.buf = self.buf.split(b"\0", 1)
            msg = json.loads(raw)
            if "id" in msg:
                self.responses[msg["id"]] = msg
            else:
                self.events.append(msg)
                for h in self.handlers:
                    h(msg)

    def call(self, method, params=None, session=None, timeout=30.0):
        i = self.send(method, params, session)
        end = time.monotonic() + timeout
        while i not in self.responses:
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"{method} sans réponse")
            self.pump(min(left, 0.25))
        msg = self.responses.pop(i)
        if "error" in msg:
            raise RuntimeError(f"{method} : {msg['error']}")
        return msg.get("result", {})

    def close(self):
        try:
            self.send("Browser.close")
            end = time.monotonic() + 10
            while time.monotonic() < end:
                pid, _ = os.waitpid(self.pid, os.WNOHANG)
                if pid:
                    break
                time.sleep(0.1)
            else:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, 0)
        except OSError:
            pass
        self.log.close()


def describe_remote(obj):
    if not isinstance(obj, dict):
        return str(obj)
    return str(obj.get("value", obj.get("description", obj.get("unserializableValue", obj.get("type", "")))))


# Évalué dans le document moteur dès la création de son contexte JavaScript : horodate, en
# performance.now() du document, la fin du chargeur Trunk (wasm instancié, main lancé) et le premier
# dimensionnement du canvas par eframe. Le relevé ne dépend donc pas de la latence du sondage.
TIMING = """(() => {
  if (window.__evoraT) return;
  const T = window.__evoraT = {};
  const mark = (k) => { if (!(k in T)) T[k] = performance.now(); };
  const watch = (c) => new MutationObserver(() => { if (c.width !== 300) mark('canvasSized'); })
    .observe(c, {attributes: true, attributeFilter: ['width']});
  const find = () => { const c = document.getElementById('pdfcraft'); if (c) { watch(c); return true; } return false; };
  if (!find()) new MutationObserver((_, o) => { if (find()) o.disconnect(); })
    .observe(document, {childList: true, subtree: true});
  addEventListener('TrunkApplicationStarted', () => mark('trunkStarted'));
})()"""

PROBE = """(() => {
  const c = document.getElementById('pdfcraft');
  if (!c) return JSON.stringify({canvas: false, t: performance.now()});
  const dpr = window.devicePixelRatio || 1;
  return JSON.stringify({canvas: true, w: c.width, h: c.height, cw: c.clientWidth, ch: c.clientHeight,
                         dpr, t: performance.now(), marks: window.__evoraT || {}});
})()"""

GL_PROBE = """(() => {
  const c = document.getElementById('pdfcraft');
  if (!c) return 'no-canvas';
  const gl = c.getContext('webgl2');
  return gl ? (gl.isContextLost() ? 'lost' : 'webgl2') : 'other';
})()"""

RESOURCES = """JSON.stringify(performance.getEntriesByType('resource').map(e => ({
  name: e.name.split('/').pop(), dur: Math.round(e.duration), size: e.transferSize || e.encodedBodySize || 0})))"""


def run_scenario(name, site, csp, out_dir, chrome_bin, query=ENGINE_QUERY, expect=None):
    served = []
    expect = expect or {}
    host = bool(expect.get("ehp"))
    multi = bool(expect.get("instances"))
    robust = bool(expect.get("robustesse"))
    fin = bool(expect.get("finitions"))
    no_listeners = "no-listeners" in expect.get("sabotage", "").split()
    engine = start_server(PORT_A, "127.0.0.1", directory=site, csp=csp, served=served,
                          host_config={"parentOrigins": [PARENT_ORIGIN]} if host else None)
    body = parent_page_multi(query) if multi else parent_page_rob(query) if robust else parent_page_fin(query) if fin \
        else parent_page(query, host, ACK_HARNESS if expect.get("accuse") else None)
    parent = start_server(PORT_B, "127.0.0.1", page=body, served=served)
    # « localhost » peut se résoudre en ::1 : la page parente écoute aussi en IPv6 quand c'est possible.
    try:
        parent6 = start_server(PORT_B, "::1", page=body, served=served)
    except OSError:
        parent6 = None
    intruders = []
    if host:
        intruders.append(start_server(PORT_C, "127.0.0.1", page=intruder_page(), served=served))
        try:
            intruders.append(start_server(PORT_C, "::1", page=intruder_page(), served=served))
        except OSError:
            pass
    profile = tempfile.mkdtemp(prefix=f"evora-smoke-{name}-")
    chrome = Chrome(chrome_bin, profile, os.path.join(out_dir, f"chrome-{name}.log"))
    errors = []
    contexts = {}  # (session, contextId) -> origin
    sessions = {}  # sessionId -> type

    def on_event(msg):
        method, params, sess = msg.get("method"), msg.get("params", {}), msg.get("sessionId")
        where = sessions.get(sess, "navigateur")
        if method == "Target.attachedToTarget":
            child = params["sessionId"]
            sessions[child] = params.get("targetInfo", {}).get("type", "?") + " " + params.get("targetInfo", {}).get("url", "")
            for m in ("Runtime.enable", "Log.enable"):
                chrome.send(m, {}, child)
            chrome.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, child)
            chrome.send("Runtime.runIfWaitingForDebugger", {}, child)
        elif method == "Runtime.executionContextCreated":
            ctx = params["context"]
            if ctx.get("auxData", {}).get("isDefault"):
                contexts[(sess, ctx["id"])] = ctx.get("origin", "")
                if ctx.get("origin") == ENGINE_ORIGIN:
                    # Le contexte naît au premier script du document, bien avant la fin du chargement
                    # du .wasm : l'horodatage (et le sabordage du témoin « no-listeners ») est posé à temps.
                    if no_listeners:
                        chrome.send("Runtime.evaluate", {"expression": NO_LISTENERS, "contextId": ctx["id"]}, sess)
                    if robust:
                        # COL-40 : mémoire d'eframe semée et lectures journalisées avant le .wasm.
                        chrome.send("Runtime.evaluate", {"expression": ROB_EARLY, "contextId": ctx["id"]}, sess)
                    if fin:
                        # COL-42 : tout lien de téléchargement cliqué par le moteur relevé (et retenu) avant le .wasm.
                        chrome.send("Runtime.evaluate", {"expression": FIN_EARLY, "contextId": ctx["id"]}, sess)
                    chrome.send("Runtime.evaluate", {"expression": TIMING, "contextId": ctx["id"]}, sess)
        elif method == "Runtime.executionContextDestroyed":
            contexts.pop((sess, params.get("executionContextId")), None)
        elif method == "Runtime.executionContextsCleared":
            for k in [k for k in contexts if k[0] == sess]:
                contexts.pop(k, None)
        elif method == "Runtime.exceptionThrown":
            d = params.get("exceptionDetails", {})
            errors.append(f"[{where}] exception : {d.get('text', '')} {describe_remote(d.get('exception', {}))} "
                          f"({d.get('url', '')}:{d.get('lineNumber', '')})")
        elif method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "assert"):
            text = " ".join(describe_remote(a) for a in params.get("args", []))
            errors.append(f"[{where}] console.{params.get('type')} : {text}")
        elif method == "Log.entryAdded":
            e = params.get("entry", {})
            if e.get("level") == "error":
                errors.append(f"[{where}] journal ({e.get('source', '')}) : {e.get('text', '')} {e.get('url', '')}")

    chrome.handlers.append(on_event)
    result = {"scenario": name, "csp": bool(csp), "query": query, "ok": False}
    try:
        version = chrome.call("Browser.getVersion")
        result["chrome"] = version.get("product", "?")
        target = chrome.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        page = chrome.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        sessions[page] = "page parente"
        for m in ("Page.enable", "Runtime.enable", "Log.enable"):
            chrome.call(m, {}, page)
        chrome.call("Emulation.setDeviceMetricsOverride",
                    {"width": IFRAME_W + 40, "height": IFRAME_H + 40, "deviceScaleFactor": 1, "mobile": False}, page)
        chrome.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, page)
        if host:
            # Le banc donne le focus au canvas du moteur (Ctrl+S, enregistrement des réglages) : la page
            # se comporte comme une fenêtre au premier plan, même sans interface.
            try:
                chrome.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, page)
            except (RuntimeError, TimeoutError) as exc:
                result["focus_emulation"] = f"indisponible : {exc}"

        def wait_ready(t0, stale=()):
            """Attend un contexte moteur (hors `stale`) dont eframe a dimensionné le canvas."""
            probe = None
            while time.monotonic() - t0 < READY_TIMEOUT:
                chrome.pump(0.1)
                if errors and time.monotonic() - t0 > ERROR_GRACE:
                    break  # erreurs déjà relevées : inutile d'attendre la fin du délai
                # Plusieurs documents de l'origine moteur (le moteur, et l'observateur du scénario
                # « pont-ehp ») : seul celui qui porte le canvas compte.
                engine_ctx = [k for k, o in contexts.items() if o == ENGINE_ORIGIN and k not in stale]
                for sess, ctx in reversed(engine_ctx):
                    try:
                        r = chrome.call("Runtime.evaluate", {"expression": PROBE, "contextId": ctx, "returnByValue": True}, sess, 10)
                    except (RuntimeError, TimeoutError):
                        continue
                    found = json.loads(r.get("result", {}).get("value", "{}") or "{}")
                    if not found.get("canvas"):
                        continue
                    probe = found
                    if probe.get("cw", 0) > 0 and probe.get("w") != 300 \
                            and abs(probe["w"] - round(probe["cw"] * probe.get("dpr", 1))) <= 1:
                        marks = probe.get("marks", {})
                        result["trunk_started_ms"] = round(marks["trunkStarted"]) if "trunkStarted" in marks else None
                        return (time.monotonic() - t0, marks.get("canvasSized", probe["t"]), sess, ctx), probe
            return None, probe

        t0 = time.monotonic()
        chrome.call("Page.navigate", {"url": f"{PARENT_ORIGIN}/"}, page)
        ready, probe = wait_ready(t0)
        if ready is not None and expect.get("upstream_storage"):
            # E5, hors pont (sans ?host=evora) : comportement amont inchangé. Les réglages laissés sous
            # les clés de l'amont ne sont pas purgés au démarrage : seuls evora:init et evora:purge,
            # sous le pont, effacent quelque chose.
            _, _, sess0, ctx0 = ready
            seed = ("localStorage.setItem('pdfcraft', JSON.stringify({language: 'en', reload_changed_files: false}));"
                    "localStorage.setItem('printcraft', '{}'); 'ok'")
            chrome.call("Runtime.evaluate", {"expression": seed, "contextId": ctx0, "returnByValue": True}, sess0)
            stale = set(k for k, o in contexts.items() if o == ENGINE_ORIGIN)
            chrome.send("Runtime.evaluate", {"expression": "location.reload()", "contextId": ctx0}, sess0)
            ready, probe = wait_ready(time.monotonic(), stale)
            if ready is not None:
                _, _, sess1, ctx1 = ready
                keys = chrome.call("Runtime.evaluate", {"expression": "JSON.stringify(Object.keys(localStorage))",
                                                        "contextId": ctx1, "returnByValue": True}, sess1)
                result["storage_keys"] = json.loads(keys.get("result", {}).get("value", "[]"))
                missing = [k for k in ("pdfcraft", "printcraft") if k not in result["storage_keys"]]
                if missing:
                    errors.append(f"[hors-pont] clés de l'amont effacées au démarrage sans pont (amont modifié) : {missing}")
        result["probe"] = probe
        if ready is None:
            errors.append(f"[test] canvas non dimensionné par eframe après {time.monotonic() - t0:.0f} s "
                          f"(dernier relevé : {probe})")
        else:
            wall, inner, sess, ctx = ready
            result["cold_start_ms_iframe"] = round(inner)
            result["cold_start_ms_parent"] = round(wall * 1000)
            settle_end = time.monotonic() + SETTLE
            while time.monotonic() < settle_end:
                chrome.pump(0.1)
            if multi:
                run_instances(chrome, page, contexts, result, errors)
            elif robust:
                run_robustesse(chrome, page, contexts, result, errors)
            elif fin:
                run_finitions(chrome, page, contexts, result, errors)
            elif expect.get("accuse"):
                run_accuse(chrome, page, (sess, ctx), contexts, result, errors, expect.get("sabotage", ""))
            elif host:
                run_ehp(chrome, page, (sess, ctx), contexts, result, errors, expect.get("sabotage", ""))
            gl = chrome.call("Runtime.evaluate", {"expression": GL_PROBE, "contextId": ctx, "returnByValue": True}, sess)
            result["gl"] = gl.get("result", {}).get("value")
            if result["gl"] != "webgl2":
                errors.append(f"[test] contexte du canvas : {result['gl']} (attendu : webgl2)")
            if "evora-audit=1" in query:
                # E9 et E10 vérifiés au rendu : le moteur audite chaque texte dessiné (window.__evoraAudit).
                audit = chrome.call("Runtime.evaluate", {"expression": "JSON.stringify(window.__evoraAudit || null)",
                                                         "contextId": ctx, "returnByValue": True}, sess)
                a = json.loads(audit.get("result", {}).get("value", "null") or "null")
                result["audit"] = a
                if not a or not a.get("frames") or not a.get("texts") or a.get("selftest") is not True:
                    errors.append(f"[test] audit au rendu absent, sans image, sans texte ou détecteur muet : {a}")
                elif a.get("emoji") or a.get("terms"):
                    errors.append(f"[test] audit au rendu : {a.get('emoji')} émoji(s) (E10) et {a.get('terms')} terme(s) "
                                  f"sensible(s) (E9) dessinés, ex. « {a.get('sample', '')} »")
                if a and "dark" in expect and a.get("dark") is not expect["dark"]:
                    errors.append(f"[test] thème au rendu : sombre={a.get('dark')} (attendu : {expect['dark']})")
                if a and expect.get("probe") and not a.get("probe"):
                    errors.append(f"[test] texte attendu au rendu absent (sonde {expect['probe']!r}) : langue non appliquée ?")
                if a and expect.get("masks"):
                    # COL-05, COL-10, OCR, Q47 (a) au rendu : un compte par sonde (?evora-probe=a|b|c).
                    probes = a.get("probes")
                    if not isinstance(probes, dict) or sorted(probes) != sorted(MASKED_PROBES + KEPT_PROBES):
                        errors.append(f"[masquage-instrument] sondes non relevées une à une par l'audit : {probes!r}")
                    else:
                        missing = [p for p in KEPT_PROBES if not probes.get(p)]
                        drawn = {p: probes[p] for p in MASKED_PROBES if probes.get(p)}
                        result["masks"] = {"masques": {p: probes[p] for p in MASKED_PROBES},
                                           "temoins": {p: probes[p] for p in KEPT_PROBES}}
                        if missing:
                            errors.append(f"[masquage-temoin] surfaces du démarrage non dessinées (témoins à 0) : {missing}")
                        if drawn:
                            errors.append(f"[masquage] libellés masqués dessinés au rendu (fois) : {drawn}")
            res = chrome.call("Runtime.evaluate", {"expression": RESOURCES, "contextId": ctx, "returnByValue": True}, sess)
            result["resources"] = json.loads(res.get("result", {}).get("value", "[]"))
            msgs = chrome.call("Runtime.evaluate", {"expression": "JSON.stringify(window.__evoraMessages || [])",
                                                    "returnByValue": True}, page)
            result["parent_messages"] = json.loads(msgs.get("result", {}).get("value", "[]"))
            shot = chrome.call("Page.captureScreenshot", {"format": "png"}, page)
            with open(os.path.join(out_dir, f"smoke-{name}.png"), "wb") as fh:
                fh.write(base64.b64decode(shot["data"]))
        result["ok"] = ready is not None and not errors
    except Exception as exc:  # noqa: BLE001 — tout incident du banc est un échec visible
        errors.append(f"[test] incident : {exc!r}")
    finally:
        chrome.close()
        for srv in (engine, parent, parent6, *intruders):
            if srv is not None:
                srv.shutdown()
                srv.server_close()
        shutil.rmtree(profile, ignore_errors=True)
    result["errors"] = errors
    result["requests"] = served
    result["ok"] = result["ok"] and not errors
    return result


LOG_EXPR = "JSON.stringify({log: window.__evoraLog || [], ids: window.__evoraIds || {}, obs: window.__evoraObs || {}})"

# Instrument posé par le banc dans le document moteur, avant evora:init : journal des écritures du
# stockage (sans horloge ; les messages reçus par le moteur y servent de bornes, avec le compteur
# d'images de l'audit à leur réception) et, pour le témoin sabordé seulement, un removeItem sans effet.
STORE_HOOK = """(() => {
  if (window.__evoraStoreLog) return "déjà posé";
  const S = Storage.prototype;
  const orig = {set: S.setItem, remove: S.removeItem, clear: S.clear};
  const log = window.__evoraStoreLog = [];
  const sabotage = "%(sabotage)s";
  const noRemove = sabotage.split(" ").includes("no-remove");
  window.__evoraBench = false;
  const entry = (op, key, extra) => log.push(Object.assign({op, key, bench: window.__evoraBench === true}, extra || {}));
  // Témoin « no-remove » : le moteur croit effacer, rien ne l'est. removeItem et clear sont sans effet, et
  // les clés qu'il a « effacées » sont cachées à son énumération (length, key()) : sa propre vérification
  // passe (sans quoi, depuis EVORA-COL-39, il refuserait evora:init). Seuls l'observateur (autre document)
  // et l'instantané du banc (Object.keys) voient la vérité.
  const gone = new Set();
  S.setItem = function (k, v) { entry("set", String(k)); gone.delete(String(k)); return orig.set.call(this, k, v); };
  S.removeItem = function (k) { entry("remove", String(k)); if (noRemove) { gone.add(String(k)); return undefined; } return orig.remove.call(this, k); };
  S.clear = function () { entry("clear", null); if (noRemove) { Object.keys(this).forEach((k) => gone.add(k)); return undefined; } return orig.clear.call(this); };
  if (noRemove) {
    const visible = (store) => Object.keys(store).filter((k) => !gone.has(k));
    Object.defineProperty(S, "length", {configurable: true, get() { return visible(this).length; }});
    S.key = function (i) { const v = visible(this); return i >= 0 && i < v.length ? v[i] : null; };
  }
  addEventListener("message", (e) => {
    const d = e.data;
    const a = window.__evoraAudit;
    entry("msg", e.origin + " " + (d !== null && typeof d === "object" ? String(d.type) : "?"),
          {frames: a && typeof a.frames === "number" ? a.frames : null});
  }, true);
  return sabotage ? "posé, sabordage " + sabotage : "posé";
})()"""

SEED = """((seeds) => {
  window.__evoraBench = true;
  try { for (const [k, v] of seeds) localStorage.setItem(k, v); } finally { window.__evoraBench = false; }
  return Object.keys(localStorage).sort();
})(%s)"""

SNAPSHOT = """(async () => {
  const keys = Object.keys(localStorage).sort();
  const values = {};
  for (const k of keys) values[k] = localStorage.getItem(k);
  const out = {keys, values, log: window.__evoraStoreLog || null};
  try {
    const root = await navigator.storage.getDirectory();
    const names = [];
    for await (const name of root.keys()) names.push(name);
    out.opfs = names;
  } catch (e) { out.opfs = "indisponible : " + e.name; }
  try { out.idb = (await indexedDB.databases()).map((d) => d.name); } catch (e) { out.idb = "indisponible : " + e.name; }
  try { out.cache = await caches.keys(); } catch (e) { out.cache = "indisponible : " + e.name; }
  return JSON.stringify(out);
})()"""

# Témoin sabordé « early-dirty » : un evora:dirty venu de la fenêtre du moteur avant evora:open (le
# défaut relevé au labo : état modifié annoncé alors qu'aucun document n'est ouvert).
WITNESS_DIRTY_ID = "01J" + "W" * 23
EARLY_DIRTY = ("(() => { window.parent.postMessage({v: 1, type: 'evora:dirty', id: '%s', payload: {dirty: false}}, '%s');"
               " return 'envoyé'; })()") % (WITNESS_DIRTY_ID, PARENT_ORIGIN)
ENGINE_MSGS = "JSON.stringify((window.__evoraStoreLog || []).filter((op) => op.op === 'msg'))"

# Focus réel du canvas (évalué comme un geste de l'utilisateur), puis l'événement que suit eframe.
FOCUS = """(() => { const c = document.getElementById("pdfcraft"); c.focus();
  c.dispatchEvent(new FocusEvent("focus")); return document.activeElement === c; })()"""
# Perte de focus : eframe enregistre alors l'état de l'app (App::save).
BLUR = """(() => { const c = document.getElementById("pdfcraft"); c.blur();
  c.dispatchEvent(new FocusEvent("blur")); return document.activeElement !== c; })()"""
KEY = """(() => { const c = document.getElementById("pdfcraft");
  c.dispatchEvent(new KeyboardEvent("%(type)s", {key: "s", code: "KeyS", ctrlKey: %(ctrl)s, bubbles: true, cancelable: true}));
  return document.activeElement === c; })()"""


def engine_keys(keys):
    """Clés du moteur parmi `keys` : espaces de noms et clés hors espace."""
    return sorted(k for k in keys if k.startswith(NS_PREFIX) or k in LOOSE_KEYS)


def leftovers(keys, doomed):
    return [k for k in doomed if k in keys]


def writes_after(log, message):
    """Écritures du moteur (hors banc) journalisées après la réception de `message` (« origine type »)."""
    seen, out = False, []
    for op in log:
        if op.get("op") == "msg" and op.get("key") == message:
            seen = True
        elif seen and op.get("op") in ("set", "clear") and not op.get("bench"):
            out.append(op.get("key"))
    return out


def frames_between(msgs, first, then):
    """Images du moteur achevées entre la réception du dernier `first` précédant le premier `then` et
    celle de ce `then` (« origine type ») ; `None` si l'instrument n'a pas relevé les deux bornes."""
    start = end = None
    for op in msgs:
        if op.get("key") == then:
            end = op.get("frames")
            break
        if op.get("key") == first:
            start = op.get("frames")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    return end - start


def dirty_problems(log, ids):
    """doc.dirty (§7.1 étape 8, §4.4) : aucun evora:dirty avant que la coquille ait ouvert un document
    (accusé d'evora:open) ; après cet accusé, un premier evora:dirty {dirty: false} pour ce document ;
    chacun porte le docRef du document ouvert (un seul document, sans doc.multi)."""
    engine = [m for m in log if m.get("fromEngine")]
    opened = next((i for i, m in enumerate(engine)
                   if ids.get("open") and m.get("type") == "evora:ack" and m.get("re") == ids["open"]), None)
    if opened is None:
        return ["accusé d'evora:open absent : contrôle de doc.dirty impossible"]
    dirty = [(i, m.get("payload") or {}) for i, m in enumerate(engine) if m.get("type") == "evora:dirty"]
    problems = []
    early = [p for i, p in dirty if i < opened]
    if early:
        problems.append(f"{len(early)} evora:dirty avant l'ouverture d'un document (avant l'accusé d'evora:open) : {early}")
    late = [p for i, p in dirty if i > opened]
    expected = {"dirty": False, "docRef": ids.get("docRef")}
    if not late:
        problems.append(f"aucun evora:dirty après l'accusé d'evora:open (attendu : {expected})")
    elif late[0] != expected:
        problems.append(f"premier evora:dirty après l'ouverture : {late[0]} (attendu : {expected})")
    stray = [p for p in late if p.get("docRef") != ids.get("docRef")]
    if stray:
        problems.append(f"evora:dirty sans le docRef du document ouvert : {stray}")
    return problems


def detector_selftest():
    """Les détecteurs signalent des cas connus et se taisent sur des cas sains : un détecteur muet ne
    peut pas passer pour un vert."""
    purge = PARENT_ORIGIN + " evora:purge"
    late = [{"op": "msg", "key": purge}, {"op": "remove", "key": "k"}, {"op": "set", "key": "k", "bench": False}]
    benign = [{"op": "set", "key": "k", "bench": False}, {"op": "msg", "key": purge},
              {"op": "msg", "key": INTRUDER_ORIGIN + " evora:purge"}, {"op": "set", "key": "w", "bench": True}]
    own = NS_PREFIX + NS_OWN
    # doc.dirty : le défaut du labo (état annoncé avant l'ouverture, rien après), le silence après
    # l'ouverture, un docRef absent ; et une séance saine, que le détecteur laisse passer.
    ids = {"init": "I", "open": "O", "docRef": "D"}

    def ack(re_id):
        return {"fromEngine": True, "type": "evora:ack", "re": re_id, "payload": {"ok": True}}

    def dirty(payload):
        return {"fromEngine": True, "type": "evora:dirty", "payload": payload}

    good = [ack("I"), ack("O"), dirty({"dirty": False, "docRef": "D"}), dirty({"dirty": True, "docRef": "D"})]
    labo = [ack("I"), dirty({"dirty": False}), ack("O")]
    silent = [ack("I"), ack("O")]
    no_ref = [ack("I"), ack("O"), dirty({"dirty": False})]
    msgs = [{"key": "x evora:init", "frames": 3}, {"key": "x evora:init", "frames": 5}, {"key": "x evora:open", "frames": 9}]
    dirty_ok = (dirty_problems(good, ids) == [] and len(dirty_problems(labo, ids)) == 2
                and len(dirty_problems(silent, ids)) == 1 and len(dirty_problems(no_ref, ids)) == 2
                and frames_between(msgs, "x evora:init", "x evora:open") == 4
                and frames_between(msgs[:2], "x evora:init", "x evora:open") is None)
    return (dirty_ok and writes_after(late, purge) == ["k"] and writes_after(benign, purge) == []
            and leftovers([own, WITNESS_KEY], [own]) == [own] and leftovers([WITNESS_KEY], [own]) == []
            and engine_keys([WITNESS_KEY, "pdfcraft", own]) == sorted(["pdfcraft", own]))


def run_ehp(chrome, page, engine, contexts, result, errors, sabotage=""):
    """E4 et E5 : poignée de main EHP v1 et cycle de vie du stockage, vus de la page parente, de
    l'observateur et du document moteur (HOST-PROTOCOL.md §3, §4, §5, §7.1, §7.7, §9)."""
    sess, ctx = engine
    own, other, other2 = NS_PREFIX + NS_OWN, NS_PREFIX + NS_OTHER, NS_PREFIX + NS_OTHER2
    store = result.setdefault("stockage", {})

    def evaluate(expr, session, context=None, await_promise=False, gesture=False):
        params = {"expression": expr, "returnByValue": True}
        if context is not None:
            params["contextId"] = context
        if await_promise:
            params["awaitPromise"] = True
        if gesture:
            params["userGesture"] = True
        r = chrome.call("Runtime.evaluate", params, session, 20)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RuntimeError(f"évaluation : {d.get('text', '')} {describe_remote(d.get('exception', {}))}")
        return r.get("result", {}).get("value")

    def in_engine(expr, await_promise=False, gesture=False):
        return evaluate(expr, sess, ctx, await_promise, gesture)

    def state():
        return json.loads(evaluate(LOG_EXPR, page) or "{}")

    def wait(cond, timeout=30.0):
        end = time.monotonic() + timeout
        st = state()
        while not cond(st) and time.monotonic() < end:
            chrome.pump(0.2)
            st = state()
        return st

    def settle(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            chrome.pump(0.1)

    def acks(st, key):
        i = st.get("ids", {}).get(key)
        return [m for m in st.get("log", []) if i and m.get("type") == "evora:ack" and m.get("re") == i]

    def observed(st, key):
        i = st.get("ids", {}).get(key)
        return st.get("obs", {}).get(i) if i else None

    def snapshot(label):
        snap = json.loads(in_engine(SNAPSHOT, await_promise=True) or "{}")
        store[label] = {"cles": snap.get("keys"), "opfs": snap.get("opfs"), "idb": snap.get("idb"), "cache": snap.get("cache")}
        return snap

    def check_purge(label, key, st):
        got = acks(st, key)
        if len(got) != 1 or (got[0].get("payload") or {}).get("ok") is not True:
            errors.append(f"[purge] accusé d'evora:purge ({label}) absent ou négatif : {[m.get('payload') for m in got]}")
        seen = observed(st, key)
        store[f"observateur_purge_{label}"] = seen
        if seen is None:
            errors.append(f"[banc] observateur muet après l'accusé d'evora:purge ({label})")
        elif seen.get("engine"):
            errors.append(f"[purge] à l'arrivée de l'accusé d'evora:purge ({label}), stockage du moteur non vide : {seen['engine']}")
        snap = snapshot(f"apres_purge_{label}")
        if engine_keys(snap.get("keys") or []):
            errors.append(f"[purge] après l'accusé d'evora:purge ({label}), stockage du moteur non vide : "
                          f"{engine_keys(snap.get('keys') or [])}")
        if WITNESS_KEY not in (snap.get("keys") or []):
            errors.append(f"[purge] evora:purge ({label}) a effacé une clé étrangère au moteur ({WITNESS_KEY})")
        for where in ("opfs", "idb", "cache"):
            if isinstance(snap.get(where), list) and snap[where]:
                errors.append(f"[purge] {where} non vide après evora:purge ({label}) : {snap[where]}")
        return snap

    if not detector_selftest():
        errors.append("[banc] détecteur muet : un cas connu n'est pas signalé (autotest des détecteurs)")

    # 1. evora:ready ; la page parente n'envoie rien tant que le banc n'a pas semé le stockage.
    st = wait(lambda s: s.get("ids", {}).get("ready"))
    if st.get("ids", {}).get("ready"):
        # 2. Instrument, puis les restes d'une séance précédente : un autre compte, l'amont, la mémoire
        # d'eframe, des réglages du compte courant, et une clé étrangère au moteur.
        store["instrument"] = in_engine(STORE_HOOK % {"sabotage": sabotage})
        seeds = [[other, json.dumps({"language": "ja", "author": "Autre compte"})],
                 [own, json.dumps({"reload_changed_files": False, "author": "Ancien nom", "language": "ja"})],
                 ["pdfcraft", json.dumps({"language": "ja", "author": "Compte précédent"})], ["printcraft", "{}"],
                 ["egui_memory_ron", "()"], [WITNESS_KEY, "1"]]
        store["seme"] = in_engine(SEED % json.dumps(seeds))
        # 3. evora:init de version 2 (à ignorer), puis evora:init valide (storageNs du compte courant).
        if evaluate("window.__evoraGo()", page) is not True:
            errors.append("[banc] la page parente n'a pas pu envoyer evora:init")
        st = wait(lambda s: acks(s, "init") and observed(s, "init") is not None)
        if acks(st, "init"):
            # E5, §7.7 b : à l'accusé d'init, l'autre compte et les restes hors espace sont effacés ;
            # l'espace du compte courant et la clé étrangère restent.
            doomed = [other, *LOOSE_KEYS]
            seen = observed(st, "init")
            store["observateur_init"] = seen
            if seen is None:
                errors.append("[banc] observateur muet après l'accusé d'evora:init")
            elif leftovers(seen.get("all") or [], doomed):
                errors.append(f"[purge-demarrage] à l'arrivée de l'accusé d'evora:init, restes d'un autre compte ou "
                              f"hors espace : {leftovers(seen.get('all') or [], doomed)}")
            snap = snapshot("apres_init")
            keys = snap.get("keys") or []
            if leftovers(keys, doomed):
                errors.append(f"[purge-demarrage] après l'accusé d'evora:init, restes encore présents : {leftovers(keys, doomed)}")
            if own not in keys:
                errors.append("[purge-demarrage] l'espace du compte courant a été effacé au démarrage")
            if WITNESS_KEY not in keys:
                errors.append(f"[purge-demarrage] clé étrangère au moteur effacée au démarrage ({WITNESS_KEY})")
        # 4. doc.dirty (§7.1 étapes 7 et 8) : entre l'accusé d'init et evora:open, le moteur dessine des
        # images (la coquille lit le contenu du document) et ne doit rien dire de son état modifié. Le
        # témoin sabordé (« early-dirty ») glisse ici un evora:dirty depuis la fenêtre du moteur.
        settle(1.5)
        if "early-dirty" in sabotage.split():
            store["sabordage_dirty"] = in_engine(EARLY_DIRTY)
        if evaluate("window.__evoraOpen()", page) is not True:
            errors.append("[banc] la page parente n'a pas pu envoyer evora:open")
        # evora:open (octets) ; puis langue et thème à chaud.
        st = wait(lambda s: acks(s, "open"))
        # Prémisse du contrôle doc.dirty : au moins une image du moteur entre evora:init et evora:open,
        # sans quoi un evora:dirty prématuré n'aurait pas eu l'occasion de partir.
        frames = frames_between(json.loads(in_engine(ENGINE_MSGS) or "[]"), PARENT_ORIGIN + " evora:init",
                                PARENT_ORIGIN + " evora:open")
        store["images_entre_init_et_open"] = frames
        if not (isinstance(frames, (int, float)) and frames >= 1):
            errors.append(f"[banc] aucune image du moteur relevée entre evora:init et evora:open ({frames}) : "
                          "le contrôle de doc.dirty ne pourrait pas rougir")
        evaluate("window.__evoraSend('lang', 'evora:lang', {lang: 'de', engineLang: 'de'})", page)
        evaluate("window.__evoraSend('themeLight', 'evora:theme', {theme: 'light', accent: '#4F46E5'})", page)
        st = wait(lambda s: acks(s, "lang") and acks(s, "themeLight"))
        settle(1.0)
        # 5. doc.save : Ctrl+S dans le moteur ⇒ evora:save (la page parente répond evora:saved).
        store["focus"] = in_engine(FOCUS, gesture=True)
        if store["focus"] is not True:
            errors.append("[banc] le canvas du moteur n'a pas pris le focus")
        settle(0.3)
        in_engine(KEY % {"type": "keydown", "ctrl": "true"}, gesture=True)
        settle(0.5)
        in_engine(KEY % {"type": "keyup", "ctrl": "false"}, gesture=True)
        st = wait(lambda s: s.get("ids", {}).get("save"), 20)
        check_save(st, errors)
        # 6. storage.ns, author, live.lang, live.theme : à la perte de focus, eframe enregistre les
        # réglages, sous l'espace du compte seulement.
        store["blur"] = in_engine(BLUR, gesture=True)
        settle(0.5)
        snap = snapshot("apres_enregistrement")
        try:
            saved = json.loads((snap.get("values") or {}).get(own) or "null")
        except ValueError:
            saved = None
        expected = {"author": "Compte Evora", "language": "de", "theme": "Light", "reload_changed_files": False}
        got = {k: saved.get(k) for k in expected} if isinstance(saved, dict) else None
        store["reglages_du_compte"] = got
        if got != expected:
            errors.append(f"[stockage.ns] réglages enregistrés sous l'espace du compte : {got} (attendu : {expected})")
        outside = [k for k in engine_keys(snap.get("keys") or []) if k != own]
        if outside:
            errors.append(f"[stockage.ns] clés du moteur hors de l'espace du compte après enregistrement : {outside}")
        stray = sorted({op.get("key") for op in snap.get("log") or []
                        if op.get("op") in ("set", "clear") and not op.get("bench") and op.get("key") != own})
        if stray:
            errors.append(f"[stockage.ns] écritures du moteur hors de l'espace du compte : {stray}")
        # 7. Origine non admise (autre origine, autre fenêtre) : purge, langue, thème sans réponse ni effet.
        intruder = [k for k, o in contexts.items() if o == INTRUDER_ORIGIN]
        if not intruder:
            errors.append("[banc] page intruse introuvable")
        else:
            isess, ictx = intruder[-1]
            sent = json.loads(evaluate("window.__evoraIntrude()", isess, ictx) or "[]")
            settle(2.0)
            st = state()
            answered = [m.get("type") for m in st.get("log", []) if m.get("re") in sent]
            store["intrus"] = {"envoyes": sent, "reponses": answered}
            if sent != INTRUDER_IDS:
                errors.append(f"[banc] la page intruse n'a pas envoyé ses messages : {sent}")
            if answered:
                errors.append(f"[intrus] le moteur a répondu à des messages d'une origine non admise : {answered}")
            if own not in (snapshot("apres_intrus").get("keys") or []):
                errors.append("[intrus] un evora:purge d'une origine non admise a effacé l'espace du compte")
        # 8. Thème sombre (attendu au rendu), puis evora:purge {scope: "current"} : accusé après effacement.
        evaluate("window.__evoraSend('themeDark', 'evora:theme', {theme: 'dark', accent: '#4F46E5'})", page)
        st = wait(lambda s: acks(s, "themeDark"))
        evaluate("window.__evoraSend('purge', 'evora:purge', {scope: 'current'})", page)
        st = wait(lambda s: acks(s, "purge") and observed(s, "purge") is not None, 15)
        after = check_purge("current", "purge", st)
        # 9. Écritures arrêtées : une nouvelle perte de focus (eframe enregistrerait) ne recrée rien.
        in_engine(FOCUS, gesture=True)
        settle(0.3)
        in_engine(BLUR, gesture=True)
        settle(0.5)
        snap = snapshot("apres_purge_et_focus")
        back = sorted(set(engine_keys(snap.get("keys") or [])) - set(engine_keys(after.get("keys") or [])))
        if back:
            errors.append(f"[ecritures] clés du moteur recréées après evora:purge : {back}")
        late = writes_after(snap.get("log") or [], PARENT_ORIGIN + " evora:purge")
        if late:
            errors.append(f"[ecritures] écritures du moteur après la réception d'evora:purge : {late}")
        # 10. evora:purge {scope: "all"} : un autre espace et une clé hors espace, semés par le banc.
        in_engine(SEED % json.dumps([[other2, "{}"], ["pdfcraft", "{}"]]))
        evaluate("window.__evoraSend('purgeAll', 'evora:purge', {scope: 'all'})", page)
        st = wait(lambda s: acks(s, "purgeAll") and observed(s, "purgeAll") is not None, 15)
        check_purge("all", "purgeAll", st)
        store["journal"] = (snapshot("fin").get("log") or [])[-60:]
    check_envelopes(state(), result, errors)


# Scénarios « pont-accuse » et « pont-accuse-temoin » (COL-08 et COL-09 ; CONCEPTION-PROTOCOLE §4.1.8,
# HOST-PROTOCOL.md §4.5 l.480, §7.2). Coquille minimale à la main du banc : elle journalise tout, dans
# l'ordre où la page parente envoie et reçoit (« sent » pour ses propres envois), annonce à evora:init
# les capacités du moteur moins celles que le banc retire (le témoin retire doc.saved-ack : comportement
# amont), et ne répond à un evora:save que quand le banc le lui dit (__ackSend). Le moteur est modifié
# par window.__evoraRun("page.rotate"), sonde CI du moteur (?evora-audit=1).
ACK_HARNESS = """
const ENGINE = "%(engine)s";
const A = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
let n = 0;
const ulid = () => { n += 1; return "01JZZZZZZZZZZZZZZZZZZZZZ" + A[(n >> 5) %% 32] + A[n %% 32]; };
const PDF = "%(pdf)s";
const now = () => performance.timeOrigin + performance.now();
const frame = document.getElementById("engine");
const observer = document.getElementById("observer");
const plainObject = (x) => x !== null && typeof x === "object" && Object.getPrototypeOf(x) === Object.prototype;
const copy = (p) => JSON.parse(JSON.stringify(p, (k, v) => v instanceof ArrayBuffer ? {byteLength: v.byteLength} : v));
const st = window.__evoraAck = {log: [], ids: {}, caps: []};
addEventListener("message", (e) => {
  if (e.source === observer.contentWindow) return;
  const d = e.data;
  const plain = plainObject(d);
  const fromEngine = e.source === frame.contentWindow && e.origin === ENGINE;
  st.log.push({t: now(), fromEngine, origin: e.origin, plain, keys: plain ? Object.keys(d) : [], v: plain ? d.v : null,
               type: plain ? d.type : null, id: plain ? d.id : null, re: plain && "re" in d ? d.re : null,
               payloadPlain: plain && plainObject(d.payload), payload: plain && d.payload ? copy(d.payload) : null});
  if (fromEngine && plain && d.v === 1 && d.type === "evora:ready" && !st.ids.ready) {
    st.ids.ready = d.id;
    st.caps = Array.isArray(d.payload && d.payload.capabilities) ? d.payload.capabilities : [];
  }
});
const post = (type, payload, re, transfer) => {
  const id = ulid();
  const m = {v: 1, type, id, payload};
  if (re) m.re = re;
  st.log.push({t: now(), sent: true, type, id, re: re || null, payload: copy(payload)});
  frame.contentWindow.postMessage(m, ENGINE, transfer || []);
  return id;
};
window.__ackInit = (without) => {
  if (!st.ids.ready || st.ids.init) return null;
  st.ids.init = post("evora:init", {lang: "fr", engineLang: "fr", theme: "dark", accent: "#4F46E5", readOnly: false,
    storageNs: "%(ns)s", displayName: "Compte Evora", capabilities: st.caps.filter((c) => !without.includes(c)),
    prefs: {}, limits: {maxDocumentBytes: 1048576, maxExportBytes: 1048576}}, st.ids.ready);
  return st.ids.init;
};
window.__ackOpen = (docRef, name) => {
  const bytes = Uint8Array.from(atob(PDF), (c) => c.charCodeAt(0)).buffer;
  return post("evora:open", {docRef, name, bytes}, null, [bytes]);
};
window.__ackSend = (type, payload, re) => post(type, payload, re);
"""
ACK_DOC = "01JX" + "X" * 20 + "D1"
ACK_DOC_OTHER = "01JX" + "X" * 20 + "D2"
ACK_NAME = "evora-accuse.pdf"
ACK_EXPR = "JSON.stringify(window.__evoraAck || {})"
ACK_FORGED_ID = "01J" + "Y" * 22 + "F"
# Invite beforeunload propre au moteur (S-ACK-4) : un événement annulable envoyé à la fenêtre du moteur
# est-il annulé ? Autotest de l'instrument d'abord : un écouteur du banc qui annule doit être vu.
BEFOREUNLOAD = """(() => {
  const fire = () => { const e = new Event("beforeunload", {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented; };
  const probe = (e) => e.preventDefault();
  addEventListener("beforeunload", probe);
  const selftest = fire();
  removeEventListener("beforeunload", probe);
  return JSON.stringify({selftest, engine: fire()});
})()"""
# Témoin : doc.saved-ack retiré des capacités d'evora:init (le moteur se croit enregistré dès l'envoi,
# comportement amont) et réouverture sous un AUTRE docRef (rien à remplacer). Il DOIT rougir par les
# cinq détecteurs S-ACK, et eux seuls.
ACK_SABOTAGE = "no-saved-ack other-docref"
ACK_EXPECTED = {"ack-conflit", "ack-occupe", "ack-intrus", "ack-modifie-pendant", "ack-reouverture"}


def run_accuse(chrome, page, engine, contexts, result, errors, sabotage=""):
    """COL-08 (evora:request-save) et COL-09 (doc.saved-ack), scénarios S-ACK de CONCEPTION-PROTOCOLE
    §4.1.8 : chaque étape modifie d'abord le document (prémisse vérifiée : dernier evora:dirty vrai),
    puis demande l'enregistrement et répond comme la coquille le ferait. Détecteurs : [ack-conflit]
    (S-ACK-1), [ack-occupe] et [ack-beforeunload] (S-ACK-4), [ack-intrus] (S-ACK-5),
    [ack-modifie-pendant] (S-ACK-2), [ack-reouverture] (S-ACK-6) ; S-ACK-3 (DEVRAIT) est relevé."""
    sess, ctx = engine
    temoin = "no-saved-ack" in sabotage.split()
    other_ref = "other-docref" in sabotage.split()
    acc = result.setdefault("accuse", {})
    steps = acc.setdefault("etapes", [])

    def evaluate(expr, session, context=None):
        params = {"expression": expr, "returnByValue": True}
        if context is not None:
            params["contextId"] = context
        r = chrome.call("Runtime.evaluate", params, session, 20)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RuntimeError(f"évaluation : {d.get('text', '')} {describe_remote(d.get('exception', {}))}")
        return r.get("result", {}).get("value")

    def state():
        return json.loads(evaluate(ACK_EXPR, page) or "{}")

    def wait(cond, timeout=20.0):
        end = time.monotonic() + timeout
        st = state()
        while not cond(st) and time.monotonic() < end:
            chrome.pump(0.2)
            st = state()
        return st

    def settle(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            chrome.pump(0.1)

    def sent_index(st, mid):
        return next((i for i, m in enumerate(st.get("log", [])) if m.get("sent") and m.get("id") == mid), len(st.get("log", [])))

    def dirties(st, after=-1):
        return [(m.get("payload") or {}).get("dirty") for i, m in enumerate(st.get("log", []))
                if i > after and m.get("fromEngine") and m.get("type") == "evora:dirty"]

    def last_dirty(st):
        d = dirties(st)
        return d[-1] if d else None

    def answer(st, rid):
        """La réponse du moteur à la demande `rid` (evora:save ou evora:ack), ou None."""
        return next((m for m in st.get("log", []) if m.get("fromEngine") and rid and m.get("re") == rid), None)

    def send(type_, payload, re_=None):
        return evaluate(f"window.__ackSend({json.dumps(type_)}, {json.dumps(payload)}, {json.dumps(re_)})", page)

    def reply(label, save_id, payload):
        """La coquille répond evora:saved ; renvoie l'index de cet envoi dans le journal."""
        sid = send("evora:saved", payload, save_id)
        steps.append({"etape": label, "evora:saved": payload})
        settle(1.5)
        return sent_index(state(), sid)

    def request(label):
        rid = send("evora:request-save", {"reason": "user", "docRef": ACK_DOC})
        got = answer(wait(lambda s: answer(s, rid) is not None, 15), rid)
        kind = got.get("type") if got else None
        code = (got.get("payload") or {}).get("code") if got else None
        steps.append({"etape": label, "reponse": kind, "code": code})
        return kind, code, (got.get("id") if got else None)

    def edit(label):
        done = evaluate("typeof window.__evoraRun === 'function' && window.__evoraRun('page.rotate')", sess, ctx)
        if done is not True:
            errors.append(f"[banc] {label} : window.__evoraRun('page.rotate') indisponible ou refusé ({done})")
            return False
        st = wait(lambda s: last_dirty(s) is True, 10)
        settle(0.5)
        if last_dirty(st) is not True:
            errors.append(f"[banc] {label} : le moteur ne s'est pas dit modifié après l'édition ({dirties(st)[-3:]})")
            return False
        return True

    st = wait(lambda s: s.get("ids", {}).get("ready"))
    if not st.get("ids", {}).get("ready"):
        errors.append("[banc] evora:ready absent")
        return
    acc["capacites_annoncees"] = st.get("caps")
    for c in ("doc.saved-ack", "doc.request-save"):
        if c not in (st.get("caps") or []):
            errors.append(f"[ack-capacite] {c} absente des capacités d'evora:ready : {st.get('caps')}")
    without = ["doc.saved-ack"] if temoin else []
    init = evaluate(f"window.__ackInit({json.dumps(without)})", page)
    got = answer(wait(lambda s: answer(s, init) is not None), init)
    if not got or (got.get("payload") or {}).get("ok") is not True:
        errors.append(f"[banc] accusé d'evora:init absent ou négatif : {got}")
        return
    settle(1.0)
    opened = evaluate(f"window.__ackOpen({json.dumps(ACK_DOC)}, {json.dumps(ACK_NAME)})", page)
    st = wait(lambda s: answer(s, opened) is not None and dirties(s, sent_index(s, opened)), 15)
    if ((answer(st, opened) or {}).get("payload") or {}).get("ok") is not True or dirties(st, sent_index(st, opened))[:1] != [False]:
        errors.append(f"[banc] ouverture : accusé {answer(st, opened)}, evora:dirty {dirties(st, sent_index(st, opened))}")
        return

    # S-ACK-1 : evora:saved {ok: false, error: "conflict"} ⇒ le document reste modifié ; la demande
    # suivante produit un evora:save, jamais « clean ».
    if edit("S-ACK-1"):
        kind, code, save = request("S-ACK-1 demande")
        if kind != "evora:save":
            errors.append(f"[banc] S-ACK-1 : document modifié, la demande reçoit {kind} {code or ''}")
        else:
            at = reply("S-ACK-1 conflit", save, {"ok": False, "error": "conflict"})
            after = dirties(state(), at)
            kind2, code2, save2 = request("S-ACK-1 seconde demande")
            if False in after or kind2 != "evora:save":
                errors.append(f"[ack-conflit] après un conflit : evora:dirty {after}, demande suivante → {kind2} "
                              f"{code2 or ''} (attendu : rester modifié, puis evora:save)")
            if kind2 == "evora:save":
                reply("S-ACK-1 conflit (bis)", save2, {"ok": False, "error": "conflict"})
    # S-ACK-4 : evora:saved {ok: false, error: "busy"} ⇒ reste modifié ; aucune invite beforeunload
    # propre au moteur sous le pont (la coquille la possède).
    if edit("S-ACK-4"):
        kind, code, save = request("S-ACK-4 demande")
        if kind != "evora:save":
            errors.append(f"[banc] S-ACK-4 : document modifié, la demande reçoit {kind} {code or ''}")
        else:
            at = reply("S-ACK-4 occupé", save, {"ok": False, "error": "busy"})
            after = dirties(state(), at)
            bu = json.loads(evaluate(BEFOREUNLOAD, sess, ctx) or "{}")
            acc["beforeunload"] = bu
            if bu.get("selftest") is not True:
                errors.append(f"[banc] instrument beforeunload muet : {bu}")
            elif bu.get("engine") is not False:
                errors.append(f"[ack-beforeunload] invite beforeunload propre au moteur sous le pont : {bu}")
            kind2, code2, save2 = request("S-ACK-4 seconde demande")
            if False in after or kind2 != "evora:save":
                errors.append(f"[ack-occupe] après « busy » : evora:dirty {after}, demande suivante → {kind2} "
                              f"{code2 or ''} (attendu : rester modifié, puis evora:save)")
            if kind2 == "evora:save":
                reply("S-ACK-4 occupé (bis)", save2, {"ok": False, "error": "busy"})
    # S-ACK-5 : un evora:saved {ok: true} forgé par une origine non admise est ignoré (le moteur reste
    # modifié) ; le même message venu de la coquille, lui, rend le document enregistré (témoin interne).
    intruder = [k for k, o in contexts.items() if o == INTRUDER_ORIGIN]
    if edit("S-ACK-5"):
        kind, code, save = request("S-ACK-5 demande")
        if kind != "evora:save" or not intruder:
            errors.append(f"[banc] S-ACK-5 : demande → {kind} {code or ''} ; page intruse {'présente' if intruder else 'absente'}")
        else:
            settle(1.0)
            mark = len(state().get("log", [])) - 1
            isess, ictx = intruder[-1]
            forged = evaluate(f"window.__evoraForge({json.dumps(save)}, {json.dumps(ACK_FORGED_ID)})", isess, ictx)
            settle(1.5)
            st = state()
            after_forged, still = dirties(st, mark), last_dirty(st)
            reply("S-ACK-5 accusé de la coquille", save, {"ok": True, "version": 2})
            kind2, code2, _ = request("S-ACK-5 demande après l'accusé")
            acc["s_ack_5"] = {"forge": forged, "dirty_apres_forge": after_forged, "dernier_dirty": still,
                              "apres_accuse": [kind2, code2]}
            if forged != ACK_FORGED_ID or False in after_forged or still is not True \
                    or (kind2, code2) != ("evora:ack", "clean"):
                errors.append(f"[ack-intrus] evora:saved forgé par {INTRUDER_ORIGIN} : evora:dirty ensuite {after_forged}, "
                              f"dernier état {still} ; après l'accusé de la coquille : {kind2} {code2 or ''} (attendu : "
                              "aucun effet du message forgé, document modifié, puis « clean » après l'accusé légitime)")
    # S-ACK-2 : une modification entre evora:save et evora:saved {ok: true} ⇒ evora:dirty {dirty: true}
    # APRÈS l'accusé (l.480) ; puis S-ACK-3 relevé : accusé sans modification ⇒ evora:dirty {dirty: false}.
    if edit("S-ACK-2"):
        kind, code, save = request("S-ACK-2 demande")
        if kind != "evora:save":
            errors.append(f"[banc] S-ACK-2 : document modifié, la demande reçoit {kind} {code or ''}")
        else:
            settle(0.5)
            if evaluate("window.__evoraRun('page.rotate')", sess, ctx) is not True:
                errors.append("[banc] S-ACK-2 : modification pendant l'aller-retour refusée")
            settle(1.5)
            at = reply("S-ACK-2 accusé après une modification", save, {"ok": True, "version": 3})
            st = wait(lambda s: dirties(s, at), 5)
            after = dirties(st, at)
            kind2, code2, save2 = request("S-ACK-2 seconde demande")
            if after[:1] != [True] or kind2 != "evora:save":
                errors.append(f"[ack-modifie-pendant] modification pendant l'envoi, puis evora:saved {{ok: true}} : "
                              f"evora:dirty ensuite {after}, demande suivante → {kind2} {code2 or ''} (attendu : "
                              "d'abord {dirty: true}, puis evora:save)")
            if kind2 == "evora:save":
                at3 = reply("S-ACK-3 accusé sans modification", save2, {"ok": True, "version": 4})
                acc["s_ack_3"] = dirties(wait(lambda s: dirties(s, at3), 5), at3)
    # S-ACK-6 : evora:open du même docRef sur un document modifié (« Recharger la version du serveur ») ⇒
    # contenu remplacé, accusé positif (jamais busy), puis evora:dirty {dirty: false} ; rien à enregistrer.
    if edit("S-ACK-6"):
        ref = ACK_DOC_OTHER if other_ref else ACK_DOC
        opened2 = evaluate(f"window.__ackOpen({json.dumps(ref)}, {json.dumps(ACK_NAME)})", page)
        st = wait(lambda s: answer(s, opened2) is not None and dirties(s, sent_index(s, opened2)), 10)
        p = (answer(st, opened2) or {}).get("payload") or {}
        after = dirties(st, sent_index(st, opened2))
        kind2, code2 = (None, None) if other_ref else request("S-ACK-6 demande après réouverture")[:2]
        if p.get("ok") is not True or after[:1] != [False] or (not other_ref and (kind2, code2) != ("evora:ack", "clean")):
            errors.append(f"[ack-reouverture] réouverture du document modifié : accusé {p}, evora:dirty ensuite {after}, "
                          f"demande suivante → {kind2} {code2 or ''} (attendu : accusé positif, {{dirty: false}}, « clean »)")
    # Enveloppes et charges utiles de tout ce que le moteur a envoyé (§3, §4.4, §4.5).
    for m in state().get("log", []):
        if not m.get("fromEngine"):
            continue
        rule = PAYLOAD_KEYS.get(m.get("type"))
        p = m.get("payload") or {}
        if m.get("v") != 1 or not m.get("payloadPlain") or rule is None or not rule[0] <= set(p) <= rule[1] \
                or not ULID_RE.match(str(m.get("id"))) or (m.get("re") is not None and not ULID_RE.match(str(m.get("re")))):
            errors.append(f"[ehp] message du moteur non conforme : {m.get('type')} {p}")
    acc["messages"] = [{k: m.get(k) for k in ("sent", "type", "re", "payload")} for m in state().get("log", [])][-60:]


def check_save(st, errors):
    """doc.save : un evora:save conforme (§4.4), pour le document ouvert par la page parente."""
    ids = st.get("ids", {})
    saves = [m for m in st.get("log", []) if m.get("type") == "evora:save"]
    if not saves:
        errors.append("[save] aucun evora:save après Ctrl+S dans le moteur")
        return
    m = saves[0]
    p = m.get("payload") or {}
    b = (m.get("binary") or {}).get("bytes") or {}
    problems = []
    if set(p) != {"docRef", "name", "saveAs", "bytes"}:
        problems.append(f"champs {sorted(p)}")
    if p.get("docRef") != ids.get("docRef"):
        problems.append("docRef différent de celui du document ouvert")
    if p.get("name") != "evora-smoke.pdf":
        problems.append(f"nom {p.get('name')!r}")
    if p.get("saveAs") is not False:
        problems.append(f"saveAs {p.get('saveAs')!r}")
    if b.get("kind") != "[object ArrayBuffer]" or not (b.get("byteLength") or 0) >= 1:
        problems.append(f"octets {b}")
    if m.get("re") is not None:
        problems.append("re posé sans evora:request-save")
    if problems:
        errors.append(f"[save] evora:save non conforme : {', '.join(problems)}")


def check_envelopes(st, result, errors):
    """Enveloppe et charge utile de chaque message reçu du moteur (§3, §4.4, §4.5) ; un seul
    evora:ready ; rien en réponse au message de version 2 ; accusés positifs attendus ; doc.dirty
    (aucun evora:dirty avant l'ouverture, puis {dirty: false} pour le document ouvert)."""
    log, ids = st.get("log", []), st.get("ids", {})
    result["ehp"] = {"messages": [{k: m.get(k) for k in ("type", "re", "payload")} for m in log], "ids": ids}
    for m in log:
        where = f"{m.get('type')} {m.get('id')}"
        keys = set(m.get("keys") or [])
        if not (m.get("fromEngine") and m.get("plain") and m.get("v") == 1):
            errors.append(f"[ehp] message hors norme ou d'une autre source : {m}")
            continue
        if not {"v", "type", "id", "payload"} <= keys <= {"v", "type", "id", "re", "payload"}:
            errors.append(f"[ehp] enveloppe non conforme ({where}) : champs {sorted(keys)}")
            continue
        if not ULID_RE.match(str(m.get("id"))):
            errors.append(f"[ehp] id qui n'est pas un ULID ({where})")
        if "re" in keys and not ULID_RE.match(str(m.get("re"))):
            errors.append(f"[ehp] re qui n'est pas un ULID ({where})")
        if not m.get("payloadPlain"):
            errors.append(f"[ehp] charge utile qui n'est pas un objet simple ({where})")
            continue
        p = m.get("payload") or {}
        rule = PAYLOAD_KEYS.get(m.get("type"))
        if rule is None:
            errors.append(f"[ehp] type inattendu venu du moteur ({where})")
        elif not rule[0] <= set(p) <= rule[1]:
            errors.append(f"[ehp] charge utile non conforme ({where}) : champs {sorted(p)}")
        if m.get("type") == "evora:ack" and ("re" not in keys or not isinstance(p.get("ok"), bool)
                                             or (p.get("ok") is False and "code" not in p)):
            errors.append(f"[ehp] accusé non conforme ({where}) : {p}")
        if m.get("type") in ("evora:ready", "evora:dirty", "evora:export", "evora:focus-out", "evora:commands") and "re" in keys:
            errors.append(f"[ehp] re inattendu ({where})")
        if m.get("type") == "evora:dirty" and not isinstance(p.get("dirty"), bool):
            errors.append(f"[ehp] evora:dirty non conforme ({where}) : {p}")
    ready = [m for m in log if m.get("type") == "evora:ready"]
    if len(ready) != 1:
        errors.append(f"[ehp] evora:ready reçu {len(ready)} fois (attendu : 1)")
    else:
        p = ready[0].get("payload") or {}
        caps = p.get("capabilities")
        result["capabilities"] = caps
        if (p.get("app") != "colophon-atelier" or p.get("ehp") != "1.0" or not SEMVER_RE.match(str(p.get("version")))
                or not isinstance(caps, list) or len(set(caps)) != len(caps) or not set(caps) <= CAPABILITY_NAMES
                or not {"doc.open", "doc.save", "storage.ns", "storage.purge"} <= set(caps)):
            errors.append(f"[ehp] evora:ready non conforme : {p}")
    if ids.get("bogus") and [m for m in log if m.get("re") == ids["bogus"]]:
        errors.append("[ehp] le moteur a répondu à un evora:init de version 2 (doit l'ignorer)")
    for step in ("init", "open", "lang", "themeLight", "themeDark"):
        got = [m for m in log if ids.get(step) and m.get("type") == "evora:ack" and m.get("re") == ids[step]]
        if len(got) != 1 or (got[0].get("payload") or {}).get("ok") is not True:
            errors.append(f"[ehp] accusé de {step} absent ou négatif : {[g.get('payload') for g in got]}")
    if not [m for m in log if m.get("type") == "evora:dirty"]:
        errors.append("[ehp] aucun evora:dirty (capacité doc.dirty non exercée)")
    for problem in dirty_problems(log, ids):
        errors.append(f"[dirty] {problem}")


# Témoin sabordé « no-listeners » (scénario « pont-deux-instances-temoin »), posé dans chaque document
# de l'origine moteur dès la création de son contexte, bien avant le démarrage du moteur :
# BroadcastChannel devient inerte et aucun écouteur « storage » n'est posé sur la fenêtre. Le moteur
# n'apprend donc plus les effacements faits par ses autres pages.
NO_LISTENERS = """(() => {
  if (window.__evoraNoListeners) return "déjà posé";
  window.__evoraNoListeners = true;
  const add = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, listener, options) {
    if (type === "storage" && this === window) return undefined;
    return add.call(this, type, listener, options);
  };
  window.BroadcastChannel = class {
    constructor(name) { this.name = String(name); }
    postMessage() {}
    close() {}
    addEventListener() {}
    removeEventListener() {}
    dispatchEvent() { return true; }
  };
  return "posé";
})()"""

MULTI_STATE = "JSON.stringify(window.__evoraMulti || {})"


def cdp_evaluate(chrome, expr, session, context=None, gesture=False):
    params = {"expression": expr, "returnByValue": True}
    if context is not None:
        params["contextId"] = context
    if gesture:
        params["userGesture"] = True
    r = chrome.call("Runtime.evaluate", params, session, 20)
    if r.get("exceptionDetails"):
        d = r["exceptionDetails"]
        raise RuntimeError(f"évaluation : {d.get('text', '')} {describe_remote(d.get('exception', {}))}")
    return r.get("result", {}).get("value")


def run_instances(chrome, page, contexts, result, errors):
    """E5 entre pages de l'origine moteur (HOST-PROTOCOL.md §7.7). eframe enregistre les réglages
    toutes les 30 s et à chaque perte de focus, même onglet masqué : une page qui n'apprend pas un
    effacement le dément. Trois chemins, chacun isolé par sa prémisse :
    a) deux onglets du même compte (e1, e2) : une purge dans e1 ne doit pas être démentie par e2 ; la
       clé n'existe pas encore, donc seule la diffusion de la purge peut l'empêcher ;
    b) un onglet du même compte ouvert après la purge (e3), puis un autre compte (e4) qui démarre :
       son evora:init efface les autres espaces, et e3 ne doit pas recréer le sien ; la clé de e3
       n'existe pas encore, donc seule la diffusion de l'evora:init peut l'empêcher ;
    c) e4 écrit sa clé (prémisse), une autre fenêtre de l'origine (l'observateur) l'efface, et e4 ne
       doit pas la recréer : seul l'événement storage peut l'empêcher."""
    own = NS_PREFIX + NS_OWN
    other = NS_PREFIX + NS_OTHER
    store = result.setdefault("instances", {})

    def ev(expr, session, context=None, gesture=False):
        return cdp_evaluate(chrome, expr, session, context, gesture)

    def state():
        return json.loads(ev(MULTI_STATE, page) or "{}")

    def wait(cond, timeout=30.0):
        end = time.monotonic() + timeout
        st = state()
        while not cond(st) and time.monotonic() < end:
            chrome.pump(0.2)
            st = state()
        return st

    def settle(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            chrome.pump(0.1)

    def engines():
        """Contextes des moteurs (par window.name), une fois leur canvas dimensionné par eframe."""
        found = {}
        for (sess, ctx), origin in list(contexts.items()):
            if origin != ENGINE_ORIGIN:
                continue
            try:
                name = ev("window.name", sess, ctx)
                probe = json.loads(ev(PROBE, sess, ctx) or "{}")
            except (RuntimeError, TimeoutError):
                continue
            key = name[len("evora-"):] if isinstance(name, str) and name.startswith("evora-") else None
            if key in INSTANCES and probe.get("canvas") and probe.get("cw", 0) > 0 and probe.get("w") != 300 \
                    and abs(probe["w"] - round(probe["cw"] * probe.get("dpr", 1))) <= 1:
                found[key] = (sess, ctx)
        return found

    def observe(remove=None):
        """Clés du moteur lues par l'observateur (après avoir effacé `remove`, s'il est donné)."""
        pid = ev(f"window.__evoraProbe({json.dumps(remove)})", page)
        st = wait(lambda s: pid in (s.get("obs") or {}), 15)
        seen = (st.get("obs") or {}).get(pid)
        if seen is None:
            errors.append("[banc] observateur muet")
            return None
        return seen.get("engine") or []

    def acked(st, i, frm):
        a = (st.get("acks") or {}).get(i) or {}
        return a.get("from") == frm and a.get("ok") is True

    def save(frm):
        """Focus puis perte de focus du canvas : eframe enregistre alors l'état de l'app (App::save).
        Sans focus pris puis perdu, aucun enregistrement : le contrôle qui suit ne pourrait pas rougir."""
        sess, ctx = found[frm]
        focus = ev(FOCUS, sess, ctx, gesture=True)
        settle(0.3)
        blur = ev(BLUR, sess, ctx, gesture=True)
        settle(1.0)
        if focus is not True or blur is not True:
            errors.append(f"[banc] {frm} : focus pris {focus}, perdu {blur} (attendu : true, true) ; "
                          "aucun enregistrement provoqué")
        return {"focus": focus, "blur": blur}

    end = time.monotonic() + READY_TIMEOUT
    found = engines()
    while len(found) < len(INSTANCES) and time.monotonic() < end:
        chrome.pump(0.5)
        found = engines()
    store["moteurs"] = sorted(found)
    st = wait(lambda s: all(i in (s.get("ready") or {}) for i in INSTANCES))
    if len(found) < len(INSTANCES) or not all(i in (st.get("ready") or {}) for i in INSTANCES):
        errors.append(f"[banc] {len(INSTANCES)} moteurs prêts attendus : canvas {sorted(found)}, evora:ready {sorted(st.get('ready') or {})}")
        return
    # 1. Deux onglets du même compte : evora:init avec le même storageNs ; la clé n'existe pas encore.
    i1 = ev(f"window.__evoraInit('e1', '{NS_OWN}')", page)
    i2 = ev(f"window.__evoraInit('e2', '{NS_OWN}')", page)
    st = wait(lambda s: acked(s, i1, "e1") and acked(s, i2, "e2"))
    if not (acked(st, i1, "e1") and acked(st, i2, "e2")):
        errors.append(f"[banc] accusés d'evora:init de e1 et e2 absents ou négatifs : {st.get('acks')}")
        return
    settle(1.0)
    before = observe()
    store["avant_purge"] = before
    if before is not None and own in before:
        errors.append(f"[banc] {own} écrit avant la purge : le contrôle de la diffusion n'est pas isolé")
    # 2. Déconnexion depuis e1 : evora:purge {scope: "current"}, accusé positif.
    p1 = ev("window.__evoraSendTo('e1', 'evora:purge', {scope: 'current'})", page)
    st = wait(lambda s: acked(s, p1, "e1"), 15)
    if not acked(st, p1, "e1"):
        errors.append(f"[banc] accusé d'evora:purge de e1 absent ou négatif : {(st.get('acks') or {}).get(p1)}")
    settle(1.0)
    # 3. e2 enregistrerait à sa perte de focus : rien ne doit reparaître.
    store["e2_enregistrement"] = save("e2")
    after = observe()
    store["apres_purge_e1_puis_enregistrement_e2"] = after
    if after is not None and own in after:
        errors.append(f"[deux-instances-diffusion] le second onglet du compte a recréé {own} après l'accusé de purge du premier")
    # 4. Un onglet du même compte ouvert après la purge (e3) ; l'espace du compte, effacé d'abord s'il
    # reste (il ne reste que sur un moteur fautif), pour que la prémisse de l'étape 5 tienne.
    observe(own)
    i3 = ev(f"window.__evoraInit('e3', '{NS_OWN}')", page)
    st = wait(lambda s: acked(s, i3, "e3"))
    if not acked(st, i3, "e3"):
        errors.append(f"[banc] accusé d'evora:init de e3 absent ou négatif : {(st.get('acks') or {}).get(i3)}")
        return
    settle(1.0)
    before = observe()
    store["avant_init_e4"] = before
    if before is not None and own in before:
        errors.append(f"[banc] {own} présent avant l'evora:init de e4 : le contrôle de sa diffusion n'est pas isolé")
    # 5. Un autre compte démarre (e4) : son evora:init efface les autres espaces ; e3, qui enregistrerait
    # à sa perte de focus, ne doit pas recréer le sien.
    i4 = ev(f"window.__evoraInit('e4', '{NS_OTHER}')", page)
    st = wait(lambda s: acked(s, i4, "e4"))
    if not acked(st, i4, "e4"):
        errors.append(f"[banc] accusé d'evora:init de e4 absent ou négatif : {(st.get('acks') or {}).get(i4)}")
        return
    settle(1.0)
    store["e3_enregistrement"] = save("e3")
    after = observe()
    store["apres_init_e4_puis_enregistrement_e3"] = after
    if after is not None and own in after:
        errors.append(f"[deux-instances-compte] l'onglet du premier compte a recréé {own} après l'evora:init d'un autre compte")
    # 6. e4 écrit sa clé (prémisse) ; une autre fenêtre de l'origine l'efface ; e4 ne doit pas la recréer.
    store["e4_enregistrement"] = save("e4")
    written = observe()
    store["apres_enregistrement_e4"] = written
    if written is not None and other not in written:
        errors.append(f"[banc] e4 n'a pas écrit {other} : le contrôle de l'effacement ne pourrait pas rougir")
    elif written is not None:
        store["apres_effacement_par_une_autre_fenetre"] = observe(other)
        settle(1.0)
        store["e4_enregistrement_apres_effacement"] = save("e4")
        again = observe()
        store["apres_effacement_puis_enregistrement_e4"] = again
        if again is not None and other in again:
            errors.append(f"[deux-instances-stockage] e4 a recréé {other} après son effacement par une autre fenêtre de l'origine")
    # 7. Enveloppes : un seul evora:ready par moteur ; aucun message d'une autre source.
    st = state()
    for i in INSTANCES:
        n = len([m for m in st.get("log", []) if m.get("from") == i and m.get("type") == "evora:ready"])
        if n != 1:
            errors.append(f"[ehp] {i} : evora:ready reçu {n} fois (attendu : 1)")
    if st.get("stray"):
        errors.append(f"[ehp] messages d'une autre source ou hors norme : {st['stray'][:5]}")
    store["messages"] = [{k: m.get(k) for k in ("from", "type", "payload")} for m in st.get("log", [])][-30:]


# Témoin sabordé : les détecteurs qui doivent rougir, et eux seuls, quand removeItem est sans effet
# dans le moteur (le moteur croit effacer, rien ne l'est) et qu'un evora:dirty part de la fenêtre du
# moteur avant evora:open.
WITNESS_SABOTAGE = "no-remove early-dirty"
WITNESS_EXPECTED = {"purge-demarrage", "purge", "stockage.ns", "dirty"}
# Témoin « pont-deux-instances-temoin » : sans diffusion ni événement storage, chacun des trois
# contrôles du scénario 7 rougit, et eux seuls.
INSTANCES_SABOTAGE = "no-listeners"
INSTANCES_EXPECTED = {"deux-instances-diffusion", "deux-instances-compte", "deux-instances-stockage"}


# Scénario « pont-robustesse » (COL-40, EVORA-COL-39) : quatre défauts du pont relevés par les revues
# du 2026-10-15 (apps/pdf-tool/UPSTREAM.md d'Evora §14.8, §15.5), un détecteur chacun, deux moteurs
# dans la même page parente (r1, r2 ; window.name evora-<id>) et l'observateur :
#  [rob-memoire-eframe] la mémoire d'eframe (egui_memory_ron) laissée par une séance précédente n'est
#     jamais lue avant evora:init : le banc la sème dès la création du contexte du document moteur
#     (avant le .wasm) et journalise chaque lecture de la clé (ROB_EARLY) ; prémisse : la clé semée et
#     au moins une lecture d'eframe relevée ;
#  [rob-init-purge] r2 : un evora:init dont la purge de démarrage n'est pas effective (removeItem sans
#     effet pour la clé d'un autre compte, semée par le banc) est refusé ({ok: false, code: forbidden})
#     et le moteur reste non initialisé (un evora:open ensuite reste sans réponse) ; prémisse : la clé
#     de l'autre compte est toujours là ;
#  [rob-open-ack] r1 : evora:open d'octets illisibles reçoit {ok: false, code: invalid_content}, jamais
#     un accusé positif avant l'ouverture réelle ; prémisse : un PDF valide reçoit {ok: true} ;
#  [rob-docref-nom] r1 : un fichier local du même nom que le document ouvert par la coquille (déposé sur
#     le canevas) n'est jamais envoyé sous le docRef de ce document par Ctrl+S ; prémisses : Ctrl+S
#     sur le document de la coquille produit son evora:save, et Ctrl+S sur le fichier local produit
#     un evora:save ou le refus affiché par le moteur (sonde au rendu ROB_TOAST).
ROB_INSTANCES = ("r1", "r2")
ROB_DOC = "01JX" + "R" * 20 + "D1"
ROB_DOC_BAD = "01JX" + "R" * 20 + "B1"
ROB_DOC_R2 = "01JX" + "R" * 20 + "D2"
ROB_NAME = "evora-robustesse.pdf"
ROB_TOAST = "only a document opened from Evora"
ROB_EXPECTED = {"rob-memoire-eframe", "rob-init-purge", "rob-open-ack", "rob-docref-nom"}
# Correction 1 de COL-FK-B1 (EVORA-COL-42) : le document de la coquille qui attend sa boîte de mot de passe.
#  [rob-chiffre-depot] r1 : un fichier local déposé sur le canevas pendant la boîte d'un PDF chiffré ouvert
#     par la coquille ne prend jamais son docRef : aucune réponse à cet evora:open avant le mot de passe
#     (le dépôt ne ferme pas la boîte et n'est pas acquitté à sa place), et Ctrl+S sur le fichier déposé
#     n'envoie aucun evora:save sous ce docRef ; prémisses : la boîte dessinée (sonde ROB_ENC_PROBE, le
#     nom du fichier dans son message), le dépôt fait, la sonde du mot de passe acceptée, Ctrl+S suivi
#     d'un effet observable (evora:save ou refus affiché) ;
#  [rob-chiffre-mdp] r1 : le mot de passe saisi (sonde CI ROB_PASSWORD_COMMAND, ce que fait le bouton
#     Ouvrir de la boîte), l'evora:open reçoit {ok: true}, et le fichier déposé s'ouvre ensuite (son onglet
#     dessiné, sonde ROB_LOCAL_PROBE) : rien n'est perdu.
ROB_DOC_ENC = "01JX" + "R" * 20 + "E1"
ROB_ENC_NAME = "evora-chiffre.pdf"
ROB_ENC_PROBE = "evora-chiffre"
ROB_LOCAL_NAME = "evora-depose.pdf"
ROB_LOCAL_PROBE = "evora-depose"
# Mot de passe utilisateur du PDF chiffré du banc ; le moteur le saisit sur ROB_PASSWORD_COMMAND
# (PROBE_PASSWORD_VALUE d'apps/pdfcraft-web/src/main.rs). Une donnée d'essai, pas un secret.
ROB_PASSWORD = b"evora-smoke"
ROB_PASSWORD_COMMAND = "evora-ci.password"
ROB_FIX_EXPECTED = {"rob-chiffre-depot"}
ROB_HARNESS = """
const ENGINE = "%(engine)s";
const A = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
let n = 0;
const ulid = () => { n += 1; return "01JZZZZZZZZZZZZZZZZZZZZZ" + A[(n >> 5) %% 32] + A[n %% 32]; };
const PDF = "%(pdf)s";
const ENC = "%(enc)s";
const plainObject = (x) => x !== null && typeof x === "object" && Object.getPrototypeOf(x) === Object.prototype;
const copy = (p) => JSON.parse(JSON.stringify(p, (k, v) => v instanceof ArrayBuffer ? {byteLength: v.byteLength} : v));
const frames = {};
for (const id of %(ids)s) frames[id] = document.getElementById(id);
const observer = document.getElementById("observer");
const st = window.__evoraRob = {ready: {}, caps: {}, log: [], obs: {}, stray: []};
addEventListener("message", (e) => {
  const d = e.data;
  if (e.source === observer.contentWindow && e.origin === ENGINE) {
    if (plainObject(d) && typeof d.probe === "string") st.obs[d.probe] = {all: d.all, engine: d.engine};
    return;
  }
  const from = Object.keys(frames).find((k) => frames[k].contentWindow === e.source) || null;
  if (from === null || e.origin !== ENGINE || !plainObject(d) || d.v !== 1) {
    st.stray.push({origin: e.origin, from, type: plainObject(d) ? d.type : null});
    return;
  }
  st.log.push({from, v: d.v, keys: Object.keys(d), type: d.type, id: d.id, re: "re" in d ? d.re : null,
               payloadPlain: plainObject(d.payload), payload: plainObject(d.payload) ? copy(d.payload) : null});
  if (d.type === "evora:ready" && !st.ready[from]) {
    st.ready[from] = d.id;
    st.caps[from] = Array.isArray(d.payload && d.payload.capabilities) ? d.payload.capabilities : [];
  }
});
const post = (to, type, payload, re, transfer) => {
  const id = ulid();
  const m = {v: 1, type, id, payload};
  if (re) m.re = re;
  st.log.push({from: "coquille:" + to, sent: true, type, id, re: re || null, payload: copy(payload)});
  frames[to].contentWindow.postMessage(m, ENGINE, transfer || []);
  return id;
};
window.__robInit = (to, ns) => st.ready[to] ? post(to, "evora:init", {lang: "fr", engineLang: "fr", theme: "dark",
  accent: "#4F46E5", readOnly: false, storageNs: ns, displayName: "Compte Evora", capabilities: st.caps[to],
  prefs: {}, limits: {maxDocumentBytes: 1048576, maxExportBytes: 1048576}}, st.ready[to]) : null;
window.__robOpen = (to, docRef, name, kind) => {
  const b64 = kind === "pdf" ? PDF : kind === "enc" ? ENC : null;
  const bytes = b64 !== null ? Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer
                             : new TextEncoder().encode("SABORDAGE QA : ceci n'est pas un PDF").buffer;
  return post(to, "evora:open", {docRef, name, bytes}, null, [bytes]);
};
window.__robSend = (to, type, payload, re) => post(to, type, payload, re);
window.__robProbe = () => { const id = ulid(); observer.contentWindow.postMessage({probe: id}, ENGINE); return id; };
"""
ROB_STATE = "JSON.stringify(window.__evoraRob || {})"
# Posé dès la création du contexte de chaque document de l'origine moteur, avant le .wasm : la mémoire
# d'eframe d'une séance précédente, et le journal de chaque lecture de sa clé (trouvée ou non, avant ou
# après la réception d'evora:init par ce document).
ROB_EARLY = """(() => {
  if (window.__evoraEarly) return "déjà posé";
  const early = window.__evoraEarly = {seeded: false, reads: [], init: false};
  try {
    localStorage.setItem("egui_memory_ron", "(SABORDAGE QA : mémoire d'eframe d'une séance précédente)");
    early.seeded = localStorage.getItem("egui_memory_ron") !== null;
  } catch (e) { early.error = String(e); }
  const S = Storage.prototype;
  const get = S.getItem;
  S.getItem = function (k) {
    const v = get.call(this, k);
    if (String(k) === "egui_memory_ron") early.reads.push({found: v !== null, beforeInit: !early.init});
    return v;
  };
  addEventListener("message", (e) => {
    const d = e.data;
    if (d !== null && typeof d === "object" && d.type === "evora:init") early.init = true;
  }, true);
  return "posé";
})()"""
# r2 : removeItem sans effet pour la seule clé `key` (le reste de l'effacement marche).
ROB_NO_REMOVE = """((key) => {
  const S = Storage.prototype;
  const orig = S.removeItem;
  S.removeItem = function (k) { if (String(k) === key) return undefined; return orig.call(this, k); };
  return "posé";
})(%s)"""
# Un fichier local déposé sur le canevas, comme un glisser-déposer depuis l'ordinateur.
ROB_DROP = """((b64, name) => {
  const c = document.getElementById("pdfcraft");
  if (!c) return -1;
  const bytes = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
  const dt = new DataTransfer();
  dt.items.add(new File([bytes], name, {type: "application/pdf"}));
  for (const type of ["dragenter", "dragover", "drop"]) {
    c.dispatchEvent(new DragEvent(type, {dataTransfer: dt, bubbles: true, cancelable: true}));
  }
  return dt.files.length;
})(%s, %s)"""


def two_page_pdf():
    """Un PDF de deux pages, distinct de minimal_pdf() : le fichier local homonyme de [rob-docref-nom]."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
    for o in offsets:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


PDF_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def rc4(key, data):
    """RC4 (gestionnaire de sécurité standard des PDF, révision 2) : bibliothèque standard seule."""
    s, j = list(range(256)), 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    out, i, j = bytearray(), 0, 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def encrypted_pdf():
    """Un PDF d'une page chiffré (RC4 40 bits, /V 1 /R 2) de mot de passe utilisateur ROB_PASSWORD : il
    ouvre la boîte de mot de passe du moteur (correction 1, [rob-chiffre-depot]). Aucune chaîne ni flux
    à chiffrer : seuls /O et /U se calculent (algorithmes 2, 3 et 4 de la norme)."""
    pad = lambda pw: (pw + PDF_PAD)[:32]  # noqa: E731
    p = -4
    doc_id = hashlib.md5(b"evora-smoke-chiffre").digest()
    owner = rc4(hashlib.md5(pad(b"evora-smoke-proprietaire")).digest()[:5], pad(ROB_PASSWORD))
    key = hashlib.md5(pad(ROB_PASSWORD) + owner + struct.pack("<i", p) + doc_id).digest()[:5]
    user = rc4(key, PDF_PAD)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 240 160] /Resources << >> >>",
            b"<< /Filter /Standard /V 1 /R 2 /Length 40 /O <%s> /U <%s> /P %d >>" % (owner.hex().encode(), user.hex().encode(), p)]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
    for o in offsets:
        out += b"%010d 00000 n \n" % o
    ident = doc_id.hex().encode()
    out += b"trailer\n<< /Size %d /Root 1 0 R /Encrypt 4 0 R /ID [<%s> <%s>] >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, ident, ident, xref)
    return bytes(out)


def parent_page_rob(query):
    """Page parente du scénario « pont-robustesse » : deux moteurs côte à côte, tous deux visibles, et
    l'observateur."""
    harness = ROB_HARNESS % {"engine": ENGINE_ORIGIN, "ids": json.dumps(list(ROB_INSTANCES)),
                             "pdf": base64.b64encode(minimal_pdf()).decode(),
                             "enc": base64.b64encode(encrypted_pdf()).decode()}
    engines = "".join(
        f'<iframe id="{i}" name="evora-{i}" src="{ENGINE_ORIGIN}/index.html{query}" width="{INSTANCE_W}" '
        f'height="{INSTANCE_H}"\n style="border:0;display:block" sandbox="allow-scripts allow-same-origin"></iframe>\n'
        for i in ROB_INSTANCES)
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><link rel="icon" href="data:,"><title>Evora smoke : robustesse du pont</title></head>
<body style="margin:0;background:#fff">
<div style="display:grid;grid-template-columns:repeat(2,{INSTANCE_W}px);gap:0">
{engines}</div>
<iframe id="observer" src="{ENGINE_ORIGIN}/__evora-observer.html" width="10" height="10" style="border:0;display:block"></iframe>
<script>
window.__evoraMessages = [];
addEventListener("message", (e) => {{
  const d = e.data;
  window.__evoraMessages.push({{origin: e.origin, type: (d && typeof d === "object" && typeof d.type === "string") ? d.type : null}});
}});
{harness}
</script>
</body></html>
""".encode()


def run_robustesse(chrome, page, contexts, result, errors):
    """COL-40 : robustesse du pont (mémoire d'eframe, purge de démarrage, accusé d'ouverture, docRef par
    document), un détecteur par cas (voir ROB_EXPECTED et l'en-tête du scénario)."""
    other = NS_PREFIX + NS_OTHER
    rob = result.setdefault("robustesse", {})

    def ev(expr, session, context=None, gesture=False):
        return cdp_evaluate(chrome, expr, session, context, gesture)

    def state():
        return json.loads(ev(ROB_STATE, page) or "{}")

    def wait(cond, timeout=30.0):
        end = time.monotonic() + timeout
        st = state()
        while not cond(st) and time.monotonic() < end:
            chrome.pump(0.2)
            st = state()
        return st

    def settle(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            chrome.pump(0.1)

    def answer(st, rid, frm):
        return next((m for m in st.get("log", []) if m.get("from") == frm and rid and m.get("re") == rid), None)

    def ack_payload(st, rid, frm):
        m = answer(st, rid, frm)
        return (m.get("payload") or {}) if m and m.get("type") == "evora:ack" else None

    def saves(st, frm, after=-1):
        return [m for i, m in enumerate(st.get("log", [])) if i > after and m.get("from") == frm and m.get("type") == "evora:save"]

    def engines():
        found = {}
        for (sess, ctx), origin in list(contexts.items()):
            if origin != ENGINE_ORIGIN:
                continue
            try:
                name = ev("window.name", sess, ctx)
                probe = json.loads(ev(PROBE, sess, ctx) or "{}")
            except (RuntimeError, TimeoutError):
                continue
            key = name[len("evora-"):] if isinstance(name, str) and name.startswith("evora-") else None
            if key in ROB_INSTANCES and probe.get("canvas") and probe.get("cw", 0) > 0 and probe.get("w") != 300:
                found[key] = (sess, ctx)
        return found

    def ctrl_s(frm):
        sess, ctx = found[frm]
        focus = ev(FOCUS, sess, ctx, gesture=True)
        settle(0.3)
        ev(KEY % {"type": "keydown", "ctrl": "true"}, sess, ctx, gesture=True)
        settle(0.5)
        ev(KEY % {"type": "keyup", "ctrl": "false"}, sess, ctx, gesture=True)
        return focus

    def probe_hits(frm, probe):
        sess, ctx = found[frm]
        a = json.loads(ev("JSON.stringify(window.__evoraAudit || null)", sess, ctx) or "null") or {}
        return int((a.get("probes") or {}).get(probe) or 0)

    def toast_hits(frm):
        return probe_hits(frm, ROB_TOAST)

    end = time.monotonic() + READY_TIMEOUT
    found = engines()
    while len(found) < len(ROB_INSTANCES) and time.monotonic() < end:
        chrome.pump(0.5)
        found = engines()
    st = wait(lambda s: all(s.get("ready", {}).get(i) for i in ROB_INSTANCES))
    if len(found) < len(ROB_INSTANCES) or not all(st.get("ready", {}).get(i) for i in ROB_INSTANCES):
        errors.append(f"[banc] moteurs prêts : {sorted(found)}, evora:ready reçus : {sorted(st.get('ready', {}))}")
        return

    # [rob-memoire-eframe] : lectures de egui_memory_ron par chaque moteur avant son evora:init.
    early = {}
    for frm in ROB_INSTANCES:
        sess, ctx = found[frm]
        early[frm] = json.loads(ev("JSON.stringify(window.__evoraEarly || null)", sess, ctx) or "null")
    rob["memoire_eframe"] = early
    for frm, e in early.items():
        if not e or e.get("seeded") is not True or not e.get("reads"):
            errors.append(f"[banc] {frm} : mémoire d'eframe non semée avant le .wasm, ou aucune lecture relevée ({e})")
        elif any(r.get("found") and r.get("beforeInit") for r in e["reads"]):
            errors.append(f"[rob-memoire-eframe] {frm} : egui_memory_ron d'une séance précédente lue avant evora:init "
                          f"({e['reads']})")

    # [rob-init-purge] : r2, purge de démarrage sans effet sur la clé d'un autre compte.
    sess2, ctx2 = found["r2"]
    rob["r2_sabordage"] = ev(ROB_NO_REMOVE % json.dumps(other), sess2, ctx2)
    rob["r2_seme"] = ev(SEED % json.dumps([[other, json.dumps({"author": "Autre compte"})]]), sess2, ctx2)
    init2 = ev(f"window.__robInit('r2', {json.dumps(NS_OWN)})", page)
    st = wait(lambda s: answer(s, init2, "r2") is not None, 15)
    p2 = ack_payload(st, init2, "r2")
    open2 = ev(f"window.__robOpen('r2', {json.dumps(ROB_DOC_R2)}, 'evora-r2.pdf', 'pdf')", page)
    st = wait(lambda s: answer(s, open2, "r2") is not None, 5)
    late = answer(st, open2, "r2")
    pid = ev("window.__robProbe()", page)
    st = wait(lambda s: pid in (s.get("obs") or {}), 15)
    kept = other in (((st.get("obs") or {}).get(pid) or {}).get("all") or [])
    rob["r2"] = {"accuse_init": p2, "reponse_open": late, "cle_autre_compte_presente": kept}
    if not kept:
        errors.append("[banc] r2 : la clé de l'autre compte a disparu malgré le sabordage de removeItem ; mesure impossible")
    elif p2 != {"ok": False, "code": "forbidden"} or late is not None:
        errors.append(f"[rob-init-purge] r2 : purge de démarrage sans effet, accusé d'evora:init {p2}, réponse à "
                      f"evora:open ensuite {late} (attendu : {{ok: false, code: forbidden}}, puis aucune réponse)")

    # [rob-open-ack] : r1, octets illisibles, puis un PDF valide (prémisse).
    init1 = ev(f"window.__robInit('r1', {json.dumps(NS_OWN)})", page)
    st = wait(lambda s: answer(s, init1, "r1") is not None, 15)
    if ack_payload(st, init1, "r1") != {"ok": True}:
        errors.append(f"[banc] r1 : accusé d'evora:init {ack_payload(st, init1, 'r1')} (attendu : {{ok: true}})")
        return
    settle(1.0)
    bad = ev(f"window.__robOpen('r1', {json.dumps(ROB_DOC_BAD)}, 'evora-illisible.pdf', 'garbage')", page)
    st = wait(lambda s: answer(s, bad, "r1") is not None, 15)
    pbad = ack_payload(st, bad, "r1")
    good = ev(f"window.__robOpen('r1', {json.dumps(ROB_DOC)}, {json.dumps(ROB_NAME)}, 'pdf')", page)
    st = wait(lambda s: answer(s, good, "r1") is not None, 15)
    pgood = ack_payload(st, good, "r1")
    rob["r1_ouvertures"] = {"illisible": pbad, "valide": pgood}
    if pgood != {"ok": True}:
        errors.append(f"[banc] r1 : un PDF valide reçoit {pgood} (attendu : {{ok: true}}) ; mesure impossible")
        return
    if pbad != {"ok": False, "code": "invalid_content"}:
        errors.append(f"[rob-open-ack] r1 : evora:open d'octets illisibles reçoit {pbad} "
                      "(attendu : {ok: false, code: invalid_content}, après la tentative d'ouverture)")

    # [rob-docref-nom] : r1, Ctrl+S sur le document de la coquille (prémisse), puis sur un fichier local
    # homonyme déposé sur le canevas.
    settle(1.5)
    mark = len(state().get("log", [])) - 1
    focus = ctrl_s("r1")
    st = wait(lambda s: saves(s, "r1", mark), 15)
    first = saves(st, "r1", mark)
    if focus is not True or not first or (first[0].get("payload") or {}).get("docRef") != ROB_DOC:
        errors.append(f"[banc] r1 : Ctrl+S sur le document de la coquille → {[(m.get('payload') or {}).get('docRef') for m in first]} "
                      f"(focus {focus}) ; attendu : un evora:save de {ROB_DOC}")
        return
    ev(f"window.__robSend('r1', 'evora:saved', {{ok: true, version: 2}}, {json.dumps(first[0].get('id'))})", page)
    settle(1.5)
    sess1, ctx1 = found["r1"]
    dropped = ev(ROB_DROP % (json.dumps(base64.b64encode(two_page_pdf()).decode()), json.dumps(ROB_NAME)), sess1, ctx1)
    settle(3.0)
    hits0 = toast_hits("r1")
    mark = len(state().get("log", [])) - 1
    focus = ctrl_s("r1")
    st = wait(lambda s: saves(s, "r1", mark), 6)
    settle(1.0)
    after = saves(state(), "r1", mark)
    hits1 = toast_hits("r1")
    rob["r1_fichier_local"] = {"depose": dropped, "focus": focus, "evora_save_ensuite": [(m.get("payload") or {}).get("docRef") for m in after],
                               "refus_affiche": [hits0, hits1]}
    if dropped != 1:
        errors.append(f"[banc] r1 : dépôt du fichier local sur le canevas impossible ({dropped})")
    elif after:
        errors.append(f"[rob-docref-nom] r1 : Ctrl+S sur un fichier local du même nom ({ROB_NAME}) envoie evora:save sous "
                      f"{[(m.get('payload') or {}).get('docRef') for m in after]} (attendu : aucun envoi, le document "
                      "de la coquille n'est jamais retrouvé par son nom)")
    elif hits1 <= hits0:
        errors.append(f"[banc] r1 : Ctrl+S sur le fichier local sans effet observable (ni evora:save, ni refus affiché : "
                      f"sonde {hits0} → {hits1}) ; mesure impossible")

    # [rob-chiffre-depot] et [rob-chiffre-mdp] (correction 1, EVORA-COL-42) : r1, un PDF chiffré ouvert par
    # la coquille, un fichier local déposé pendant sa boîte de mot de passe, puis le mot de passe.
    run_chiffre(ev, page, found["r1"], state, wait, settle, answer, saves, ctrl_s, probe_hits, rob, errors)
    # Enveloppes et charges utiles de tout ce que les moteurs ont envoyé (§3, §4.4, §4.5).
    for m in state().get("log", []):
        if m.get("sent"):
            continue
        rule = PAYLOAD_KEYS.get(m.get("type"))
        p = m.get("payload") or {}
        if m.get("v") != 1 or not m.get("payloadPlain") or rule is None or not rule[0] <= set(p) <= rule[1] \
                or not ULID_RE.match(str(m.get("id"))) or (m.get("re") is not None and not ULID_RE.match(str(m.get("re")))):
            errors.append(f"[ehp] message du moteur non conforme : {m.get('type')} {p}")
    stray = state().get("stray") or []
    if stray:
        errors.append(f"[ehp] messages d'une autre source ou malformés reçus par la page parente : {stray[:5]}")
    rob["messages"] = [{k: m.get(k) for k in ("from", "sent", "type", "re", "payload")} for m in state().get("log", [])][-40:]


def run_chiffre(ev, page, engine, state, wait, settle, answer, saves, ctrl_s, probe_hits, rob, errors):
    """Correction 1 de COL-FK-B1 : [rob-chiffre-depot] et [rob-chiffre-mdp] (voir ROB_FIX_EXPECTED)."""
    sess1, ctx1 = engine
    enc0, loc0 = probe_hits("r1", ROB_ENC_PROBE), probe_hits("r1", ROB_LOCAL_PROBE)
    enc = ev(f"window.__robOpen('r1', {json.dumps(ROB_DOC_ENC)}, {json.dumps(ROB_ENC_NAME)}, 'enc')", page)
    settle(3.0)
    shown = probe_hits("r1", ROB_ENC_PROBE)
    first = answer(state(), enc, "r1")
    chiffre = rob.setdefault("r1_chiffre", {"boite": [enc0, shown], "reponse_avant_depot": first})
    if first is not None or shown <= enc0:
        errors.append(f"[banc] r1 : le PDF chiffré n'attend pas sa boîte de mot de passe (réponse {first}, sonde "
                      f"{enc0} → {shown}) ; mesure impossible")
        return
    dropped = ev(ROB_DROP % (json.dumps(base64.b64encode(two_page_pdf()).decode()), json.dumps(ROB_LOCAL_NAME)), sess1, ctx1)
    settle(3.0)
    early = answer(state(), enc, "r1")
    ran = ev(f"typeof window.__evoraRun === 'function' && window.__evoraRun({json.dumps(ROB_PASSWORD_COMMAND)})", sess1, ctx1)
    st = wait(lambda s: answer(s, enc, "r1") is not None, 15)
    late = answer(st, enc, "r1")
    settle(2.0)
    loc1 = probe_hits("r1", ROB_LOCAL_PROBE)
    toast0 = probe_hits("r1", ROB_TOAST)
    mark = len(state().get("log", [])) - 1
    focus = ctrl_s("r1")
    wait(lambda s: saves(s, "r1", mark), 6)
    settle(1.0)
    after = saves(state(), "r1", mark)
    toast1 = probe_hits("r1", ROB_TOAST)
    under = [(m.get("payload") or {}).get("docRef") for m in after]
    chiffre.update({"depose": dropped, "reponse_apres_depot": early, "sonde_mot_de_passe": ran,
                    "reponse_apres_mot_de_passe": late, "onglet_depose": [loc0, loc1], "focus": focus,
                    "evora_save_ensuite": under, "refus_affiche": [toast0, toast1]})
    if dropped != 1:
        errors.append(f"[banc] r1 : dépôt du fichier local sur le canevas impossible ({dropped})")
        return
    if ran is not True:
        errors.append(f"[banc] r1 : sonde du mot de passe {ROB_PASSWORD_COMMAND} indisponible ou refusée ({ran})")
        return
    why = []
    if early is not None:
        why.append(f"evora:open du PDF chiffré répondu avant son mot de passe, après le dépôt : {early.get('type')} "
                   f"{early.get('payload')}")
    if loc1 > loc0 and ROB_DOC_ENC in under:
        why.append(f"Ctrl+S sur le fichier déposé ({ROB_LOCAL_NAME}) envoie evora:save sous {ROB_DOC_ENC}")
    if why:
        errors.append("[rob-chiffre-depot] r1 : " + " ; ".join(why) + " (attendu : la boîte reste, aucune réponse avant "
                      "le mot de passe, jamais le docRef de la coquille pour un fichier local)")
    elif (late or {}).get("payload") != {"ok": True} or loc1 <= loc0:
        errors.append(f"[rob-chiffre-mdp] r1 : mot de passe saisi, réponse {late} (attendu : {{ok: true}}), onglet du "
                      f"fichier déposé {loc0} → {loc1} (attendu : dessiné ensuite)")
    if not after and toast1 <= toast0:
        errors.append(f"[banc] r1 : Ctrl+S sur le fichier déposé sans effet observable (ni evora:save, ni refus "
                      f"affiché : sonde {toast0} → {toast1}) ; mesure impossible")


# Scénario « pont-finitions » (lot COL-FK-B2 : COL-42, COL-43 ; règle d'Evora du 2026-10-27 sur les ponts de
# commandes, avenant §4). Un moteur (f1 ; window.name evora-f1) et l'observateur, un détecteur par finition :
#  [fin-catalogue] evora:commands (command.catalog) émis après evora:init en français, conforme (champs, compte,
#     empreinte FNV-1a 64 recalculée ici, libellés, chemins), liste blanche par construction : aucune commande des
#     espaces de la coquille (file.*, create.*, app.*, help.*, prefs.*), aucune masquée, aucune de FIN_OFF ; témoins
#     présents avec leur drapeau destructif (FIN_PRESENT) ; réémis après evora:lang (allemand), même empreinte, mêmes
#     identifiants, libellés traduits. Le premier catalogue reçu est le commands.json de l'artefact ;
#  [fin-liste-blanche] evora:command d'une commande hors catalogue (FIN_REFUSED) : {ok: false, code: capability} ;
#  [fin-params] page.rotate avec des paramètres (dont une chaîne de chemin) : {ok: false, code: invalid_content} et
#     aucun effet (aucun evora:dirty vrai) ; prémisse : page.rotate {} agit (evora:dirty vrai) ;
#  [fin-retraits] (correction 1, avenant §5) le catalogue livré (commands.json, en français), commande par commande :
#     un marqueur de retrait (FIN_RETRAIT_ID sur l'identifiant, FIN_RETRAIT_LABEL sur le libellé) exige le drapeau
#     destructif, sauf exception justifiée une par une (FIN_RETRAIT_EXCEPTIONS) ; une exception absente du catalogue,
#     sans marqueur ou déjà destructive est périmée ;
#  [fin-destructive] page.delete et les destructives ajoutées par la correction 1 (FIN_DESTRUCTIVE_PROBES) sans
#     confirmed : {ok: false, code: forbidden} chacune et aucun effet ; page.delete avec confirmed: true : {ok: true}
#     et le document modifié ;
#  [fin-export] export.docx et export.html : un evora:export chacun (nom, type MIME du format, docRef du document de la
#     coquille, octets), et AUCUN téléchargement du navigateur (FIN_EARLY relève tout lien de téléchargement cliqué
#     dans le moteur, et le retient : rien ne part) ;
#  [fin-focus-out] F6 sans modificateur, canevas du moteur au focus : un evora:focus-out {} ; Maj+F6 : rien ;
#  [fin-signatures] signatures, paraphes, identités numériques et certificats jamais écrits dans le stockage : laissés
#     par une séance précédente dans l'espace du compte (repère « SABORDAGE QA »), ils n'y sont plus après
#     l'enregistrement des réglages qui suit evora:init (prémisse : réglages réécrits, auteur de la coquille).
# Ses sept détecteurs, et eux seuls, rougissent sous le témoin groupé du lot COL-FK-B2 (défauts réintroduits dans le
# moteur, puis retirés : FIN_EXPECTED) ; [fin-retraits] et [fin-destructive], et eux seuls, sous le témoin de sa
# correction 1 (FIN_FIX_EXPECTED).
FIN_DOC = "01JX" + "F" * 20 + "D1"
FIN_NAME = "evora-finitions.pdf"
FIN_MARK = "SABORDAGE QA"
FIN_EXPECTED = {"fin-catalogue", "fin-liste-blanche", "fin-params", "fin-destructive", "fin-export", "fin-focus-out",
                "fin-signatures"}
# Clés des réglages du moteur qui portent l'identité du membre (écrites ici, indépendamment du moteur).
FIN_IDENTITY = ("signature", "signature_text", "signature_image", "initials", "sign_graphic", "digital_ids", "trusted")
# Espaces de noms de la coquille, refusés en bloc (avenant §4, règle 1).
FIN_SHELL = ("file", "create", "app", "help", "prefs")
# Commandes masquées (COL-05, COL-10, OCR, Q47 a), écrites ici indépendamment de crates/ui-egui/src/evora.rs.
FIN_MASKED = ("help.github", "help.check_updates", "sign.digital", "sign.certify", "sign.certify_invisible",
              "sign.timestamp", "redact.mark", "redact.apply", "redact.sanitize", "ocr.recognize", "ocr.recognize_batch",
              "actions.wizard", "file.open_recent", "comment.import", "form.import_data", "tools.js_console",
              "edit.edit_text", "protect.remove_hidden")
# Hors catalogue : un document neuf fait des fichiers de l'ordinateur ; le thème est celui de la coquille.
FIN_OFF = ("page.combine", "view.theme", "view.theme.system", "view.theme.light", "view.theme.dark")
# Témoins du catalogue : présents, avec ce drapeau destructif.
FIN_PRESENT = {"page.rotate": False, "page.delete": True, "form.clear": True, "comment.flatten": True,
               "export.docx": False, "export.html": False, "comment.export": False, "edit.undo": False,
               "print.dialog": False}
# Correction 1 du lot (avenant §5) : marqueurs de retrait, sur l'identifiant (anglais, en tête d'un segment) et sur le
# libellé du catalogue livré (français, en tête d'un mot) : suppressions, coupes, aplatissements, retraits,
# effacements, réinitialisations et leurs équivalents.
FIN_RETRAIT_ID = re.compile(r"(?:^|[._-])(?:delete|remove|cut|clear|flatten|reset|discard|eras|purge|wipe|strip|"
                            r"trash|destroy|redact|sanitiz|revert|crop)", re.I)
FIN_RETRAIT_LABEL = re.compile(r"\b(?:supprim|retir|enl[eè]v|coup|découp|effac|aplati|réinitialis|vider|vidage|"
                               r"abandonn|gomm|écras|purg|caviard|nettoy|rogn)", re.I)
# Exceptions justifiées une par une, écrites ici indépendamment de host_commands.rs.
FIN_RETRAIT_EXCEPTIONS = {
    "comment.eraser": "Effacer les dessins choisit l'outil gomme : rien n'est effacé avant que le membre frotte la page, "
                      "et chaque effacement est un pas que Annuler reprend",
    "page.crop": "Rogner les pages choisit l'outil de rognage : rien ne change avant que le membre trace un cadre, et "
                 "un rognage pose une zone de page (le contenu reste) que Annuler reprend",
}
# Refusées sans confirmed, sans effet : page.delete, puis les destructives ajoutées par la correction 1.
FIN_DESTRUCTIVE_PROBES = ("page.delete", "page.cut", "sign.fill.signature.remove", "sign.fill.initials.remove",
                          "ui.dock.reset")
# Sous le témoin de la correction 1 du lot (EVORA-COL-51) : ces détecteurs, et eux seuls.
FIN_FIX_EXPECTED = {"fin-retraits", "fin-destructive"}
FIN_REFUSED = ("file.save", "file.close", "file.revert", "help.about", "app.preferences", "create.blank", "page.combine",
               "view.theme.dark", "redact.mark", "sign.digital", "evora.inconnue")
FIN_EXPORTS = (("export.docx", ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
               ("export.html", ".html", "text/html"))
FIN_BAD_PARAMS = ({"pages": "1"}, {"cible": "/opfs/evora/document.pdf"})
FIN_PARAMS_SCHEMA = {"type": "object", "maxProperties": 0}
COMMAND_RE = re.compile(r"^[a-z][A-Za-z0-9_.-]*$")
HASH_RE = re.compile(r"^[0-9a-f]{16}$")
LANG_RE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$")
FIN_HARNESS = """
const ENGINE = "%(engine)s";
const A = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
let n = 0;
const ulid = () => { n += 1; return "01JZZZZZZZZZZZZZZZZZZZZZ" + A[(n >> 5) %% 32] + A[n %% 32]; };
const PDF = "%(pdf)s";
const plainObject = (x) => x !== null && typeof x === "object" && Object.getPrototypeOf(x) === Object.prototype;
const copy = (p) => JSON.parse(JSON.stringify(p, (k, v) => v instanceof ArrayBuffer ? {byteLength: v.byteLength} : v));
const frame = document.getElementById("f1");
const observer = document.getElementById("observer");
const st = window.__evoraFin = {ready: null, caps: [], log: [], obs: {}, stray: []};
const post = (type, payload, re, transfer) => {
  const id = ulid();
  const m = {v: 1, type, id, payload};
  if (re) m.re = re;
  st.log.push({sent: true, type, id, re: re || null, payload: copy(payload)});
  frame.contentWindow.postMessage(m, ENGINE, transfer || []);
  return id;
};
addEventListener("message", (e) => {
  const d = e.data;
  if (e.source === observer.contentWindow && e.origin === ENGINE) {
    if (plainObject(d) && typeof d.probe === "string") st.obs[d.probe] = {all: d.all, engine: d.engine};
    return;
  }
  if (e.source !== frame.contentWindow || e.origin !== ENGINE || !plainObject(d) || d.v !== 1) {
    st.stray.push({origin: e.origin, type: plainObject(d) ? d.type : null});
    return;
  }
  const binary = {};
  if (plainObject(d.payload)) for (const k of Object.keys(d.payload)) {
    const x = d.payload[k];
    if (x !== null && typeof x === "object" && !Array.isArray(x) && !plainObject(x))
      binary[k] = {kind: Object.prototype.toString.call(x), byteLength: typeof x.byteLength === "number" ? x.byteLength : null};
  }
  st.log.push({v: d.v, keys: Object.keys(d), type: d.type, id: d.id, re: "re" in d ? d.re : null,
               payloadPlain: plainObject(d.payload), payload: plainObject(d.payload) ? copy(d.payload) : null, binary});
  if (d.type === "evora:ready" && !st.ready) {
    st.ready = d.id;
    st.caps = Array.isArray(d.payload && d.payload.capabilities) ? d.payload.capabilities : [];
  }
  // Comme la coquille : un export est déposé dans Drive puis acquitté (§7.4), un enregistrement est acquitté.
  if (d.type === "evora:export") post("evora:ack", {ok: true}, d.id);
  if (d.type === "evora:save") post("evora:saved", {ok: true, version: 2}, d.id);
});
window.__finInit = (ns) => st.ready ? post("evora:init", {lang: "fr", engineLang: "fr", theme: "dark", accent: "#4F46E5",
  readOnly: false, storageNs: ns, displayName: "Compte Evora", capabilities: st.caps, prefs: {},
  limits: {maxDocumentBytes: 1048576, maxExportBytes: 1048576}}, st.ready) : null;
window.__finOpen = (docRef) => {
  const bytes = Uint8Array.from(atob(PDF), (c) => c.charCodeAt(0)).buffer;
  return post("evora:open", {docRef, name: "%(name)s", bytes}, null, [bytes]);
};
window.__finCommand = (command, params, confirmed) => {
  const payload = {command, params};
  if (confirmed !== null) payload.confirmed = confirmed;
  return post("evora:command", payload);
};
window.__finSend = (type, payload, re) => post(type, payload, re);
"""
FIN_STATE = "JSON.stringify(window.__evoraFin || {})"
# Posé dès la création du contexte de chaque document de l'origine moteur, avant le .wasm : tout lien de
# téléchargement cliqué (HTMLElement.prototype.click d'un <a download>) est relevé, et retenu (le navigateur ne
# télécharge rien, et la page sabordée de l'iframe ne journalise aucune erreur). Autotest : un clic du banc relevé.
FIN_EARLY = """(() => {
  if (window.__evoraFinEarly) return "déjà posé";
  const fin = window.__evoraFinEarly = {downloads: [], selftest: 0};
  const click = HTMLElement.prototype.click;
  let bench = false;
  HTMLElement.prototype.click = function () {
    if (this instanceof HTMLAnchorElement && this.hasAttribute("download")) {
      if (bench) fin.selftest += 1; else fin.downloads.push({name: String(this.download), href: String(this.href).slice(0, 40)});
      return undefined;
    }
    return click.call(this);
  };
  bench = true;
  try {
    const a = document.createElement("a");
    a.href = "data:text/plain,SABORDAGE%20QA";
    a.download = "evora-autotest.txt";
    a.click();
  } finally { bench = false; }
  return "posé";
})()"""
FIN_F6 = """((shift) => { const c = document.getElementById("pdfcraft");
  for (const type of ["keydown", "keyup"]) {
    c.dispatchEvent(new KeyboardEvent(type, {key: "F6", code: "F6", shiftKey: shift, bubbles: true, cancelable: true}));
  }
  return document.activeElement === c; })(%s)"""


def parent_page_fin(query):
    """Page parente du scénario « pont-finitions » : un moteur et l'observateur."""
    harness = FIN_HARNESS % {"engine": ENGINE_ORIGIN, "pdf": base64.b64encode(two_page_pdf()).decode(), "name": FIN_NAME}
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><link rel="icon" href="data:,"><title>Evora smoke : finitions du pont</title></head>
<body style="margin:0;background:#fff">
<iframe id="f1" name="evora-f1" src="{ENGINE_ORIGIN}/index.html{query}" width="{IFRAME_W}" height="{IFRAME_H}"
 style="border:0;display:block" sandbox="allow-scripts allow-same-origin"></iframe>
<iframe id="observer" src="{ENGINE_ORIGIN}/__evora-observer.html" width="10" height="10" style="border:0;display:block"></iframe>
<script>
window.__evoraMessages = [];
addEventListener("message", (e) => {{
  const d = e.data;
  window.__evoraMessages.push({{origin: e.origin, type: (d && typeof d === "object" && typeof d.type === "string") ? d.type : null}});
}});
{harness}
</script>
</body></html>
""".encode()


def fin_hash(commands):
    """Empreinte du catalogue (§9.1) recalculée ici : FNV-1a 64 de chaque identifiant, d'un octet nul et de son
    drapeau destructif (« 1 » ou « 0 »), et d'un saut de ligne, dans l'ordre du catalogue."""
    h = 0xCBF29CE484222325
    for c in commands:
        flag = b"1" if isinstance(c, dict) and c.get("destructive") is True else b"0"
        for byte in str(c.get("id") if isinstance(c, dict) else "").encode() + b"\x00" + flag + b"\n":
            h = ((h ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def judge_catalog(p, lang):
    """Les écarts d'un evora:commands à la norme (§9.1) et à la règle de liste blanche (avenant §4)."""
    if not isinstance(p, dict):
        return ["catalogue absent"]
    problems = []
    if not {"lang", "count", "hash", "commands"} <= set(p) <= {"lang", "count", "hash", "params", "commands"}:
        problems.append(f"champs {sorted(p)}")
    cmds = p.get("commands")
    if not isinstance(cmds, list) or not cmds:
        return problems + [f"liste de commandes vide ou absente ({type(cmds).__name__})"]
    if p.get("lang") != lang or not LANG_RE.match(str(p.get("lang"))):
        problems.append(f"langue {p.get('lang')!r} (attendue : {lang!r})")
    if p.get("count") != len(cmds):
        problems.append(f"count {p.get('count')!r} pour {len(cmds)} commandes")
    if not HASH_RE.match(str(p.get("hash"))):
        problems.append(f"empreinte mal formée {p.get('hash')!r}")
    elif p["hash"] != fin_hash(cmds):
        problems.append(f"empreinte {p['hash']} (recalculée : {fin_hash(cmds)})")
    if "params" in p and p["params"] != FIN_PARAMS_SCHEMA:
        problems.append(f"schéma des paramètres {p['params']!r} (attendu : aucun paramètre)")
    ids = [c.get("id") if isinstance(c, dict) else None for c in cmds]
    if len(set(map(str, ids))) != len(ids):
        problems.append("identifiants en double")
    bad = []
    for c in cmds:
        if not isinstance(c, dict):
            bad.append(repr(c)[:40])
            continue
        if not {"id", "label", "enabled", "destructive"} <= set(c) <= {"id", "label", "path", "enabled", "destructive"}:
            bad.append(f"{c.get('id')}: champs {sorted(c)}")
        cid, label = c.get("id"), c.get("label")
        if not isinstance(cid, str) or len(cid) > 100 or not COMMAND_RE.match(cid):
            bad.append(f"identifiant {cid!r}")
        if not isinstance(label, str) or not 1 <= len(label.encode("utf-16-le")) // 2 <= 200:
            bad.append(f"{cid}: libellé {label!r}")
        if not isinstance(c.get("enabled"), bool) or not isinstance(c.get("destructive"), bool):
            bad.append(f"{cid}: drapeaux {c.get('enabled')!r} {c.get('destructive')!r}")
        path = c.get("path", [])
        if not isinstance(path, list) or len(path) > 8 or not all(isinstance(x, str) and 1 <= len(x) <= 200 for x in path):
            bad.append(f"{cid}: chemin {path!r}")
    if bad:
        problems.append(f"entrées non conformes : {bad[:6]}")
    shell = [i for i in ids if isinstance(i, str) and i.split(".", 1)[0] in FIN_SHELL]
    masked = [i for i in ids if i in FIN_MASKED]
    off = [i for i in ids if i in FIN_OFF]
    if shell:
        problems.append(f"commandes de la coquille dans le catalogue (hors liste blanche) : {shell[:8]}")
    if masked:
        problems.append(f"commandes masquées dans le catalogue : {masked[:8]}")
    if off:
        problems.append(f"commandes hors catalogue présentes : {off}")
    flags = {c.get("id"): c.get("destructive") for c in cmds if isinstance(c, dict)}
    wrong = {i: flags.get(i) for i, d in FIN_PRESENT.items() if flags.get(i) is not d}
    if wrong:
        problems.append(f"témoins du catalogue absents ou mal marqués (reçu ; attendu {FIN_PRESENT}) : {wrong}")
    return problems


def fin_selftest():
    """Le juge du catalogue se tait sur un catalogue sain et signale chaque défaut connu."""
    good = [{"id": i, "label": i, "path": ["Menu"], "enabled": True, "destructive": d} for i, d in FIN_PRESENT.items()]
    sane = {"lang": "fr", "count": len(good), "hash": fin_hash(good), "params": dict(FIN_PARAMS_SCHEMA), "commands": good}
    shell = good + [{"id": "file.save", "label": "Save", "enabled": True, "destructive": False}]
    masked = good + [{"id": "redact.mark", "label": "Redact", "enabled": True, "destructive": False}]
    flat = [dict(c, destructive=False) for c in good]
    cases = [dict(sane, commands=shell, count=len(shell), hash=fin_hash(shell)),
             dict(sane, commands=masked, count=len(masked), hash=fin_hash(masked)),
             dict(sane, commands=flat, count=len(flat), hash=fin_hash(flat)),
             dict(sane, hash="0" * 16), dict(sane, count=1), dict(sane, lang="de"), dict(sane, params={"type": "object"})]
    return judge_catalog(sane, "fr") == [] and all(judge_catalog(c, "fr") for c in cases) and judge_catalog(None, "fr")


def removal_marked(c):
    """Une entrée du catalogue porte-t-elle un marqueur de retrait (identifiant ou libellé) ?"""
    return isinstance(c, dict) and bool(FIN_RETRAIT_ID.search(str(c.get("id", "")))
                                        or FIN_RETRAIT_LABEL.search(str(c.get("label", ""))))


def judge_removals(p):
    """Avenant §5, point 2 : les commandes du catalogue livré qui portent un marqueur de retrait sans drapeau
    destructif ni exception justifiée, et les exceptions périmées. Sans catalogue, le contrôle ne peut pas se taire."""
    cmds = p.get("commands") if isinstance(p, dict) else None
    if not isinstance(cmds, list) or not cmds:
        return ["catalogue absent : contrôle des marqueurs de retrait impossible"]
    entries = {str(c.get("id")): c for c in cmds if isinstance(c, dict)}
    unflagged = [f"{i} ({c.get('label')!r})" for i, c in entries.items()
                 if removal_marked(c) and c.get("destructive") is not True and i not in FIN_RETRAIT_EXCEPTIONS]
    stale = [i for i in FIN_RETRAIT_EXCEPTIONS
             if i not in entries or not removal_marked(entries[i]) or entries[i].get("destructive") is True]
    problems = []
    if unflagged:
        problems.append(f"marqueur de retrait sans drapeau destructif ni exception justifiée : {unflagged}")
    if stale:
        problems.append(f"exceptions périmées (absentes, sans marqueur ou déjà destructives) : {stale}")
    return problems


def removal_selftest():
    """Le contrôle des marqueurs de retrait se tait sur un catalogue sain et signale chaque défaut connu : marqueur
    dans l'identifiant seul, dans le libellé seul, drapeau retiré, exception périmée, catalogue absent."""
    def cat(entries):
        cmds = [{"id": i, "label": label, "enabled": True, "destructive": d} for i, label, d in entries]
        return {"lang": "fr", "count": len(cmds), "hash": fin_hash(cmds), "commands": cmds}
    base = [("page.delete", "Supprimer des pages", True), ("page.rotate", "Pivoter les pages", False),
            ("comment.eraser", "Effacer les dessins", False), ("page.crop", "Rogner les pages", False)]
    cases = [base + [("page.cut", "Pages", False)], base + [("edit.tout", "Retirer tout", False)],
             [(i, label, False) for i, label, _ in base], [e for e in base if e[0] != "comment.eraser"],
             [(i, label, d or i == "page.crop") for i, label, d in base]]
    return judge_removals(cat(base)) == [] and all(judge_removals(cat(c)) for c in cases) and bool(judge_removals(None))


def run_finitions(chrome, page, contexts, result, errors):
    """COL-42 et COL-43 (lot COL-FK-B2) : un détecteur par finition (voir FIN_EXPECTED et l'en-tête du scénario)."""
    own = NS_PREFIX + NS_OWN
    fin = result.setdefault("finitions", {})

    def ev(expr, session, context=None, gesture=False):
        return cdp_evaluate(chrome, expr, session, context, gesture)

    def state():
        return json.loads(ev(FIN_STATE, page) or "{}")

    def wait(cond, timeout=30.0):
        end = time.monotonic() + timeout
        st = state()
        while not cond(st) and time.monotonic() < end:
            chrome.pump(0.2)
            st = state()
        return st

    def settle(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            chrome.pump(0.1)

    def received(st, after=-1, kind=None):
        return [m for i, m in enumerate(st.get("log", [])) if i > after and not m.get("sent")
                and (kind is None or m.get("type") == kind)]

    def answer(st, rid):
        return next((m for m in received(st) if rid and m.get("re") == rid), None)

    def ack_payload(st, rid):
        m = answer(st, rid)
        return (m.get("payload") or {}) if m and m.get("type") == "evora:ack" else None

    def mark():
        return len(state().get("log", [])) - 1

    def dirty(st, after, value):
        return [m for m in received(st, after, "evora:dirty") if (m.get("payload") or {}).get("dirty") is value]

    def command(cmd, params, confirmed=None, timeout=15.0):
        rid = ev(f"window.__finCommand({json.dumps(cmd)}, {json.dumps(params)}, {json.dumps(confirmed)})", page)
        st = wait(lambda s: answer(s, rid) is not None, timeout)
        return rid, ack_payload(st, rid)

    def engine():
        for (sess, ctx), origin in list(contexts.items()):
            if origin != ENGINE_ORIGIN:
                continue
            try:
                name = ev("window.name", sess, ctx)
                probe = json.loads(ev(PROBE, sess, ctx) or "{}")
            except (RuntimeError, TimeoutError):
                continue
            if name == "evora-f1" and probe.get("canvas") and probe.get("cw", 0) > 0 and probe.get("w") != 300:
                return sess, ctx
        return None

    def reopen(label):
        m = mark()
        rid = ev(f"window.__finOpen({json.dumps(FIN_DOC)})", page)
        st = wait(lambda s: answer(s, rid) is not None and dirty(s, m, False), 20)
        fin[f"ouverture_{label}"] = {"accuse": ack_payload(st, rid), "dirty_faux": len(dirty(st, m, False))}
        if ack_payload(st, rid) != {"ok": True} or not dirty(st, m, False):
            errors.append(f"[banc] ouverture du document de la coquille ({label}) : accusé {ack_payload(st, rid)}, "
                          f"evora:dirty {{dirty: false}} reçus {len(dirty(st, m, False))} (attendu : {{ok: true}}, puis 1)")
            return False
        return True

    if not fin_selftest():
        errors.append("[banc] juge du catalogue muet : un défaut connu n'est pas signalé (autotest)")
    if not removal_selftest():
        errors.append("[banc] contrôle des marqueurs de retrait muet : un défaut connu n'est pas signalé (autotest)")
    end = time.monotonic() + READY_TIMEOUT
    found = engine()
    while found is None and time.monotonic() < end:
        chrome.pump(0.5)
        found = engine()
    st = wait(lambda s: s.get("ready"))
    if found is None or not st.get("ready"):
        errors.append(f"[banc] moteur prêt : {found is not None}, evora:ready reçu : {bool(st.get('ready'))}")
        return
    sess, ctx = found
    early = json.loads(ev("JSON.stringify(window.__evoraFinEarly || null)", sess, ctx) or "null")
    fin["instrument_telechargements"] = early
    if not early or early.get("selftest") != 1:
        errors.append(f"[banc] instrument des téléchargements absent ou muet : {early}")
        return

    # Une séance précédente du même compte a laissé signatures, paraphes, identités et certificats dans son espace.
    seeded = {"author": "Ancien nom", "language": "ja", "reload_changed_files": False,
              "signature": {"strokes": [[[0, 0], [10, 10]]], "note": FIN_MARK}, "signature_text": FIN_MARK,
              "signature_image": None, "initials": {"note": FIN_MARK}, "sign_graphic": FIN_MARK,
              "digital_ids": [{"path": FIN_MARK, "name": FIN_MARK}], "trusted": [FIN_MARK]}
    fin["seme"] = ev(SEED % json.dumps([[own, json.dumps(seeded)]]), sess, ctx)
    m0 = mark()
    init = ev(f"window.__finInit({json.dumps(NS_OWN)})", page)
    st = wait(lambda s: answer(s, init) is not None, 15)
    if ack_payload(st, init) != {"ok": True}:
        errors.append(f"[banc] accusé d'evora:init {ack_payload(st, init)} (attendu : {{ok: true}})")
        return
    fin["capacites"] = st.get("caps")

    # [fin-catalogue], en français : le premier catalogue reçu est le commands.json de l'artefact.
    st = wait(lambda s: received(s, m0, "evora:commands"), 20)
    first = received(st, m0, "evora:commands")
    cat_fr = (first[0].get("payload") or {}) if first else None
    problems = judge_catalog(cat_fr, "fr")
    fin["catalogue_fr"] = {"recus": len(first), "compte": (cat_fr or {}).get("count"), "empreinte": (cat_fr or {}).get("hash"),
                           "ecarts": problems}
    if cat_fr and os.environ.get("EVORA_COMMANDS_OUT"):
        with open(os.environ["EVORA_COMMANDS_OUT"], "w", encoding="utf-8") as fh:
            json.dump(cat_fr, fh, ensure_ascii=False, indent=1)
        fin["catalogue_fr"]["ecrit"] = os.environ["EVORA_COMMANDS_OUT"]
    if problems:
        errors.append(f"[fin-catalogue] evora:commands après evora:init : {'; '.join(problems)}")

    # [fin-retraits] (avenant §5) : le catalogue livré, commande par commande, contre les marqueurs de retrait.
    removals = judge_removals(cat_fr)
    fin["retraits"] = {"marquees": [c.get("id") for c in (cat_fr or {}).get("commands") or [] if removal_marked(c)],
                       "exceptions": sorted(FIN_RETRAIT_EXCEPTIONS), "ecarts": removals}
    if removals:
        errors.append(f"[fin-retraits] commands.json : {'; '.join(removals)}")

    # Le document de la coquille (deux pages).
    if not reopen("initiale"):
        return

    # [fin-signatures] : l'enregistrement des réglages qui suit (perte de focus) les laisse hors du stockage.
    focus = ev(FOCUS, sess, ctx, gesture=True)
    settle(0.3)
    ev(BLUR, sess, ctx, gesture=True)
    raw, saved = None, None
    end = time.monotonic() + 8.0
    while time.monotonic() < end:
        settle(0.5)
        raw = ev(f"localStorage.getItem({json.dumps(own)})", sess, ctx)
        try:
            saved = json.loads(raw) if raw else None
        except ValueError:
            saved = None
        if isinstance(saved, dict) and saved.get("author") == "Compte Evora":
            break
    kept = [k for k in FIN_IDENTITY if isinstance(saved, dict) and k in saved]
    fin["signatures"] = {"focus": focus, "auteur": saved.get("author") if isinstance(saved, dict) else None,
                         "cles_identite_restees": kept, "repere_present": bool(raw and FIN_MARK in raw)}
    if not isinstance(saved, dict) or saved.get("author") != "Compte Evora":
        errors.append(f"[banc] réglages du compte non réécrits après evora:init (auteur {fin['signatures']['auteur']!r}) : "
                      "le contrôle des signatures ne peut pas rougir")
    elif kept or FIN_MARK in raw:
        errors.append(f"[fin-signatures] réglages écrits avec l'identité du membre : clés {kept}, repère "
                      f"« {FIN_MARK} » {'présent' if FIN_MARK in raw else 'absent'} (attendu : aucune)")

    # [fin-catalogue], en allemand : réémis, même empreinte, mêmes identifiants, libellés traduits.
    m1 = mark()
    lang = ev("window.__finSend('evora:lang', {lang: 'de', engineLang: 'de'})", page)
    st = wait(lambda s: answer(s, lang) is not None and received(s, m1, "evora:commands"), 20)
    second = received(st, m1, "evora:commands")
    cat_de = (second[0].get("payload") or {}) if second else None
    problems = judge_catalog(cat_de, "de")
    if cat_fr and cat_de:
        ids_fr = [c.get("id") for c in cat_fr.get("commands") or [] if isinstance(c, dict)]
        ids_de = [c.get("id") for c in cat_de.get("commands") or [] if isinstance(c, dict)]
        labels_fr = {c.get("id"): c.get("label") for c in cat_fr.get("commands") or [] if isinstance(c, dict)}
        moved = sum(1 for c in cat_de.get("commands") or [] if isinstance(c, dict) and labels_fr.get(c.get("id")) != c.get("label"))
        if cat_de.get("hash") != cat_fr.get("hash") or ids_de != ids_fr:
            problems.append(f"catalogue allemand d'une autre identité (empreinte {cat_de.get('hash')} contre {cat_fr.get('hash')})")
        if moved == 0:
            problems.append("aucun libellé traduit en allemand")
        fin["catalogue_de"] = {"empreinte": cat_de.get("hash"), "libelles_traduits": moved}
    if problems:
        errors.append(f"[fin-catalogue] evora:commands après evora:lang (de) : {'; '.join(problems)}")

    # [fin-export] : chaque export part vers la coquille, avec le type MIME de son format ; rien n'est téléchargé.
    exports = fin.setdefault("exports", [])
    why = []
    for cmd, ext, mime in FIN_EXPORTS:
        m = mark()
        rid, ack_cmd = command(cmd, {})
        st = wait(lambda s: received(s, m, "evora:export"), 15)
        sent = received(st, m, "evora:export")
        p = (sent[0].get("payload") or {}) if sent else {}
        b = (sent[0].get("binary") or {}).get("bytes") or {} if sent else {}
        exports.append({"commande": cmd, "accuse": ack_cmd, "exports": len(sent), "nom": p.get("name"), "mime": p.get("mime"),
                        "docRef": p.get("docRef"), "octets": b.get("byteLength")})
        if ack_cmd != {"ok": True}:
            why.append(f"{cmd} : accusé {ack_cmd}")
        if len(sent) != 1:
            why.append(f"{cmd} : {len(sent)} evora:export (attendu : 1)")
        elif (not str(p.get("name", "")).endswith(ext) or p.get("mime") != mime or p.get("docRef") != FIN_DOC
              or b.get("kind") != "[object ArrayBuffer]" or not (b.get("byteLength") or 0) >= 1):
            why.append(f"{cmd} : evora:export {{nom {p.get('name')!r}, mime {p.get('mime')!r}, docRef {p.get('docRef')!r}, "
                       f"octets {b}}} (attendu : *{ext}, {mime}, {FIN_DOC})")
    settle(1.0)
    early = json.loads(ev("JSON.stringify(window.__evoraFinEarly || null)", sess, ctx) or "null") or {}
    fin["telechargements"] = early.get("downloads")
    if early.get("downloads"):
        why.append(f"téléchargements du navigateur demandés par le moteur : {early.get('downloads')}")
    if why:
        errors.append(f"[fin-export] {'; '.join(why)}")

    # [fin-params] : des paramètres, et surtout un chemin, sont refusés sans effet ; prémisse : page.rotate {} agit.
    if not reopen("parametres"):
        return
    m = mark()
    refused = [command("page.rotate", params)[1] for params in FIN_BAD_PARAMS]
    settle(2.0)
    early_dirty = dirty(state(), m, True)
    m2 = mark()
    ok_rotate = command("page.rotate", {})[1]
    st = wait(lambda s: dirty(s, m2, True), 10)
    fin["parametres"] = {"refus": refused, "dirty_vrai_apres_refus": len(early_dirty), "rotation_sans_parametre": ok_rotate,
                         "dirty_vrai_apres_rotation": len(dirty(st, m2, True))}
    if any(r != {"ok": False, "code": "invalid_content"} for r in refused) or early_dirty:
        errors.append(f"[fin-params] page.rotate avec {list(FIN_BAD_PARAMS)} : accusés {refused}, document modifié "
                      f"{bool(early_dirty)} (attendu : invalid_content, sans effet)")
    elif ok_rotate != {"ok": True} or not dirty(st, m2, True):
        errors.append(f"[fin-params] page.rotate {{}} : accusé {ok_rotate}, document modifié {bool(dirty(st, m2, True))} "
                      "(attendu : {ok: true}, puis evora:dirty vrai)")

    # [fin-destructive] : page.delete et les destructives ajoutées par la correction 1 sans confirmed refusées sans
    # effet ; page.delete avec confirmed: true, exécutée.
    if not reopen("destructive"):
        return
    m = mark()
    unconfirmed = {cmd: command(cmd, {})[1] for cmd in FIN_DESTRUCTIVE_PROBES}
    settle(2.0)
    early_dirty = dirty(state(), m, True)
    m2 = mark()
    _, confirmed = command("page.delete", {}, True)
    st = wait(lambda s: dirty(s, m2, True), 10)
    fin["destructive"] = {"sans_confirmation": unconfirmed, "dirty_vrai_apres_refus": len(early_dirty),
                          "avec_confirmation": confirmed, "dirty_vrai_apres": len(dirty(st, m2, True))}
    ran = {c: a for c, a in unconfirmed.items() if a != {"ok": False, "code": "forbidden"}}
    if ran or early_dirty:
        errors.append(f"[fin-destructive] sans confirmed : accusés hors forbidden {ran}, document modifié "
                      f"{bool(early_dirty)} (attendu : forbidden pour chacune de {list(FIN_DESTRUCTIVE_PROBES)}, "
                      "sans effet)")
    elif confirmed != {"ok": True} or not dirty(st, m2, True):
        errors.append(f"[fin-destructive] page.delete avec confirmed : accusé {confirmed}, document modifié "
                      f"{bool(dirty(st, m2, True))} (attendu : {{ok: true}}, puis evora:dirty vrai)")

    # [fin-focus-out] : F6 rend le clavier à la coquille ; Maj+F6 ne le rend pas.
    focus = ev(FOCUS, sess, ctx, gesture=True)
    settle(0.3)
    m = mark()
    ev(FIN_F6 % "false", sess, ctx, gesture=True)
    st = wait(lambda s: received(s, m, "evora:focus-out"), 5)
    plain = received(st, m, "evora:focus-out")
    ev(FIN_F6 % "true", sess, ctx, gesture=True)
    settle(1.5)
    after_shift = received(state(), m, "evora:focus-out")
    fin["sortie_clavier"] = {"focus": focus, "f6": [x.get("payload") for x in plain], "apres_maj_f6": len(after_shift)}
    if focus is not True:
        errors.append("[banc] le canevas du moteur n'a pas pris le focus : sortie clavier non mesurable")
    elif len(plain) != 1 or plain[0].get("payload") != {} or plain[0].get("re") is not None or len(after_shift) != 1:
        errors.append(f"[fin-focus-out] F6 : {len(plain)} evora:focus-out {[x.get('payload') for x in plain]}, puis "
                      f"{len(after_shift)} après Maj+F6 (attendu : un evora:focus-out {{}}, et rien de plus)")

    # [fin-liste-blanche], en dernier : une commande hors catalogue n'est jamais exécutée.
    answers = {cmd: command(cmd, {})[1] for cmd in FIN_REFUSED}
    fin["hors_catalogue"] = answers
    wrong = {c: a for c, a in answers.items() if a != {"ok": False, "code": "capability"}}
    if wrong:
        errors.append(f"[fin-liste-blanche] commandes hors catalogue exécutées ou mal refusées : {wrong} "
                      "(attendu : {ok: false, code: capability})")

    # Enveloppes et charges utiles de tout ce que le moteur a envoyé (§3, §4.4, §4.5, §9.1).
    st = state()
    for msg in received(st):
        rule = PAYLOAD_KEYS.get(msg.get("type"))
        p = msg.get("payload") or {}
        if msg.get("v") != 1 or not msg.get("payloadPlain") or rule is None or not rule[0] <= set(p) <= rule[1] \
                or not ULID_RE.match(str(msg.get("id"))) or (msg.get("re") is not None and not ULID_RE.match(str(msg.get("re")))):
            errors.append(f"[ehp] message du moteur non conforme : {msg.get('type')} {sorted(p)}")
    if st.get("stray"):
        errors.append(f"[ehp] messages d'une autre source ou malformés reçus par la page parente : {st['stray'][:5]}")
    fin["messages"] = [{k: x.get(k) for k in ("sent", "type", "re", "payload")} for x in st.get("log", [])
                       if x.get("type") != "evora:commands"][-40:]


def error_tags(errors):
    return {m.group(1) for m in (re.match(r"^\[([^\]]+)\]", e) for e in errors) if m}


def mark_witness(witness, expected, description):
    """Un témoin sabordé est VALIDE s'il est rouge, et rouge par les seuls détecteurs `expected`."""
    tags = error_tags(witness["errors"])
    witness["sabotage_desc"] = description
    witness["expected_red"] = sorted(expected)
    witness["tags"] = sorted(tags)
    witness["witness_ok"] = (not witness["ok"]) and tags == expected
    return witness


def main(argv):
    if len(argv) != 5:
        print(__doc__)
        return 2
    site, hashes_file, out_dir, report_path = argv[1:]
    os.makedirs(out_dir, exist_ok=True)
    chrome_bin = (os.environ.get("EVORA_CHROME") or shutil.which("google-chrome") or shutil.which("google-chrome-stable")
                  or shutil.which("chromium"))
    if not chrome_bin:
        print("::error::Chrome introuvable sur le runner")
        return 1
    with open(hashes_file, encoding="utf-8") as fh:
        hashes = [line.strip() for line in fh if line.strip().startswith("sha256-")]
    audit = "evora-audit=1" in ENGINE_QUERY
    sep = "&" if "?" in ENGINE_QUERY else "?"
    en = f"{ENGINE_QUERY}{sep}evora-probe=Welcome" if audit else ENGINE_QUERY
    fr = f"{ENGINE_QUERY}{sep}lang=fr&theme=dark&evora-probe=Bienvenue"
    results = [run_scenario("sans-csp", site, None, out_dir, chrome_bin, en,
                            {"probe": "Welcome", "dark": False} if audit else None),
               run_scenario("csp", site, engine_csp(hashes), out_dir, chrome_bin, en,
                            {"probe": "Welcome", "dark": False} if audit else None)]
    if audit:
        # E3 : langue et thème imposés par l'URL du moteur, vérifiés au rendu.
        results.append(run_scenario("fr-sombre", site, engine_csp(hashes), out_dir, chrome_bin, fr,
                                    {"probe": "Bienvenue", "dark": True}))
        # E4 et E5 : pont EHP natif, origine parente admise par evora-host.json (run_ehp) ; à la fin,
        # thème sombre et onglet « evora-smoke.pdf » dessinés.
        ehp_query = "?host=evora&evora-audit=1&evora-probe=evora-smoke"
        results.append(run_scenario("pont-ehp", site, engine_csp(hashes), out_dir, chrome_bin, ehp_query,
                                    {"probe": "evora-smoke", "dark": True, "ehp": True}))
        # E5 hors pont : comportement amont inchangé (aucune purge au démarrage sans ?host=evora).
        results.append(run_scenario("hors-pont", site, engine_csp(hashes), out_dir, chrome_bin, en,
                                    {"probe": "Welcome", "dark": False, "upstream_storage": True}))
        # Témoin sabordé : le même banc que « pont-ehp », sur un moteur dont removeItem est sans effet.
        # Il DOIT être rouge, par les seuls détecteurs du stockage et de doc.dirty (WITNESS_EXPECTED).
        witness = run_scenario("pont-ehp-temoin", site, engine_csp(hashes), out_dir, chrome_bin, ehp_query,
                               {"probe": "evora-smoke", "dark": True, "ehp": True, "sabotage": WITNESS_SABOTAGE})
        results.append(mark_witness(witness, WITNESS_EXPECTED, f"{WITNESS_SABOTAGE} : removeItem sans effet dans le "
                                    "moteur (clés « effacées » cachées à son énumération), evora:dirty glissé avant "
                                    "evora:open"))
        # E5 entre pages de l'origine moteur : quatre moteurs (deux comptes) dans la même page parente.
        instances_query = "?host=evora&evora-audit=1"
        results.append(run_scenario("pont-deux-instances", site, engine_csp(hashes), out_dir, chrome_bin,
                                    instances_query, {"ehp": True, "instances": True}))
        # Son témoin : sans diffusion ni écouteur storage dans le moteur, il DOIT rougir par ses trois
        # seuls détecteurs (INSTANCES_EXPECTED).
        witness2 = run_scenario("pont-deux-instances-temoin", site, engine_csp(hashes), out_dir, chrome_bin,
                                instances_query, {"ehp": True, "instances": True, "sabotage": INSTANCES_SABOTAGE})
        results.append(mark_witness(witness2, INSTANCES_EXPECTED, f"{INSTANCES_SABOTAGE} : BroadcastChannel inerte et "
                                    "aucun écouteur storage dans les documents moteur"))
        # COL-08 et COL-09 : demande d'enregistrement et accusé (S-ACK), puis son témoin, qui DOIT rougir
        # par ses cinq seuls détecteurs (ACK_EXPECTED).
        accuse_query = "?host=evora&evora-audit=1"
        results.append(run_scenario("pont-accuse", site, engine_csp(hashes), out_dir, chrome_bin, accuse_query,
                                    {"ehp": True, "accuse": True}))
        witness3 = run_scenario("pont-accuse-temoin", site, engine_csp(hashes), out_dir, chrome_bin, accuse_query,
                                {"ehp": True, "accuse": True, "sabotage": ACK_SABOTAGE})
        results.append(mark_witness(witness3, ACK_EXPECTED, f"{ACK_SABOTAGE} : doc.saved-ack retiré d'evora:init "
                                    "(comportement amont), réouverture sous un autre docRef"))
        # COL-40 : robustesse du pont (mémoire d'eframe, purge de démarrage, accusé d'ouverture, docRef par
        # document), deux moteurs ; ses détecteurs rougissent sous le témoin groupé du lot COL-FK-B1.
        rob_query = ("?host=evora&evora-audit=1&evora-probe="
                     + urllib.parse.quote("|".join((ROB_TOAST, ROB_ENC_PROBE, ROB_LOCAL_PROBE)), safe=""))
        results.append(run_scenario("pont-robustesse", site, engine_csp(hashes), out_dir, chrome_bin, rob_query,
                                    {"ehp": True, "robustesse": True}))
        # COL-42 et COL-43 : export vers Drive, sortie clavier, signatures jamais écrites, catalogue de commandes
        # en liste blanche ; ses détecteurs rougissent sous le témoin groupé du lot COL-FK-B2.
        results.append(run_scenario("pont-finitions", site, engine_csp(hashes), out_dir, chrome_bin,
                                    "?host=evora&evora-audit=1", {"ehp": True, "finitions": True}))
        # COL-05, COL-10, OCR, Q47 (a) : masquages vus au rendu sur les surfaces du démarrage, et leurs
        # témoins (tests/evora_masks.rs juge toutes les autres surfaces).
        masks_query = (f"{ENGINE_QUERY}{sep}evora-probe="
                       + urllib.parse.quote("|".join(MASKED_PROBES + KEPT_PROBES), safe=""))
        results.append(run_scenario("masquages", site, engine_csp(hashes), out_dir, chrome_bin, masks_query,
                                    {"masks": True, "dark": False}))
    with open(os.path.join(out_dir, "smoke.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)

    def verdict(r):
        if "witness_ok" in r:
            return "ROUGE attendu : témoin VALIDE" if r["witness_ok"] else "témoin INVALIDE"
        return "VERT" if r["ok"] else "ROUGE"

    with open(report_path, "a", encoding="utf-8") as report:
        def log(line=""):
            print(line)
            report.write(line + "\n")
        log("### Test de fumée Chrome sans interface, origine croisée (bloquant)")
        log()
        log(f"Moteur servi par {ENGINE_ORIGIN}, encadré par une page de {PARENT_ORIGIN} ; origine non admise : "
            f"{INTRUDER_ORIGIN} ; profil vierge par scénario. "
            "URL de l'iframe : " + " ; ".join(f"{r['scenario']} index.html{r['query']}" for r in results))
        log(f"Navigateur : {results[0].get('chrome', '?')}")
        log()
        log("| Scénario | Résultat | Démarrage à froid : canvas dimensionné (iframe) | dont chargeur Trunk terminé | "
            "Depuis la navigation parente (sondage) | WebGL2 | Erreurs |")
        log("|---|---|---|---|---|---|---|")
        for r in results:
            log(f"| {r['scenario']} | {verdict(r)} | {r.get('cold_start_ms_iframe', 'n/d')} ms | "
                f"{r.get('trunk_started_ms', 'n/d')} ms | {r.get('cold_start_ms_parent', 'n/d')} ms | {r.get('gl', 'n/d')} | "
                f"{len(r['errors'])} |")
        log()
        for r in results:
            wasm = [x for x in r.get("resources", []) if x["name"].endswith(".wasm")]
            if wasm:
                log(f"- {r['scenario']} : .wasm chargé en {wasm[0]['dur']} ms ({wasm[0]['size']} octets transférés, sans compression HTTP)")
            log(f"- {r['scenario']} : messages reçus par la page parente : {r.get('parent_messages', [])}")
            if "ehp" in r:
                log(f"- {r['scenario']} : échanges EHP vus de la page parente : "
                    + " ; ".join(f"{m['type']}" + (f" (re {m['re'][-4:]})" if m.get('re') else "")
                                 + (f" {json.dumps(m['payload'], ensure_ascii=False)[:160]}" if m.get('payload') else "")
                                 for m in r["ehp"]["messages"]))
            if "capabilities" in r:
                log(f"- {r['scenario']} : capacités annoncées dans evora:ready : {r['capabilities']}")
            if "stockage" in r:
                log(f"- {r['scenario']} : stockage du moteur (E5) : "
                    + json.dumps({k: v for k, v in r["stockage"].items() if k != "journal"}, ensure_ascii=False)[:2400])
                if r["stockage"].get("journal"):
                    log(f"- {r['scenario']} : journal des écritures du stockage (fin) : "
                        + json.dumps(r["stockage"]["journal"], ensure_ascii=False)[:1600])
            if "storage_keys" in r:
                log(f"- {r['scenario']} : clés localStorage de l'origine moteur après rechargement : {r['storage_keys']}")
            if "audit" in r:
                log(f"- {r['scenario']} : audit au rendu E9/E10 (window.__evoraAudit) : {r['audit']}")
            if "masks" in r:
                log(f"- {r['scenario']} : masquages au rendu (textes dessinés qui contiennent chaque sonde) : "
                    + json.dumps(r["masks"], ensure_ascii=False))
            if "accuse" in r:
                log(f"- {r['scenario']} : demande d'enregistrement et accusé (COL-08, COL-09) : "
                    + json.dumps({k: v for k, v in r["accuse"].items() if k != "messages"}, ensure_ascii=False)[:2400])
                log(f"- {r['scenario']} : échanges (fin) : " + json.dumps(r["accuse"].get("messages", []), ensure_ascii=False)[:2400])
            if "instances" in r:
                log(f"- {r['scenario']} : stockage entre pages de l'origine moteur (E5) : "
                    + json.dumps({k: v for k, v in r["instances"].items() if k != "messages"}, ensure_ascii=False)[:2400])
            if "robustesse" in r:
                log(f"- {r['scenario']} : robustesse du pont (COL-40) : "
                    + json.dumps({k: v for k, v in r["robustesse"].items() if k != "messages"}, ensure_ascii=False)[:2400])
                log(f"- {r['scenario']} : étiquettes rouges : {sorted(error_tags(r['errors']))} "
                    f"(sous le témoin groupé du lot COL-FK-B1, attendues : {sorted(ROB_EXPECTED)} ; sous celui de "
                    f"sa correction 1 : {sorted(ROB_FIX_EXPECTED)})")
            if "finitions" in r:
                log(f"- {r['scenario']} : finitions du pont (COL-42, COL-43) : "
                    + json.dumps({k: v for k, v in r["finitions"].items() if k != "messages"}, ensure_ascii=False)[:4800])
                log(f"- {r['scenario']} : échanges (fin) : " + json.dumps(r["finitions"].get("messages", []), ensure_ascii=False)[:2400])
                log(f"- {r['scenario']} : étiquettes rouges : {sorted(error_tags(r['errors']))} "
                    f"(sous le témoin groupé du lot COL-FK-B2, attendues : {sorted(FIN_EXPECTED)} ; sous celui de "
                    f"sa correction 1 : {sorted(FIN_FIX_EXPECTED)})")
            if "witness_ok" in r:
                log(f"- {r['scenario']} : témoin sabordé ({r['sabotage_desc']}) ; "
                    f"détecteurs déclenchés {r['tags']} ; attendus {r['expected_red']} ; "
                    f"{'VALIDE' if r['witness_ok'] else 'INVALIDE : le banc ne rougit pas comme il le doit'}")
            for e in r["errors"]:
                log(f"  - {e}")
        log()
        if any(r.get("csp") for r in results):
            log(f"CSP appliquée au scénario « csp » : `{engine_csp(hashes)}`")
            log()
    for r in results:
        print(f"::notice::fumée {r['scenario']} : {verdict(r)}, démarrage à froid "
              f"{r.get('cold_start_ms_iframe', 'n/d')} ms (iframe), {r.get('cold_start_ms_parent', 'n/d')} ms (parent)")
        if "witness_ok" in r:
            if not r["witness_ok"]:
                print(f"::error::fumée {r['scenario']} : témoin INVALIDE, détecteurs {r['tags']} au lieu de {r['expected_red']}")
            continue
        for e in r["errors"]:
            print(f"::error::fumée {r['scenario']} : {e[:900]}")
    green = all(r["ok"] for r in results if "witness_ok" not in r)
    witnesses = all(r["witness_ok"] for r in results if "witness_ok" in r)
    return 0 if green and witnesses else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

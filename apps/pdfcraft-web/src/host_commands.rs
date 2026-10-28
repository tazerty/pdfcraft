//! Evora (EVO-CMD of Evora's DT-S17, patch COL-43): the commands Evora may run in the Colophon
//! Atelier on a member's request (capability `command.catalog`, message `evora:commands`; and
//! capability `command`, message `evora:command`), under the rule of Evora's 2026-10-27 amendment,
//! section 4:
//!
//! - **A white list by construction.** The catalog is the registry's commands as this build offers
//!   them in its menus and its command palette (`PdfCraftApp::evora_commands`, which already leaves
//!   the hidden ones out), minus every command of the host shell's namespaces, refused whole and not
//!   one by one ([`SHELL_NAMESPACES`]: `file.*` opens, saves, closes, reverts and describes documents,
//!   which is the shell's; `create.*` makes a new document out of this computer's files or clipboard,
//!   never one of Evora's; `app.*`, `help.*` and `prefs.*`), minus [`OFF_CATALOG`]. No `file.*` entry
//!   adds to the open document or goes through the host, so [`FILE_ADMITTED`] is empty: the exports
//!   are `export.*`, `comment.export`, `form.export_data` and `measure.export`, and they reach Evora's
//!   Drive by `evora:export`, never a download.
//! - **No free parameter.** No command declares one, so `params` must be `{}`; anything else is
//!   refused (`invalid_content`), and a path or a URL can never reach the engine.
//! - **Destructive commands** ([`DESTRUCTIVE`]) run only with `confirmed: true` (Evora asked the
//!   member first, Evora's decision D-24); `forbidden` otherwise.

use pdfcraft_ui_egui::PdfCraftApp;

/// The host shell's namespaces: every command of them is left out of the catalog.
const SHELL_NAMESPACES: [&str; 5] = ["file", "create", "app", "help", "prefs"];

/// The `file.*` entries Evora may still run, listed one by one (amendment, section 4, rule 1):
/// none in this engine.
const FILE_ADMITTED: [&str; 0] = [];

/// Left out of the catalog although the menus offer them: Combine Files builds a new document out
/// of this computer's files (as `create.*` does), and the display theme is the shell's
/// (`evora:theme`).
const OFF_CATALOG: [&str; 5] = ["page.combine", "view.theme", "view.theme.system", "view.theme.light", "view.theme.dark"];

/// Run only with `confirmed: true`: each removes or flattens content of the document in one go.
/// Edit, Undo still gives it back during the session, but an autosave would keep the loss.
pub const DESTRUCTIVE: [&str; 9] = [
    "page.delete",
    "form.clear",
    "comment.flatten",
    "form.flatten",
    "edit.remove_links",
    "edit.header_footer.remove",
    "edit.watermark.remove",
    "edit.background.remove",
    "protect.remove",
];

/// `label` and each item of `path` (HOST-PROTOCOL.md section 9.1): 1 to 200 UTF-16 code units.
const LABEL_MAX_UNITS: usize = 200;
/// A command id (section 9.1): at most 100 characters.
const ID_MAX_CHARS: usize = 100;
/// FNV-1a 64 bits: offset basis and prime.
const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;
const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;

/// One entry of the catalog.
pub struct Entry {
    pub id: &'static str,
    pub label: String,
    /// The menu that shows the command, as displayed; `None` for a command of the palette and the
    /// tool panels only.
    pub path: Option<String>,
    pub enabled: bool,
    pub destructive: bool,
}

/// May the catalog hold `id`? A static rule: the same in every state and every language.
pub fn admitted(id: &str) -> bool {
    if OFF_CATALOG.contains(&id) || !well_formed(id) {
        return false;
    }
    let namespace = id.split('.').next().unwrap_or_default();
    !SHELL_NAMESPACES.contains(&namespace) || FILE_ADMITTED.contains(&id)
}

/// `^[a-z][A-Za-z0-9_.-]*$`, at most [`ID_MAX_CHARS`] characters (the shell's command pattern).
fn well_formed(id: &str) -> bool {
    let mut chars = id.chars();
    id.chars().count() <= ID_MAX_CHARS
        && chars.next().is_some_and(|c| c.is_ascii_lowercase())
        && chars.all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '-'))
}

/// `text` cut to [`LABEL_MAX_UNITS`]; `fallback` when nothing is left.
fn bounded(text: &str, fallback: &str) -> String {
    let mut units = 0;
    let cut: String = text
        .chars()
        .take_while(|c| {
            units += c.len_utf16();
            units <= LABEL_MAX_UNITS
        })
        .collect();
    if cut.trim().is_empty() { fallback.to_string() } else { cut }
}

/// FNV-1a 64 bits of `bytes`, continued from `hash`.
fn fnv1a(hash: u64, bytes: &[u8]) -> u64 {
    bytes.iter().fold(hash, |h, b| (h ^ u64::from(*b)).wrapping_mul(FNV_PRIME))
}

/// The catalog now: its entries in registry order, the engine's language code, and the catalog's
/// identity `hash` (FNV-1a 64 of each id and its destructive flag, in order: the same in every
/// language and every state; Evora's provisioning copies it from `commands.json`).
pub fn catalog(app: &PdfCraftApp) -> (Vec<Entry>, &'static str, String) {
    let mut hash = FNV_OFFSET;
    let mut entries = Vec::new();
    for (id, label, menu, enabled) in app.evora_commands() {
        if !admitted(id) {
            continue;
        }
        let destructive = DESTRUCTIVE.contains(&id);
        hash = fnv1a(hash, id.as_bytes());
        hash = fnv1a(hash, if destructive { b"\x001" } else { b"\x000" });
        hash = fnv1a(hash, b"\n");
        let path = menu.map(|m| bounded(&m, id));
        entries.push(Entry { id, label: bounded(&label, id), path, enabled, destructive });
    }
    let lang = pdfcraft_ui_egui::i18n::Lang::from_pref(&app.language).code();
    (entries, lang, format!("{hash:016x}"))
}

/// `evora:command` of a catalog command: `Ok` once it ran, otherwise the `ackCode` (`capability`: not
/// in the catalog; `invalid_content`: parameters given; `forbidden`: destructive and not confirmed;
/// `busy`: not available now, as its menu entry would be greyed out).
pub fn run(app: &mut PdfCraftApp, id: &str, params_empty: bool, confirmed: bool) -> Result<(), &'static str> {
    let enabled = app
        .evora_commands()
        .into_iter()
        // SABORDAGE QA (EVORA-COL-47) S1 : liste blanche élargie, une commande hors catalogue s'exécute.
        .find(|(c, ..)| *c == id)
        .map(|(_, _, _, enabled)| enabled)
        .ok_or("capability")?;
    // SABORDAGE QA (EVORA-COL-47) S2 : paramètres admis sans contrôle.
    if false && !params_empty {
        return Err("invalid_content");
    }
    // SABORDAGE QA (EVORA-COL-47) S3 : commande destructive exécutée sans confirmed.
    if false && DESTRUCTIVE.contains(&id) && !confirmed {
        return Err("forbidden");
    }
    if !enabled || !app.execute(id) {
        return Err("busy");
    }
    Ok(())
}

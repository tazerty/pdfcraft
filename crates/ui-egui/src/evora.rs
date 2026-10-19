//! Evora (patches E7, COL-05, COL-10): what the Colophon Atelier build, served inside Evora, does not
//! offer, and the guard that keeps it out of reach.
//!
//! - E7: the app's own outbound links (the upstream source repository) and the update check (which,
//!   on the web, opens the upstream releases page). Updates of the Atelier are Evora's (pinned
//!   upstream tag, rebuilt by the fork's CI).
//! - COL-05 (Evora decision D-9): digital signatures (PAdES), certification and the creation of
//!   self-signed digital IDs, which happens in the signing dialog only, belong to Evora Sign. The
//!   Signatures panel still shows and validates signatures (read only); Fill & Sign stays.
//! - COL-10 (D-9): redaction is done by Colophon's server tool, which really removes the content,
//!   until a server-side check of redacted areas exists.
//! - OCR: the engine recognizes unaccented Latin script only; Colophon's server OCR tool does the
//!   job, and the guided actions that recognize text (Action Wizard steps) go with it.
//! - Q47 (a), Evora's default hypothesis until it is decided: the Atelier does fine editing only.
//!   The upstream automations, the engine's own recent files, XFDF and FDF imports, the JavaScript
//!   console, the rest of the redaction family (sanitize, remove hidden information), the rest of the
//!   Scan & OCR family (camera images) and editing existing text (until Evora Drive keeps versions,
//!   F7) are hidden too.
//!
//! Hidden commands and catalogue items stay out of the menus, the command palette, the keyboard
//! shortcuts list, the tool panels and Home, and do nothing if run another way; a tool group whose
//! items are all hidden disappears. Every frame, [`enforce`] closes a dialog, drops a page tool and
//! leaves a tool panel that only a hidden command opens, whatever opened it (a click on an empty
//! signature field, the Signatures panel, automation). Links found in documents are not affected:
//! they keep their confirmation dialog.

use pdfcraft_engine::catalog::{self, ToolGroup};

use crate::{Dialog, LeftPanel, PdfCraftApp, QuickTool};

/// Registry commands and catalogue items hidden from every list and ignored when run.
pub(crate) const HIDDEN_COMMANDS: &[&str] = &[
    // E7.
    "help.github",
    "help.check_updates",
    // COL-05 (D-9): digital signatures, certification, the digital IDs created for them, and the
    // timestamp the catalogue plans beside them.
    "sign.digital",
    "sign.certify",
    "sign.certify_invisible",
    "sign.timestamp",
    // COL-10 (D-9): redaction.
    "redact.mark",
    "redact.pages",
    "redact.search",
    "redact.properties",
    "redact.apply",
    "redact.clear",
    // OCR, planned OCR items, and the guided actions that recognize text.
    "ocr.recognize",
    "ocr.recognize_batch",
    "ocr.enhance",
    "ocr.correct",
    "actions.wizard",
    "actions.optimize_scans",
    // Q47 (a), default hypothesis: upstream automations.
    "actions.distribution",
    "actions.make_accessible",
    "actions.archive",
    // Q47 (a): the engine's recent files (Evora Drive keeps the documents).
    "file.open_recent",
    "file.clear_recent",
    "file.pin_folder",
    // Q47 (a): XFDF and FDF imports.
    "comment.import",
    "form.import_data",
    // Q47 (a): the JavaScript console (document scripts and scripted forms stay).
    "tools.js_console",
    "js.console",
    // Q47 (a): the rest of the redaction family.
    "redact.sanitize",
    "protect.remove_hidden",
    // Q47 (a): the rest of the Scan & OCR family.
    "ocr.enhance_camera",
    // Q47 (a): editing existing text, until Evora Drive keeps versions (F7).
    "edit.edit_text",
];

pub(crate) fn hidden(id: &str) -> bool {
    HIDDEN_COMMANDS.contains(&id)
}

/// A tool group with items, all of them hidden.
pub(crate) fn hidden_group(group: &ToolGroup) -> bool {
    group.sections.iter().any(|s| !s.items.is_empty()) && group.sections.iter().flat_map(|s| s.items).all(|i| hidden(i.command))
}

/// The catalogue's tool groups still on offer, in catalogue order.
pub(crate) fn visible_groups() -> impl Iterator<Item = &'static ToolGroup> {
    catalog::TOOL_GROUPS.iter().filter(|g| !hidden_group(g))
}

/// The tool groups the command palette lists: [`visible_groups`]. Under the CI witness
/// `evora-witness-palette-groups` (never in the web build), every catalogue group, as upstream, so
/// that tests/evora_masks.rs shows its palette checks of hidden groups fail without this filter.
pub(crate) fn palette_groups() -> impl Iterator<Item = &'static ToolGroup> {
    catalog::TOOL_GROUPS.iter().filter(|g| cfg!(feature = "evora-witness-palette-groups") || !hidden_group(g))
}

/// Whether tool panel `id` may open (an id the catalogue doesn't know is left to the caller).
pub(crate) fn tool_allowed(id: &str) -> bool {
    catalog::group(id).is_none_or(|g| !hidden_group(g))
}

/// The command a dialog belongs to, when only that command's family opens it.
fn dialog_command(dialog: &Dialog) -> Option<&'static str> {
    Some(match dialog {
        // Digitally sign, Certify, a click on an empty signature field, the Signatures panel.
        Dialog::Sign => "sign.digital",
        Dialog::RedactPages => "redact.pages",
        Dialog::RedactSearch => "redact.search",
        Dialog::RedactProps => "redact.properties",
        Dialog::RedactApply => "redact.apply",
        Dialog::RecognizeText => "ocr.recognize",
        // The Action Wizard runs and edits actions whose steps recognize text.
        Dialog::ActionWizard => "actions.wizard",
        Dialog::JsConsole => "tools.js_console",
        Dialog::Sanitize => "redact.sanitize",
        Dialog::RemoveHidden => "protect.remove_hidden",
        _ => return None,
    })
}

/// The command a page tool belongs to.
fn tool_command(tool: &QuickTool) -> Option<&'static str> {
    Some(match tool {
        QuickTool::SignArea { certify: false } => "sign.digital",
        QuickTool::SignArea { certify: true } => "sign.certify",
        QuickTool::Redact => "redact.mark",
        QuickTool::EnhanceCamera => "ocr.enhance_camera",
        QuickTool::EditText => "edit.edit_text",
        _ => return None,
    })
}

/// Run at the start of every frame (`logic` and `ui`): no dialog, page tool or tool panel that only
/// a hidden command opens stays open, whatever opened it.
pub(crate) fn enforce(app: &mut PdfCraftApp) {
    // CI witness only (`--features evora-witness-enforce`, never in the web build): the guard is off.
    if cfg!(feature = "evora-witness-enforce") {
        return;
    }
    if app.dialog.as_ref().and_then(dialog_command).is_some_and(hidden) {
        app.dialog = None;
    }
    if tool_command(&app.quick_tool).is_some_and(hidden) {
        app.quick_tool = QuickTool::Select;
    }
    if let LeftPanel::Tool(id) = app.left
        && !tool_allowed(id)
    {
        app.left = LeftPanel::AllTools;
    }
}

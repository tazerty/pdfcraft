//! Evora (EVORA-COL-25): what the Colophon Atelier must not offer, judged in the real shell
//! (egui_kittest + AccessKit, like `tests/ui.rs`) on every surface that lists commands: All tools,
//! the tool panels, Home, the command palette, the File menu, the keyboard shortcuts list, the
//! Signatures and Comments panels, and the state that commands, automation and a click on an empty
//! signature field leave behind.
//!
//! The list judged here is written below, independently of `src/evora.rs` (a recipe must not read
//! what it judges), from the Evora decisions: D-9 (COL-05: digital signatures, certification and the
//! self-signed digital IDs created for them are Evora Sign's; COL-10: redaction is Colophon's server
//! tool), the OCR rule of the suite (`apps/creative/CLAUDE.md` §5.9 in Evora) and Q47 (a), the
//! default hypothesis until it is decided. Labels come from the engine's registry and catalogue.
//!
//! Each test collects every fault before failing, so a red run names each missing mask, and prints
//! its count of checks, which must not change from run to run. Kept neighbours are witnesses
//! (validating signatures, Fill & Sign, document scripts, adding text, exporting form data, the
//! Preferences): they must stay reachable, so a surface that isn't drawn can't pass for a mask.
//!
//! EVORA-COL-32: the palette lists tool groups too (`palette.rs`); a hidden group (Scan & OCR, Redact
//! a PDF, Use guided actions) is searched for there by its label, beside a kept group that must be
//! proposed (twin witness). The CI witness `evora-witness-palette-groups` reopens every group in the
//! palette: these checks, and they alone, must then fail (judged by `gates.py masks-witness`).
//!
//! EVORA-COL-38 (rise to v0.14.0): the expanded All tools view (« Expand all tools », all_tools_ui.rs)
//! lists the catalogue's tools by category and names the items a search finds; a hidden tool must have
//! no tile and a hidden item no mention (family « vue-outils »). The Edit workspace's quick bar offers
//! « Edit text & images » (Q47 (a)): it must not while editing existing text is hidden.

use egui_kittest::Harness;
use egui_kittest::kittest::Queryable;
use pdfcraft_engine::catalog::TOOL_GROUPS;
use pdfcraft_engine::commands::COMMANDS;
use pdfcraft_ui_egui::{Dialog, LeftPanel, Mode, PdfCraftApp, QuickTool, RightPanel};

/// D-9, COL-05: digital signatures, certification, and the timestamp planned beside them.
const SIGNATURE: &[&str] = &["sign.digital", "sign.certify", "sign.certify_invisible", "sign.timestamp"];
/// D-9, COL-10: redaction.
const REDACTION: &[&str] = &["redact.mark", "redact.pages", "redact.search", "redact.properties", "redact.apply", "redact.clear"];
/// The engine's OCR (unaccented Latin script only), planned OCR items, and the guided actions that
/// recognize text.
const OCR: &[&str] = &["ocr.recognize", "ocr.recognize_batch", "ocr.enhance", "ocr.correct", "actions.wizard", "actions.optimize_scans"];
/// Q47 (a), default hypothesis: upstream automations, the engine's recent files, XFDF and FDF
/// imports, the JavaScript console, the rest of the redaction and Scan & OCR families, editing
/// existing text (until Evora Drive keeps versions, F7).
const SCOPE: &[&str] = &[
    "actions.distribution",
    "actions.make_accessible",
    "actions.archive",
    "file.open_recent",
    "file.clear_recent",
    "file.pin_folder",
    "comment.import",
    "form.import_data",
    "tools.js_console",
    "js.console",
    "redact.sanitize",
    "protect.remove_hidden",
    "ocr.enhance_camera",
    "edit.edit_text",
];
/// Tool groups whose items are all hidden: they must disappear.
const HIDDEN_GROUPS: &[&str] = &["scan", "redact", "actions"];
/// Commands that open a native file picker (they can't run headless, see `tests/commands.rs`).
const PICKERS: &[&str] = &["ocr.recognize_batch", "file.pin_folder", "comment.import", "form.import_data", "file.open_recent"];

/// Collects faults, so that a red run names every one of them.
struct Verdict {
    name: &'static str,
    checks: usize,
    faults: Vec<String>,
}

impl Verdict {
    fn new(name: &'static str) -> Self {
        Self { name, checks: 0, faults: Vec::new() }
    }

    fn holds(&mut self, ok: bool, fault: impl FnOnce() -> String) {
        self.checks += 1;
        if !ok {
            self.faults.push(fault());
        }
    }

    /// `label` is neither an AccessKit node (exact label) nor a painted text (exact text).
    fn absent(&mut self, h: &Harness<'static, PdfCraftApp>, surface: &str, label: &str) {
        let (n, t) = (nodes(h, label), painted_exact(h, label));
        self.holds(n + t == 0, || format!("{surface} : « {label} » visible ({n} nœud(s), {t} texte(s) dessiné(s))"));
    }

    /// `label` is not an AccessKit node (exact label): for the palette, whose search field paints
    /// the query itself.
    fn absent_node(&mut self, h: &Harness<'static, PdfCraftApp>, surface: &str, label: &str) {
        let n = nodes(h, label);
        self.holds(n == 0, || format!("{surface} : « {label} » proposé ({n} nœud(s))"));
    }

    /// No AccessKit node and no painted text contains `needle`.
    fn absent_contains(&mut self, h: &Harness<'static, PdfCraftApp>, surface: &str, needle: &str) {
        let n = h.query_all_by_label_contains(needle).count() + painted(h).iter().filter(|t| t.contains(needle)).count();
        self.holds(n == 0, || format!("{surface} : « {needle} » visible ({n} fois, sous-chaîne)"));
    }

    /// Witness: `label` is on screen (AccessKit node or painted text, exact).
    fn present(&mut self, h: &Harness<'static, PdfCraftApp>, surface: &str, label: &str) {
        let n = nodes(h, label) + painted_exact(h, label);
        self.holds(n > 0, || format!("{surface} : témoin « {label} » absent (surface non dessinée ?)"));
    }

    /// Witness: a node or a painted text contains `needle`.
    fn present_contains(&mut self, h: &Harness<'static, PdfCraftApp>, surface: &str, needle: &str) {
        let n = h.query_all_by_label_contains(needle).count() + painted(h).iter().filter(|t| t.contains(needle)).count();
        self.holds(n > 0, || format!("{surface} : témoin « {needle} » absent (surface non dessinée ?)"));
    }

    fn finish(self) {
        eprintln!("[{}] {} contrôle(s), {} faute(s)", self.name, self.checks, self.faults.len());
        for f in &self.faults {
            eprintln!("[{}] FAUTE {f}", self.name);
        }
        assert!(self.faults.is_empty(), "{} : {} faute(s) sur {} contrôle(s), détail ci-dessus", self.name, self.faults.len(), self.checks);
    }
}

fn nodes(h: &Harness<'static, PdfCraftApp>, label: &str) -> usize {
    h.query_all_by_label(label).count()
}

/// Every text painted on the last frame (whole texts, even when drawn cut short).
fn painted(h: &Harness<'static, PdfCraftApp>) -> Vec<String> {
    h.output()
        .shapes
        .iter()
        .filter_map(|c| match &c.shape {
            egui::Shape::Text(t) => Some(t.galley.text().to_owned()),
            _ => None,
        })
        .collect()
}

fn painted_exact(h: &Harness<'static, PdfCraftApp>, label: &str) -> usize {
    painted(h).iter().filter(|t| t.as_str() == label).count()
}

/// The labels an id shows under: its registry label (with and without its "…") and its catalogue
/// items' labels.
fn labels(id: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut add = |label: &str| {
        if !label.is_empty() && !out.iter().any(|l| l == label) {
            out.push(label.to_string());
        }
    };
    if let Some(c) = COMMANDS.iter().find(|c| c.id == id) {
        add(c.label);
        add(c.label.trim_end_matches('…'));
    }
    for g in TOOL_GROUPS {
        for s in g.sections {
            for i in s.items {
                if i.command == id {
                    add(i.label);
                }
            }
        }
    }
    out
}

fn registered(id: &str) -> bool {
    COMMANDS.iter().any(|c| c.id == id)
}

fn group_label(id: &str) -> &'static str {
    TOOL_GROUPS.iter().find(|g| g.id == id).map_or("", |g| g.label)
}

/// Painted tile notes of the expanded All tools view that name `label`: a note lists the items the
/// search found the tool by, joined by « · » (all_tools_ui.rs `tile`).
fn named_in_notes(h: &Harness<'static, PdfCraftApp>, label: &str) -> usize {
    painted(h).iter().filter(|t| t.split(" · ").any(|s| s == label)).count()
}

/// The expanded All tools view searched for `label`, typed in lower case without its « … » (the
/// search field paints what is typed, which then differs from every label).
fn view_search(h: &mut Harness<'static, PdfCraftApp>, label: &str) {
    h.state_mut().all_tools_query = label.trim_end_matches('…').to_lowercase();
    h.run_steps(3);
}

/// A PDF built from its objects (numbered from 1), with a cross-reference table.
fn pdf(objects: &[&str]) -> Vec<u8> {
    let mut out = b"%PDF-1.7\n".to_vec();
    let mut offsets = Vec::new();
    for (i, o) in objects.iter().enumerate() {
        offsets.push(out.len());
        out.extend_from_slice(format!("{} 0 obj\n{o}\nendobj\n", i + 1).as_bytes());
    }
    let xref = out.len();
    out.extend_from_slice(format!("xref\n0 {}\n0000000000 65535 f \n", objects.len() + 1).as_bytes());
    for o in offsets {
        out.extend_from_slice(format!("{o:010} 00000 n \n").as_bytes());
    }
    out.extend_from_slice(format!("trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n", objects.len() + 1).as_bytes());
    out
}

/// One page with text, an unsigned digital signature field (« Signature1 ») and a sticky note.
fn fixture() -> Vec<u8> {
    let body = "BT /F1 14 Tf 20 150 Td (Atelier) Tj ET";
    let contents = format!("<< /Length {} >>\nstream\n{body}\nendstream", body.len());
    pdf(&[
        "<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [5 0 R] /SigFlags 1 >> >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 /MediaBox [0 0 300 200] >>",
        "<< /Type /Page /Parent 2 0 R /Contents 4 0 R /Resources << /Font << /F1 6 0 R >> >> /Annots [5 0 R 7 0 R] >>",
        contents.as_str(),
        "<< /Type /Annot /Subtype /Widget /FT /Sig /T (Signature1) /Rect [20 20 160 60] /P 3 0 R /F 4 >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        "<< /Type /Annot /Subtype /Text /Rect [250 170 270 190] /T (Tester) /Contents (Check the numbers) /P 3 0 R >>",
    ])
}

fn harness(document: bool, setup: impl FnOnce(&mut PdfCraftApp) + 'static) -> Harness<'static, PdfCraftApp> {
    let mut h = Harness::builder().with_size(egui::vec2(1400.0, 1000.0)).build_eframe(move |_cc| {
        let mut app = PdfCraftApp::new();
        app.set_option("language", "en").unwrap();
        if document {
            app.open_bytes("atelier.pdf", None, fixture()).expect("the fixture opens");
        }
        setup(&mut app);
        app
    });
    // Fonts install on frame 1 and apply on frame 2.
    h.run_steps(4);
    h
}

/// Back to a calm state between checks: no dialog, palette or page tool.
fn calm(h: &mut Harness<'static, PdfCraftApp>) {
    let app = h.state_mut();
    app.dialog = None;
    app.palette_open = false;
    app.palette_query.clear();
    app.quick_tool = QuickTool::Select;
    h.run_steps(2);
}

/// The palette searched for `label`, typed in lower case without its "…" (the search field paints
/// what is typed, which then differs from every label).
fn palette_for(h: &mut Harness<'static, PdfCraftApp>, label: &str) {
    calm(h);
    let query = label.trim_end_matches('…').to_lowercase();
    h.state_mut().set_option("palette", &query).unwrap();
    h.run_steps(3);
}

/// All tools, expanded (« View more »).
fn all_tools(h: &mut Harness<'static, PdfCraftApp>) {
    calm(h);
    let app = h.state_mut();
    app.left_open = true;
    app.left = LeftPanel::AllTools;
    app.all_tools_expanded = true;
    h.run_steps(3);
}

/// Tool panel `id`, asked as automation does (`--tool`).
fn tool_panel(h: &mut Harness<'static, PdfCraftApp>, id: &str) {
    calm(h);
    h.state_mut().left_open = true;
    let _ = h.state_mut().set_option("tool", id);
    h.run_steps(3);
}

/// The palette proposes none of `ids`' labels.
fn palette_offers_none(v: &mut Verdict, h: &mut Harness<'static, PdfCraftApp>, ids: &[&'static str]) {
    for id in ids {
        for label in labels(id) {
            palette_for(h, &label);
            v.holds(h.state().palette_open, || format!("palette « {label} » : la palette ne s'est pas ouverte"));
            v.absent_node(h, &format!("palette « {label} »"), &label);
        }
    }
}

/// Tool group `id` searched for in the palette by its label (EVORA-COL-32), with the tool panel closed
/// so that All tools or a tool panel can't show the label: a hidden group must not be proposed, a kept
/// one must (the twin, which shows the palette lists groups at all). The label must be on no node
/// before the palette opens, so that a node found afterwards is the palette's. One check per search;
/// each cause of a fault has its own wording (`gates.py masks-witness` reads « proposé »).
fn palette_group(v: &mut Verdict, h: &mut Harness<'static, PdfCraftApp>, id: &str, offered: bool) {
    let label = group_label(id);
    let was_open = h.state().left_open;
    calm(h);
    h.state_mut().left_open = false;
    h.run_steps(3);
    let before = nodes(h, label);
    palette_for(h, label);
    let (open, after) = (h.state().palette_open, nodes(h, label));
    let fault = if label.is_empty() {
        Some(format!("groupe de palette {id} : libellé introuvable au catalogue"))
    } else if before > 0 {
        Some(format!("groupe de palette {id} : « {label} » déjà à l'écran avant la palette ({before} nœud(s)), mesure impossible"))
    } else if !open {
        Some(format!("groupe de palette {id} : la palette ne s'est pas ouverte"))
    } else if offered && after == 0 {
        Some(format!("groupe de palette {id} : témoin « {label} » non proposé"))
    } else if !offered && after > 0 {
        Some(format!("groupe de palette {id} : « {label} » proposé ({after} nœud(s))"))
    } else {
        None
    };
    v.holds(fault.is_none(), move || fault.unwrap_or_default());
    calm(h);
    h.state_mut().left_open = was_open;
    h.run_steps(2);
}

/// Running `ids` (as menus, shortcuts and automation do) leaves no dialog of theirs, no page tool
/// of theirs and no tool panel of theirs.
fn running_leaves_nothing(v: &mut Verdict, h: &mut Harness<'static, PdfCraftApp>, ids: &[&'static str], dialogs: &[Dialog], tools: &[QuickTool]) {
    for id in ids.iter().filter(|id| registered(id) && !PICKERS.contains(id)) {
        calm(h);
        h.state_mut().left = LeftPanel::AllTools;
        let _ = h.state_mut().execute(id);
        h.run_steps(3);
        let app = h.state();
        let dialog = app.dialog;
        let tool = app.quick_tool;
        let left = app.left;
        v.holds(dialog.is_none_or(|d| !dialogs.contains(&d)), || format!("exécution de {id} : dialogue {dialog:?} ouvert"));
        v.holds(!tools.contains(&tool), || format!("exécution de {id} : outil de page {tool:?} actif"));
        v.holds(!matches!(left, LeftPanel::Tool(g) if HIDDEN_GROUPS.contains(&g)), || format!("exécution de {id} : panneau {left:?} ouvert"));
    }
}

/// Dialogs and page tools set directly (automation, any other path) don't survive a frame.
fn forced_state_closes(v: &mut Verdict, h: &mut Harness<'static, PdfCraftApp>, dialogs: &[Dialog], tools: &[QuickTool]) {
    for d in dialogs {
        calm(h);
        h.state_mut().dialog = Some(*d);
        h.run_steps(3);
        let still = h.state().dialog;
        v.holds(still != Some(*d), || format!("dialogue {d:?} posé directement : toujours ouvert"));
    }
    for t in tools {
        calm(h);
        h.state_mut().quick_tool = *t;
        h.run_steps(3);
        let still = h.state().quick_tool;
        v.holds(still != *t, || format!("outil de page {t:?} posé directement : toujours actif"));
    }
}

#[test]
fn every_masked_id_is_in_the_registry_or_the_catalogue() {
    let mut v = Verdict::new("ids");
    let catalogued = |id: &str| TOOL_GROUPS.iter().flat_map(|g| g.sections.iter().flat_map(|s| s.items)).any(|i| i.command == id);
    for id in SIGNATURE.iter().chain(REDACTION).chain(OCR).chain(SCOPE) {
        v.holds(registered(id) || catalogued(*id), || format!("{id} : ni au registre ni au catalogue (masquage sans objet)"));
        v.holds(!labels(id).is_empty(), || format!("{id} : aucun libellé"));
    }
    for g in HIDDEN_GROUPS {
        let group = TOOL_GROUPS.iter().find(|x| x.id == *g);
        v.holds(group.is_some(), || format!("groupe {g} inconnu du catalogue"));
        for i in group.into_iter().flat_map(|x| x.sections.iter().flat_map(|s| s.items)) {
            let listed = SIGNATURE.iter().chain(REDACTION).chain(OCR).chain(SCOPE).any(|id| *id == i.command);
            v.holds(listed, || format!("groupe {g} : {} n'est pas dans la liste, le groupe ne peut pas disparaître", i.command));
        }
    }
    v.finish();
}

#[test]
fn digital_signatures_certification_and_identities_are_out_of_reach() {
    let mut v = Verdict::new("signature");
    let mut h = harness(true, |_| {});
    palette_offers_none(&mut v, &mut h, SIGNATURE);
    tool_panel(&mut h, "certificate");
    for id in SIGNATURE {
        for label in labels(id) {
            v.absent(&h, "panneau « Use a certificate »", &label);
        }
    }
    v.present(&h, "panneau « Use a certificate »", "Validate all signatures");
    // The Signatures panel shows the unsigned field, without a way to sign it.
    calm(&mut h);
    {
        let app = h.state_mut();
        app.right = Some(RightPanel::Signatures);
        app.sig_expanded = vec!["Signature1".to_string()];
    }
    h.run_steps(4);
    v.present(&h, "panneau Signatures", "Unsigned signature field: Signature1");
    v.absent(&h, "panneau Signatures", "Sign this field…");
    running_leaves_nothing(&mut v, &mut h, SIGNATURE, &[Dialog::Sign], &[QuickTool::SignArea { certify: false }, QuickTool::SignArea { certify: true }]);
    // A click on the empty field, and automation, open the signing dialog (where digital IDs are
    // created) or the signature area tool: none of them may stay.
    calm(&mut h);
    h.state_mut().start_signing(0, None, Some("Signature1".to_string()), None);
    h.run_steps(3);
    let dialog = h.state().dialog;
    v.holds(dialog != Some(Dialog::Sign), || format!("clic sur le champ vide : dialogue {dialog:?} ouvert"));
    for (key, value) in [("dialog", "sign"), ("dialog", "certify"), ("quick", "sign"), ("quick", "certify")] {
        calm(&mut h);
        let _ = h.state_mut().set_option(key, value);
        h.run_steps(3);
        let (dialog, tool) = (h.state().dialog, h.state().quick_tool);
        v.holds(dialog != Some(Dialog::Sign) && !matches!(tool, QuickTool::SignArea { .. }), || {
            format!("automatisation --{key} {value} : dialogue {dialog:?}, outil {tool:?}")
        });
    }
    forced_state_closes(&mut v, &mut h, &[Dialog::Sign], &[QuickTool::SignArea { certify: false }, QuickTool::SignArea { certify: true }]);
    v.finish();
}

#[test]
fn redaction_is_out_of_reach() {
    let mut v = Verdict::new("caviardage");
    let mut h = harness(true, |_| {});
    all_tools(&mut h);
    v.absent(&h, "All tools", group_label("redact"));
    v.present(&h, "All tools", group_label("protect"));
    palette_offers_none(&mut v, &mut h, REDACTION);
    palette_group(&mut v, &mut h, "redact", false);
    palette_group(&mut v, &mut h, "export", true);
    tool_panel(&mut h, "redact");
    let left = h.state().left;
    v.holds(left != LeftPanel::Tool("redact"), || format!("--tool redact : panneau {left:?} ouvert"));
    let dialogs = [Dialog::RedactPages, Dialog::RedactSearch, Dialog::RedactProps, Dialog::RedactApply];
    running_leaves_nothing(&mut v, &mut h, REDACTION, &dialogs, &[QuickTool::Redact]);
    calm(&mut h);
    let _ = h.state_mut().set_option("quick", "redact");
    h.run_steps(3);
    let tool = h.state().quick_tool;
    v.holds(tool != QuickTool::Redact, || format!("automatisation --quick redact : outil {tool:?}"));
    forced_state_closes(&mut v, &mut h, &dialogs, &[QuickTool::Redact]);
    v.finish();
}

#[test]
fn ocr_and_the_guided_actions_that_run_it_are_out_of_reach() {
    let mut v = Verdict::new("ocr");
    let mut h = harness(true, |_| {});
    all_tools(&mut h);
    v.absent(&h, "All tools", group_label("scan"));
    v.absent(&h, "All tools", group_label("actions"));
    v.present(&h, "All tools", group_label("compress"));
    palette_offers_none(&mut v, &mut h, OCR);
    palette_group(&mut v, &mut h, "scan", false);
    palette_group(&mut v, &mut h, "actions", false);
    palette_group(&mut v, &mut h, "compress", true);
    for g in ["scan", "actions"] {
        tool_panel(&mut h, g);
        let left = h.state().left;
        v.holds(left != LeftPanel::Tool(g), || format!("--tool {g} : panneau {left:?} ouvert"));
    }
    running_leaves_nothing(&mut v, &mut h, OCR, &[Dialog::RecognizeText, Dialog::ActionWizard], &[]);
    calm(&mut h);
    let _ = h.state_mut().set_option("dialog", "recognize-text");
    h.run_steps(3);
    let dialog = h.state().dialog;
    v.holds(dialog != Some(Dialog::RecognizeText), || format!("automatisation --dialog recognize-text : dialogue {dialog:?}"));
    forced_state_closes(&mut v, &mut h, &[Dialog::RecognizeText, Dialog::ActionWizard], &[]);
    v.finish();
}

#[test]
fn the_atelier_scope_q47_a_is_respected() {
    let mut v = Verdict::new("perimetre-q47");
    // Home, without a document, with a recent file the engine would list.
    let mut home = harness(false, |app| {
        app.recent.push(pdfcraft_ui_egui::RecentFile { name: "recent-atelier.pdf".into(), path: "/nowhere/recent-atelier.pdf".into(), pages: 1, size: 0 });
    });
    v.absent(&home, "Home", "Recent");
    v.absent(&home, "Home", "Clear Recent Files");
    v.absent(&home, "Home", "recent-atelier.pdf");
    v.absent_contains(&home, "Home, cartes", "Remove hidden information");
    v.present(&home, "Home", "Open file");
    v.present_contains(&home, "Home, cartes", "Protect with password");
    calm(&mut home);
    let _ = home.state_mut().execute("file.clear_recent");
    home.run_steps(2);
    let left = home.state().recent.len();
    v.holds(left == 1, || format!("exécution de file.clear_recent : liste des récents vidée ({left} restant)"));
    // With a document.
    let mut h = harness(true, |_| {});
    all_tools(&mut h);
    v.absent(&h, "All tools", group_label("actions"));
    v.present(&h, "All tools", group_label("javascript"));
    palette_offers_none(&mut v, &mut h, SCOPE);
    palette_group(&mut v, &mut h, "actions", false);
    palette_group(&mut v, &mut h, "accessibility", true);
    tool_panel(&mut h, "edit");
    v.absent(&h, "panneau « Edit a PDF »", "Edit text & images");
    v.present(&h, "panneau « Edit a PDF »", "Header and footer");
    // EVORA-COL-38: the Edit workspace's quick bar (v0.14.0). Witness: its Select button is drawn.
    calm(&mut h);
    let mode = h.state().mode;
    h.state_mut().mode = Mode::Edit;
    h.run_steps(3);
    v.absent(&h, "barre d'outils de l'espace Edit", "Edit text & images");
    v.present(&h, "barre d'outils de l'espace Edit", "Select (V)");
    h.state_mut().mode = mode;
    h.run_steps(2);
    tool_panel(&mut h, "form");
    v.absent(&h, "panneau « Prepare a form »", "Import data");
    v.present(&h, "panneau « Prepare a form »", "Export data");
    tool_panel(&mut h, "protect");
    v.absent(&h, "panneau « Protect a PDF »", "Remove hidden information");
    v.present(&h, "panneau « Protect a PDF »", "Protect with password");
    tool_panel(&mut h, "javascript");
    v.absent(&h, "panneau « Use JavaScript »", "Console");
    v.present(&h, "panneau « Use JavaScript »", "Document JavaScripts");
    // The File menu.
    calm(&mut h);
    if let Some(menu) = h.query_all_by_label("Menu").next() {
        menu.click();
    }
    h.run_steps(2);
    if let Some(file) = h.query_all_by_label("File ⏵").next() {
        file.hover();
    }
    h.run_steps(3);
    v.present_contains(&h, "menu Fichier", "Close all");
    v.absent_contains(&h, "menu Fichier", "Open Recent");
    v.absent_contains(&h, "menu Fichier", "Pin folder to Home");
    // The keyboard shortcuts list.
    calm(&mut h);
    let _ = h.state_mut().set_option("dialog", "shortcuts");
    h.run_steps(3);
    v.present(&h, "raccourcis clavier", "Find");
    v.absent(&h, "raccourcis clavier", "JavaScript console");
    // The Comments panel's « More options » menu.
    calm(&mut h);
    h.state_mut().right = Some(RightPanel::Comments);
    h.run_steps(3);
    if let Some(more) = h.query_all_by_label("More options").next() {
        more.click();
    }
    h.run_steps(3);
    v.present(&h, "panneau Commentaires, menu", "Export all to data file…");
    v.absent(&h, "panneau Commentaires, menu", "Import comments…");
    let dialogs = [Dialog::JsConsole, Dialog::Sanitize, Dialog::RemoveHidden, Dialog::ActionWizard];
    let tools = [QuickTool::EditText, QuickTool::EnhanceCamera];
    running_leaves_nothing(&mut v, &mut h, SCOPE, &dialogs, &tools);
    for (key, value) in [("quick", "edit-text"), ("quick", "enhance-camera"), ("dialog", "js-console"), ("dialog", "action-wizard")] {
        calm(&mut h);
        let _ = h.state_mut().set_option(key, value);
        h.run_steps(3);
        let (dialog, tool) = (h.state().dialog, h.state().quick_tool);
        v.holds(dialog.is_none_or(|d| !dialogs.contains(&d)) && !tools.contains(&tool), || {
            format!("automatisation --{key} {value} : dialogue {dialog:?}, outil {tool:?}")
        });
    }
    forced_state_closes(&mut v, &mut h, &dialogs, &tools);
    v.finish();
}

/// EVORA-COL-38: the expanded All tools view (new in v0.14.0), opened without a document (the view
/// closes when another tab comes to the front): no tile of a hidden tool, no mention of a hidden item
/// whatever the search, and the kept tools and items found (twins, without which an empty view would
/// pass for a mask).
#[test]
fn the_expanded_all_tools_view_offers_nothing_hidden() {
    let mut v = Verdict::new("vue-outils");
    let mut h = harness(false, |app| {
        app.mode = Mode::AllTools;
        app.all_tools_full = true;
    });
    let open = h.state().all_tools_full && h.state().mode == Mode::AllTools;
    v.holds(open, || "vue « All tools » étendue : non ouverte, mesure impossible".to_string());
    v.present(&h, "vue « All tools »", "Collapse all tools");
    for g in HIDDEN_GROUPS {
        v.absent(&h, "vue « All tools »", group_label(g));
    }
    for g in ["certificate", "fill_sign", "protect", "edit", "form", "javascript", "compress"] {
        v.present(&h, "vue « All tools »", group_label(g));
    }
    for id in SIGNATURE.iter().chain(REDACTION).chain(OCR).chain(SCOPE) {
        for label in labels(id) {
            view_search(&mut h, &label);
            let n = named_in_notes(&h, &label);
            v.holds(n == 0, || format!("vue « All tools », recherche « {label} » : élément masqué nommé ({n} fois)"));
            for g in HIDDEN_GROUPS {
                v.absent(&h, &format!("vue « All tools », recherche « {label} »"), group_label(g));
            }
        }
    }
    for label in ["Validate all signatures", "Reduce file size", "Protect with password", "Export data", "Add text"] {
        view_search(&mut h, label);
        let n = named_in_notes(&h, label);
        v.holds(n > 0, || format!("vue « All tools », recherche « {label} » : témoin non nommé"));
    }
    v.finish();
}

/// Witness: the neighbours that stay (they must be reachable whatever the masks do).
#[test]
fn kept_neighbours_stay_reachable() {
    let mut v = Verdict::new("temoins");
    let mut h = harness(true, |_| {});
    for label in ["Validate all signatures", "Signatures panel", "Fill & Sign: sign", "Document JavaScripts…", "Add text", "Reduce file size…"] {
        palette_for(&mut h, label);
        let n = nodes(&h, label);
        v.holds(n > 0, || format!("palette « {label} » : témoin absent"));
    }
    all_tools(&mut h);
    for g in ["certificate", "fill_sign", "protect", "edit", "form", "javascript", "export", "compress"] {
        v.present(&h, "All tools", group_label(g));
    }
    for (d, what) in [(Dialog::Preferences, "Préférences"), (Dialog::Shortcuts, "raccourcis clavier")] {
        calm(&mut h);
        h.state_mut().dialog = Some(d);
        h.run_steps(3);
        let still = h.state().dialog;
        v.holds(still == Some(d), || format!("{what} : dialogue fermé ({still:?}), garde trop large"));
    }
    calm(&mut h);
    h.state_mut().quick_tool = QuickTool::AddText;
    h.run_steps(3);
    let tool = h.state().quick_tool;
    v.holds(tool == QuickTool::AddText, || format!("outil Add text : remplacé par {tool:?}, garde trop large"));
    tool_panel(&mut h, "certificate");
    let left = h.state().left;
    v.holds(left == LeftPanel::Tool("certificate"), || format!("--tool certificate : panneau {left:?}, garde trop large"));
    v.finish();
}

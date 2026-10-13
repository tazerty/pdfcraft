//! PdfCraft in the browser. Build: `cd apps/pdfcraft-web && trunk build --release`
//! (trunk generates the JS loader; no handwritten JS — plan/execution-plan.md §1).

#![deny(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::unimplemented, clippy::todo, clippy::unreachable)]

#[cfg(target_arch = "wasm32")]
fn main() {
    use eframe::wasm_bindgen::JsCast;
    use pdfcraft_ui_egui::PdfCraftApp;

    let options = eframe::WebOptions { renderer: eframe::Renderer::Glow, ..Default::default() };
    wasm_bindgen_futures::spawn_local(async move {
        let Some(canvas) = web_sys::window()
            .and_then(|w| w.document())
            .and_then(|d| d.get_element_by_id("pdfcraft"))
            .and_then(|e| e.dyn_into::<web_sys::HtmlCanvasElement>().ok())
        else {
            return;
        };
        let started = eframe::WebRunner::new()
            .start(
                canvas,
                options,
                Box::new(|cc| {
                    let mut app = PdfCraftApp::new();
                    let evora_host = query_param("host").as_deref() == Some("evora");
                    // Evora (E9, E10): `?evora-audit=1` (CI smoke test) audits every text drawn.
                    if query_param("evora-audit").as_deref() == Some("1") {
                        cc.egui_ctx.add_plugin(e10::Audit::new(query_param("evora-probe")));
                    }
                    // Evora (E5): under the Evora bridge (`?host=evora`) the browser storage is a namespace
                    // per Evora account, which only `evora:init` opens and only `evora:init` and
                    // `evora:purge` erase (module `storage_ns`); until then the settings stay in memory,
                    // and upstream's shared keys are never read. Outside the bridge, upstream's behaviour
                    // is unchanged: "printcraft" holds settings saved under the app's former name, PrintCraft.
                    if !evora_host
                        && let Some(json) = cc.storage.and_then(|s| s.get_string("pdfcraft").or_else(|| s.get_string("printcraft")))
                    {
                        app.restore(&json);
                    }
                    // Evora (E3): `?lang=` and `?theme=` impose the first language and theme, read
                    // after the saved settings so the host's choice wins (HOST-PROTOCOL.md §2.4).
                    if let Some(code) = query_param("lang").and_then(|tag| evora_lang(&tag)) {
                        app.language = code.to_string();
                    }
                    match query_param("theme").as_deref() {
                        Some("light") => app.set_theme_preference(pdfcraft_ui_egui::theme::ThemePreference::Light),
                        Some("dark") => app.set_theme_preference(pdfcraft_ui_egui::theme::ThemePreference::Dark),
                        _ => {}
                    }
                    // Evora (E7): no `?file=<url>`. The engine fetches nothing named by its URL;
                    // documents come from the host page only (EHP, HOST-PROTOCOL.md §2.4, §5.4).
                    // eframe never raises a close request on a browser reload or tab close, so `guard_quit` never
                    // prompts; ask the browser to confirm instead while a document has unsaved work (#812).
                    warn_before_unload(app.unsaved_flag.clone());
                    // Evora (E4, COL-02): `?host=evora` speaks the Evora host protocol (EHP v1) with the
                    // parent origin that `evora-host.json` admits (module `ehp` below).
                    let events = ehp::Events::default();
                    let mut gate = None;
                    if evora_host {
                        let shared = storage_ns::SharedGate::default();
                        let link = ehp::Link::default();
                        app.host_save = Some(link.save_fn());
                        app.host_dirty = Some(link.dirty_fn());
                        ehp::connect(link, app.startup_inbox.clone(), events.clone(), shared.clone(), cc.egui_ctx.clone());
                        gate = Some(shared);
                    }
                    // `?host=parent`: a same-origin page embedding PdfCraft in an iframe (such
                    // as the Nextcloud app) passes files in and takes saves back (`host` below).
                    else if query_param("host").as_deref() == Some("parent")
                        && let Some(bridge) = host::Bridge::new()
                    {
                        // `?author=`: the host's name for the user signs their comments,
                        // unless they chose a name in PdfCraft (the web default is "Guest").
                        if let Some(author) = query_param("author").map(|a| a.trim().to_string()).filter(|a| !a.is_empty())
                            && app.comment_prefs.author == "Guest"
                        {
                            app.comment_prefs.author = author.chars().take(200).collect();
                        }
                        bridge.listen(app.startup_inbox.clone(), cc.egui_ctx.clone());
                        app.host_save = Some(bridge.save_fn());
                        app.host_dirty = Some(bridge.dirty_fn());
                        bridge.post_ready();
                    } else if query_param("host").as_deref() == Some("parent") {
                        eframe::web_sys::console::warn_1(
                            &"PdfCraft: ?host=parent needs a framing page on the same origin; saves download instead".into(),
                        );
                    }
                    Ok(Box::new(EvoraApp { inner: app, events, gate }))
                }),
            )
            .await;
        if let Err(e) = started {
            eframe::web_sys::console::error_1(&e);
            if query_param("host").as_deref() == Some("evora") {
                let text = e.as_string().unwrap_or_else(|| format!("{e:?}"));
                ehp::report_failure(if text.contains("WebGL") { "no_webgl2" } else { "init" });
            } else if query_param("host").as_deref() == Some("parent")
                && let Some(bridge) = host::Bridge::new()
            {
                bridge.post_failed(&e.as_string().unwrap_or_else(|| format!("{e:?}")));
            }
        }
    });
}

#[cfg(target_arch = "wasm32")]
fn warn_before_unload(unsaved: std::sync::Arc<std::sync::atomic::AtomicBool>) {
    use eframe::wasm_bindgen::{JsCast, closure::Closure};
    let Some(window) = web_sys::window() else { return };
    let handler = Closure::<dyn FnMut(web_sys::Event)>::new(move |event: web_sys::Event| {
        if unsaved.load(std::sync::atomic::Ordering::Relaxed) {
            event.prevent_default();
        }
    });
    if window.add_event_listener_with_callback("beforeunload", handler.as_ref().unchecked_ref()).is_ok() {
        handler.forget();
    }
}

/// Evora (E5): the engine's browser storage under the Evora bridge (`?host=evora`), a namespace per
/// Evora account. `storageNs`, an opaque HMAC of the account, arrives only in `evora:init`, never in
/// the URL (HOST-PROTOCOL.md §2.4, §4.3). A namespace, not a partition: any script of the engine's
/// origin can still list every key; the isolation comes from serving the engine on its own site
/// (mode B).
///
/// What this engine keeps in the browser, as measured in its code: its settings (drawn signatures,
/// initials, digital IDs, trusted certificates and stamps included) and eframe's UI memory
/// (`egui_memory_ron`), both in localStorage. No OPFS, no IndexedDB, no Cache Storage, no cookie,
/// and no recovery store on the web (`RecoveryStore` is desktop only). Under the bridge:
/// - the settings are written only under `evora.pdfcraft.<storageNs>`, once `evora:init` has given
///   the namespace and the app has restored them, and eframe's UI memory is never written
///   ([`Gate`], `EvoraApp::save`);
/// - `evora:init` erases, before its answer, every other namespace and every key the engine leaves
///   outside the namespaces on its origin ([`LOOSE`]) (§7.1 step 6, §7.7 b);
/// - `evora:purge` first seals the gate (no write any more, for the rest of the page's life), then
///   erases, checks that nothing is left, and only then answers (§7.7 a).
///
/// Nothing else erases anything: no URL parameter, no other message, not the start of the page.
/// Outside the bridge, upstream's behaviour is unchanged.
#[cfg(target_arch = "wasm32")]
mod storage_ns {
    use std::cell::RefCell;
    use std::rc::Rc;

    /// Prefix of the namespaced keys.
    const PREFIX: &str = "evora.pdfcraft.";
    /// The keys this engine writes outside the namespaces on its origin: upstream's shared settings,
    /// the settings of the app's former name (PrintCraft), and eframe's UI memory.
    const LOOSE: [&str; 3] = ["pdfcraft", "printcraft", "egui_memory_ron"];

    /// Whether, and where, the settings may be written: shared by the bridge, which opens the gate
    /// (`evora:init`, once the app has restored the account's settings) and seals it (`evora:purge`),
    /// and by the app, which asks it on every save. Closed at first; sealed for good.
    #[derive(Default)]
    pub struct Gate {
        key: Option<String>,
        sealed: bool,
    }

    pub type SharedGate = Rc<RefCell<Gate>>;

    impl Gate {
        /// The key the settings may be written under now, if any.
        pub fn key(&self) -> Option<String> {
            if self.sealed { None } else { self.key.clone() }
        }

        /// Allow writing under namespace `ns`, unless a purge has sealed the gate.
        pub fn open(&mut self, ns: &str) {
            if !self.sealed {
                self.key = key(ns);
            }
        }

        /// Stop every write, for the rest of the page's life.
        pub fn seal(&mut self) {
            self.sealed = true;
            self.key = None;
        }
    }

    /// `storageNs` is 64 lowercase hexadecimal digits (HOST-PROTOCOL.md §4.3); anything else is refused.
    pub fn valid(ns: &str) -> bool {
        ns.len() == 64 && ns.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    }

    /// The key holding namespace `ns`'s settings.
    pub fn key(ns: &str) -> Option<String> {
        valid(ns).then(|| format!("{PREFIX}{ns}"))
    }

    fn storage() -> Option<web_sys::Storage> {
        web_sys::window()?.local_storage().ok()?
    }

    /// The saved settings of namespace `ns`.
    pub fn read(ns: &str) -> Option<String> {
        storage()?.get_item(&key(ns)?).ok()?
    }

    /// This engine's keys present now (namespaces and loose keys); `None` if they can't be listed.
    fn engine_keys(s: &web_sys::Storage) -> Option<Vec<String>> {
        let mut found = Vec::new();
        for i in 0..s.length().ok()? {
            let k = s.key(i).ok()??;
            if k.starts_with(PREFIX) || LOOSE.contains(&k.as_str()) {
                found.push(k);
            }
        }
        Some(found)
    }

    /// Remove this engine's keys that `doomed` picks, then check that none is left. `false` when the
    /// storage can't be reached or listed, or a key survived: the erasure isn't effective.
    fn erase(doomed: impl Fn(&str) -> bool) -> bool {
        let Some(s) = storage() else { return false };
        let Some(before) = engine_keys(&s) else { return false };
        for k in before.iter().filter(|k| doomed(k.as_str())) {
            let _ = s.remove_item(k);
        }
        engine_keys(&s).is_some_and(|after| !after.iter().any(|k| doomed(k.as_str())))
    }

    /// `evora:init` (§7.7 b): every key of this engine except namespace `keep`.
    pub fn purge_except(keep: Option<&str>) -> bool {
        let keep = keep.and_then(key);
        erase(|k| keep.as_deref() != Some(k))
    }

    /// `evora:purge` with `scope: "current"`: namespace `ns` and the keys outside the namespaces.
    pub fn purge_current(ns: Option<&str>) -> bool {
        let current = ns.and_then(key);
        erase(|k| LOOSE.contains(&k) || current.as_deref() == Some(k))
    }

    /// `evora:purge` with `scope: "all"`: every namespace and the keys outside them.
    pub fn purge_all() -> bool {
        erase(|_| true)
    }
}

/// Evora (E3): the interface language for an Evora language code (`engineLang` of
/// HOST-PROTOCOL.md, already converted by the host, or the Evora code itself). `zh-Hans` and the
/// Simplified regions map to `zh-hans`, the Traditional ones to `zh-hant`. Plain `pt` maps to
/// nothing until Evora picks its Portuguese variant (decision D-23); `pt-br` given explicitly is
/// honoured. A language without a catalogue here (hi, id, ko…) gives `None`: the engine stays in
/// English and the host shows its own banner.
#[cfg(target_arch = "wasm32")]
fn evora_lang(tag: &str) -> Option<&'static str> {
    let tag = tag.trim().replace('_', "-").to_ascii_lowercase();
    let code = match tag.as_str() {
        "zh-hans" | "zh-cn" | "zh-sg" | "zh-hans-cn" => "zh-hans",
        "zh-hant" | "zh-tw" | "zh-hk" | "zh-mo" | "zh-hant-tw" => "zh-hant",
        "pt" => return None,
        other => other,
    };
    pdfcraft_ui_egui::i18n::normalize_pref(code).filter(|c| *c != pdfcraft_ui_egui::i18n::AUTO)
}

#[cfg(target_arch = "wasm32")]
fn query_param(key: &str) -> Option<String> {
    let search = web_sys::window()?.location().search().ok()?;
    web_sys::UrlSearchParams::new_with_str(&search).ok()?.get(key)
}

/// The `postMessage` bridge to a same-origin parent page. Messages are plain objects with a
/// `type`:
///
/// - `pdfcraft:ready` (to the parent): the app is listening; send files now.
/// - `pdfcraft:open` (from the parent): `{ name, bytes }`, where `bytes` is an `ArrayBuffer` or
///   `Uint8Array` holding a PDF. It opens in a tab, like a `?file=` URL.
/// - `pdfcraft:save` (to the parent): `{ name, saveAs, bytes }` when the user saves; `bytes` is
///   a transferred `ArrayBuffer`. The parent stores the file (and reports its own errors).
/// - `pdfcraft:dirty` (to the parent): `{ dirty }` whenever unsaved work appears or goes away.
/// - `pdfcraft:failed` (to the parent): `{ error }` when the app couldn't start.
///
/// Only the parent window on the app's own origin is heard or answered. With a parent on
/// another origin there is no bridge: the app runs as if unframed and saves download.
#[cfg(target_arch = "wasm32")]
mod host {
    use eframe::wasm_bindgen::{JsCast, JsValue, closure::Closure};

    #[derive(Clone)]
    pub struct Bridge {
        window: web_sys::Window,
        parent: web_sys::Window,
        origin: String,
    }

    impl Bridge {
        /// `None` when the page isn't framed (there is no parent to talk to), or when the parent
        /// is on another origin: messages only go to this origin, so the browser would drop
        /// every save without an error while the document showed as saved (#2167).
        pub fn new() -> Option<Self> {
            let window = web_sys::window()?;
            let parent = window.parent().ok().flatten()?;
            if js_sys::Object::is(&parent, &window) {
                return None;
            }
            let origin = window.location().origin().ok()?;
            // Reading another origin's location throws, which is `None` too.
            if parent.location().origin().ok()? != origin {
                return None;
            }
            Some(Self { window, parent, origin })
        }

        fn post(&self, message: &js_sys::Object, transfer: Option<&JsValue>) -> Result<(), String> {
            let sent = match transfer {
                Some(t) => self.parent.post_message_with_transfer(message, &self.origin, &js_sys::Array::of1(t)),
                None => self.parent.post_message(message, &self.origin),
            };
            sent.map_err(|e| e.as_string().unwrap_or_else(|| format!("{e:?}")))
        }

        pub fn post_ready(&self) {
            if let Some(m) = message(&[("type", "pdfcraft:ready".into()), ("version", env!("CARGO_PKG_VERSION").into())]) {
                let _ = self.post(&m, None);
            }
        }

        /// The app couldn't start (no WebGL, for example): let the parent say so.
        pub fn post_failed(&self, error: &str) {
            if let Some(m) = message(&[("type", "pdfcraft:failed".into()), ("error", error.into())]) {
                let _ = self.post(&m, None);
            }
        }

        /// Hear `pdfcraft:open` from the parent and queue the file like a `?file=` download.
        pub fn listen(&self, inbox: pdfcraft_ui_egui::Inbox, ctx: egui::Context) {
            let parent = self.parent.clone();
            let origin = self.origin.clone();
            let on_message = Closure::<dyn FnMut(web_sys::MessageEvent)>::new(move |event: web_sys::MessageEvent| {
                if event.origin() != origin || !event.source().is_some_and(|s| js_sys::Object::is(&s, &parent)) {
                    return;
                }
                let data = event.data();
                if string(&data, "type").as_deref() != Some("pdfcraft:open") {
                    return;
                }
                let name = string(&data, "name").filter(|n| !n.trim().is_empty()).unwrap_or_else(|| "document.pdf".to_string());
                let Ok(bytes) = js_sys::Reflect::get(&data, &JsValue::from_str("bytes")) else { return };
                let bytes = if let Some(array) = bytes.dyn_ref::<js_sys::Uint8Array>() {
                    array.to_vec()
                } else if bytes.is_instance_of::<js_sys::ArrayBuffer>() {
                    js_sys::Uint8Array::new(&bytes).to_vec()
                } else {
                    return;
                };
                if let Ok(mut q) = inbox.lock() {
                    q.push((name, bytes));
                }
                ctx.request_repaint();
            });
            if self.window.add_event_listener_with_callback("message", on_message.as_ref().unchecked_ref()).is_ok() {
                // The listener lives as long as the page.
                on_message.forget();
            }
        }

        pub fn save_fn(&self) -> pdfcraft_ui_egui::HostSaveFn {
            let bridge = self.clone();
            Box::new(move |name: &str, bytes: &[u8], save_as: bool| {
                let buffer = js_sys::Uint8Array::from(bytes).buffer();
                let m =
                    message(&[("type", "pdfcraft:save".into()), ("name", name.into()), ("saveAs", save_as.into()), ("bytes", buffer.clone().into())])
                        .ok_or_else(|| "couldn't build the message".to_string())?;
                bridge.post(&m, Some(&buffer))
            })
        }

        pub fn dirty_fn(&self) -> pdfcraft_ui_egui::HostDirtyFn {
            let bridge = self.clone();
            let mut last = false;
            Box::new(move |dirty: bool| {
                if dirty != last {
                    last = dirty;
                    if let Some(m) = message(&[("type", "pdfcraft:dirty".into()), ("dirty", dirty.into())]) {
                        let _ = bridge.post(&m, None);
                    }
                }
            })
        }
    }

    fn message(fields: &[(&str, JsValue)]) -> Option<js_sys::Object> {
        let m = js_sys::Object::new();
        for (key, value) in fields {
            js_sys::Reflect::set(&m, &JsValue::from_str(key), value).ok()?;
        }
        Some(m)
    }

    fn string(data: &JsValue, key: &str) -> Option<String> {
        js_sys::Reflect::get(data, &JsValue::from_str(key)).ok()?.as_string()
    }
}

/// Evora (E9, E10): render-time audit for the CI smoke test. With `?evora-audit=1`, every text egui
/// draws is checked just before it reaches the screen for emoji (E10) and for third-party product
/// names (E9), and the running totals are published as
/// `window.__evoraAudit = { frames, texts, emoji, terms, sample, selftest, dark, probe }`, where
/// `probe` counts the drawn texts containing `?evora-probe=` (E3: the imposed language shows).
#[cfg(target_arch = "wasm32")]
mod e10 {
    use eframe::wasm_bindgen::JsValue;

    /// Same set as `.github/evora/gates.py` (`is_emoji_like`): emoji and pictograph blocks,
    /// dingbats (✓ ✔ ✕ ✖ ⚠ ★…), the emoji presentation selector and isolated pictographs.
    pub fn is_emoji_like(c: char) -> bool {
        let cp = c as u32;
        matches!(cp, 0x1F000..=0x1FAFF | 0x2600..=0x27BF | 0x2B00..=0x2BFF | 0x23E9..=0x23F3 | 0x23F8..=0x23FA | 0x25FB..=0x25FE)
            || matches!(
                cp,
                0xFE0F
                    | 0x20E3
                    | 0x203C
                    | 0x2049
                    | 0x2139
                    | 0x24C2
                    | 0x231A
                    | 0x231B
                    | 0x2328
                    | 0x23CF
                    | 0x25B6
                    | 0x25C0
                    | 0x2934
                    | 0x2935
                    | 0x3030
                    | 0x303D
                    | 0x3297
                    | 0x3299
            )
    }

    /// Product names the interface must not show (E9, see ui-egui `i18n/evora-overrides.txt`).
    const SENSITIVE: [&str; 6] = ["Lumetri", "Lightroom", "Acrobat", "Premiere", "Adobe", "Cycore"]; // evora-gates: allow

    #[derive(Default)]
    pub struct Audit {
        frames: u64,
        texts: u64,
        emoji: u64,
        terms: u64,
        sample: String,
        dark: bool,
        probe: Option<String>,
        probe_hits: u64,
    }

    fn sensitive_terms(text: &str) -> u64 {
        SENSITIVE.iter().filter(|term| text.contains(**term)).count() as u64
    }

    /// The detectors fire on known samples (U+2713, U+1F600, a product name) and stay quiet on a
    /// letter, the menu separator U+25B8 and a neutral label: the CI requires it, so a detector that
    /// never fires can't pass for green.
    fn selftest() -> bool {
        is_emoji_like('\u{2713}')
            && is_emoji_like('\u{1F600}')
            && !is_emoji_like('A')
            && !is_emoji_like('\u{25B8}')
            && sensitive_terms(SENSITIVE[2]) == 1
            && sensitive_terms("Enable PDF JavaScript") == 0
    }

    impl Audit {
        pub fn new(probe: Option<String>) -> Self {
            Self { probe: probe.filter(|p| !p.is_empty()), ..Self::default() }
        }

        fn scan(&mut self, shape: &egui::Shape) {
            match shape {
                egui::Shape::Vec(shapes) => {
                    for s in shapes {
                        self.scan(s);
                    }
                }
                egui::Shape::Text(text) => {
                    self.texts += 1;
                    let shown = text.galley.text();
                    let emoji = shown.chars().filter(|c| is_emoji_like(*c)).count() as u64;
                    let terms = sensitive_terms(shown);
                    if self.probe.as_deref().is_some_and(|p| shown.contains(p)) {
                        self.probe_hits += 1;
                    }
                    if emoji + terms > 0 {
                        self.emoji += emoji;
                        self.terms += terms;
                        if self.sample.is_empty() {
                            self.sample = shown.chars().take(120).collect();
                        }
                    }
                }
                _ => {}
            }
        }

        fn publish(&self) {
            let Some(window) = web_sys::window() else { return };
            let report = js_sys::Object::new();
            for (key, value) in [
                ("frames", JsValue::from_f64(self.frames as f64)),
                ("texts", JsValue::from_f64(self.texts as f64)),
                ("emoji", JsValue::from_f64(self.emoji as f64)),
                ("terms", JsValue::from_f64(self.terms as f64)),
                ("sample", JsValue::from_str(&self.sample)),
                ("selftest", JsValue::from_bool(selftest())),
                ("dark", JsValue::from_bool(self.dark)),
                ("probe", JsValue::from_f64(self.probe_hits as f64)),
            ] {
                let _ = js_sys::Reflect::set(&report, &JsValue::from_str(key), &value);
            }
            let _ = js_sys::Reflect::set(&window, &JsValue::from_str("__evoraAudit"), &report);
        }
    }

    impl egui::Plugin for Audit {
        fn debug_name(&self) -> &'static str {
            "evora-display-audit"
        }

        fn output_hook(&mut self, ctx: &egui::Context, output: &mut egui::FullOutput) {
            self.frames += 1;
            self.dark = ctx.global_style().visuals.dark_mode;
            for clipped in &output.shapes {
                self.scan(&clipped.shape);
            }
            self.publish();
        }
    }
}

/// Evora (E4, COL-02): the native Evora host protocol bridge, EHP v1 (`apps/creative/HOST-PROTOCOL.md`
/// in Evora). With `?host=evora`, the engine talks to its parent page only when that page's origin
/// is admitted by `evora-host.json`, written next to `index.html` when Evora provisions the build
/// (HOST-PROTOCOL.md §2.3): never from a URL parameter, a message or the referrer alone.
///
/// Every message is `{ v: 1, type, id, re?, payload }` (§3). Incoming messages are examined only if
/// `event.source` is the parent window AND `event.origin` is the admitted parent origin (§5.1), then
/// checked in the order of §5.2 (plain object, version, known type, capability, envelope, payload,
/// binary sizes, correlation); anything else is ignored. Outgoing messages always name the parent
/// origin as `targetOrigin`, never `*`.
///
/// Handled: `evora:init`, `evora:open` (bytes), `evora:saved` (checked; without the `doc.saved-ack`
/// capability the engine does not act on it, so the host keeps its own save state, §6.3),
/// `evora:lang`, `evora:theme`, `evora:purge`. Sent: `evora:ready`, `evora:failed`, `evora:ack`,
/// `evora:dirty`, `evora:save`.
#[cfg(target_arch = "wasm32")]
mod ehp {
    use std::cell::RefCell;
    use std::rc::Rc;

    use eframe::wasm_bindgen::{JsCast, JsValue, closure::Closure};

    /// Build slug and protocol version announced in `evora:ready` (§4.4, §10).
    const APP: &str = "colophon-atelier";
    const EHP: &str = "1.0";
    /// What this engine honours (§9.1). Not yet: `doc.saved-ack`, `doc.request-save`,
    /// `export.drive` (patches COL-09, COL-08, COL-03).
    const CAPABILITIES: [&str; 8] = ["doc.open", "doc.save", "doc.dirty", "live.lang", "live.theme", "storage.ns", "storage.purge", "author"];
    /// The admitted parent origins, beside `index.html` (§2.3).
    const CONFIG: &str = "evora-host.json";
    const LANGS: [&str; 14] = ["ar", "de", "en", "es", "fr", "hi", "id", "it", "ja", "ko", "pt", "ru", "tr", "zh-Hans"];
    const CAPABILITY_NAMES: [&str; 18] = [
        "doc.open",
        "doc.save",
        "doc.saved-ack",
        "doc.dirty",
        "doc.multi",
        "doc.request-save",
        "export.drive",
        "media.need",
        "media.ranges",
        "pick.drive",
        "command",
        "storage.ns",
        "storage.memory",
        "storage.purge",
        "live.lang",
        "live.theme",
        "font.inject",
        "author",
    ];

    /// What the host asks of the app, applied at the start of the next frame (`EvoraApp::logic`).
    pub enum HostEvent {
        /// `evora:init`: the account's saved settings (read before the other namespaces were
        /// erased), the namespace the settings may then be written under (`None`: memory only), the
        /// language (`None`: English), the theme and the author name.
        Init { settings: Option<String>, storage_ns: Option<String>, lang: Option<&'static str>, dark: bool, author: Option<String> },
        Lang(Option<&'static str>),
        Theme(bool),
    }

    pub type Events = Rc<RefCell<Vec<HostEvent>>>;

    struct State {
        parent: web_sys::Window,
        origin: String,
        ctx: egui::Context,
        inbox: pdfcraft_ui_egui::Inbox,
        events: Events,
        /// E5: whether, and where, the app may write its settings (`storage_ns::Gate`).
        gate: crate::storage_ns::SharedGate,
        ready_id: String,
        initialized: bool,
        caps: Vec<String>,
        max_document: f64,
        storage_ns: Option<String>,
        /// `(name, docRef)` of the documents the host opened, to tell which one a save is.
        docs: Vec<(String, String)>,
        pending_saves: Vec<String>,
        last_dirty: Option<bool>,
    }

    /// The bridge once connected; empty until `evora-host.json` is read and the parent admitted.
    #[derive(Clone, Default)]
    pub struct Link(Rc<RefCell<Option<Rc<RefCell<State>>>>>);

    impl Link {
        fn state(&self) -> Option<Rc<RefCell<State>>> {
            self.0.borrow().clone()
        }

        /// `evora:save` for the app's Save and Save As (`HostSaveFn`).
        pub fn save_fn(&self) -> pdfcraft_ui_egui::HostSaveFn {
            let link = self.clone();
            Box::new(move |name: &str, bytes: &[u8], save_as: bool| {
                let state = link.state().ok_or_else(|| "Evora is not connected yet".to_string())?;
                let mut st = state.borrow_mut();
                if !st.initialized || !st.caps.iter().any(|c| c == "doc.save") {
                    return Err("Evora is not ready to save yet".into());
                }
                let refs: Vec<&String> = st.docs.iter().filter(|(n, _)| n == name).map(|(_, r)| r).collect();
                let [doc_ref] = refs.as_slice() else {
                    return Err("only a document opened from Evora can be saved here".into());
                };
                let doc_ref = (*doc_ref).clone();
                if bytes.is_empty() || bytes.len() as f64 > st.max_document {
                    return Err("the document is too large to save in Evora".into());
                }
                let buffer = js_sys::Uint8Array::from(bytes).buffer();
                let payload = object(&[
                    ("docRef", doc_ref.into()),
                    ("name", clean_name(name).into()),
                    ("saveAs", save_as.into()),
                    ("bytes", buffer.clone().into()),
                ])
                .ok_or_else(|| "couldn't build the message".to_string())?;
                let id = send(&st, "evora:save", None, &payload, Some(&buffer)).ok_or_else(|| "couldn't send the document".to_string())?;
                st.pending_saves.push(id);
                Ok(())
            })
        }

        /// `evora:dirty` when unsaved work appears or goes away (`HostDirtyFn`).
        pub fn dirty_fn(&self) -> pdfcraft_ui_egui::HostDirtyFn {
            let link = self.clone();
            Box::new(move |dirty: bool| {
                let Some(state) = link.state() else { return };
                let mut st = state.borrow_mut();
                if !st.initialized || !st.caps.iter().any(|c| c == "doc.dirty") || st.last_dirty == Some(dirty) {
                    return;
                }
                st.last_dirty = Some(dirty);
                let mut fields: Vec<(&str, JsValue)> = vec![("dirty", dirty.into())];
                if let [(_, doc_ref)] = st.docs.as_slice() {
                    fields.push(("docRef", doc_ref.clone().into()));
                }
                if let Some(payload) = object(&fields) {
                    let _ = send(&st, "evora:dirty", None, &payload, None);
                }
            })
        }
    }

    /// Read `evora-host.json`, find the admitted parent, listen, and announce `evora:ready`.
    pub fn connect(link: Link, inbox: pdfcraft_ui_egui::Inbox, events: Events, gate: crate::storage_ns::SharedGate, ctx: egui::Context) {
        wasm_bindgen_futures::spawn_local(async move {
            let Some((window, parent, origin)) = admitted_parent().await else { return };
            let state = Rc::new(RefCell::new(State {
                parent,
                origin,
                ctx,
                inbox,
                events,
                gate,
                ready_id: String::new(),
                initialized: false,
                caps: Vec::new(),
                max_document: 0.0,
                storage_ns: None,
                docs: Vec::new(),
                pending_saves: Vec::new(),
                last_dirty: None,
            }));
            let listener = state.clone();
            let on_message = Closure::<dyn FnMut(web_sys::MessageEvent)>::new(move |event: web_sys::MessageEvent| {
                receive(&listener, &event);
            });
            if window.add_event_listener_with_callback("message", on_message.as_ref().unchecked_ref()).is_err() {
                return;
            }
            // The listener lives as long as the page.
            on_message.forget();
            let capabilities = js_sys::Array::new();
            for c in CAPABILITIES {
                capabilities.push(&JsValue::from_str(c));
            }
            let Some(payload) = object(&[
                ("app", APP.into()),
                ("version", env!("CARGO_PKG_VERSION").into()),
                ("ehp", EHP.into()),
                ("capabilities", capabilities.into()),
            ]) else {
                return;
            };
            let id = send(&state.borrow(), "evora:ready", None, &payload, None);
            if let Some(id) = id {
                state.borrow_mut().ready_id = id;
            }
            *link.0.borrow_mut() = Some(state);
        });
    }

    /// The engine couldn't start: tell an admitted parent with `evora:failed {code}` (§4.4).
    pub fn report_failure(code: &'static str) {
        wasm_bindgen_futures::spawn_local(async move {
            let Some((_, parent, origin)) = admitted_parent().await else { return };
            if let Some(payload) = object(&[("code", code.into())])
                && let Some(message) = envelope("evora:failed", None, &payload)
            {
                let _ = parent.post_message(&message.0, &origin);
            }
        });
    }

    /// The parent window and its origin, when the page is framed by an origin `evora-host.json`
    /// admits. The browser's own record of the parent (`location.ancestorOrigins`) decides when it
    /// exists; otherwise the referrer may only pick among the admitted origins, or the single one.
    async fn admitted_parent() -> Option<(web_sys::Window, web_sys::Window, String)> {
        let window = web_sys::window()?;
        let parent = window.parent().ok().flatten()?;
        if js_sys::Object::is(&parent, &window) {
            return None;
        }
        let admitted = read_config(&window).await?;
        // `location.ancestorOrigins` (a DOMStringList; absent from web-sys and from some browsers).
        let location: JsValue = window.location().into();
        let ancestors = get(&location, "ancestorOrigins");
        let first_ancestor = (get(&ancestors, "length").as_f64().unwrap_or(0.0) >= 1.0)
            .then(|| js_sys::Reflect::get_u32(&ancestors, 0).ok().and_then(|o| o.as_string()))
            .flatten();
        let origin = match first_ancestor {
            Some(parent_origin) => Some(parent_origin).filter(|o| admitted.contains(o))?,
            None => {
                let referrer = window.document().map(|d| d.referrer()).unwrap_or_default();
                let from_referrer = web_sys::Url::new(&referrer).ok().map(|u| u.origin()).filter(|o| admitted.contains(o));
                match (from_referrer, admitted.as_slice()) {
                    (Some(o), _) => o,
                    (None, [only]) => only.clone(),
                    _ => return None,
                }
            }
        };
        Some((window, parent, origin))
    }

    /// `evora-host.json`: `{ "parentOrigins": ["https://…", …] }`, each a bare web origin.
    async fn read_config(window: &web_sys::Window) -> Option<Vec<String>> {
        let response = wasm_bindgen_futures::JsFuture::from(window.fetch_with_str(CONFIG)).await.ok()?;
        let response: web_sys::Response = response.dyn_into().ok()?;
        if !response.ok() {
            return None;
        }
        let text = wasm_bindgen_futures::JsFuture::from(response.text().ok()?).await.ok()?.as_string()?;
        let config = js_sys::JSON::parse(&text).ok()?;
        let list = get(&config, "parentOrigins");
        if !js_sys::Array::is_array(&list) {
            return None;
        }
        let origins: Vec<String> = js_sys::Array::from(&list).iter().filter_map(|o| o.as_string()).filter(|o| is_origin(o)).collect();
        (!origins.is_empty()).then_some(origins)
    }

    /// `http(s)://host[:port]`, nothing after.
    fn is_origin(o: &str) -> bool {
        let rest = o.strip_prefix("https://").or_else(|| o.strip_prefix("http://"));
        rest.is_some_and(|r| !r.is_empty() && !r.contains(['/', '?', '#', '@', ' ', '\\']))
    }

    fn receive(state: &Rc<RefCell<State>>, event: &web_sys::MessageEvent) {
        // §5.1: source AND origin.
        {
            let st = state.borrow();
            if event.origin() != st.origin || !event.source().is_some_and(|s| js_sys::Object::is(&s, &st.parent)) {
                return;
            }
        }
        // §5.2: a plain object, version 1, a known type, a well-formed envelope.
        let data = event.data();
        if !plain_object(&data) || get(&data, "v").as_f64() != Some(1.0) {
            return;
        }
        let Some(kind) = get(&data, "type").as_string() else { return };
        let capability = match kind.as_str() {
            "evora:init" => None,
            "evora:open" => Some("doc.open"),
            "evora:saved" => Some("doc.save"),
            "evora:lang" => Some("live.lang"),
            "evora:theme" => Some("live.theme"),
            "evora:purge" => Some("storage.purge"),
            // Unknown here, or a capability this engine doesn't declare: ignored (§4.1, §10).
            _ => return,
        };
        if let Some(c) = capability {
            let st = state.borrow();
            if !st.initialized || !st.caps.iter().any(|have| have == c) {
                return;
            }
        }
        if !only_keys(&data, &["v", "type", "id", "re", "payload"]) {
            return;
        }
        let Some(id) = get(&data, "id").as_string().filter(|i| is_ulid(i)) else { return };
        let re = get(&data, "re");
        let re = if re.is_undefined() {
            None
        } else {
            match re.as_string().filter(|r| is_ulid(r)) {
                Some(r) => Some(r),
                None => return,
            }
        };
        let payload = get(&data, "payload");
        if !plain_object(&payload) {
            return;
        }
        match kind.as_str() {
            "evora:init" => on_init(state, &id, re.as_deref(), &payload),
            "evora:open" => on_open(state, &id, &payload),
            "evora:saved" => on_saved(state, re.as_deref(), &payload),
            "evora:lang" => on_lang(state, &id, &payload),
            "evora:theme" => on_theme(state, &id, &payload),
            "evora:purge" => on_purge(state, &id, &payload),
            _ => {}
        }
    }

    fn on_init(state: &Rc<RefCell<State>>, id: &str, re: Option<&str>, p: &JsValue) {
        let mut st = state.borrow_mut();
        if st.initialized || re != Some(st.ready_id.as_str()) {
            return;
        }
        let required = ["lang", "engineLang", "theme", "accent", "readOnly", "storageNs", "capabilities", "prefs", "limits"];
        let mut allowed = required.to_vec();
        allowed.push("displayName");
        if !only_keys(p, &allowed) || !required.iter().all(|k| !get(p, k).is_undefined()) {
            return;
        }
        let lang_ok = get(p, "lang").as_string().is_some_and(|l| LANGS.contains(&l.as_str()));
        let engine_lang = get(p, "engineLang");
        let engine_lang = if engine_lang.is_null() {
            Some(None)
        } else {
            engine_lang.as_string().filter(|l| is_lang_tag(l)).map(Some)
        };
        let theme = get(p, "theme").as_string();
        let dark = match theme.as_deref() {
            Some("dark") => true,
            Some("light") => false,
            _ => return,
        };
        let accent_ok = get(p, "accent").as_string().is_some_and(|a| {
            a.len() == 7 && a.starts_with('#') && a.chars().skip(1).all(|c| c.is_ascii_hexdigit())
        });
        let read_only_ok = get(p, "readOnly").as_bool().is_some();
        let ns = get(p, "storageNs").as_string().filter(|ns| crate::storage_ns::valid(ns));
        let author = get(p, "displayName");
        let author = if author.is_undefined() {
            Some(None)
        } else {
            author.as_string().filter(|a| (1..=100).contains(&a.chars().count())).map(Some)
        };
        let caps = string_list(&get(p, "capabilities"));
        let caps_ok = caps.as_ref().is_some_and(|c| c.iter().all(|x| CAPABILITY_NAMES.contains(&x.as_str())));
        let prefs_ok = plain_object(&get(p, "prefs"));
        let limits = get(p, "limits");
        let max_document = get(&limits, "maxDocumentBytes").as_f64();
        let max_export = get(&limits, "maxExportBytes").as_f64();
        let limits_ok = plain_object(&limits)
            && only_keys(&limits, &["maxDocumentBytes", "maxExportBytes"])
            && [max_document, max_export].iter().all(|m| m.is_some_and(|m| m >= 1.0 && m.fract() == 0.0));
        let (Some(engine_lang), Some(ns), Some(author), Some(caps), Some(max_document)) = (engine_lang, ns, author, caps, max_document) else {
            return;
        };
        if !(lang_ok && accent_ok && read_only_ok && caps_ok && prefs_ok && limits_ok) {
            return;
        }
        // The effective set: what the host offers and this engine declares (§9).
        st.caps = caps.into_iter().filter(|c| CAPABILITIES.contains(&c.as_str())).collect();
        st.max_document = max_document;
        st.initialized = true;
        let author = author.filter(|_| st.caps.iter().any(|c| c == "author"));
        let lang = engine_lang.and_then(|l| crate::evora_lang(&l));
        // E5 (§7.1 step 6, §7.7 b), before the answer: this account's settings are read (only with
        // `storage.ns`; otherwise the engine keeps nothing), then every other namespace and every
        // key the engine leaves outside the namespaces is erased and the erasure checked. The app
        // restores the settings on its next frame and may only then write them, under this
        // namespace, and only if the erasure was effective; otherwise it stays in memory.
        st.storage_ns = st.caps.iter().any(|c| c == "storage.ns").then_some(ns);
        let settings = st.storage_ns.as_deref().and_then(crate::storage_ns::read);
        let erased = crate::storage_ns::purge_except(st.storage_ns.as_deref());
        let storage_ns = st.storage_ns.clone().filter(|_| erased);
        st.events.borrow_mut().push(HostEvent::Init { settings, storage_ns, lang, dark, author });
        ack(&st, id, true, None);
        st.ctx.request_repaint();
    }

    fn on_open(state: &Rc<RefCell<State>>, id: &str, p: &JsValue) {
        let mut st = state.borrow_mut();
        if !only_keys(p, &["docRef", "name", "bytes", "url", "new"]) {
            return;
        }
        let Some(doc_ref) = get(p, "docRef").as_string().filter(|r| is_ulid(r)) else { return };
        let Some(name) = get(p, "name").as_string().filter(|n| is_name(n)) else { return };
        let given = ["bytes", "url", "new"].iter().filter(|k| !get(p, k).is_undefined()).count();
        if given != 1 {
            return;
        }
        if !get(p, "url").is_undefined() {
            // `url` needs `media.ranges`, which this engine doesn't declare.
            ack(&st, id, false, Some("capability"));
            return;
        }
        if !get(p, "new").is_undefined() {
            ack(&st, id, false, Some("unsupported"));
            return;
        }
        let bytes = get(p, "bytes");
        // An ArrayBuffer (never a SharedArrayBuffer or a typed view), 1 byte up to the limit.
        if !bytes.is_instance_of::<js_sys::ArrayBuffer>() {
            return;
        }
        let length = f64::from(bytes.unchecked_ref::<js_sys::ArrayBuffer>().byte_length());
        if length < 1.0 {
            return;
        }
        if length > st.max_document {
            ack(&st, id, false, Some("too_large"));
            return;
        }
        let data = js_sys::Uint8Array::new(&bytes).to_vec();
        if let Ok(mut q) = st.inbox.lock() {
            q.push((name.clone(), data));
        } else {
            ack(&st, id, false, Some("busy"));
            return;
        }
        st.docs.retain(|(n, _)| n != &name);
        st.docs.push((name, doc_ref));
        ack(&st, id, true, None);
        st.ctx.request_repaint();
    }

    fn on_saved(state: &Rc<RefCell<State>>, re: Option<&str>, p: &JsValue) {
        let mut st = state.borrow_mut();
        let Some(re) = re else { return };
        if !st.pending_saves.iter().any(|s| s == re) || !only_keys(p, &["ok", "version", "docRef", "error"]) || get(p, "ok").as_bool().is_none() {
            return;
        }
        st.pending_saves.retain(|s| s != re);
        // Without `doc.saved-ack` (patch COL-09) the engine keeps upstream's behaviour: it counts
        // a document as saved once handed over, and the host shows its own save state (§6.3).
    }

    fn on_lang(state: &Rc<RefCell<State>>, id: &str, p: &JsValue) {
        let st = state.borrow();
        if !only_keys(p, &["lang", "engineLang"]) || !get(p, "lang").as_string().is_some_and(|l| LANGS.contains(&l.as_str())) {
            return;
        }
        let engine_lang = get(p, "engineLang");
        let lang = if engine_lang.is_null() {
            None
        } else {
            match engine_lang.as_string().filter(|l| is_lang_tag(l)) {
                Some(l) => crate::evora_lang(&l),
                None => return,
            }
        };
        st.events.borrow_mut().push(HostEvent::Lang(lang));
        ack(&st, id, true, None);
        st.ctx.request_repaint();
    }

    fn on_theme(state: &Rc<RefCell<State>>, id: &str, p: &JsValue) {
        let st = state.borrow();
        let accent_ok = get(p, "accent").as_string().is_some_and(|a| a.len() == 7 && a.starts_with('#') && a.chars().skip(1).all(|c| c.is_ascii_hexdigit()));
        let dark = match get(p, "theme").as_string().as_deref() {
            Some("dark") => true,
            Some("light") => false,
            _ => return,
        };
        if !only_keys(p, &["theme", "accent"]) || !accent_ok {
            return;
        }
        // The accent is Evora's indigo already (patch E2); only light or dark changes here.
        st.events.borrow_mut().push(HostEvent::Theme(dark));
        ack(&st, id, true, None);
        st.ctx.request_repaint();
    }

    fn on_purge(state: &Rc<RefCell<State>>, id: &str, p: &JsValue) {
        let mut st = state.borrow_mut();
        let all = match get(p, "scope").as_string().as_deref() {
            Some("all") => true,
            Some("current") => false,
            _ => return,
        };
        if !only_keys(p, &["scope"]) {
            return;
        }
        // §7.7 a, E5: the writes stop first (the gate is sealed for the rest of the page's life, so
        // no later save, on a frame or on a focus change, can bring a key back), then the storage is
        // erased and checked. The answer comes only after an effective erasure; otherwise it is
        // negative ("forbidden": the browser storage could not be reached or kept a key).
        st.gate.borrow_mut().seal();
        let erased = if all { crate::storage_ns::purge_all() } else { crate::storage_ns::purge_current(st.storage_ns.as_deref()) };
        st.storage_ns = None;
        if erased {
            ack(&st, id, true, None);
        } else {
            ack(&st, id, false, Some("forbidden"));
        }
    }

    fn ack(st: &State, re: &str, ok: bool, code: Option<&str>) {
        let mut fields: Vec<(&str, JsValue)> = vec![("ok", ok.into())];
        if let Some(code) = code {
            fields.push(("code", code.into()));
        }
        if let Some(payload) = object(&fields) {
            let _ = send(st, "evora:ack", Some(re), &payload, None);
        }
    }

    /// Post a message to the parent origin; returns its `id`.
    fn send(st: &State, kind: &str, re: Option<&str>, payload: &js_sys::Object, transfer: Option<&JsValue>) -> Option<String> {
        let (message, id) = envelope(kind, re, payload)?;
        let sent = match transfer {
            Some(t) => st.parent.post_message_with_transfer(&message, &st.origin, &js_sys::Array::of1(t)),
            None => st.parent.post_message(&message, &st.origin),
        };
        sent.ok().map(|()| id)
    }

    fn envelope(kind: &str, re: Option<&str>, payload: &js_sys::Object) -> Option<(js_sys::Object, String)> {
        let id = ulid();
        let mut fields: Vec<(&str, JsValue)> = vec![("v", 1.0.into()), ("type", kind.into()), ("id", id.clone().into())];
        if let Some(re) = re {
            fields.push(("re", re.into()));
        }
        fields.push(("payload", payload.clone().into()));
        Some((object(&fields)?, id))
    }

    fn object(fields: &[(&str, JsValue)]) -> Option<js_sys::Object> {
        let m = js_sys::Object::new();
        for (key, value) in fields {
            js_sys::Reflect::set(&m, &JsValue::from_str(key), value).ok()?;
        }
        Some(m)
    }

    fn get(data: &JsValue, key: &str) -> JsValue {
        if !data.is_object() {
            return JsValue::UNDEFINED;
        }
        js_sys::Reflect::get(data, &JsValue::from_str(key)).unwrap_or(JsValue::UNDEFINED)
    }

    /// A plain object: not null, not an array, prototype `Object.prototype` (§5.2 step 2).
    fn plain_object(v: &JsValue) -> bool {
        if !v.is_object() || js_sys::Array::is_array(v) {
            return false;
        }
        let plain = js_sys::Object::get_prototype_of(&js_sys::Object::new().into());
        js_sys::Object::is(&js_sys::Object::get_prototype_of(v), &plain)
    }

    /// No property outside `allowed` (`additionalProperties: false`).
    fn only_keys(v: &JsValue, allowed: &[&str]) -> bool {
        if !v.is_object() {
            return false;
        }
        js_sys::Object::keys(v.unchecked_ref::<js_sys::Object>()).iter().all(|k| k.as_string().is_some_and(|k| allowed.contains(&k.as_str())))
    }

    fn string_list(v: &JsValue) -> Option<Vec<String>> {
        if !js_sys::Array::is_array(v) {
            return None;
        }
        let list: Vec<String> = js_sys::Array::from(v).iter().map(|x| x.as_string()).collect::<Option<Vec<_>>>()?;
        let mut unique = list.clone();
        unique.sort();
        unique.dedup();
        (unique.len() == list.len()).then_some(list)
    }

    const CROCKFORD: &[u8; 32] = b"0123456789ABCDEFGHJKMNPQRSTVWXYZ";

    fn is_ulid(s: &str) -> bool {
        s.len() == 26 && s.bytes().all(|b| CROCKFORD.contains(&b))
    }

    /// A fresh ULID: 48 bits of milliseconds, then 80 random bits (§3: unique per sender).
    fn ulid() -> String {
        let mut time = js_sys::Date::now() as u64;
        let mut out = [b'0'; 26];
        for slot in out.iter_mut().take(10).rev() {
            *slot = CROCKFORD[(time % 32) as usize];
            time /= 32;
        }
        for slot in out.iter_mut().skip(10) {
            *slot = CROCKFORD[((js_sys::Math::random() * 32.0) as usize) % 32];
        }
        String::from_utf8_lossy(&out).into_owned()
    }

    /// `name` of §4.2: 1 to 255 characters, no `/`, `\` or control character.
    fn is_name(n: &str) -> bool {
        (1..=255).contains(&n.chars().count()) && !n.chars().any(|c| c == '/' || c == '\\' || c.is_control())
    }

    /// A file name the host's schema accepts, from the app's document name.
    fn clean_name(n: &str) -> String {
        let cleaned: String = n.chars().map(|c| if c == '/' || c == '\\' || c.is_control() { '_' } else { c }).take(255).collect();
        if cleaned.trim().is_empty() { "document.pdf".to_string() } else { cleaned }
    }

    /// `engineLang` of §4.2: `^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$`.
    fn is_lang_tag(tag: &str) -> bool {
        let mut parts = tag.split(['-', '_']);
        let first_ok = parts.next().is_some_and(|p| (2..=3).contains(&p.len()) && p.chars().all(|c| c.is_ascii_alphabetic()));
        first_ok && parts.all(|p| (2..=8).contains(&p.len()) && p.chars().all(|c| c.is_ascii_alphanumeric()))
    }
}

/// Evora: the app as eframe runs it. It hands the host's requests (EHP, `ehp::HostEvent`) to
/// `PdfCraftApp` at the start of each frame and otherwise defers to it entirely.
#[cfg(target_arch = "wasm32")]
struct EvoraApp {
    inner: pdfcraft_ui_egui::PdfCraftApp,
    events: ehp::Events,
    /// E5: `Some` under the Evora bridge (`?host=evora`): whether, and where, the settings may be
    /// written. `None` outside the bridge, where upstream's saving is unchanged.
    gate: Option<storage_ns::SharedGate>,
}

#[cfg(target_arch = "wasm32")]
impl EvoraApp {
    fn apply_host_events(&mut self) {
        let events: Vec<ehp::HostEvent> = std::mem::take(&mut *self.events.borrow_mut());
        for event in events {
            match event {
                ehp::HostEvent::Init { settings, storage_ns, lang, dark, author } => {
                    // E5: this account's settings first, then the host's language, theme and author
                    // on top; only then may the settings be written, under this account's namespace
                    // (unless a purge has sealed the gate meanwhile).
                    if let Some(json) = settings {
                        self.inner.restore(&json);
                    }
                    self.inner.language = lang.unwrap_or("en").to_string();
                    self.set_dark(dark);
                    if let Some(author) = author {
                        self.inner.comment_prefs.author = author;
                    }
                    if let (Some(gate), Some(ns)) = (&self.gate, storage_ns) {
                        gate.borrow_mut().open(&ns);
                    }
                }
                ehp::HostEvent::Lang(lang) => self.inner.language = lang.unwrap_or("en").to_string(),
                ehp::HostEvent::Theme(dark) => self.set_dark(dark),
            }
        }
    }

    fn set_dark(&mut self, dark: bool) {
        use pdfcraft_ui_egui::theme::ThemePreference;
        self.inner.set_theme_preference(if dark { ThemePreference::Dark } else { ThemePreference::Light });
    }
}

#[cfg(target_arch = "wasm32")]
impl eframe::App for EvoraApp {
    fn raw_input_hook(&mut self, ctx: &egui::Context, raw: &mut egui::RawInput) {
        eframe::App::raw_input_hook(&mut self.inner, ctx, raw);
    }

    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        match &self.gate {
            // Outside the Evora bridge: upstream's saving, unchanged (shared key "pdfcraft").
            None => eframe::App::save(&mut self.inner, storage),
            // E5: under this account's namespace only, once `evora:init` has opened the gate, and
            // never after `evora:purge` has sealed it.
            Some(gate) => {
                let key = gate.borrow().key();
                if let Some(key) = key {
                    storage.set_string(&key, self.inner.persist());
                }
            }
        }
    }

    fn persist_egui_memory(&self) -> bool {
        // E5: under the Evora bridge, eframe's UI memory (`egui_memory_ron`, one key for the whole
        // origin, outside any namespace) is never written.
        self.gate.is_none() && eframe::App::persist_egui_memory(&self.inner)
    }

    fn logic(&mut self, ctx: &egui::Context, frame: &mut eframe::Frame) {
        self.apply_host_events();
        eframe::App::logic(&mut self.inner, ctx, frame);
    }

    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        eframe::App::ui(&mut self.inner, ui, frame);
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn main() {
    eprintln!("pdfcraft-web targets wasm32: run `trunk serve` or `trunk build --release` in apps/pdfcraft-web");
}

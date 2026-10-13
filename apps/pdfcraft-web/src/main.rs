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
                    // Evora (E9, E10): `?evora-audit=1` (CI smoke test) audits every text drawn.
                    if query_param("evora-audit").as_deref() == Some("1") {
                        cc.egui_ctx.add_plugin(e10::Audit::new(query_param("evora-probe")));
                    }
                    // Evora (E5): the browser storage is a namespace per Evora account. Settings are kept
                    // under `evora.pdfcraft.<storageNs>`, the namespace the host sends in `evora:init`
                    // (HOST-PROTOCOL.md §4.3, §7.7); until it arrives they stay in memory only. Upstream's
                    // shared keys ("pdfcraft", and "printcraft" from the app's former name), readable by
                    // every account of the browser, are neither read nor written, and are purged.
                    app.storage_key = None;
                    storage_ns::purge_legacy();
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
                    // `?host=parent`: a same-origin page embedding PdfCraft in an iframe (such
                    // as the Nextcloud app) passes files in and takes saves back (`host` below).
                    if query_param("host").as_deref() == Some("parent")
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
                    }
                    Ok(Box::new(app))
                }),
            )
            .await;
        if let Err(e) = started {
            eframe::web_sys::console::error_1(&e);
            if query_param("host").as_deref() == Some("parent")
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

/// Evora (E5): the engine's browser storage as a namespace per Evora account (`storageNs`, an
/// opaque HMAC of the account, sent by the host). A namespace, not a partition: any script of the
/// engine's origin can still list every key; the isolation comes from serving the engine on its
/// own site (mode B). This engine keeps its settings in localStorage only (no OPFS, no IndexedDB).
#[cfg(target_arch = "wasm32")]
#[allow(dead_code)] // `read` and `purge` serve the host bridge's `evora:init` and `evora:purge`.
mod storage_ns {
    /// Upstream's keys, shared by every account of the browser.
    const LEGACY: [&str; 2] = ["pdfcraft", "printcraft"];
    /// Prefix of the namespaced keys.
    const PREFIX: &str = "evora.pdfcraft.";

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

    /// Remove upstream's shared keys.
    pub fn purge_legacy() {
        if let Some(s) = storage() {
            for k in LEGACY {
                let _ = s.remove_item(k);
            }
        }
    }

    /// Remove this engine's namespaced keys except namespace `keep`, and the shared ones.
    /// `keep: None` removes every namespace (`evora:purge` with `scope: "all"`).
    pub fn purge(keep: Option<&str>) {
        purge_legacy();
        let Some(s) = storage() else { return };
        let keep = keep.and_then(key);
        let mut doomed = Vec::new();
        for i in 0..s.length().unwrap_or(0) {
            if let Ok(Some(k)) = s.key(i)
                && k.starts_with(PREFIX)
                && Some(&k) != keep.as_ref()
            {
                doomed.push(k);
            }
        }
        for k in doomed {
            let _ = s.remove_item(&k);
        }
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
/// Only the parent window on the app's own origin is heard or answered.
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
        /// `None` when the page isn't framed (there is no parent to talk to).
        pub fn new() -> Option<Self> {
            let window = web_sys::window()?;
            let parent = window.parent().ok().flatten()?;
            if js_sys::Object::is(&parent, &window) {
                return None;
            }
            let origin = window.location().origin().ok()?;
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

#[cfg(not(target_arch = "wasm32"))]
fn main() {
    eprintln!("pdfcraft-web targets wasm32: run `trunk serve` or `trunk build --release` in apps/pdfcraft-web");
}

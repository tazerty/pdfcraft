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
        // Evora (COL-40): under the Evora bridge, eframe never gets the UI memory an earlier session
        // left (`egui_memory_ron`, one key for the whole origin, outside any namespace). eframe reads
        // that key as it starts, before `evora:ready` and `evora:init` (HOST-PROTOCOL.md §4.3, §4.4);
        // the bridge never writes it and `evora:init` erases it anyway, so it goes first, unread.
        if query_param("host").as_deref() == Some("evora") {
            storage_ns::forget_eframe_memory();
        }
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
                    // Evora (COL-09): not under the Evora bridge, where the host page owns that prompt.
                    if !evora_host {
                        warn_before_unload(app.unsaved_flag.clone());
                    }
                    // Evora (E4, COL-02): `?host=evora` speaks the Evora host protocol (EHP v1) with the
                    // parent origin that `evora-host.json` admits (module `ehp` below).
                    let events = ehp::Events::default();
                    let probe = ehp::Probe::default();
                    let mut gate = None;
                    let mut bridge_link = None;
                    if evora_host {
                        let shared = storage_ns::SharedGate::default();
                        let link = ehp::Link::default();
                        // COL-08, COL-09: saves wait for `evora:saved` when `doc.saved-ack` is effective.
                        app.host_save_ack = Some(link.save_fn());
                        app.host_dirty = Some(link.dirty_fn());
                        // COL-42: under the bridge the browser downloads nothing; every file the app
                        // would download goes to the host (`evora:export`), or is refused.
                        // SABORDAGE QA (EVORA-COL-47) S4 : aucun relais d'export, le navigateur télécharge.
                        PdfCraftApp::set_host_export(None);
                        let _ = link.export_fn();
                        // COL-42: F6 gives the keyboard back to the host (`ui.focus-out`).
                        // SABORDAGE QA (EVORA-COL-47) S5 : F6 n'est plus écoutée.
                        let _ = ehp::listen_exit_key as fn(ehp::Link);
                        let outcomes = app.host_save_outcomes.clone();
                        ehp::connect(link.clone(), outcomes, events.clone(), shared.clone(), cc.egui_ctx.clone());
                        // CI only (`?evora-audit=1`): the smoke test edits the document (`window.__evoraRun`).
                        if query_param("evora-audit").as_deref() == Some("1") {
                            ehp::install_probe(probe.clone(), cc.egui_ctx.clone());
                        }
                        gate = Some(shared);
                        bridge_link = Some(link);
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
                    Ok(Box::new(EvoraApp {
                        inner: app,
                        events,
                        gate,
                        link: bridge_link,
                        probe,
                        pending_open: None,
                        held: Vec::new(),
                        catalog_due: false,
                    }))
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

/// Evora (EVO-CMD, COL-43): the commands Evora may run in the Atelier.
#[cfg(target_arch = "wasm32")]
mod host_commands;

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
/// What this engine keeps in the browser, as measured in its code: its settings and eframe's UI
/// memory (`egui_memory_ron`), both in localStorage. No OPFS, no IndexedDB, no Cache Storage, no
/// cookie, and no recovery store on the web (`RecoveryStore` is desktop only). Under the bridge, the
/// member's signatures, initials, digital IDs and trusted certificates are never among the settings
/// written, and are ignored if an earlier build left them there (COL-42, [`IDENTITY_SETTINGS`]):
/// they live in memory for the session only. Under the bridge:
/// - the settings are written only under `evora.pdfcraft.<storageNs>`, once `evora:init` has given
///   the namespace and the app has restored them, and eframe's UI memory is never written
///   ([`Gate`], `EvoraApp::save`);
/// - `evora:init` erases, before its answer, every other namespace and every key the engine leaves
///   outside the namespaces on its origin ([`LOOSE`]) (§7.1 step 6, §7.7 b);
/// - `evora:purge` first seals the gate (no write any more, for the rest of the page's life), then
///   erases, checks that nothing is left, and only then answers (§7.7 a);
/// - the engine's other pages on the origin (a second editor tab of the same account, the next
///   account's session) are told of each erasure, and stand down when it covers their namespace
///   ([`watch`]): otherwise eframe, which saves every 30 s and on each loss of focus, even in a hidden
///   tab, would write the erased namespace back from their memory.
///
/// Nothing else erases anything: no URL parameter, no other message, not the start of the page, with
/// one exception (COL-40): under the bridge, eframe's UI memory, which the bridge never writes and
/// `evora:init` would erase anyway, goes before eframe starts, so that eframe never reads what an
/// earlier session left there ([`forget_eframe_memory`]). An `evora:init` whose erasure isn't
/// effective is refused (COL-40). Outside the bridge, upstream's behaviour is unchanged.
#[cfg(target_arch = "wasm32")]
mod storage_ns {
    use std::cell::RefCell;
    use std::rc::Rc;

    use eframe::wasm_bindgen::{JsCast, JsValue, closure::Closure};

    /// Prefix of the namespaced keys.
    const PREFIX: &str = "evora.pdfcraft.";
    /// eframe's UI memory, read by eframe as it starts and written by it on each save (one key for the
    /// whole origin).
    const EFRAME_MEMORY: &str = "egui_memory_ron";
    /// The keys this engine writes outside the namespaces on its origin: upstream's shared settings,
    /// the settings of the app's former name (PrintCraft), and eframe's UI memory.
    const LOOSE: [&str; 3] = ["pdfcraft", "printcraft", EFRAME_MEMORY];
    /// The channel on which the engine's pages of one origin tell each other what they erased.
    const CHANNEL: &str = "evora.pdfcraft.erased";

    /// Whether, and where, the settings may be written: shared by the bridge, which names the
    /// namespace (`evora:init`), opens the gate (once the app has restored the account's settings) and
    /// seals it (`evora:purge`, or an erasure of the namespace by another page), and by the app, which
    /// asks it on every save. Closed at first; sealed for good.
    #[derive(Default)]
    pub struct Gate {
        /// The key of this page's namespace, from `evora:init` on; kept once sealed, so that a later
        /// erasure of it by another page is still recognised.
        own: Option<String>,
        open: bool,
        sealed: bool,
    }

    pub type SharedGate = Rc<RefCell<Gate>>;

    impl Gate {
        /// The key the settings may be written under now, if any.
        pub fn key(&self) -> Option<String> {
            if self.open && !self.sealed { self.own.clone() } else { None }
        }

        /// `evora:init` names this page's namespace `ns`, before the app restores its settings.
        pub fn name(&mut self, ns: &str) {
            if !self.sealed {
                self.own = key(ns);
            }
        }

        /// Allow writing under the named namespace, unless a purge has sealed the gate.
        pub fn open(&mut self) {
            if !self.sealed && self.own.is_some() {
                self.open = true;
            }
        }

        /// Stop every write, for the rest of the page's life.
        pub fn seal(&mut self) {
            self.sealed = true;
            self.open = false;
        }
    }

    /// What a page erased, as told to the engine's other pages of the origin.
    pub enum Erased<'a> {
        /// `evora:purge {scope: "all"}`: every namespace.
        All,
        /// `evora:purge {scope: "current"}`: this namespace (`None`: none, only the loose keys).
        Current(Option<&'a str>),
        /// `evora:init`: every namespace except this one (`None`: every namespace).
        Except(Option<&'a str>),
    }

    fn encode(erased: &Erased<'_>) -> String {
        match erased {
            Erased::All => "all".to_string(),
            Erased::Current(ns) => format!("current:{}", ns.unwrap_or("")),
            Erased::Except(ns) => format!("except:{}", ns.unwrap_or("")),
        }
    }

    /// Whether the erasure another page told (`message`, from [`encode`]) covers the namespace key
    /// `own`; `None` for a message of another form, which is ignored.
    fn covers(message: &str, own: &str) -> Option<bool> {
        let well_formed = |ns: &str| ns.is_empty() || valid(ns);
        if message == "all" {
            return Some(true);
        }
        if let Some(ns) = message.strip_prefix("current:") {
            return well_formed(ns).then(|| key(ns).as_deref() == Some(own));
        }
        if let Some(ns) = message.strip_prefix("except:") {
            return well_formed(ns).then(|| key(ns).as_deref() != Some(own));
        }
        None
    }

    /// Another page of the origin erased this page's namespace: no write any more, and the key erased
    /// again if this page wrote it back meanwhile (the pages' tasks run in any order).
    fn stand_down(gate: &SharedGate) {
        let own = {
            let mut g = gate.borrow_mut();
            g.seal();
            g.own.clone()
        };
        if let Some(k) = own
            && let Some(s) = storage()
            && s.get_item(&k).ok().flatten().is_some()
        {
            let _ = s.remove_item(&k);
        }
    }

    /// Under the bridge, listen for the erasures made by the engine's other pages of this origin, and
    /// stand down ([`stand_down`]) when one covers this page's namespace:
    /// - told on [`CHANNEL`] (`evora:purge` or the start purge of `evora:init` there), which covers a
    ///   namespace not written yet as well;
    /// - seen by the browser's `storage` event: another page removed this page's key, or cleared
    ///   localStorage (an event of sessionStorage, which the engine doesn't use, is left aside).
    ///
    /// Returns the channel this page tells its own erasures on ([`announce`]).
    pub fn watch(gate: &SharedGate) -> Option<web_sys::BroadcastChannel> {
        let window = web_sys::window()?;
        let on_storage = {
            let gate = gate.clone();
            Closure::<dyn FnMut(web_sys::StorageEvent)>::new(move |event: web_sys::StorageEvent| {
                let session = web_sys::window().and_then(|w| w.session_storage().ok().flatten());
                if let (Some(area), Some(session)) = (event.storage_area(), session)
                    && js_sys::Object::is(&area, &session)
                {
                    return;
                }
                let erased = match event.key() {
                    None => true,
                    Some(k) => event.new_value().is_none() && gate.borrow().own.as_deref() == Some(k.as_str()),
                };
                if erased {
                    stand_down(&gate);
                }
            })
        };
        if window.add_event_listener_with_callback("storage", on_storage.as_ref().unchecked_ref()).is_ok() {
            // The listener lives as long as the page.
            on_storage.forget();
        }
        let channel = web_sys::BroadcastChannel::new(CHANNEL).ok()?;
        let on_message = {
            let gate = gate.clone();
            Closure::<dyn FnMut(web_sys::MessageEvent)>::new(move |event: web_sys::MessageEvent| {
                let Some(message) = event.data().as_string() else { return };
                let own = gate.borrow().own.clone();
                if let Some(own) = own
                    && covers(&message, &own) == Some(true)
                {
                    stand_down(&gate);
                }
            })
        };
        if channel.add_event_listener_with_callback("message", on_message.as_ref().unchecked_ref()).is_ok() {
            on_message.forget();
        }
        Some(channel)
    }

    /// Tell the engine's other pages of the origin what this page erases.
    pub fn announce(channel: Option<&web_sys::BroadcastChannel>, erased: &Erased<'_>) {
        if let Some(c) = channel {
            let _ = c.post_message(&JsValue::from_str(&encode(erased)));
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

    /// What an erasure came to.
    #[derive(Clone, Copy, PartialEq, Eq)]
    pub enum Erasure {
        /// Every key it picked is gone, checked by listing the storage again.
        Done,
        /// The browser gives this page no storage at all: nothing can be read, written or erased.
        NoStorage,
        /// The storage couldn't be listed, or a key survived: the erasure isn't effective.
        Failed,
    }

    /// Remove this engine's keys that `doomed` picks, then check that none is left.
    fn erase(doomed: impl Fn(&str) -> bool) -> Erasure {
        let Some(s) = storage() else { return Erasure::NoStorage };
        let Some(before) = engine_keys(&s) else { return Erasure::Failed };
        for k in before.iter().filter(|k| doomed(k.as_str())) {
            let _ = s.remove_item(k);
        }
        if engine_keys(&s).is_some_and(|after| !after.iter().any(|k| doomed(k.as_str()))) { Erasure::Done } else { Erasure::Failed }
    }

    /// `evora:init` (§7.7 b): every key of this engine except namespace `keep`.
    pub fn purge_except(keep: Option<&str>) -> Erasure {
        let keep = keep.and_then(key);
        erase(|k| keep.as_deref() != Some(k))
    }

    /// `evora:purge` with `scope: "current"`: namespace `ns` and the keys outside the namespaces.
    pub fn purge_current(ns: Option<&str>) -> Erasure {
        let current = ns.and_then(key);
        erase(|k| LOOSE.contains(&k) || current.as_deref() == Some(k))
    }

    /// `evora:purge` with `scope: "all"`: every namespace and the keys outside them.
    pub fn purge_all() -> Erasure {
        erase(|_| true)
    }

    /// COL-40, before eframe starts under the bridge: eframe's UI memory goes, unread, so that eframe
    /// (which reads it as it starts, before `evora:init`) never gets what an earlier session left.
    pub fn forget_eframe_memory() {
        if let Some(s) = storage() {
            let _ = s.remove_item(EFRAME_MEMORY);
        }
    }

    /// COL-42: the settings the Atelier never keeps in the browser under the bridge: the member's
    /// drawn, typed or image signature, initials and signature graphic, digital IDs and trusted
    /// certificates (keys of `PdfCraftApp::persist`). They stay in memory for the session only.
    pub const IDENTITY_SETTINGS: [&str; 7] =
        ["signature", "signature_text", "signature_image", "initials", "sign_graphic", "digital_ids", "trusted"];

    /// The settings `json` without [`IDENTITY_SETTINGS`]; `None` when it isn't a JSON object (then
    /// nothing is written, nor restored).
    pub fn without_identity(json: &str) -> Option<String> {
        let value = js_sys::JSON::parse(json).ok()?;
        if !value.is_object() || js_sys::Array::is_array(&value) {
            return None;
        }
        let object: &js_sys::Object = value.unchecked_ref();
        for key in IDENTITY_SETTINGS {
            if !js_sys::Reflect::delete_property(object, &JsValue::from_str(key)).ok()? {
                return None;
            }
        }
        js_sys::JSON::stringify(&value).ok().map(String::from)
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
        probe_hits: u64,
        /// `?evora-probe=a|b|c` (EVORA-COL-25): texts drawn that contain each probe. One probe
        /// without `|` counts as before; `probe` (texts with any probe) stays.
        probes: Vec<(String, u64)>,
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
            let probes: Vec<(String, u64)> = probe.as_deref().map(|p| p.split('|').filter(|s| !s.is_empty()).map(|s| (s.to_string(), 0)).collect()).unwrap_or_default();
            Self { probes, ..Self::default() }
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
                    let mut hit = false;
                    for (probe, count) in &mut self.probes {
                        if shown.contains(probe.as_str()) {
                            *count += 1;
                            hit = true;
                        }
                    }
                    if hit {
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
            let probes = js_sys::Object::new();
            for (probe, count) in &self.probes {
                let _ = js_sys::Reflect::set(&probes, &JsValue::from_str(probe), &JsValue::from_f64(*count as f64));
            }
            let _ = js_sys::Reflect::set(&report, &JsValue::from_str("probes"), &probes);
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
/// Handled: `evora:init` (refused, `forbidden`, when its erasure isn't effective, COL-40), `evora:open`
/// (bytes, answered once the app has really opened them or failed to, COL-40; the same `docRef` again
/// replaces the document),
/// `evora:request-save` (COL-08: `evora:save` with `re`, or `evora:ack` `clean`), `evora:saved`
/// (COL-09, with `doc.saved-ack` effective: the document counts as saved only on `ok: true` and only
/// if unchanged since, and the engine then tells its state again, l.480; without it, upstream's
/// behaviour and the host's own save state, §6.3), `evora:lang`, `evora:theme`, `evora:purge`.
/// Sent: `evora:ready`, `evora:failed`, `evora:ack`, `evora:dirty` (only once the host has opened a
/// document, and again after each `evora:open` and each successful `evora:saved`), `evora:save`.
#[cfg(target_arch = "wasm32")]
mod ehp {
    use std::cell::RefCell;
    use std::rc::Rc;

    use eframe::wasm_bindgen::{JsCast, JsValue, closure::Closure};

    /// Build slug and protocol version announced in `evora:ready` (§4.4, §10).
    const APP: &str = "colophon-atelier";
    const EHP: &str = "1.0";
    /// What this engine honours (§9.1). COL-42: `export.drive` (every file the app would download
    /// goes to the host) and `ui.focus-out` (F6, amendment A-19 of §7.9, which a host of minor 0
    /// accepts: the engine still speaks EHP 1.0); COL-43: `command` and `command.catalog` (EVO-CMD).
    const CAPABILITIES: [&str; 14] = [
        "doc.open",
        "doc.save",
        "doc.saved-ack",
        "doc.dirty",
        "doc.request-save",
        "export.drive",
        "command",
        "command.catalog",
        "ui.focus-out",
        "live.lang",
        "live.theme",
        "storage.ns",
        "storage.purge",
        "author",
    ];
    /// `ackCode` (§3): the `error` an unsuccessful `evora:saved` may carry.
    const ACK_CODES: [&str; 16] = [
        "clean",
        "cancelled",
        "conflict",
        "too_large",
        "quota",
        "forbidden",
        "not_found",
        "invalid_content",
        "unsupported",
        "rate_limited",
        "read_only",
        "busy",
        "capability",
        "network",
        "server",
        "timeout",
    ];
    /// `evora:request-save` reasons (§4.3).
    const SAVE_REASONS: [&str; 5] = ["autosave", "visibility", "close", "logout", "user"];
    /// CI only: what the smoke test may run in the engine (`window.__evoraRun`, [`install_probe`]).
    const PROBE_COMMANDS: [&str; 2] = ["page.rotate", PROBE_PASSWORD];
    /// CI only (COL-40, correction 1): answers the password prompt with [`PROBE_PASSWORD_VALUE`], as
    /// the prompt's Open button does. No free text crosses: the value is fixed.
    pub const PROBE_PASSWORD: &str = "evora-ci.password";
    /// CI only: the user password of the encrypted PDF the smoke test generates (scenario
    /// « pont-robustesse », detector `rob-chiffre-depot`). A test fixture's, never a secret.
    pub const PROBE_PASSWORD_VALUE: &str = "evora-smoke";
    /// The admitted parent origins, beside `index.html` (§2.3).
    const CONFIG: &str = "evora-host.json";
    const LANGS: [&str; 14] = ["ar", "de", "en", "es", "fr", "hi", "id", "it", "ja", "ko", "pt", "ru", "tr", "zh-Hans"];
    /// COL-42: the key that gives the keyboard back to the host, without a modifier (§7.9).
    const EXIT_KEY: &str = "F6";
    /// `command` of `evora:command` (§4.3, §9.1): at most 100 characters.
    const COMMAND_MAX_CHARS: usize = 100;
    /// What an `evora:init` may name: §4.2, and the extensions of the host's ceiling (§9.1).
    const CAPABILITY_NAMES: [&str; 23] = [
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
        "ui.focus-out",
        "ui.activity",
        "drop.files",
        "prefs.sync",
        "command.catalog",
    ];

    /// What the host asks of the app, applied at the start of the next frame (`EvoraApp::logic`).
    pub enum HostEvent {
        /// `evora:init`: the account's saved settings (read before the other namespaces were
        /// erased), whether the settings may then be written under the namespace the bridge named in
        /// the gate (`false`: memory only), the language (`None`: English), the theme and the author
        /// name.
        Init { settings: Option<String>, writable: bool, lang: Option<&'static str>, dark: bool, author: Option<String> },
        Lang(Option<&'static str>),
        Theme(bool),
        /// COL-08: `evora:request-save` `re` for the session's document `doc` (`DocId.0`).
        RequestSave { re: String, doc: u64 },
        /// `evora:open` `re` (COL-40): the app opens the bytes, then the bridge answers. S-ACK-6: the
        /// same `docRef` again ("reload the server's version") replaces the document it names.
        Open(OpenRequest),
        /// COL-43: `evora:command` `re`: the command, whether its `params` were `{}`, and whether
        /// Evora's member confirmed it (`confirmed: true`).
        Command { re: String, command: String, params_empty: bool, confirmed: bool },
    }

    /// An `evora:open` with bytes, checked, for the app to open on its next frame.
    pub struct OpenRequest {
        pub re: String,
        pub doc_ref: String,
        pub name: String,
        pub bytes: Vec<u8>,
    }

    /// COL-40: a document the host opened, known by the session's id of the document (`DocId.0`),
    /// never by its name (a local file of the same name would otherwise be saved as it).
    struct HostDoc {
        doc: u64,
        doc_ref: String,
    }

    pub type Events = Rc<RefCell<Vec<HostEvent>>>;

    /// CI only: commands queued by the smoke test (`window.__evoraRun`), run on the next frame.
    pub type Probe = Rc<RefCell<Vec<String>>>;

    /// An `evora:save` sent and not answered yet: its `id`, the app's ticket, the session's document,
    /// and whether `doc.saved-ack` was effective (the app then waits for the answer).
    struct PendingSave {
        id: String,
        ticket: u64,
        doc: u64,
        acked: bool,
    }

    struct State {
        parent: web_sys::Window,
        origin: String,
        ctx: egui::Context,
        events: Events,
        /// E5: whether, and where, the app may write its settings (`storage_ns::Gate`).
        gate: crate::storage_ns::SharedGate,
        /// E5: where this page tells the engine's other pages of the origin what it erases.
        channel: Option<web_sys::BroadcastChannel>,
        ready_id: String,
        initialized: bool,
        caps: Vec<String>,
        max_document: f64,
        /// COL-42: `limits.maxExportBytes` of `evora:init`.
        max_export: f64,
        /// COL-42: the session's document shown now (`DocId.0`), whose `docRef` an `evora:export`
        /// names when the host opened it.
        active_doc: Option<u64>,
        storage_ns: Option<String>,
        /// The documents the host opened, to tell which one a save is (COL-40: by document, not name).
        docs: Vec<HostDoc>,
        pending_saves: Vec<PendingSave>,
        /// COL-09: where the app reads the outcome of each acknowledged save (by ticket).
        outcomes: pdfcraft_ui_egui::HostSaveOutcomes,
        next_ticket: u64,
        /// COL-08: the `evora:request-save` the next `evora:save` answers (its `re`), and why that
        /// save could not go out, if it couldn't.
        request: Option<String>,
        request_failure: Option<&'static str>,
        /// The modified state last told to the host; `None` again after each `evora:open`, so that
        /// the state of the newly opened document follows its answer (§7.1 step 8).
        last_dirty: Option<bool>,
    }

    /// The bridge once connected; empty until `evora-host.json` is read and the parent admitted.
    #[derive(Clone, Default)]
    pub struct Link(Rc<RefCell<Option<Rc<RefCell<State>>>>>);

    impl Link {
        fn state(&self) -> Option<Rc<RefCell<State>>> {
            self.0.borrow().clone()
        }

        /// `evora:save` for the app's Save and Save As (`HostSaveAckFn`), with `re` when it answers
        /// the host's `evora:request-save` (COL-08). With `doc.saved-ack` effective (COL-09) the app
        /// gets a ticket and the document stays modified until `evora:saved`; otherwise the app
        /// counts it saved once handed over, as upstream does.
        pub fn save_fn(&self) -> pdfcraft_ui_egui::HostSaveAckFn {
            let link = self.clone();
            Box::new(move |doc: u64, name: &str, bytes: &[u8], save_as: bool| {
                let state = link.state().ok_or_else(|| "Evora is not connected yet".to_string())?;
                let mut st = state.borrow_mut();
                if !st.initialized || !st.caps.iter().any(|c| c == "doc.save") {
                    return Err("Evora is not ready to save yet".into());
                }
                // COL-40: the host's document is the one the host opened in this very tab, never one
                // found by its name: a local file of the same name is not saved as it.
                let Some(doc_ref) = st.docs.iter().find(|d| d.doc == doc).map(|d| d.doc_ref.clone()) else {
                    st.request_failure = Some("not_found");
                    return Err("only a document opened from Evora can be saved here".into());
                };
                if bytes.is_empty() {
                    st.request_failure = Some("invalid_content");
                    return Err("the document is empty".into());
                }
                if bytes.len() as f64 > st.max_document {
                    st.request_failure = Some("too_large");
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
                // COL-08: the answer to the host's `evora:request-save`, when this save is one.
                let re = st.request.clone();
                let id = send(&st, "evora:save", re.as_deref(), &payload, Some(&buffer)).ok_or_else(|| "couldn't send the document".to_string())?;
                st.request = None;
                let acked = st.caps.iter().any(|c| c == "doc.saved-ack");
                st.next_ticket += 1;
                let ticket = st.next_ticket;
                st.pending_saves.push(PendingSave { id, ticket, doc, acked });
                Ok(acked.then_some(ticket))
            })
        }

        /// COL-08: answer the host's `evora:request-save` `re` with `evora:ack`.
        pub fn answer(&self, re: &str, ok: bool, code: &str) {
            if let Some(state) = self.state() {
                ack(&state.borrow(), re, ok, Some(code));
            }
        }

        /// COL-40: the session's document that holds the host's document `doc_ref`, if it is open.
        pub fn doc_of(&self, doc_ref: &str) -> Option<u64> {
            let state = self.state()?;
            let st = state.borrow();
            st.docs.iter().find(|d| d.doc_ref == doc_ref).map(|d| d.doc)
        }

        /// COL-40, S-ACK-6: the host's document `doc_ref` is no longer open (its tab was closed to be
        /// replaced).
        pub fn forget(&self, doc_ref: &str) {
            if let Some(state) = self.state() {
                state.borrow_mut().docs.retain(|d| d.doc_ref != doc_ref);
            }
        }

        /// COL-40: the answer to `evora:open` `re`, once the app has really opened the bytes (`Ok`:
        /// the session's document, which `doc_ref` names from then on) or failed to (`Err`: the
        /// `ackCode`). The state of the opened document follows on the next frame (§7.1 step 8).
        pub fn opened(&self, re: &str, doc_ref: &str, outcome: Result<u64, &'static str>) {
            let Some(state) = self.state() else { return };
            let mut st = state.borrow_mut();
            match outcome {
                Ok(doc) => {
                    st.docs.retain(|d| d.doc_ref != doc_ref && d.doc != doc);
                    st.docs.push(HostDoc { doc, doc_ref: doc_ref.to_string() });
                    st.last_dirty = None;
                    ack(&st, re, true, None);
                }
                Err(code) => {
                    st.docs.retain(|d| d.doc_ref != doc_ref);
                    ack(&st, re, false, Some(code));
                }
            }
            st.ctx.request_repaint();
        }

        /// COL-08: the next `evora:save` answers the host's `evora:request-save` `re`.
        pub fn arm_request(&self, re: &str) {
            if let Some(state) = self.state() {
                let mut st = state.borrow_mut();
                st.request = Some(re.to_string());
                st.request_failure = None;
            }
        }

        /// COL-08, after the app's save: `None` if the `evora:save` answering the request went out,
        /// otherwise the code to answer it with. The request is dropped either way.
        pub fn disarm_request(&self) -> Option<&'static str> {
            let state = self.state()?;
            let mut st = state.borrow_mut();
            let failure = st.request_failure.take();
            st.request.take().map(|_| failure.unwrap_or("busy"))
        }

        /// `evora:dirty` when unsaved work appears or goes away (`HostDirtyFn`, told every frame).
        /// Nothing while the host has opened no document: it would know no document to apply the
        /// state to (HOST-PROTOCOL.md §4.4, §7.1 step 8). After each `evora:open`, the first frame
        /// tells the state again, after the answer to the open.
        pub fn dirty_fn(&self) -> pdfcraft_ui_egui::HostDirtyFn {
            let link = self.clone();
            Box::new(move |dirty: bool| {
                let Some(state) = link.state() else { return };
                let mut st = state.borrow_mut();
                if !st.initialized || st.docs.is_empty() || !st.caps.iter().any(|c| c == "doc.dirty") || st.last_dirty == Some(dirty) {
                    return;
                }
                st.last_dirty = Some(dirty);
                let mut fields: Vec<(&str, JsValue)> = vec![("dirty", dirty.into())];
                if let [only] = st.docs.as_slice() {
                    fields.push(("docRef", only.doc_ref.clone().into()));
                }
                if let Some(payload) = object(&fields) {
                    let _ = send(&st, "evora:dirty", None, &payload, None);
                }
            })
        }

        /// Whether capability `c` is effective: the host offered it in `evora:init` and this engine
        /// declares it.
        pub fn has(&self, c: &str) -> bool {
            self.state().is_some_and(|state| {
                let st = state.borrow();
                st.initialized && st.caps.iter().any(|have| have == c)
            })
        }

        /// COL-42 (`export.drive`, §7.4): `evora:export {docRef?, name, mime, bytes}` for every file
        /// the app would download (`HostExportFn`, installed under the bridge from the start). The
        /// host files it in Evora's Drive and answers `evora:ack`, then tells the member itself.
        /// Without the capability the file is refused: under the bridge, never a browser download.
        /// `docRef` names the document shown, when the host opened it; `mime` follows the name's
        /// extension (indicative: Evora's server determines the real type, §5.4).
        pub fn export_fn(&self) -> pdfcraft_ui_egui::HostExportFn {
            let link = self.clone();
            Box::new(move |name: &str, bytes: &[u8]| {
                let state = link.state().ok_or_else(|| "Evora is not connected yet".to_string())?;
                let st = state.borrow();
                if !st.initialized || !st.caps.iter().any(|c| c == "export.drive") {
                    return Err("Evora can't receive files from here".into());
                }
                if bytes.is_empty() {
                    return Err("the file is empty".into());
                }
                if bytes.len() as f64 > st.max_export {
                    return Err("the file is too large to send to Evora".into());
                }
                let name = clean_name(name);
                let buffer = js_sys::Uint8Array::from(bytes).buffer();
                let mut fields: Vec<(&str, JsValue)> =
                    vec![("name", name.as_str().into()), ("mime", mime_of(&name).into()), ("bytes", buffer.clone().into())];
                let shown = st.active_doc.and_then(|doc| st.docs.iter().find(|d| d.doc == doc));
                if let Some(doc) = shown {
                    fields.push(("docRef", doc.doc_ref.clone().into()));
                }
                let payload = object(&fields).ok_or_else(|| "couldn't build the message".to_string())?;
                send(&st, "evora:export", None, &payload, Some(&buffer)).map(|_| ()).ok_or_else(|| "couldn't send the file".to_string())
            })
        }

        /// COL-42 (`ui.focus-out`, amendment A-19 of §7.9): `evora:focus-out {}`; `false` when the
        /// capability isn't effective.
        pub fn focus_out(&self) -> bool {
            let Some(state) = self.state() else { return false };
            let st = state.borrow();
            if !st.initialized || !st.caps.iter().any(|c| c == "ui.focus-out") {
                return false;
            }
            object(&[]).is_some_and(|payload| send(&st, "evora:focus-out", None, &payload, None).is_some())
        }

        /// Told every frame: the session's document shown (`DocId.0`), which an `evora:export` names,
        /// and the documents still open. COL-40 leftover: a host document whose tab is gone is
        /// forgotten, so no later message names its `docRef` for another document.
        pub fn sync_docs(&self, shown: Option<u64>, open: &[u64]) {
            if let Some(state) = self.state() {
                let mut st = state.borrow_mut();
                st.active_doc = shown;
                st.docs.retain(|d| open.contains(&d.doc));
            }
        }

        /// COL-43: `evora:commands` (§9.1), the catalog, with `command.catalog` effective.
        pub fn commands(&self, entries: &[crate::host_commands::Entry], lang: &str, hash: &str) {
            let Some(state) = self.state() else { return };
            let st = state.borrow();
            if !st.initialized || !st.caps.iter().any(|c| c == "command.catalog") {
                return;
            }
            let list = js_sys::Array::new();
            for e in entries {
                let mut fields: Vec<(&str, JsValue)> = vec![
                    ("id", e.id.into()),
                    ("label", e.label.as_str().into()),
                    ("enabled", e.enabled.into()),
                    ("destructive", e.destructive.into()),
                ];
                if let Some(menu) = &e.path {
                    fields.push(("path", js_sys::Array::of1(&JsValue::from_str(menu)).into()));
                }
                if let Some(entry) = object(&fields) {
                    list.push(&entry);
                }
            }
            // The default parameter schema: none (no command of this engine declares one).
            let Some(params) = object(&[("type", "object".into()), ("maxProperties", 0.0.into())]) else { return };
            let Some(payload) = object(&[
                ("lang", lang.into()),
                ("count", (list.length() as f64).into()),
                ("hash", hash.into()),
                ("params", params.into()),
                ("commands", list.into()),
            ]) else {
                return;
            };
            let _ = send(&st, "evora:commands", None, &payload, None);
        }

        /// COL-43: answer `evora:command` `re` (`Ok`: the command ran; `Err`: its `ackCode`).
        pub fn answer_command(&self, re: &str, outcome: Result<(), &'static str>) {
            if let Some(state) = self.state() {
                let st = state.borrow();
                match outcome {
                    Ok(()) => ack(&st, re, true, None),
                    Err(code) => ack(&st, re, false, Some(code)),
                }
            }
        }
    }

    /// COL-42 (`ui.focus-out`, §7.9, as the patch LUM-13 of Lumbra): F6 without a modifier, with the
    /// capability effective, is held back from the canvas and the browser, before any listener of
    /// the page (capture on the window), and gives the keyboard back to the host
    /// (`evora:focus-out`). A held key sends once. Without the capability, F6 is left alone.
    pub fn listen_exit_key(link: Link) {
        let Some(window) = web_sys::window() else { return };
        let on_key = Closure::<dyn FnMut(web_sys::KeyboardEvent)>::new(move |e: web_sys::KeyboardEvent| {
            if e.key() != EXIT_KEY || e.alt_key() || e.ctrl_key() || e.meta_key() || e.shift_key() || !link.has("ui.focus-out") {
                return;
            }
            // Neither the canvas nor the browser sees it: the key belongs to the host.
            e.prevent_default();
            e.stop_immediate_propagation();
            if e.type_() == "keydown" && !e.repeat() {
                link.focus_out();
            }
        });
        let listener: &js_sys::Function = on_key.as_ref().unchecked_ref();
        let down = window.add_event_listener_with_callback_and_bool("keydown", listener, true).is_ok();
        let up = window.add_event_listener_with_callback_and_bool("keyup", listener, true).is_ok();
        if down || up {
            // The listener lives as long as the page.
            on_key.forget();
        }
    }

    /// COL-42: the media type of an exported file, by its name's extension (`application/octet-stream`
    /// when unknown). Indicative only: Evora's server determines the real type (§5.4).
    fn mime_of(name: &str) -> &'static str {
        let ext = name.rsplit_once('.').map(|(_, e)| e.to_ascii_lowercase()).unwrap_or_default();
        match ext.as_str() {
            "pdf" => "application/pdf",
            "docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx" => "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "xlsx" => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "html" | "htm" => "text/html",
            "rtf" => "application/rtf",
            "txt" => "text/plain",
            "csv" => "text/csv",
            "xml" => "application/xml",
            "xfdf" => "application/vnd.adobe.xfdf",
            "fdf" => "application/vnd.fdf",
            "xdp" => "application/vnd.adobe.xdp+xml",
            "json" => "application/json",
            "png" => "image/png",
            "jpg" | "jpeg" => "image/jpeg",
            "tif" | "tiff" => "image/tiff",
            "gif" => "image/gif",
            "webp" => "image/webp",
            "bmp" => "image/bmp",
            "svg" => "image/svg+xml",
            "zip" => "application/zip",
            _ => "application/octet-stream",
        }
    }

    /// CI only (`?host=evora&evora-audit=1`): `window.__evoraRun("page.rotate")` queues one of
    /// [`PROBE_COMMANDS`] for the next frame and returns whether it did. That is how the smoke test
    /// edits the open document (S-ACK scenarios) without driving the menus.
    pub fn install_probe(probe: Probe, ctx: egui::Context) {
        let Some(window) = web_sys::window() else { return };
        let run = Closure::<dyn Fn(JsValue) -> bool>::new(move |command: JsValue| {
            let Some(command) = command.as_string().filter(|c| PROBE_COMMANDS.contains(&c.as_str())) else {
                return false;
            };
            probe.borrow_mut().push(command);
            ctx.request_repaint();
            true
        });
        if js_sys::Reflect::set(&window, &JsValue::from_str("__evoraRun"), run.as_ref()).is_ok() {
            run.forget();
        }
    }

    /// Read `evora-host.json`, find the admitted parent, listen, and announce `evora:ready`.
    pub fn connect(
        link: Link,
        outcomes: pdfcraft_ui_egui::HostSaveOutcomes,
        events: Events,
        gate: crate::storage_ns::SharedGate,
        ctx: egui::Context,
    ) {
        wasm_bindgen_futures::spawn_local(async move {
            let Some((window, parent, origin)) = admitted_parent().await else { return };
            // E5: the erasures of the engine's other pages of the origin seal this page's gate.
            let channel = crate::storage_ns::watch(&gate);
            let state = Rc::new(RefCell::new(State {
                parent,
                origin,
                ctx,
                events,
                gate,
                channel,
                ready_id: String::new(),
                initialized: false,
                caps: Vec::new(),
                max_document: 0.0,
                max_export: 0.0,
                active_doc: None,
                storage_ns: None,
                docs: Vec::new(),
                pending_saves: Vec::new(),
                outcomes,
                next_ticket: 0,
                request: None,
                request_failure: None,
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
            "evora:request-save" => Some("doc.request-save"),
            "evora:saved" => Some("doc.save"),
            "evora:lang" => Some("live.lang"),
            "evora:theme" => Some("live.theme"),
            "evora:purge" => Some("storage.purge"),
            "evora:command" => Some("command"),
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
            "evora:request-save" => on_request_save(state, &id, &payload),
            "evora:saved" => on_saved(state, re.as_deref(), &payload),
            "evora:lang" => on_lang(state, &id, &payload),
            "evora:theme" => on_theme(state, &id, &payload),
            "evora:purge" => on_purge(state, &id, &payload),
            "evora:command" => on_command(state, &id, &payload),
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
        let (Some(engine_lang), Some(ns), Some(author), Some(caps), Some(max_document), Some(max_export)) =
            (engine_lang, ns, author, caps, max_document, max_export)
        else {
            return;
        };
        if !(lang_ok && accent_ok && read_only_ok && caps_ok && prefs_ok && limits_ok) {
            return;
        }
        // The effective set: what the host offers and this engine declares (§9).
        let caps: Vec<String> = caps.into_iter().filter(|c| CAPABILITIES.contains(&c.as_str())).collect();
        // E5 (§7.1 step 6, §7.7 b), before the answer: this account's settings are read (only with
        // `storage.ns`; otherwise the engine keeps nothing), then every other namespace and every
        // key the engine leaves outside the namespaces is erased and the erasure checked; the
        // engine's other pages of the origin are told, so that those of another namespace stop
        // writing it. The app restores the settings on its next frame and may only then write them,
        // under this namespace, and only if the erasure was effective.
        let storage_ns = caps.iter().any(|c| c == "storage.ns").then_some(ns);
        let settings = storage_ns.as_deref().and_then(crate::storage_ns::read);
        crate::storage_ns::announce(st.channel.as_ref(), &crate::storage_ns::Erased::Except(storage_ns.as_deref()));
        let erased = crate::storage_ns::purge_except(storage_ns.as_deref());
        // COL-40: an erasure that isn't effective (storage not listed, or a key of another account
        // survived) refuses the init: the engine stays uninitialised, opens nothing and the host
        // stops (`init_refused`). A browser that gives the page no storage at all has nothing to
        // erase: the engine then starts with its settings in memory only.
        if erased == crate::storage_ns::Erasure::Failed {
            ack(&st, id, false, Some("forbidden"));
            return;
        }
        st.caps = caps;
        st.max_document = max_document;
        st.max_export = max_export;
        st.initialized = true;
        st.storage_ns = storage_ns;
        let author = author.filter(|_| st.caps.iter().any(|c| c == "author"));
        let lang = engine_lang.and_then(|l| crate::evora_lang(&l));
        let writable = erased == crate::storage_ns::Erasure::Done && st.storage_ns.is_some();
        if writable && let Some(ns) = st.storage_ns.as_deref() {
            st.gate.borrow_mut().name(ns);
        }
        st.events.borrow_mut().push(HostEvent::Init { settings, writable, lang, dark, author });
        ack(&st, id, true, None);
        st.ctx.request_repaint();
    }

    fn on_open(state: &Rc<RefCell<State>>, id: &str, p: &JsValue) {
        let st = state.borrow();
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
        // COL-40: the app opens the bytes on its next frame (`EvoraApp::open_from_host`), and only then
        // is `evora:open` answered (`Link::opened`): `{ok: true}` once the document is really open,
        // `{ok: false, code: "invalid_content"}` for bytes it can't open. S-ACK-6: the same `docRef`
        // again ("reload the server's version", after a conflict) replaces the document it names,
        // whose tab closes first, unsaved work included. §7.1 step 8: `evora:dirty` follows the answer.
        st.events.borrow_mut().push(HostEvent::Open(OpenRequest { re: id.to_string(), doc_ref, name, bytes: data }));
        st.ctx.request_repaint();
    }

    /// COL-08: the host asks to save (`evora:request-save`, §4.3). The app answers on its next frame
    /// (`EvoraApp::request_save`): `evora:save` with `re`, or `evora:ack {ok: true, code: "clean"}`.
    fn on_request_save(state: &Rc<RefCell<State>>, id: &str, p: &JsValue) {
        let st = state.borrow();
        if !only_keys(p, &["reason", "docRef"]) || !get(p, "reason").as_string().is_some_and(|r| SAVE_REASONS.contains(&r.as_str())) {
            return;
        }
        let doc_ref = get(p, "docRef");
        let doc_ref = if doc_ref.is_undefined() {
            None
        } else {
            match doc_ref.as_string().filter(|r| is_ulid(r)) {
                Some(r) => Some(r),
                None => return,
            }
        };
        // Without `doc.multi`, a request without `docRef` is for the one document the host opened.
        let doc = match &doc_ref {
            Some(r) => st.docs.iter().find(|d| d.doc_ref == *r).map(|d| d.doc),
            None => match st.docs.as_slice() {
                [only] => Some(only.doc),
                _ => None,
            },
        };
        let Some(doc) = doc else {
            ack(&st, id, false, Some("not_found"));
            return;
        };
        st.events.borrow_mut().push(HostEvent::RequestSave { re: id.to_string(), doc });
        st.ctx.request_repaint();
    }

    /// `evora:saved` (§4.5), the answer to one of this engine's `evora:save`. With `doc.saved-ack`
    /// effective (COL-09) its outcome goes to the app, which counts the document saved only on
    /// `ok: true` and only if it hasn't changed since; then the engine tells its state again.
    fn on_saved(state: &Rc<RefCell<State>>, re: Option<&str>, p: &JsValue) {
        let mut st = state.borrow_mut();
        let Some(re) = re else { return };
        let Some(at) = st.pending_saves.iter().position(|s| s.id == re) else { return };
        if !only_keys(p, &["ok", "version", "docRef", "error"]) {
            return;
        }
        let Some(ok) = get(p, "ok").as_bool() else { return };
        let doc_ref = get(p, "docRef");
        let doc_ref = if doc_ref.is_undefined() {
            None
        } else {
            match doc_ref.as_string().filter(|r| is_ulid(r)) {
                Some(r) => Some(r),
                None => return,
            }
        };
        // Success carries `version` and no `error`; failure carries `error`, no `version`, no `docRef`.
        let well_formed = if ok {
            get(p, "version").as_f64().is_some_and(|v| v >= 1.0 && v.fract() == 0.0) && get(p, "error").is_undefined()
        } else {
            get(p, "error").as_string().is_some_and(|e| ACK_CODES.contains(&e.as_str()))
                && get(p, "version").is_undefined()
                && doc_ref.is_none()
        };
        if !well_formed {
            return;
        }
        let save = st.pending_saves.remove(at);
        // Without `doc.saved-ack` the engine keeps upstream's behaviour: it counted the document
        // saved once handed over, and the host shows its own save state (§6.3).
        if !save.acked {
            return;
        }
        // §7.3: a Save As answered with the new document's `docRef`; the engine adopts it.
        if let Some(doc_ref) = doc_ref
            && let Some(entry) = st.docs.iter_mut().find(|d| d.doc == save.doc)
        {
            entry.doc_ref = doc_ref;
        }
        if let Ok(mut outcomes) = st.outcomes.lock() {
            outcomes.push((save.ticket, ok));
        }
        // l.480: once the app has applied the answer (next frame), the engine tells its state again,
        // `dirty: true` included when the document changed while the save was on its way.
        if ok {
            st.last_dirty = None;
        }
        st.ctx.request_repaint();
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
        // The engine's other pages of the origin are told too: those of the erased namespaces stop
        // writing them, and erase them again if they wrote them back meanwhile.
        st.gate.borrow_mut().seal();
        let told = if all { crate::storage_ns::Erased::All } else { crate::storage_ns::Erased::Current(st.storage_ns.as_deref()) };
        crate::storage_ns::announce(st.channel.as_ref(), &told);
        let erased = if all { crate::storage_ns::purge_all() } else { crate::storage_ns::purge_current(st.storage_ns.as_deref()) };
        st.storage_ns = None;
        if erased == crate::storage_ns::Erasure::Done {
            ack(&st, id, true, None);
        } else {
            ack(&st, id, false, Some("forbidden"));
        }
    }

    /// COL-43 (EVO-CMD): `evora:command {command, params, confirmed?}` (§4.3, §9.1), checked, for the
    /// app's next frame, which runs it and answers (`EvoraApp::run_command`). A malformed one is
    /// ignored (§5.2).
    fn on_command(state: &Rc<RefCell<State>>, id: &str, p: &JsValue) {
        let st = state.borrow();
        if !only_keys(p, &["command", "params", "confirmed"]) {
            return;
        }
        let Some(command) = get(p, "command").as_string().filter(|c| is_command(c)) else { return };
        let params = get(p, "params");
        if !plain_object(&params) {
            return;
        }
        let confirmed = get(p, "confirmed");
        let confirmed = if confirmed.is_undefined() {
            false
        } else {
            match confirmed.as_bool() {
                Some(c) => c,
                None => return,
            }
        };
        let params_empty = js_sys::Object::keys(params.unchecked_ref::<js_sys::Object>()).length() == 0;
        st.events.borrow_mut().push(HostEvent::Command { re: id.to_string(), command, params_empty, confirmed });
        st.ctx.request_repaint();
    }

    /// `command` of §4.3: `^[a-z][A-Za-z0-9_.-]*$`, at most [`COMMAND_MAX_CHARS`] characters.
    fn is_command(c: &str) -> bool {
        let mut chars = c.chars();
        c.chars().count() <= COMMAND_MAX_CHARS
            && chars.next().is_some_and(|f| f.is_ascii_lowercase())
            && chars.all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '.' | '-'))
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
    /// COL-08: the bridge, to answer the host's `evora:request-save` (`None` outside the bridge).
    link: Option<ehp::Link>,
    /// CI only: commands queued by the smoke test (`window.__evoraRun`, `?evora-audit=1`).
    probe: ehp::Probe,
    /// COL-40: a host document waiting for its password prompt before `evora:open` is answered.
    pending_open: Option<PendingOpen>,
    /// COL-40 (correction 1): files dropped or picked (the app's `inbox`) while a host document waits
    /// for its password, in order. They open once it is answered, never during the prompt.
    held: Vec<(String, Vec<u8>)>,
    /// COL-43: the catalog (`evora:commands`) is to be sent on this frame: after `evora:init`, then
    /// after each `evora:lang` (labels in the new language).
    catalog_due: bool,
}

/// COL-40: an `evora:open` whose bytes raised the password prompt: answered once the document opens,
/// or once the prompt is gone without it.
#[cfg(target_arch = "wasm32")]
struct PendingOpen {
    re: String,
    doc_ref: String,
    /// The very buffer the host sent, as the prompt holds it (correction 1): the host's document is
    /// the one opened from it, never "the newest document" (a local file opened meanwhile would be).
    bytes: std::sync::Arc<Vec<u8>>,
}

#[cfg(target_arch = "wasm32")]
impl EvoraApp {
    fn apply_host_events(&mut self) {
        self.settle_pending_open();
        let events: Vec<ehp::HostEvent> = std::mem::take(&mut *self.events.borrow_mut());
        // COL-40: one host open at a time, and never over a password prompt (the prompt belongs to the
        // document being admitted): the next opens wait, in order, for a later frame.
        let mut later: Vec<ehp::HostEvent> = Vec::new();
        for event in events {
            match event {
                ehp::HostEvent::Init { settings, writable, lang, dark, author } => {
                    // E5: this account's settings first, then the host's language, theme and author
                    // on top; only then may the settings be written, under this account's namespace
                    // (unless a purge has sealed the gate meanwhile). COL-42: never the signatures,
                    // initials or certificates an earlier build may have left there.
                    if let Some(json) = settings.as_deref().and_then(storage_ns::without_identity) {
                        self.inner.restore(&json);
                    }
                    self.inner.language = lang.unwrap_or("en").to_string();
                    self.set_dark(dark);
                    if let Some(author) = author {
                        self.inner.comment_prefs.author = author;
                    }
                    if let Some(gate) = &self.gate
                        && writable
                    {
                        gate.borrow_mut().open();
                    }
                    self.catalog_due = true;
                }
                ehp::HostEvent::Lang(lang) => {
                    self.inner.language = lang.unwrap_or("en").to_string();
                    self.catalog_due = true;
                }
                ehp::HostEvent::Theme(dark) => self.set_dark(dark),
                ehp::HostEvent::RequestSave { re, doc } => self.request_save(&re, doc),
                ehp::HostEvent::Command { re, command, params_empty, confirmed } => {
                    self.run_command(&re, &command, params_empty, confirmed);
                }
                ehp::HostEvent::Open(open) => {
                    if self.pending_open.is_some() || self.inner.password_prompt.is_some() || !later.is_empty() {
                        later.push(ehp::HostEvent::Open(open));
                    } else {
                        self.open_from_host(open);
                    }
                }
            }
        }
        if !later.is_empty() {
            let mut queue = self.events.borrow_mut();
            let newer = std::mem::take(&mut *queue);
            *queue = later;
            queue.extend(newer);
        }
    }

    /// The session's documents (`DocId.0`), in tab order.
    fn doc_ids(&self) -> Vec<u64> {
        self.inner.views.iter().map(|v| v.id.0).collect()
    }

    /// The newest document not among `before`.
    fn new_doc(&self, before: &[u64]) -> Option<u64> {
        self.inner.views.iter().map(|v| v.id.0).filter(|d| !before.contains(d)).last()
    }

    /// The tab showing the session's document `doc`, if any.
    fn index_of(&self, doc: u64) -> Option<usize> {
        self.inner.views.iter().position(|v| v.id.0 == doc)
    }

    /// COL-40: the host's `evora:open`, opened now, and answered only once the document is really
    /// open (`{ok: true}`), or refused (`invalid_content`: bytes the engine can't open). Encrypted, it
    /// raises the password prompt and the answer waits for it ([`Self::settle_pending_open`]).
    fn open_from_host(&mut self, open: ehp::OpenRequest) {
        let Some(link) = self.link.clone() else { return };
        // S-ACK-6: the same `docRef` again ("reload the server's version") replaces the document it
        // names: its tab closes first, unsaved work included.
        if let Some(old) = link.doc_of(&open.doc_ref) {
            while let Some(index) = self.index_of(old) {
                self.inner.close_tab(index);
            }
            link.forget(&open.doc_ref);
        }
        let before = self.doc_ids();
        let opened = self.inner.open_bytes(&open.name, None, open.bytes);
        // Within this one call only the host's bytes are opened (no prompt was showing: see
        // `apply_host_events`), so a document new since `before` is the host's.
        let admitted = self.new_doc(&before);
        // Encrypted: the prompt now showing is for the host's bytes; it holds the very buffer.
        let prompt = self.inner.password_prompt.as_ref().map(|p| p.bytes.clone());
        match (opened, admitted, prompt) {
            (Ok(()), Some(doc), _) => link.opened(&open.re, &open.doc_ref, Ok(doc)),
            (Ok(()), None, Some(bytes)) => {
                self.pending_open = Some(PendingOpen { re: open.re, doc_ref: open.doc_ref, bytes });
            }
            _ => link.opened(&open.re, &open.doc_ref, Err("invalid_content")),
        }
    }

    /// COL-40: the host document that waited for its password is answered once it opens (`ok`), or
    /// once the prompt is gone without it (`cancelled`). Correction 1: the answer names the document
    /// opened from the host's very bytes, never the newest one; until then the files dropped or picked
    /// are held ([`Self::hold_local_opens`]), so that no other document can open, nor take the prompt's
    /// place, while it shows.
    fn settle_pending_open(&mut self) {
        let Some(pending) = self.pending_open.take() else { return };
        let Some(link) = self.link.clone() else { return };
        // Still asking for this document's password (a wrong one asks again, for the same bytes).
        if self.inner.password_prompt.as_ref().is_some_and(|p| std::sync::Arc::ptr_eq(&p.bytes, &pending.bytes)) {
            self.pending_open = Some(pending);
            return;
        }
        match self.doc_from(&pending.bytes) {
            Some(doc) => link.opened(&pending.re, &pending.doc_ref, Ok(doc)),
            // Cancelled, or the prompt gave way to another: the host's document is not open, and no
            // other document ever takes its `docRef`.
            None => link.opened(&pending.re, &pending.doc_ref, Err("cancelled")),
        }
        self.release_local_opens();
    }

    /// COL-40 (correction 1): the session's document opened from `bytes`, the very buffer the host
    /// sent (`Arc` identity, not content), if one is open.
    fn doc_from(&self, bytes: &std::sync::Arc<Vec<u8>>) -> Option<u64> {
        self.inner
            .views
            .iter()
            .map(|v| v.id)
            .find(|id| self.inner.session.get(*id).is_some_and(|d| std::sync::Arc::ptr_eq(&d.bytes, bytes)))
            .map(|id| id.0)
    }

    /// COL-40 (correction 1): while a host document waits for its password, the files dropped on the
    /// canvas or picked (both land in the app's `inbox`, opened by `PdfCraftApp::logic`) wait too.
    /// Upstream opens them under the prompt, and opening one closes it (`finish_open`).
    fn hold_local_opens(&mut self) {
        if self.pending_open.is_none() {
            return;
        }
        if let Ok(mut inbox) = self.inner.inbox.lock() {
            self.held.append(&mut *inbox);
        }
    }

    /// The held files go back to the app's `inbox`, ahead of any newer one, once the host's document
    /// is answered: they open on this frame, as the files they are (never under the host's `docRef`).
    fn release_local_opens(&mut self) {
        if self.held.is_empty() {
            return;
        }
        if let Ok(mut inbox) = self.inner.inbox.lock() {
            let newer = std::mem::take(&mut *inbox);
            inbox.append(&mut self.held);
            inbox.extend(newer);
        }
    }

    /// COL-08: the host's `evora:request-save` `re`, for the session's document `doc`: `evora:save`
    /// with `re` when it has unsaved work, `evora:ack {ok: true, code: "clean"}` otherwise.
    fn request_save(&mut self, re: &str, doc: u64) {
        let Some(link) = self.link.clone() else { return };
        let Some(index) = self.index_of(doc) else {
            link.answer(re, false, "not_found");
            return;
        };
        if !self.inner.has_unsaved_work(index) {
            link.answer(re, true, "clean");
            return;
        }
        link.arm_request(re);
        let _ = self.inner.save_view(index, pdfcraft_ui_egui::SaveTarget::InPlace);
        if let Some(code) = link.disarm_request() {
            link.answer(re, false, code);
        }
    }

    /// COL-43: the host's `evora:command` `re`, run as its menu entry runs it, under the white list of
    /// `host_commands`, then answered (`evora:ack`).
    fn run_command(&mut self, re: &str, command: &str, params_empty: bool, confirmed: bool) {
        let Some(link) = self.link.clone() else { return };
        link.answer_command(re, host_commands::run(&mut self.inner, command, params_empty, confirmed));
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
            // COL-42: without the member's signatures, initials and certificates, which stay in
            // memory for the session; settings that can't be read as an object aren't written.
            Some(gate) => {
                let key = gate.borrow().key();
                if let Some(key) = key
                    // SABORDAGE QA (EVORA-COL-47) S6 : réglages écrits avec signatures, paraphes et certificats.
                    && let Some(settings) = Some(self.inner.persist())
                {
                    storage.set_string(&key, settings);
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
        // COL-42: the document shown names the `docRef` of an `evora:export`; COL-40 leftover: the
        // host documents whose tab is gone are forgotten.
        if let Some(link) = &self.link {
            link.sync_docs(self.inner.active_ids().map(|(_, id)| id.0), &self.doc_ids());
        }
        // CI only (`window.__evoraRun`, `?evora-audit=1`): the smoke test's edits.
        let commands: Vec<String> = std::mem::take(&mut *self.probe.borrow_mut());
        for command in commands {
            // CI only (COL-40, correction 1): the password of the smoke test's encrypted fixture.
            if command == ehp::PROBE_PASSWORD {
                self.inner.submit_password(Some(ehp::PROBE_PASSWORD_VALUE.to_string()));
            } else {
                let _ = self.inner.execute(&command);
            }
        }
        // COL-40 (correction 1): nothing dropped or picked opens under the host document's prompt.
        self.hold_local_opens();
        eframe::App::logic(&mut self.inner, ctx, frame);
        // COL-43: the catalog, once the host's language is applied (`evora:init`, `evora:lang`).
        // SABORDAGE QA (EVORA-COL-47) S7 : catalogue jamais émis.
        if std::mem::take(&mut self.catalog_due)
            && false
            && let Some(link) = &self.link
        {
            let (entries, lang, hash) = host_commands::catalog(&self.inner);
            link.commands(&entries, lang, &hash);
        }
    }

    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        eframe::App::ui(&mut self.inner, ui, frame);
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn main() {
    eprintln!("pdfcraft-web targets wasm32: run `trunk serve` or `trunk build --release` in apps/pdfcraft-web");
}

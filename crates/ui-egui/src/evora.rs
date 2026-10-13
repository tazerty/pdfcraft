//! Evora (patch E7): neutralisation for the Colophon Atelier build, served inside Evora.
//!
//! The app's own outbound links (the upstream source repository) and the update check (which, on
//! the web, opens the upstream releases page) are hidden from the menus, the command palette and
//! the About dialog, and do nothing if run another way. Updates of the Atelier are Evora's
//! (pinned upstream tag, rebuilt by the fork's CI). Links found in documents are not affected:
//! they keep their confirmation dialog.

/// Registry commands hidden from every list and ignored when run.
pub(crate) const HIDDEN_COMMANDS: &[&str] = &["help.github", "help.check_updates"];

pub(crate) fn hidden(id: &str) -> bool {
    HIDDEN_COMMANDS.contains(&id)
}

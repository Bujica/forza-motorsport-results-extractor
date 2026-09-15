//! Cooperative pause/cancel state for long extraction runs — Rust port of
//! the Python `RunControl`: cancel wins over pause, `checkpoint()` blocks
//! while paused and reports cancellation between safe units of work.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

#[derive(Debug, Clone)]
pub struct RunControl {
    pub cancel: Arc<AtomicBool>,
    pub paused: Arc<AtomicBool>,
}

impl Default for RunControl {
    fn default() -> Self {
        Self::new()
    }
}

impl RunControl {
    pub fn new() -> Self {
        Self {
            cancel: Arc::new(AtomicBool::new(false)),
            paused: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancel.load(Ordering::Relaxed)
    }

    pub fn is_paused(&self) -> bool {
        self.paused.load(Ordering::Relaxed) && !self.is_cancelled()
    }

    /// Block while paused; returns `false` when cancelled. Call at safe
    /// checkpoints (before scheduling an image, after durable persistence).
    pub fn checkpoint(&self) -> bool {
        while self.paused.load(Ordering::Relaxed) && !self.cancel.load(Ordering::Relaxed) {
            std::thread::sleep(Duration::from_millis(100));
        }
        !self.cancel.load(Ordering::Relaxed)
    }

    /// Cancellation also lifts the pause gate (Python `cancel()` semantics).
    pub fn request_cancel(&self) {
        self.cancel.store(true, Ordering::Relaxed);
        self.paused.store(false, Ordering::Relaxed);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cancel_lifts_pause_and_checkpoint_reports_cancellation() {
        let control = RunControl::new();
        control.paused.store(true, Ordering::Relaxed);
        assert!(control.is_paused());
        control.request_cancel();
        assert!(!control.is_paused(), "cancel must lift pause");
        assert!(!control.checkpoint());
    }

    #[test]
    fn checkpoint_passes_when_running() {
        let control = RunControl::new();
        assert!(control.checkpoint());
    }
}

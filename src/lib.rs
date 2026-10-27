pub mod database;
pub mod network;
pub mod server;
pub use server::{AppState, Config, Peer, app};

/// Deliberate clippy failure for the CI red proof; never merged.
pub fn red_proof_lint() -> u32 {
    return 1;
}

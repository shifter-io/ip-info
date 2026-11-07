pub mod database;
pub mod network;
pub mod server;
pub use server::{AppState, Config, Peer, app};

/// ```
/// assert_eq!(1 + 1, 3);
/// ```
pub fn throwaway() {}

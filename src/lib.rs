pub mod database;
pub mod network;
pub mod server;
pub use server::{AppState, Config, Peer, app};

pub fn throwaway(flag: bool) -> bool {
    flag == true
}

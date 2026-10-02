use hyper_util::{
    rt::{TokioExecutor, TokioIo, TokioTimer},
    server::conn::auto::Builder,
    service::TowerToHyperService,
};
use ip_info::{AppState, Config, Peer, app};
use std::{net::SocketAddr, sync::Arc, time::Duration};
use tokio::{net::TcpListener, task::JoinSet};
use tokio_util::sync::CancellationToken;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::from_env()?;
    let addr: SocketAddr = std::env::var("BIND_ADDR")
        .unwrap_or_else(|_| "0.0.0.0:8080".into())
        .parse()?;
    let path = std::env::var("MMDB_PATH").unwrap_or_else(|_| "data/dbip.mmdb".into());
    let state = Arc::new(AppState::load(&path, config));
    let router = app(state);
    let listener = TcpListener::bind(addr).await?;
    eprintln!("IP Info listening on {}", listener.local_addr()?);
    let cancel = CancellationToken::new();
    let shutdown = cancel.clone();
    tokio::spawn(async move {
        #[cfg(unix)]
        {
            let mut term =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                    .expect("install SIGTERM handler");
            tokio::select! { _ = tokio::signal::ctrl_c() => {}, _ = term.recv() => {} }
        }
        #[cfg(not(unix))]
        tokio::signal::ctrl_c()
            .await
            .expect("install signal handler");
        shutdown.cancel();
    });
    let mut connections = JoinSet::new();
    loop {
        tokio::select! {
            _ = cancel.cancelled() => break,
            Some(_) = connections.join_next(), if !connections.is_empty() => {},
            accepted = listener.accept() => {
                let (stream, peer) = accepted?;
                let service = TowerToHyperService::new(router.clone().layer(axum::Extension(Peer(peer.ip()))));
                let token = cancel.clone();
                connections.spawn(async move {
                    let mut builder = Builder::new(TokioExecutor::new());
                    builder.http1().timer(TokioTimer::new()).header_read_timeout(Duration::from_secs(10)).max_headers(64).max_buf_size(32768);
                    builder.http2().max_header_list_size(16384).max_concurrent_streams(128);
                    let connection = builder.serve_connection(TokioIo::new(stream), service);
                    tokio::pin!(connection);
                    tokio::select! {
                        _ = &mut connection => {},
                        _ = token.cancelled() => {
                            connection.as_mut().graceful_shutdown();
                            let _ = tokio::time::timeout(Duration::from_secs(10), connection).await;
                        }
                    }
                });
            }
        }
    }
    let _ = tokio::time::timeout(Duration::from_secs(11), async {
        while connections.join_next().await.is_some() {}
    })
    .await;
    connections.abort_all();
    Ok(())
}

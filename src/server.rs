use crate::{
    database::{Database, LookupLiteResponse},
    network, site,
};
use axum::{
    Json, Router,
    body::Body,
    extract::{Path, Query, Request, State},
    http::{HeaderMap, HeaderValue, StatusCode, header},
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::get,
};
use ipnet::IpNet;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{
    net::IpAddr,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tower_http::cors::{Any, CorsLayer};

#[derive(Clone)]
pub struct Config {
    pub trusted_proxies: Vec<IpNet>,
    pub client_ip_header: String,
    pub ga4_id: String,
    pub ingress_secret: String,
    pub indexable: bool,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            trusted_proxies: vec![],
            client_ip_header: "x-forwarded-for".into(),
            ga4_id: String::new(),
            ingress_secret: String::new(),
            indexable: false,
        }
    }
}
impl Config {
    pub fn from_env() -> Result<Self, Box<dyn std::error::Error>> {
        let trusted_proxies = std::env::var("TRUSTED_PROXY_CIDRS")
            .unwrap_or_default()
            .split(',')
            .filter(|s| !s.trim().is_empty())
            .map(|s| s.trim().parse())
            .collect::<Result<Vec<IpNet>, _>>()?;
        if trusted_proxies.iter().any(|n| n.prefix_len() == 0) {
            return Err("Trust-all proxy CIDRs are forbidden".into());
        }
        let client_ip_header = std::env::var("CLIENT_IP_HEADER")
            .unwrap_or_else(|_| "x-forwarded-for".into())
            .to_lowercase();
        header::HeaderName::from_bytes(client_ip_header.as_bytes())?;
        let ga4_id = std::env::var("GA4_MEASUREMENT_ID").unwrap_or_default();
        let valid_ga4 = ga4_id.starts_with("G-")
            && (6..=24).contains(&ga4_id.len())
            && ga4_id[2..]
                .chars()
                .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit());
        if !(ga4_id.is_empty() || valid_ga4) {
            return Err("Invalid GA4_MEASUREMENT_ID".into());
        }
        let indexable = match std::env::var("SITE_INDEXABLE").as_deref() {
            Ok("true") => true,
            Ok("false") | Err(_) => false,
            _ => return Err("SITE_INDEXABLE must be true or false".into()),
        };
        let ingress_secret = std::env::var("INGRESS_SECRET").unwrap_or_default();
        if !ingress_secret.is_empty()
            && (ingress_secret.len() < 32
                || ingress_secret.len() > 128
                || !ingress_secret.bytes().all(|b| b.is_ascii_alphanumeric()))
        {
            return Err("INGRESS_SECRET must be 32–128 alphanumeric characters".into());
        }
        Ok(Self {
            ingress_secret,
            trusted_proxies,
            client_ip_header,
            ga4_id,
            indexable,
        })
    }
}
#[derive(Clone, Copy)]
pub struct Peer(pub IpAddr);
pub struct AppState {
    pub db: Option<Database>,
    pub config: Config,
    healthy: AtomicBool,
}
impl AppState {
    pub fn load(path: &str, config: Config) -> Self {
        let db = match Database::open(path) {
            Ok(db) => {
                eprintln!("DB-IP database loaded");
                Some(db)
            }
            Err(_) => {
                eprintln!("Database unavailable: check MMDB_PATH and database validation");
                None
            }
        };
        Self {
            healthy: AtomicBool::new(db.is_some()),
            db,
            config,
        }
    }
}
fn pretty_json(value: impl Serialize) -> Response {
    match serde_json::to_vec_pretty(&value) {
        Ok(mut body) => {
            body.push(b'\n');
            ([(header::CONTENT_TYPE, "application/json")], body).into_response()
        }
        Err(_) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            [(header::CONTENT_TYPE, "application/json")],
            "{\n  \"error\": {\n    \"code\": \"internal_error\",\n    \"message\": \"Unable to serialize response.\"\n  }\n}\n",
        )
            .into_response(),
    }
}
pub fn error(status: StatusCode, code: &str, message: &str) -> Response {
    (
        status,
        pretty_json(json!({"error":{"code":code,"message":message}})),
    )
        .into_response()
}
fn bad(message: &str) -> Response {
    error(StatusCode::BAD_REQUEST, "invalid_ip", message)
}
fn unavailable(message: &str) -> Response {
    error(
        StatusCode::SERVICE_UNAVAILABLE,
        "database_unavailable",
        message,
    )
}
#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct Params {
    ip: Option<String>,
}

pub fn app(state: Arc<AppState>) -> Router {
    // API routes merge without its fallback, keeping unknown website pages as HTML 404s.
    site::routes()
        .route(
            "/healthz",
            get(|| async { pretty_json(json!({"status":"ok"})) })
                .layer(middleware::from_fn(api_headers)),
        )
        .route(
            "/readyz",
            get(ready).layer(middleware::from_fn(api_headers)),
        )
        .merge(api_routes())
        .fallback(|| async { (StatusCode::NOT_FOUND, Html(include_str!("../web/404.html"))) })
        .layer(middleware::from_fn_with_state(state.clone(), common))
        .with_state(state)
}
fn api_routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/myip", get(my_ip))
        .route("/json", get(lookup_self::<false>))
        .route("/{ip}/json", get(lookup_path::<false>))
        .route("/json_lite", get(lookup_self::<true>))
        .route("/{ip}/json_lite", get(lookup_path::<true>))
        .method_not_allowed_fallback(|| async {
            error(
                StatusCode::METHOD_NOT_ALLOWED,
                "method_not_allowed",
                "Use GET for lookups.",
            )
        })
        .layer(CorsLayer::new().allow_origin(Any).allow_methods([
            axum::http::Method::GET,
            axum::http::Method::HEAD,
            axum::http::Method::OPTIONS,
        ]))
        .layer(middleware::from_fn(api_headers))
}
async fn ready(State(s): State<Arc<AppState>>) -> Response {
    if s.healthy.load(Ordering::Relaxed) {
        pretty_json(json!({"status":"ready"}))
    } else {
        unavailable("Database is not ready.")
    }
}
async fn api_headers(req: Request, next: Next) -> Response {
    let mut r = next.run(req).await;
    r.headers_mut()
        .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    r.headers_mut()
        .insert("x-robots-tag", HeaderValue::from_static("noindex"));
    r
}
/// Every response: the header size check, the trailing-slash redirect, a
/// 10 s timeout, the page rewrite, then the security and robots headers.
async fn common(State(s): State<Arc<AppState>>, req: Request, next: Next) -> Response {
    let api_path = is_api_path(req.uri().path());
    let response = if oversized(&req) {
        error(
            StatusCode::REQUEST_HEADER_FIELDS_TOO_LARGE,
            "request_too_large",
            "Request headers are too large.",
        )
    } else if let Some(redirect) = trailing_slash_redirect(&req) {
        redirect
    } else {
        tokio::time::timeout(Duration::from_secs(10), next.run(req))
            .await
            .unwrap_or_else(|_| error(StatusCode::GATEWAY_TIMEOUT, "timeout", "Request timed out."))
    };
    let mut response = rewrite_page(response, &s.config).await;
    finish(&mut response, api_path, s.config.indexable);
    response
}
fn is_api_path(path: &str) -> bool {
    let path = path.trim_end_matches('/');
    path == "/myip"
        || path.ends_with("/json")
        || path.ends_with("/json_lite")
        || path == "/healthz"
        || path == "/readyz"
}
fn oversized(req: &Request) -> bool {
    let headers = req
        .headers()
        .iter()
        .map(|(k, v)| k.as_str().len() + v.len());
    req.uri().to_string().len() + headers.sum::<usize>() > 16384
}
fn trailing_slash_redirect(req: &Request) -> Option<Response> {
    let path = req.uri().path();
    if path.len() <= 1 || !path.ends_with('/') {
        return None;
    }
    let query = req.uri().query().map(|q| format!("?{q}"));
    let trimmed = path.trim_end_matches('/');
    let target = format!("{trimmed}{}", query.unwrap_or_default());
    Some(if target.starts_with("//") {
        bad("Invalid request path.")
    } else {
        (StatusCode::PERMANENT_REDIRECT, [(header::LOCATION, target)]).into_response()
    })
}
async fn rewrite_page(response: Response, config: &Config) -> Response {
    let html = response
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|h| h.to_str().ok())
        .is_some_and(|s| s.starts_with("text/html"));
    if !html {
        return response;
    }
    let (mut parts, body) = response.into_parts();
    let Ok(bytes) = axum::body::to_bytes(body, 2_000_000).await else {
        return error(
            StatusCode::INTERNAL_SERVER_ERROR,
            "internal_error",
            "Unable to serve this page.",
        );
    };
    let text = site::rewrite_html(&String::from_utf8_lossy(&bytes), &config.ga4_id);
    parts.headers.remove(header::CONTENT_LENGTH);
    Response::from_parts(parts, Body::from(text))
}
fn finish(response: &mut Response, api_path: bool, indexable: bool) {
    let not_found = response.status() == StatusCode::NOT_FOUND;
    let h = response.headers_mut();
    h.insert(
        "x-content-type-options",
        HeaderValue::from_static("nosniff"),
    );
    h.insert("referrer-policy", HeaderValue::from_static("no-referrer"));
    h.insert("x-frame-options", HeaderValue::from_static("DENY"));
    h.insert(
        "permissions-policy",
        HeaderValue::from_static("geolocation=(), camera=(), microphone=()"),
    );
    if api_path || !indexable || not_found {
        h.insert("x-robots-tag", HeaderValue::from_static("noindex"));
    }
    if api_path {
        h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    }
}
type ParsedParams = Result<Query<Params>, axum::extract::rejection::QueryRejection>;
fn caller_ip(
    config: &Config,
    headers: &HeaderMap,
    peer: Option<IpAddr>,
) -> Result<IpAddr, &'static str> {
    let peer = peer.ok_or("Unable to determine the caller IP.")?;
    if !config.ingress_secret.is_empty() {
        return network::authenticated_caller(headers, &config.ingress_secret);
    }
    network::caller(
        peer,
        headers,
        &config.trusted_proxies,
        &config.client_ip_header,
    )
}
async fn my_ip(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    peer: Option<axum::Extension<Peer>>,
) -> Response {
    match caller_ip(&s.config, &headers, peer.map(|p| p.0.0)) {
        Ok(ip) => format!("{ip}\n").into_response(),
        Err(e) => bad(e),
    }
}
async fn lookup_self<const LITE: bool>(
    State(s): State<Arc<AppState>>,
    params: ParsedParams,
    headers: HeaderMap,
    peer: Option<axum::Extension<Peer>>,
) -> Response {
    lookup::<LITE>(s, None, params, headers, peer.map(|p| p.0.0))
}
async fn lookup_path<const LITE: bool>(
    State(s): State<Arc<AppState>>,
    Path(ip): Path<String>,
    params: ParsedParams,
    headers: HeaderMap,
    peer: Option<axum::Extension<Peer>>,
) -> Response {
    lookup::<LITE>(s, Some(ip), params, headers, peer.map(|p| p.0.0))
}
fn lookup<const LITE: bool>(
    s: Arc<AppState>,
    path: Option<String>,
    params: ParsedParams,
    headers: HeaderMap,
    peer: Option<IpAddr>,
) -> Response {
    let Ok(Query(params)) = params else {
        return bad("Use a single ip query parameter.");
    };
    let query = match params.ip.as_deref().map(network::parse).transpose() {
        Ok(ip) => ip,
        Err(e) => return bad(e),
    };
    let path = match path.as_deref().map(network::parse).transpose() {
        Ok(ip) => ip,
        Err(e) => return bad(e),
    };
    if path.zip(query).is_some_and(|(a, b)| a != b) {
        return bad("Path and query IP addresses conflict.");
    }
    let ip = match path.or(query) {
        Some(ip) => ip,
        None => match caller_ip(&s.config, &headers, peer) {
            Ok(ip) => ip,
            Err(e) => return bad(e),
        },
    };
    if !network::public(ip) {
        return bad("Only public unicast IPv4 and IPv6 addresses are supported.");
    }
    let healthy = s.healthy.load(Ordering::Relaxed);
    let Some(db) = s.db.as_ref().filter(|_| healthy) else {
        return unavailable("Database is not ready.");
    };
    match db.lookup(ip) {
        Ok(Some(record)) => {
            if LITE {
                Json(LookupLiteResponse::from(record)).into_response()
            } else {
                pretty_json(record)
            }
        }
        Ok(None) => error(
            StatusCode::NOT_FOUND,
            "ip_not_found",
            "No record exists for this IP in the active database.",
        ),
        Err(_) => {
            s.healthy.store(false, Ordering::Relaxed);
            eprintln!("Database lookup failed; readiness disabled");
            unavailable("Database could not be read.")
        }
    }
}

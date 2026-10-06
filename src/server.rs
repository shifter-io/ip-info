use crate::{database::Database, network};
use axum::{
    Router,
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
#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct Params {
    ip: Option<String>,
}

pub fn app(state: Arc<AppState>) -> Router {
    let api = Router::new()
        .route("/myip", get(my_ip))
        .route("/json", get(lookup_self))
        .route("/{ip}/json", get(lookup_path))
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
        .layer(middleware::from_fn(api_headers));
    // API routes merge without its fallback, keeping unknown website pages as HTML 404s.
    Router::new()
        .route(
            "/",
            get(|| async { Html(include_str!("../web/index.html")) }),
        )
        .route(
            "/docs",
            get(|| async { Html(include_str!("../web/docs.html")) }),
        )
        .route(
            "/ai",
            get(|| async { Html(include_str!("../web/ai.html")) }),
        )
        .route(
            "/about",
            get(|| async { Html(include_str!("../web/about.html")) }),
        )
        .route(
            "/terms",
            get(|| async { Html(include_str!("../web/terms.html")) }),
        )
        .route(
            "/privacy",
            get(|| async { Html(include_str!("../web/privacy.html")) }),
        )
        .route(
            "/cookies",
            get(|| async { Html(include_str!("../web/cookies.html")) }),
        )
        .route(
            "/llms.txt",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
                    include_str!("../web/llms.txt"),
                )
            }),
        )
        .route(
            "/llms-full.txt",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
                    include_str!("../web/llms-full.txt"),
                )
            }),
        )
        .route(
            "/openapi.json",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "application/json")],
                    include_str!("../web/openapi.json"),
                )
            }),
        )
        .route(
            "/sitemap.xml",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "application/xml")],
                    include_str!("../web/sitemap.xml"),
                )
            }),
        )
        .route("/robots.txt", get(robots))
        .route(
            "/share.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    &include_bytes!("../web/share.png")[..],
                )
            }),
        )
        .route(
            "/meta/home.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    &include_bytes!("../web/meta/home.png")[..],
                )
            }),
        )
        .route(
            "/meta/docs.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    &include_bytes!("../web/meta/docs.png")[..],
                )
            }),
        )
        .route(
            "/meta/ai.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    &include_bytes!("../web/meta/ai.png")[..],
                )
            }),
        )
        .route(
            "/meta/about.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    &include_bytes!("../web/meta/about.png")[..],
                )
            }),
        )
        .route(
            "/meta/terms.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    &include_bytes!("../web/meta/terms.png")[..],
                )
            }),
        )
        .route(
            "/meta/privacy.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    &include_bytes!("../web/meta/privacy.png")[..],
                )
            }),
        )
        .route(
            "/meta/cookies.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    &include_bytes!("../web/meta/cookies.png")[..],
                )
            }),
        )
        .route(
            "/favicon.ico",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/x-icon")],
                    &include_bytes!("../web/favicon.ico")[..],
                )
            }),
        )
        .route(
            "/favicon.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    &include_bytes!("../web/favicon.png")[..],
                )
            }),
        )
        .route(
            "/favicon.svg",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/svg+xml")],
                    include_str!("../web/favicon.svg"),
                )
            }),
        )
        .route(
            "/healthz",
            get(|| async { pretty_json(json!({"status":"ok"})) })
                .layer(middleware::from_fn(api_headers)),
        )
        .route(
            "/readyz",
            get(ready).layer(middleware::from_fn(api_headers)),
        )
        .merge(api)
        .fallback(|| async { (StatusCode::NOT_FOUND, Html(include_str!("../web/404.html"))) })
        .layer(middleware::from_fn_with_state(state.clone(), common))
        .with_state(state)
}
async fn robots(State(s): State<Arc<AppState>>) -> String {
    if s.config.indexable {
        "User-agent: *\nAllow: /\nSitemap: https://ip-info.com/sitemap.xml\n".into()
    } else {
        "User-agent: *\nDisallow: /\n".into()
    }
}
async fn ready(State(s): State<Arc<AppState>>) -> Response {
    if s.healthy.load(Ordering::Relaxed) {
        pretty_json(json!({"status":"ready"}))
    } else {
        error(
            StatusCode::SERVICE_UNAVAILABLE,
            "database_unavailable",
            "Database is not ready.",
        )
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
async fn common(State(s): State<Arc<AppState>>, req: Request, next: Next) -> Response {
    let size = req.uri().to_string().len()
        + req
            .headers()
            .iter()
            .map(|(k, v)| k.as_str().len() + v.len())
            .sum::<usize>();
    let path = req.uri().path();
    let api_path = path == "/myip"
        || path == "/json"
        || path.ends_with("/json")
        || path == "/healthz"
        || path == "/readyz";
    let mut response = if size > 16384 {
        error(
            StatusCode::REQUEST_HEADER_FIELDS_TOO_LARGE,
            "request_too_large",
            "Request headers are too large.",
        )
    } else if path.len() > 1 && path.ends_with('/') {
        let target = format!(
            "{}{}",
            path.trim_end_matches('/'),
            req.uri()
                .query()
                .map(|q| format!("?{q}"))
                .unwrap_or_default()
        );
        if target.starts_with("//") {
            bad("Invalid request path.")
        } else {
            (StatusCode::PERMANENT_REDIRECT, [(header::LOCATION, target)]).into_response()
        }
    } else {
        tokio::time::timeout(Duration::from_secs(10), next.run(req))
            .await
            .unwrap_or_else(|_| error(StatusCode::GATEWAY_TIMEOUT, "timeout", "Request timed out."))
    };
    let html = response
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|h| h.to_str().ok())
        .is_some_and(|s| s.starts_with("text/html"));
    if html {
        let (mut parts, body) = response.into_parts();
        if let Ok(bytes) = axum::body::to_bytes(body, 2_000_000).await {
            let mut text = String::from_utf8_lossy(&bytes).replace("__GA4_ID__", &s.config.ga4_id);
            for (file, route) in [
                ("index.html", "/"),
                ("docs.html", "/docs"),
                ("ai.html", "/ai"),
                ("about.html", "/about"),
                ("terms.html", "/terms"),
                ("privacy.html", "/privacy"),
                ("cookies.html", "/cookies"),
            ] {
                text = text.replace(&format!("href=\"{file}"), &format!("href=\"{route}"));
            }
            parts.headers.remove(header::CONTENT_LENGTH);
            response = Response::from_parts(parts, Body::from(text));
        } else {
            response = error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "internal_error",
                "Unable to serve this page.",
            );
        }
    }
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
    if api_path || !s.config.indexable || response.status() == StatusCode::NOT_FOUND {
        response
            .headers_mut()
            .insert("x-robots-tag", HeaderValue::from_static("noindex"));
    }
    if api_path {
        response
            .headers_mut()
            .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    }
    response
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
async fn lookup_self(
    State(s): State<Arc<AppState>>,
    params: ParsedParams,
    headers: HeaderMap,
    peer: Option<axum::Extension<Peer>>,
) -> Response {
    lookup(s, None, params, headers, peer.map(|p| p.0.0))
}
async fn lookup_path(
    State(s): State<Arc<AppState>>,
    Path(ip): Path<String>,
    params: ParsedParams,
    headers: HeaderMap,
    peer: Option<axum::Extension<Peer>>,
) -> Response {
    lookup(s, Some(ip), params, headers, peer.map(|p| p.0.0))
}
fn lookup(
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
    if !s.healthy.load(Ordering::Relaxed) {
        return error(
            StatusCode::SERVICE_UNAVAILABLE,
            "database_unavailable",
            "Database is not ready.",
        );
    }
    let Some(db) = s.db.as_ref() else {
        return error(
            StatusCode::SERVICE_UNAVAILABLE,
            "database_unavailable",
            "Database is not ready.",
        );
    };
    match db.lookup(ip) {
        Ok(Some(record)) => pretty_json(record),
        Ok(None) => error(
            StatusCode::NOT_FOUND,
            "ip_not_found",
            "No record exists for this IP in the active database.",
        ),
        Err(_) => {
            s.healthy.store(false, Ordering::Relaxed);
            eprintln!("Database lookup failed; readiness disabled");
            error(
                StatusCode::SERVICE_UNAVAILABLE,
                "database_unavailable",
                "Database could not be read.",
            )
        }
    }
}

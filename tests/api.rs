use axum::{
    Router,
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt;
use ip_info::{AppState, Config, Peer, app};
use serde_json::Value;
use std::sync::{Arc, OnceLock};
use tower::ServiceExt;

async fn call(
    router: Router,
    url: &str,
    method: &str,
    headers: &[(&str, &str)],
) -> (StatusCode, axum::http::HeaderMap, Value) {
    let mut request = Request::builder().method(method).uri(url);
    for (key, value) in headers {
        request = request.header(*key, *value);
    }
    let response = router
        .oneshot(request.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    (
        status,
        headers,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}
fn missing() -> Router {
    app(Arc::new(AppState::load("/no-such-mmdb", Config::default())))
}
fn real() -> Router {
    static STATE: OnceLock<Arc<AppState>> = OnceLock::new();
    app(STATE
        .get_or_init(|| {
            let state = AppState::load(
                &std::env::var("MMDB_PATH").unwrap_or_else(|_| "data/dbip.mmdb".into()),
                Config::default(),
            );
            assert!(
                state.db.is_some(),
                "Real database tests require MMDB_PATH or data/dbip.mmdb"
            );
            Arc::new(state)
        })
        .clone())
}
#[tokio::test]
async fn unavailable_db_and_health() {
    let (s, h, v) = call(missing(), "/json?ip=8.8.8.8", "GET", &[]).await;
    assert_eq!(s, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(v["error"]["code"], "database_unavailable");
    assert_eq!(h["cache-control"], "no-store");
    assert_eq!(h["x-robots-tag"], "noindex");
    assert_eq!(
        call(missing(), "/healthz", "GET", &[]).await.0,
        StatusCode::OK
    );
    assert_eq!(
        call(missing(), "/readyz", "GET", &[]).await.0,
        StatusCode::SERVICE_UNAVAILABLE
    );
}
#[tokio::test]
async fn invalid_inputs_and_methods() {
    for path in [
        "/json?ip=host.example",
        "/json?ip=",
        "/json?ip=127.0.0.1",
        "/json?ip=2001:db8::1",
        "/json?ip=8.8.8.8&ip=1.1.1.1",
        "/json?wrong=1",
        "/8.8.8.8/json?ip=1.1.1.1",
        "/json?ip=8.8.8.8%3A80",
    ] {
        let (status, _, v) = call(missing(), path, "GET", &[]).await;
        assert_eq!(status, StatusCode::BAD_REQUEST, "{path}");
        assert_eq!(v["error"]["code"], "invalid_ip");
    }
    let (status, _, v) = call(missing(), "/json", "POST", &[]).await;
    assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED);
    assert_eq!(v["error"]["code"], "method_not_allowed");
}
#[tokio::test]
async fn cors_and_site_routes() {
    let (_, h, _) = call(
        missing(),
        "/json?ip=8.8.8.8",
        "GET",
        &[("origin", "https://example.com")],
    )
    .await;
    assert_eq!(h["access-control-allow-origin"], "*");
    let (s, h, _) = call(
        missing(),
        "/json",
        "OPTIONS",
        &[
            ("origin", "https://example.com"),
            ("access-control-request-method", "GET"),
        ],
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(h["access-control-allow-origin"], "*");
    assert_eq!(call(missing(), "/docs", "GET", &[]).await.0, StatusCode::OK);
    assert_eq!(
        call(missing(), "/does-not-exist", "GET", &[]).await.0,
        StatusCode::NOT_FOUND
    );
    let (s, h, _) = call(missing(), "/docs/", "GET", &[]).await;
    assert_eq!(s, StatusCode::PERMANENT_REDIRECT);
    assert_eq!(h["location"], "/docs");
    let (s, _, _) = call(
        missing(),
        "/json?ip=8.8.8.8",
        "GET",
        &[("x-large", &"x".repeat(17000))],
    )
    .await;
    assert_eq!(s, StatusCode::REQUEST_HEADER_FIELDS_TOO_LARGE);
}
#[tokio::test]
#[ignore = "requires the private DB-IP MMDB"]
async fn real_database_matches_contract() {
    let (s, h, actual) = call(real(), "/json?ip=8.8.8.8", "GET", &[]).await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(h["cache-control"], "no-store");
    assert!(actual.get("database_date").is_none());
    let (ready_status, _, readiness) = call(real(), "/readyz", "GET", &[]).await;
    assert_eq!(ready_status, StatusCode::OK);
    assert_eq!(readiness, serde_json::json!({"status":"ready"}));
    let schema: Value = serde_json::from_str(include_str!("../web/openapi.json")).unwrap();
    let fields = schema["components"]["schemas"]["IpInfo"]["properties"]
        .as_object()
        .unwrap();
    assert_eq!(actual.as_object().unwrap().len(), fields.len());
    for field in fields.keys() {
        assert!(actual.get(field).is_some(), "{field}");
    }
    let path = call(real(), "/8.8.8.8/json", "GET", &[]).await.2;
    assert_eq!(actual, path);
    let matching = call(real(), "/8.8.8.8/json?ip=8.8.8.8", "GET", &[]).await.2;
    assert_eq!(actual, matching);
    let mapped = call(real(), "/json?ip=::ffff:8.8.8.8", "GET", &[]).await.2;
    assert_eq!(actual, mapped);
    let (status, _, ipv6) = call(real(), "/json?ip=2001:4860:4860::8888", "GET", &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(ipv6["asn"], 15169);
}
#[tokio::test]
#[ignore = "requires the private DB-IP MMDB"]
async fn caller_spoofing_and_cache_isolation() {
    let one = real().layer(axum::Extension(Peer("8.8.8.8".parse().unwrap())));
    let two = real().layer(axum::Extension(Peer("9.9.9.9".parse().unwrap())));
    let a = call(
        one,
        "/json",
        "GET",
        &[("x-forwarded-for", "1.1.1.1"), ("cdn-real-ip", "1.1.1.1")],
    )
    .await
    .2;
    let b = call(two, "/json", "GET", &[]).await.2;
    assert_eq!(a["ip"], "8.8.8.8");
    assert_eq!(b["ip"], "9.9.9.9");
    let config = Config {
        trusted_proxies: vec!["10.0.0.0/24".parse().unwrap()],
        ..Config::default()
    };
    let trusted = app(Arc::new(AppState::load("data/dbip.mmdb", config)))
        .layer(axum::Extension(Peer("10.0.0.1".parse().unwrap())));
    let a = call(
        trusted.clone(),
        "/json",
        "GET",
        &[("x-forwarded-for", "1.1.1.1, 8.8.8.8, 10.0.0.2")],
    )
    .await;
    assert_eq!(a.0, StatusCode::OK);
    assert_eq!(a.2["ip"], "8.8.8.8");
    assert_eq!(
        call(trusted, "/json", "GET", &[]).await.0,
        StatusCode::BAD_REQUEST
    );
}

#[tokio::test]
#[ignore = "requires the private DB-IP MMDB"]
async fn authenticated_ingress_rejects_spoofed_headers() {
    let config = Config {
        ingress_secret: "a".repeat(64),
        ..Config::default()
    };
    let router = app(Arc::new(AppState::load("data/dbip.mmdb", config)))
        .layer(axum::Extension(Peer("10.0.0.2".parse().unwrap())));
    for headers in [
        vec![],
        vec![
            ("x-ip-info-client-ip", "1.1.1.1"),
            ("x-ip-info-ingress", "wrong"),
        ],
    ] {
        assert_eq!(
            call(router.clone(), "/json", "GET", &headers).await.0,
            StatusCode::BAD_REQUEST
        );
    }
    let secret = "a".repeat(64);
    let valid = [
        ("x-ip-info-ingress", secret.as_str()),
        ("x-ip-info-client-ip", "8.8.8.8"),
        ("x-forwarded-for", "1.1.1.1"),
    ];
    let (status, _, json) = call(router.clone(), "/json", "GET", &valid).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ip"], "8.8.8.8");
    let duplicate = [
        ("x-ip-info-ingress", secret.as_str()),
        ("x-ip-info-ingress", secret.as_str()),
        ("x-ip-info-client-ip", "8.8.8.8"),
    ];
    assert_eq!(
        call(router, "/json", "GET", &duplicate).await.0,
        StatusCode::BAD_REQUEST
    );
}

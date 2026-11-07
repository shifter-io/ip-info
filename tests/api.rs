mod common;

use axum::{Router, http::StatusCode};
use common::{call, call_raw};
use ip_info::{AppState, Config, Peer, app};
use std::sync::Arc;

fn missing() -> Router {
    app(Arc::new(AppState::load("/no-such-mmdb", Config::default())))
}
#[tokio::test]
async fn production_favicons_are_crawlable_without_a_database() {
    let router = app(Arc::new(AppState::load(
        "/no-such-mmdb",
        Config {
            indexable: true,
            ..Config::default()
        },
    )));
    for (path, content_type, expected) in [
        (
            "/favicon.ico",
            "image/x-icon",
            &include_bytes!("../web/favicon.ico")[..],
        ),
        (
            "/favicon.png",
            "image/png",
            &include_bytes!("../web/favicon.png")[..],
        ),
        (
            "/favicon.svg",
            "image/svg+xml",
            &include_bytes!("../web/favicon.svg")[..],
        ),
        (
            "/apple-touch-icon.png",
            "image/png",
            &include_bytes!("../web/apple-touch-icon.png")[..],
        ),
        (
            "/android-chrome-192x192.png",
            "image/png",
            &include_bytes!("../web/android-chrome-192x192.png")[..],
        ),
        (
            "/android-chrome-512x512.png",
            "image/png",
            &include_bytes!("../web/android-chrome-512x512.png")[..],
        ),
        (
            "/site.webmanifest",
            "application/manifest+json",
            &include_bytes!("../web/site.webmanifest")[..],
        ),
    ] {
        let (status, headers, body) = call_raw(router.clone(), path, "GET", &[]).await;
        assert_eq!(status, StatusCode::OK, "{path}");
        assert_eq!(headers["content-type"], content_type);
        assert!(!headers.contains_key("x-robots-tag"));
        assert_eq!(body, expected);
        let (status, headers, body) = call_raw(router.clone(), path, "HEAD", &[]).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(headers["content-type"], content_type);
        assert!(body.is_empty());
    }
    let (_, _, robots) = call_raw(router, "/robots.txt", "GET", &[]).await;
    assert!(
        String::from_utf8(robots)
            .unwrap()
            .contains("User-agent: *\nAllow: /")
    );
}
#[tokio::test]
async fn myip_returns_only_the_caller_without_a_database() {
    for (peer, expected) in [
        ("8.8.8.8", "8.8.8.8\n"),
        ("2001:4860:4860::8888", "2001:4860:4860::8888\n"),
        ("::ffff:8.8.8.8", "8.8.8.8\n"),
        ("127.0.0.1", "127.0.0.1\n"),
    ] {
        let router = missing().layer(axum::Extension(Peer(peer.parse().unwrap())));
        let (status, headers, body) = call_raw(
            router.clone(),
            "/myip?ip=1.1.1.1",
            "GET",
            &[
                ("x-forwarded-for", "1.1.1.1"),
                ("origin", "https://example.com"),
            ],
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body, expected.as_bytes());
        assert_eq!(headers["content-type"], "text/plain; charset=utf-8");
        assert_eq!(headers["cache-control"], "no-store");
        assert_eq!(headers["x-robots-tag"], "noindex");
        assert_eq!(headers["access-control-allow-origin"], "*");
        let (status, headers, body) = call_raw(router, "/myip", "HEAD", &[]).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(headers["content-type"], "text/plain; charset=utf-8");
        assert!(body.is_empty());
    }
    assert_eq!(
        call(missing(), "/myip", "GET", &[]).await.0,
        StatusCode::BAD_REQUEST
    );
    assert_eq!(
        call(missing(), "/myip", "POST", &[]).await.0,
        StatusCode::METHOD_NOT_ALLOWED
    );
    let (status, headers, _) = call(missing(), "/myip/", "GET", &[]).await;
    assert_eq!(status, StatusCode::PERMANENT_REDIRECT);
    assert_eq!(headers["location"], "/myip");
}

#[tokio::test]
async fn myip_respects_proxy_and_ingress_trust() {
    let config = Config {
        trusted_proxies: vec!["10.0.0.0/24".parse().unwrap()],
        ..Config::default()
    };
    let router = app(Arc::new(AppState::load("/no-such-mmdb", config)))
        .layer(axum::Extension(Peer("10.0.0.1".parse().unwrap())));
    let (status, _, body) = call_raw(
        router.clone(),
        "/myip",
        "GET",
        &[("x-forwarded-for", "1.1.1.1, 8.8.8.8, 10.0.0.2")],
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, b"8.8.8.8\n");
    assert_eq!(
        call(router, "/myip", "GET", &[]).await.0,
        StatusCode::BAD_REQUEST
    );

    let secret = "a".repeat(64);
    let config = Config {
        ingress_secret: secret.clone(),
        ..Config::default()
    };
    let router = app(Arc::new(AppState::load("/no-such-mmdb", config)))
        .layer(axum::Extension(Peer("10.0.0.1".parse().unwrap())));
    for credentials in [
        vec![],
        vec![("x-ip-info-ingress", "wrong")],
        vec![
            ("x-ip-info-ingress", secret.as_str()),
            ("x-ip-info-ingress", secret.as_str()),
        ],
    ] {
        let mut headers = credentials;
        headers.push(("x-ip-info-client-ip", "8.8.8.8"));
        assert_eq!(
            call(router.clone(), "/myip", "GET", &headers).await.0,
            StatusCode::BAD_REQUEST
        );
    }
    let (status, _, body) = call_raw(
        router,
        "/myip",
        "GET",
        &[
            ("x-ip-info-ingress", &secret),
            ("x-ip-info-client-ip", "8.8.8.8"),
            ("x-forwarded-for", "1.1.1.1"),
        ],
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, b"8.8.8.8\n");
}
#[tokio::test]
async fn unavailable_db_and_health() {
    for path in [
        "/json?ip=8.8.8.8",
        "/json_lite?ip=8.8.8.8",
        "/8.8.8.8/json_lite",
    ] {
        let (s, h, v) = call(missing(), path, "GET", &[]).await;
        assert_eq!(s, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(v["error"]["code"], "database_unavailable");
        assert_eq!(h["cache-control"], "no-store");
        assert_eq!(h["x-robots-tag"], "noindex");
    }
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
        for route in [path.to_string(), path.replace("/json", "/json_lite")] {
            let (status, _, v) = call(missing(), &route, "GET", &[]).await;
            assert_eq!(status, StatusCode::BAD_REQUEST, "{route}");
            assert_eq!(v["error"]["code"], "invalid_ip");
        }
    }
    for route in ["/json", "/json_lite", "/8.8.8.8/json_lite"] {
        let (status, _, v) = call(missing(), route, "POST", &[]).await;
        assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED);
        assert_eq!(v["error"]["code"], "method_not_allowed");
    }
}

#[test]
fn lite_response_keeps_unavailable_fields_as_null() {
    let response = ip_info::database::LookupLiteResponse {
        country_code: None,
        region: None,
        city: None,
        timezone: None,
    };
    assert_eq!(
        serde_json::to_value(response).unwrap(),
        serde_json::json!({
            "country_code": null, "region": null, "city": null, "timezone": null
        })
    );
}

#[tokio::test]
async fn lite_headers_cors_redirects_and_missing_caller() {
    let router = app(Arc::new(AppState::load(
        "/no-such-mmdb",
        Config {
            indexable: true,
            ..Config::default()
        },
    )));
    let (status, _, body) = call(router.clone(), "/json_lite", "GET", &[]).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"]["code"], "invalid_ip");
    for path in ["/json_lite", "/8.8.8.8/json_lite"] {
        let (status, headers, body) =
            call_raw(router.clone(), &format!("{path}?ip=8.8.8.8"), "HEAD", &[]).await;
        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(headers["content-type"], "application/json");
        assert_eq!(headers["cache-control"], "no-store");
        assert_eq!(headers["x-robots-tag"], "noindex");
        assert!(body.is_empty());
        let (status, headers, _) = call(
            router.clone(),
            path,
            "OPTIONS",
            &[
                ("origin", "https://example.com"),
                ("access-control-request-method", "GET"),
            ],
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(headers["access-control-allow-origin"], "*");
        let (status, headers, body) = call(
            router.clone(),
            path,
            "GET",
            &[("x-large", &"x".repeat(17000))],
        )
        .await;
        assert_eq!(status, StatusCode::REQUEST_HEADER_FIELDS_TOO_LARGE);
        assert_eq!(body["error"]["code"], "request_too_large");
        assert_eq!(headers["cache-control"], "no-store");
        assert_eq!(headers["x-robots-tag"], "noindex");
    }
    for path in ["/json", "/8.8.8.8/json", "/json_lite", "/8.8.8.8/json_lite"] {
        let (status, headers, _) =
            call(router.clone(), &format!("{path}/?ip=8.8.8.8"), "GET", &[]).await;
        assert_eq!(status, StatusCode::PERMANENT_REDIRECT);
        assert_eq!(headers["location"], format!("{path}?ip=8.8.8.8"));
        assert_eq!(headers["cache-control"], "no-store");
        assert_eq!(headers["x-robots-tag"], "noindex");
    }
}

#[tokio::test]
async fn proxy_page_and_brand_assets_are_embedded_without_a_database() {
    let router = app(Arc::new(AppState::load(
        "/no-such-mmdb",
        Config {
            indexable: true,
            ..Config::default()
        },
    )));
    let (status, headers, bytes) = call_raw(router.clone(), "/web-proxy", "GET", &[]).await;
    assert!(!headers.contains_key("x-robots-tag"));
    assert_eq!(status, StatusCode::OK);
    assert!(
        headers["content-type"]
            .to_str()
            .unwrap()
            .starts_with("text/html")
    );
    let page = String::from_utf8(bytes).unwrap();
    assert!(page.contains("https://web.p.shifter.io/sdk/v1/shifter-web-proxy.js"));
    assert!(page.contains("href=\"/web-proxy\" aria-current=\"page\""));
    assert!(!page.contains("href=\"web-proxy.html\""));
    assert!(!page.contains("__IP_INFO_BRAND__"));
    let (status, headers, image) = call_raw(router, "/meta/web-proxy.png", "GET", &[]).await;
    assert!(!headers.contains_key("x-robots-tag"));
    assert_eq!(status, StatusCode::OK);
    assert_eq!(headers["content-type"], "image/png");
    assert!(image.starts_with(b"\x89PNG\r\n\x1a\n"));
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

//! The website's routes: every embedded page and file, and /robots.txt, keep
//! their status, content type, body and robots header for GET and HEAD.
// This test uses call_raw only.
#[allow(dead_code)]
mod common;

use axum::{Router, http::StatusCode};
use common::call_raw;
use ip_info::{AppState, Config, app};
use std::sync::Arc;

const HTML: &str = "text/html; charset=utf-8";
const TEXT: &str = "text/plain; charset=utf-8";
const GA4_ID: &str = "G-TEST123";

macro_rules! page {
    ($route:literal, $file:literal) => {
        ($route, $file, include_str!(concat!("../web/", $file)))
    };
}
/// (route, file under web/, its text).
const PAGES: [(&str, &str, &str); 8] = [
    page!("/", "index.html"),
    page!("/web-proxy", "web-proxy.html"),
    page!("/docs", "docs.html"),
    page!("/ai", "ai.html"),
    page!("/about", "about.html"),
    page!("/terms", "terms.html"),
    page!("/privacy", "privacy.html"),
    page!("/cookies", "cookies.html"),
];

macro_rules! asset {
    ($file:literal, $content_type:expr) => {
        (
            concat!("/", $file),
            $content_type,
            include_bytes!(concat!("../web/", $file)).as_slice(),
        )
    };
}
/// (route, content type, bytes).
const FILES: [(&str, &str, &[u8]); 20] = [
    asset!("llms.txt", TEXT),
    asset!("llms-full.txt", TEXT),
    asset!("openapi.json", "application/json"),
    asset!("sitemap.xml", "application/xml"),
    asset!("share.png", "image/png"),
    asset!("meta/home.png", "image/png"),
    asset!("meta/web-proxy.png", "image/png"),
    asset!("meta/docs.png", "image/png"),
    asset!("meta/ai.png", "image/png"),
    asset!("meta/about.png", "image/png"),
    asset!("meta/terms.png", "image/png"),
    asset!("meta/privacy.png", "image/png"),
    asset!("meta/cookies.png", "image/png"),
    asset!("favicon.png", "image/png"),
    asset!("apple-touch-icon.png", "image/png"),
    asset!("android-chrome-192x192.png", "image/png"),
    asset!("android-chrome-512x512.png", "image/png"),
    asset!("favicon.ico", "image/x-icon"),
    asset!("favicon.svg", "image/svg+xml"),
    asset!("site.webmanifest", "application/manifest+json"),
];

fn router(indexable: bool) -> Router {
    app(Arc::new(AppState::load(
        "/no-such-mmdb",
        Config {
            ga4_id: GA4_ID.into(),
            indexable,
            ..Config::default()
        },
    )))
}

/// GET and HEAD on `route`: 200, `content_type`, the robots header that
/// `indexable` gives and, for HEAD, an empty body. Returns GET's body.
async fn get_and_head(
    router: &Router,
    route: &str,
    content_type: &str,
    indexable: bool,
) -> Vec<u8> {
    let mut get_body = Vec::new();
    for method in ["GET", "HEAD"] {
        let (status, headers, body) = call_raw(router.clone(), route, method, &[]).await;
        assert_eq!(status, StatusCode::OK, "{method} {route}");
        assert_eq!(headers["content-type"], content_type, "{method} {route}");
        if indexable {
            assert!(!headers.contains_key("x-robots-tag"), "{method} {route}");
        } else {
            assert_eq!(headers["x-robots-tag"], "noindex", "{method} {route}");
        }
        if method == "HEAD" {
            assert!(body.is_empty(), "{method} {route}");
        } else {
            get_body = body;
        }
    }
    get_body
}

async fn check_site(indexable: bool) {
    let router = router(indexable);
    for (route, _, text) in PAGES {
        let body = get_and_head(&router, route, HTML, indexable).await;
        let body = String::from_utf8(body).unwrap();
        assert!(!body.contains("__GA4_ID__"), "{route}");
        assert_eq!(
            text.contains("__GA4_ID__"),
            body.contains(GA4_ID),
            "{route}"
        );
        for (_, file, _) in PAGES {
            assert!(
                !body.contains(&format!("href=\"{file}")),
                "{route} links {file}"
            );
        }
    }
    for (route, content_type, bytes) in FILES {
        let body = get_and_head(&router, route, content_type, indexable).await;
        assert_eq!(body, bytes, "{route}");
    }
    let robots = get_and_head(&router, "/robots.txt", TEXT, indexable).await;
    let expected: &[u8] = if indexable {
        b"User-agent: *\nAllow: /\nSitemap: https://ip-info.com/sitemap.xml\n"
    } else {
        b"User-agent: *\nDisallow: /\n"
    };
    assert_eq!(robots, expected);
}

#[tokio::test]
async fn indexable_site_routes_have_no_robots_header() {
    check_site(true).await;
}
#[tokio::test]
async fn private_site_routes_are_noindex() {
    check_site(false).await;
}

//! The website: its pages and files, embedded in the binary, and the HTML
//! rewrite that links pages by route. One table drives both.
use crate::server::AppState;
use axum::{Router, extract::State, http::header, response::Html, routing::get};
use std::sync::Arc;

macro_rules! page {
    ($route:literal, $file:literal) => {
        ($route, $file, include_str!(concat!("../web/", $file)))
    };
}
/// (route, file under web/, HTML).
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

const TEXT: &str = "text/plain; charset=utf-8";
const PNG: &str = "image/png";
macro_rules! asset {
    ($file:literal, $content_type:expr) => {
        (
            concat!("/", $file),
            $content_type,
            include_bytes!(concat!("../web/", $file)).as_slice(),
        )
    };
}
/// (route, content type, bytes), served from web/<route>.
const FILES: [(&str, &str, &[u8]); 20] = [
    asset!("llms.txt", TEXT),
    asset!("llms-full.txt", TEXT),
    asset!("openapi.json", "application/json"),
    asset!("sitemap.xml", "application/xml"),
    asset!("share.png", PNG),
    asset!("meta/home.png", PNG),
    asset!("meta/web-proxy.png", PNG),
    asset!("meta/docs.png", PNG),
    asset!("meta/ai.png", PNG),
    asset!("meta/about.png", PNG),
    asset!("meta/terms.png", PNG),
    asset!("meta/privacy.png", PNG),
    asset!("meta/cookies.png", PNG),
    asset!("favicon.png", PNG),
    asset!("apple-touch-icon.png", PNG),
    asset!("android-chrome-192x192.png", PNG),
    asset!("android-chrome-512x512.png", PNG),
    asset!("favicon.ico", "image/x-icon"),
    asset!("favicon.svg", "image/svg+xml"),
    asset!("site.webmanifest", "application/manifest+json"),
];

/// Every page, every file and /robots.txt.
pub(crate) fn routes() -> Router<Arc<AppState>> {
    let mut router = Router::new().route("/robots.txt", get(robots));
    for (route, _, html) in PAGES {
        router = router.route(route, get(move || async move { Html(html) }));
    }
    for (route, content_type, bytes) in FILES {
        let file = move || async move { ([(header::CONTENT_TYPE, content_type)], bytes) };
        router = router.route(route, get(file));
    }
    router
}
async fn robots(State(s): State<Arc<AppState>>) -> String {
    if s.config.indexable {
        "User-agent: *\nAllow: /\nSitemap: https://ip-info.com/sitemap.xml\n".into()
    } else {
        "User-agent: *\nDisallow: /\n".into()
    }
}
/// Puts the GA4 measurement ID in a page and turns its `href="<file>` links
/// into `href="<route>`.
pub(crate) fn rewrite_html(text: &str, ga4_id: &str) -> String {
    let mut text = text.replace("__GA4_ID__", ga4_id);
    for (route, file, _) in PAGES {
        text = text.replace(&format!("href=\"{file}"), &format!("href=\"{route}"));
    }
    text
}

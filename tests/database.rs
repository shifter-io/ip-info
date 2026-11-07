//! Database tests. They run on the test database, tests/fixtures/*.mmdb,
//! built by scripts/build_test_mmdb.py. The tests moved from tests/api.rs use
//! MMDB_PATH instead when it is set, to run them on the licensed file:
//! `MMDB_PATH=data/dbip.mmdb cargo test --locked`.
mod common;

use axum::{Router, http::StatusCode};
use common::{call, call_raw};
use ip_info::{AppState, Config, Peer, app, database::Database};
use serde_json::{Value, json};
use std::sync::{Arc, OnceLock};

const TEST_DATABASE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/tests/fixtures/ip-info-test.mmdb"
);
const FIXTURES: [&str; 5] = [
    "ip-info-test.mmdb",
    "ip-info-test-wrong-type.mmdb",
    "ip-info-test-no-probe.mmdb",
    "ip-info-test-probe-no-asn.mmdb",
    "ip-info-test-bad-record.mmdb",
];

fn fixture(name: &str) -> String {
    format!("{}/tests/fixtures/{name}", env!("CARGO_MANIFEST_DIR"))
}
/// The test database, or MMDB_PATH when set.
fn database_path() -> String {
    std::env::var("MMDB_PATH").unwrap_or_else(|_| TEST_DATABASE.into())
}
fn database_router() -> Router {
    static STATE: OnceLock<Arc<AppState>> = OnceLock::new();
    app(STATE
        .get_or_init(|| {
            let state = AppState::load(&database_path(), Config::default());
            assert!(
                state.db.is_some(),
                "Database tests need the test database or a valid MMDB_PATH"
            );
            Arc::new(state)
        })
        .clone())
}
/// A fresh state on one fixture file, never MMDB_PATH.
fn fixture_router(name: &str) -> Router {
    app(Arc::new(AppState::load(&fixture(name), Config::default())))
}

#[test]
fn every_fixture_file_verifies() {
    for name in FIXTURES {
        let reader = maxminddb::Reader::open_readfile(fixture(name)).unwrap();
        assert!(reader.verify().is_ok(), "{name}");
    }
}
#[tokio::test]
async fn test_database_returns_the_contract_examples() {
    let router = fixture_router("ip-info-test.mmdb");
    let full: Value = serde_json::from_str(include_str!("example.json")).unwrap();
    let lite: Value = serde_json::from_str(include_str!("lite-example.json")).unwrap();
    let (status, _, body) = call(router.clone(), "/json?ip=8.8.8.8", "GET", &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, full);
    let (status, _, body) = call(router, "/json_lite?ip=8.8.8.8", "GET", &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, lite);
}
#[tokio::test]
async fn sparse_record_leaves_every_missing_field_null() {
    let router = fixture_router("ip-info-test.mmdb");
    let (status, _, body) = call(router.clone(), "/json?ip=1.1.1.1", "GET", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let present = json!({
        "ip": "1.1.1.1", "country": "AU", "country_name": "Australia",
        "country_geoname_id": 2077456, "asn": 13335
    });
    for (field, value) in body.as_object().unwrap() {
        assert_eq!(value, present.get(field).unwrap_or(&Value::Null), "{field}");
    }
    let (status, _, body) = call(router, "/json_lite?ip=1.1.1.1", "GET", &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"country_code": "AU", "region": null, "city": null, "timezone": null})
    );
}
#[tokio::test]
async fn public_ip_without_a_record_is_not_found() {
    let router = fixture_router("ip-info-test.mmdb");
    for path in ["/json?ip=8.8.4.4", "/json_lite?ip=8.8.4.4"] {
        let (status, _, body) = call(router.clone(), path, "GET", &[]).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{path}");
        assert_eq!(body["error"]["code"], "ip_not_found");
    }
    assert_eq!(call(router, "/readyz", "GET", &[]).await.0, StatusCode::OK);
}
#[tokio::test]
async fn invalid_databases_are_rejected_at_startup() {
    for (name, message) in [
        (
            "ip-info-test-wrong-type.mmdb",
            Some("Expected a DB-IP Location + ISP database"),
        ),
        (
            "ip-info-test-no-probe.mmdb",
            Some("Database startup probe has no record"),
        ),
        (
            "ip-info-test-probe-no-asn.mmdb",
            Some("Database startup probe lacks country/ASN"),
        ),
        ("no-such-file.mmdb", None),
    ] {
        let Err(error) = Database::open(&fixture(name)) else {
            panic!("{name} opened");
        };
        if let Some(message) = message {
            assert_eq!(error.to_string(), message, "{name}");
        }
        let (status, _, _) = call(fixture_router(name), "/readyz", "GET", &[]).await;
        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE, "{name}");
    }
}
#[tokio::test]
async fn unreadable_record_disables_readiness() {
    let router = fixture_router("ip-info-test-bad-record.mmdb");
    assert_eq!(
        call(router.clone(), "/readyz", "GET", &[]).await.0,
        StatusCode::OK
    );
    let (status, _, body) = call(router.clone(), "/json?ip=8.8.4.4", "GET", &[]).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(
        body,
        json!({"error": {
            "code": "database_unavailable",
            "message": "Database could not be read."
        }})
    );
    for path in ["/readyz", "/json?ip=8.8.8.8"] {
        let (status, _, _) = call(router.clone(), path, "GET", &[]).await;
        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE, "{path}");
    }
}
#[tokio::test]
async fn real_lite_lookup_matches_full_location_for_all_lookup_modes() {
    let schema: Value = serde_json::from_str(include_str!("../web/openapi.json")).unwrap();
    let fields = schema["components"]["schemas"]["IpInfoLite"]["properties"]
        .as_object()
        .unwrap();
    assert_eq!(fields.len(), 4);
    for ip in [
        "8.8.8.8",
        "1.1.1.1",
        "2001:4860:4860::8888",
        "::ffff:8.8.8.8",
    ] {
        let (status, _, full) =
            call(database_router(), &format!("/json?ip={ip}"), "GET", &[]).await;
        assert_eq!(status, StatusCode::OK);
        let expected = serde_json::json!({
            "country_code": full["country"], "region": full["region"],
            "city": full["city"], "timezone": full["timezone"]
        });
        let router = database_router().layer(axum::Extension(Peer(ip.parse().unwrap())));
        for path in [
            "/json_lite".to_string(),
            format!("/json_lite?ip={ip}"),
            format!("/{ip}/json_lite"),
            format!("/{ip}/json_lite?ip={ip}"),
        ] {
            let (status, headers, bytes) = call_raw(
                router.clone(),
                &path,
                "GET",
                &[
                    ("origin", "https://example.com"),
                    ("x-forwarded-for", "9.9.9.9"),
                    ("cdn-real-ip", "9.9.9.9"),
                ],
            )
            .await;
            assert_eq!(status, StatusCode::OK, "{path}");
            assert_eq!(headers["content-type"], "application/json");
            assert_eq!(headers["cache-control"], "no-store");
            assert_eq!(headers["x-robots-tag"], "noindex");
            assert_eq!(headers["access-control-allow-origin"], "*");
            let actual: Value = serde_json::from_slice(&bytes).unwrap();
            assert_eq!(actual, expected, "{path}");
            assert!(fields.keys().all(|name| actual.get(name).is_some()));
            assert!(!bytes.contains(&b'\n'), "Lite JSON must be compact");
            assert!(bytes.len() < serde_json::to_vec(&full).unwrap().len());
            let (status, headers, bytes) = call_raw(router.clone(), &path, "HEAD", &[]).await;
            assert_eq!(status, StatusCode::OK);
            assert_eq!(headers["content-type"], "application/json");
            assert!(bytes.is_empty());
        }
    }
}

#[tokio::test]
async fn real_database_matches_contract() {
    let (s, h, actual) = call(database_router(), "/json?ip=8.8.8.8", "GET", &[]).await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(h["cache-control"], "no-store");
    assert!(actual.get("database_date").is_none());
    let (ready_status, _, readiness) = call(database_router(), "/readyz", "GET", &[]).await;
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
    let path = call(database_router(), "/8.8.8.8/json", "GET", &[]).await.2;
    assert_eq!(actual, path);
    let matching = call(database_router(), "/8.8.8.8/json?ip=8.8.8.8", "GET", &[])
        .await
        .2;
    assert_eq!(actual, matching);
    let mapped = call(database_router(), "/json?ip=::ffff:8.8.8.8", "GET", &[])
        .await
        .2;
    assert_eq!(actual, mapped);
    let (status, _, ipv6) = call(
        database_router(),
        "/json?ip=2001:4860:4860::8888",
        "GET",
        &[],
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(ipv6["asn"], 15169);
}
#[tokio::test]
async fn caller_spoofing_and_cache_isolation() {
    let one = database_router().layer(axum::Extension(Peer("8.8.8.8".parse().unwrap())));
    let two = database_router().layer(axum::Extension(Peer("9.9.9.9".parse().unwrap())));
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
    let trusted = app(Arc::new(AppState::load(&database_path(), config)))
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
async fn authenticated_ingress_rejects_spoofed_headers() {
    let config = Config {
        ingress_secret: "a".repeat(64),
        ..Config::default()
    };
    let router = app(Arc::new(AppState::load(&database_path(), config)))
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

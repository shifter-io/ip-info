use axum::http::HeaderMap;
use ipnet::IpNet;
use std::{net::IpAddr, sync::LazyLock};

// Conservative policy: private, documentation, benchmarking and special-purpose
// networks are not geolocated. This is address classification, not an egress ACL.
static NON_PUBLIC: LazyLock<Vec<IpNet>> = LazyLock::new(|| {
    [
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/3",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "3fff::/20",
    ]
    .iter()
    .map(|s| s.parse().expect("static CIDR"))
    .collect()
});

pub fn normalize(ip: IpAddr) -> IpAddr {
    match ip {
        IpAddr::V6(v6) => v6.to_ipv4_mapped().map(IpAddr::V4).unwrap_or(ip),
        _ => ip,
    }
}
pub fn public(ip: IpAddr) -> bool {
    let ip = normalize(ip);
    let allocated = match ip {
        IpAddr::V4(_) => true,
        IpAddr::V6(v) => (v.segments()[0] & 0xe000) == 0x2000,
    };
    allocated && !NON_PUBLIC.iter().any(|n| n.contains(&ip))
}
pub fn parse(value: &str) -> Result<IpAddr, &'static str> {
    value
        .parse()
        .map(normalize)
        .map_err(|_| "Supply a literal IPv4 or IPv6 address.")
}
pub fn caller(
    peer: IpAddr,
    headers: &HeaderMap,
    trusted: &[IpNet],
    header: &str,
) -> Result<IpAddr, &'static str> {
    let peer = normalize(peer);
    if !trusted.iter().any(|n| n.contains(&peer)) {
        return Ok(peer);
    }
    let mut values = headers.get_all(header).iter();
    let value = values
        .next()
        .ok_or("Trusted ingress did not supply the client IP header.")?;
    if values.next().is_some() {
        return Err("Duplicate client IP headers.");
    }
    let value = value.to_str().map_err(|_| "Invalid client IP header.")?;
    if header != "x-forwarded-for" {
        return parse(value.trim());
    }
    let chain = value
        .split(',')
        .map(|s| parse(s.trim()))
        .collect::<Result<Vec<_>, _>>()?;
    if chain.is_empty() || chain.len() > 32 {
        return Err("Invalid proxy chain.");
    }
    let mut candidate = peer;
    for address in chain.into_iter().rev() {
        if !trusted.iter().any(|n| n.contains(&candidate)) {
            break;
        }
        candidate = address;
    }
    Ok(candidate)
}

/// A CDN-only endpoint overwrites both headers. No network-wide proxy trust is
/// needed; absent, duplicated or incorrect credentials fail closed.
pub fn authenticated_caller(headers: &HeaderMap, secret: &str) -> Result<IpAddr, &'static str> {
    let single = |name: &str| -> Result<&str, &'static str> {
        let mut values = headers.get_all(name).iter();
        let value = values
            .next()
            .ok_or("Authenticated ingress header missing.")?;
        if values.next().is_some() {
            return Err("Duplicate ingress headers.");
        }
        value.to_str().map_err(|_| "Invalid ingress header.")
    };
    let supplied = single("x-ip-info-ingress")?;
    if secret.is_empty()
        || supplied.len() != secret.len()
        || supplied
            .bytes()
            .zip(secret.bytes())
            .fold(0u8, |difference, (a, b)| difference | (a ^ b))
            != 0
    {
        return Err("Unauthenticated ingress.");
    }
    parse(single("x-ip-info-client-ip")?.trim())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn classifies_special_addresses() {
        for s in [
            "127.0.0.1",
            "10.2.3.4",
            "100.64.0.1",
            "192.168.1.1",
            "192.0.2.1",
            "198.18.1.1",
            "203.0.113.2",
            "224.0.0.1",
            "255.255.255.255",
            "::",
            "::1",
            "fc00::1",
            "fe80::1",
            "ff02::1",
            "2001:db8::1",
            "3fff::1",
            "::ffff:127.0.0.1",
        ] {
            assert!(!public(parse(s).unwrap()), "{s}");
        }
        for s in [
            "9.9.9.9",
            "1.1.1.1",
            "8.8.8.8",
            "2001:4860:4860::8888",
            "2606:4700:4700::1111",
            "::ffff:8.8.8.8",
        ] {
            assert!(public(parse(s).unwrap()), "{s}");
        }
    }
    #[test]
    fn forwarded_headers_require_trust_and_walk_from_right() {
        let mut h = HeaderMap::new();
        h.insert(
            "x-forwarded-for",
            "1.1.1.1, 9.9.9.9, 10.0.0.2".parse().unwrap(),
        );
        assert_eq!(
            caller(parse("8.8.8.8").unwrap(), &h, &[], "x-forwarded-for")
                .unwrap()
                .to_string(),
            "8.8.8.8"
        );
        assert_eq!(
            caller(
                parse("10.0.0.1").unwrap(),
                &h,
                &["10.0.0.0/24".parse().unwrap()],
                "x-forwarded-for"
            )
            .unwrap()
            .to_string(),
            "9.9.9.9"
        );
        h.append("x-forwarded-for", "8.8.8.8".parse().unwrap());
        assert!(
            caller(
                parse("10.0.0.1").unwrap(),
                &h,
                &["10.0.0.0/24".parse().unwrap()],
                "x-forwarded-for"
            )
            .is_err()
        );
    }
}

//! Local-only HTTP/1.1 load generator, one request in flight per connection.
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    thread,
    time::{Duration, Instant},
};
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let workers: usize = args[1].parse().unwrap();
    let seconds: u64 = args[2].parse().unwrap();
    let mode = args[3].clone();
    let start = Instant::now();
    let deadline = start + Duration::from_secs(seconds);
    let handles: Vec<_> = (0..workers)
        .map(|w| {
            let mode = mode.clone();
            thread::spawn(move || {
                let mut conn: Option<BufReader<TcpStream>> = None;
                let mut seed = w as u64 + 20260929;
                let mut hist = vec![0u64; 60001];
                let mut statuses = std::collections::BTreeMap::new();
                let mut error_kinds = std::collections::BTreeMap::new();
                let (mut errors, mut invalid, mut n) = (0, 0, 0);
                while Instant::now() < deadline {
                    seed ^= seed << 13;
                    seed ^= seed >> 7;
                    seed ^= seed << 17;
                    let ip = if mode == "hot" {
                        "8.8.8.8".to_string()
                    } else if seed.is_multiple_of(4) {
                        format!(
                            "2606:4700:{:x}:{:x}::{:x}",
                            (seed >> 16) & 65535,
                            (seed >> 32) & 65535,
                            seed & 65535
                        )
                    } else {
                        format!(
                            "{}.{}.{}.{}",
                            [
                                1, 8, 23, 31, 45, 64, 81, 94, 103, 122, 142, 151, 177, 185, 201,
                                223
                            ][(seed % 16) as usize],
                            (seed >> 8) & 255,
                            (seed >> 24) & 255,
                            (seed >> 40) & 255
                        )
                    };
                    let (path, expected, validate) = if mode == "mixed" {
                        match seed % 10 {
                            0 => ("/".into(), 200, false),
                            1 => ("/docs".into(), 200, false),
                            2 => ("/json?ip=invalid".into(), 400, false),
                            _ => (format!("/json?ip={ip}"), 200, true),
                        }
                    } else {
                        (format!("/json?ip={ip}"), 200, true)
                    };
                    let t = Instant::now();
                    let result = (|| -> std::io::Result<()> {
                        if conn.is_none() {
                            let s = TcpStream::connect("127.0.0.1:18080")?;
                            s.set_read_timeout(Some(Duration::from_secs(5)))?;
                            s.set_write_timeout(Some(Duration::from_secs(5)))?;
                            s.set_nodelay(true)?;
                            conn = Some(BufReader::new(s));
                        }
                        let c = conn.as_mut().unwrap();
                        write!(
                            c.get_mut(),
                            "GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n"
                        )?;
                        let mut line = String::new();
                        c.read_line(&mut line)?;
                        let status: u16 = line
                            .split_whitespace()
                            .nth(1)
                            .unwrap_or("0")
                            .parse()
                            .unwrap_or(0);
                        let mut len = None;
                        loop {
                            line.clear();
                            if c.read_line(&mut line)? == 0 {
                                return Err(std::io::ErrorKind::UnexpectedEof.into());
                            }
                            if line == "\r\n" {
                                break;
                            }
                            if let Some((k, v)) = line.split_once(':')
                                && k.eq_ignore_ascii_case("content-length")
                            {
                                len = v.trim().parse::<usize>().ok()
                            }
                        }
                        let len = len.ok_or(std::io::ErrorKind::InvalidData)?;
                        let mut body = vec![0; len];
                        c.read_exact(&mut body)?;
                        *statuses.entry(status).or_insert(0u64) += 1;
                        if validate && status == 200 {
                            let v: serde_json::Value =
                                serde_json::from_slice(&body).unwrap_or_default();
                            if v["ip"]
                                .as_str()
                                .and_then(|s| s.parse::<std::net::IpAddr>().ok())
                                != ip.parse::<std::net::IpAddr>().ok()
                            {
                                invalid += 1
                            }
                        } else if status != expected && !(validate && status == 404) {
                            invalid += 1
                        }
                        Ok(())
                    })();
                    if let Err(error) = result {
                        *error_kinds.entry(error.to_string()).or_insert(0u64) += 1;
                        errors += 1;
                        conn = None
                    }
                    if mode == "churn" {
                        conn = None
                    }
                    n += 1;
                    hist[(t.elapsed().as_micros() / 100).min(60000) as usize] += 1;
                }
                (n, errors, invalid, hist, statuses, error_kinds)
            })
        })
        .collect();
    let (mut n, mut errors, mut invalid) = (0u64, 0u64, 0u64);
    let mut hist = vec![0u64; 60001];
    let mut statuses = std::collections::BTreeMap::new();
    let mut error_kinds = std::collections::BTreeMap::new();
    for h in handles {
        let (a, b, c, d, e, kinds) = h.join().unwrap();
        for (k, v) in kinds {
            *error_kinds.entry(k).or_insert(0u64) += v;
        }
        n += a;
        errors += b;
        invalid += c;
        for (i, v) in d.iter().enumerate() {
            hist[i] += v
        }
        for (k, v) in e {
            *statuses.entry(k).or_insert(0u64) += v
        }
    }
    let q = |p: f64| {
        let mut sum = 0;
        for (i, v) in hist.iter().enumerate() {
            sum += v;
            if sum as f64 >= n as f64 * p {
                return (i + 1) as f64 / 10.;
            }
        }
        0.
    };
    let elapsed = start.elapsed().as_secs_f64();
    println!(
        "{}",
        serde_json::json!({"mode":mode,"workers":workers,"seconds":elapsed,"requests":n,"rps":n as f64/elapsed,"p50_ms":q(0.5),"p95_ms":q(0.95),"p99_ms":q(0.99),"transport_errors":errors,"invalid_responses":invalid,"statuses":statuses,"error_kinds":error_kinds})
    );
}

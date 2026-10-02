use maxminddb::{Mmap, Reader};
use serde::Deserialize;
use std::net::IpAddr;

include!("response.rs");

#[derive(Default, Deserialize)]
#[serde(default)]
struct Names {
    en: Option<String>,
}
#[derive(Default, Deserialize)]
#[serde(default)]
struct Place {
    names: Names,
    geoname_id: Option<u32>,
    iso_code: Option<String>,
    code: Option<String>,
    is_in_european_union: Option<bool>,
}
#[derive(Default, Deserialize)]
#[serde(default)]
struct Location {
    latitude: Option<f64>,
    longitude: Option<f64>,
    time_zone: Option<String>,
    weather_code: Option<String>,
}
#[derive(Default, Deserialize)]
#[serde(default)]
struct Postal {
    code: Option<String>,
}
#[derive(Default, Deserialize)]
#[serde(default)]
struct Traits {
    autonomous_system_number: Option<u32>,
    autonomous_system_organization: Option<String>,
    isp: Option<String>,
    organization: Option<String>,
    connection_type: Option<String>,
    user_type: Option<String>,
    is_anycast: Option<bool>,
}
#[derive(Default, Deserialize)]
#[serde(default)]
struct Record {
    city: Place,
    country: Place,
    continent: Place,
    subdivisions: Vec<Place>,
    location: Location,
    postal: Postal,
    traits: Traits,
}

pub struct Database {
    reader: Reader<Mmap>,
}
impl Database {
    pub fn open(path: &str) -> Result<Self, Box<dyn std::error::Error>> {
        // SAFETY: deployment treats this file as immutable. Docker makes /data read-only;
        // local operators must stop the process before replacing it (see operations.html).
        let reader = unsafe { Reader::open_mmap(path)? };
        if !reader
            .metadata()
            .database_type
            .starts_with("DBIP-Location-ISP")
        {
            return Err("Expected a DB-IP Location + ISP database".into());
        }
        let db = Self { reader };
        // Exercise both trees and typed decoding before advertising readiness.
        for ip in ["8.8.8.8", "2001:4860:4860::8888"] {
            let record = db
                .lookup(ip.parse()?)?
                .ok_or("Database startup probe has no record")?;
            if record.country.is_none() || record.asn.is_none() {
                return Err("Database startup probe lacks country/ASN".into());
            }
        }
        Ok(db)
    }

    pub fn lookup(&self, ip: IpAddr) -> Result<Option<LookupResponse>, maxminddb::MaxMindDbError> {
        let Some(r) = self.reader.lookup(ip)?.decode::<Record>()? else {
            return Ok(None);
        };
        let mut subdivisions = r.subdivisions.into_iter();
        let region = subdivisions.next().unwrap_or_default();
        let district = subdivisions.next().unwrap_or_default();
        Ok(Some(LookupResponse {
            ip: ip.to_string(),
            city: r.city.names.en,
            city_geoname_id: r.city.geoname_id,
            region: region.names.en,
            region_code: region.iso_code,
            region_geoname_id: region.geoname_id,
            district: district.names.en,
            district_code: district.iso_code,
            district_geoname_id: district.geoname_id,
            country: r.country.iso_code,
            country_name: r.country.names.en,
            country_geoname_id: r.country.geoname_id,
            is_eu: r.country.is_in_european_union,
            continent: r.continent.code,
            continent_name: r.continent.names.en,
            continent_geoname_id: r.continent.geoname_id,
            loc: r
                .location
                .latitude
                .zip(r.location.longitude)
                .map(|(lat, lon)| format!("{lat},{lon}")),
            latitude: r.location.latitude,
            longitude: r.location.longitude,
            postal: r.postal.code,
            timezone: r.location.time_zone,
            weather_code: r.location.weather_code,
            asn: r.traits.autonomous_system_number,
            as_name: r.traits.autonomous_system_organization,
            isp: r.traits.isp,
            org: r.traits.organization,
            connection_type: r.traits.connection_type,
            user_type: r.traits.user_type,
            is_anycast: r.traits.is_anycast,
        }))
    }
}

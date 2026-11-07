#!/usr/bin/env python3
"""Build the fake MaxMind DB test files in tests/fixtures. Standard library only.

Writes MaxMind DB format 2.0 (https://maxmind.github.io/MaxMind-DB/) with fake
records: the inverse of Database::lookup in src/database.rs. The values come
from EXAMPLE in api_contract.py and the record table of issue #29; no licensed
data. The output is byte-identical on every run.
Run: python3 scripts/build_test_mmdb.py [--out-dir DIR]
"""
import argparse, ipaddress, struct
from pathlib import Path
from api_contract import EXAMPLE

ROOT = Path(__file__).resolve().parents[1]
DBIP_TYPE = 'DBIP-Location-ISP (compat=Enterprise)'
DESCRIPTION = 'IP Info test database: fake data, no licensed data'
BUILD_EPOCH = 1793491200  # 2026-11-01T00:00:00Z, fixed so the files never change
RECORD_SIZE = 24
METADATA_MARKER = b'\xab\xcd\xefMaxMind.com'

class UInt16(int):
    """An integer written as uint16; a plain int is written as uint32."""

class UInt64(int):
    """An integer written as uint64."""

def present(**fields):
    """The fields whose value is not None."""
    return {key: value for key, value in fields.items() if value is not None}

def place(names_en, geoname_id, **codes):
    return present(names={'en': names_en}, geoname_id=geoname_id, **codes)

def example_record(e):
    """EXAMPLE (one /json response) mapped back to a DB-IP record; loc is derived by the server."""
    return {
        'city': place(e['city'], e['city_geoname_id']),
        'country': place(e['country_name'], e['country_geoname_id'], iso_code=e['country'],
                         is_in_european_union=e['is_eu']),
        'continent': place(e['continent_name'], e['continent_geoname_id'], code=e['continent']),
        'subdivisions': [
            place(e['region'], e['region_geoname_id'], iso_code=e['region_code']),
            place(e['district'], e['district_geoname_id'], iso_code=e['district_code']),
        ],
        'location': present(latitude=e['latitude'], longitude=e['longitude'],
                            time_zone=e['timezone'], weather_code=e['weather_code']),
        'postal': present(code=e['postal']),
        'traits': present(autonomous_system_number=e['asn'], autonomous_system_organization=e['as_name'],
                          isp=e['isp'], organization=e['org'], connection_type=e['connection_type'],
                          user_type=e['user_type'], is_anycast=e['is_anycast']),
    }

GOOGLE_V4 = example_record(EXAMPLE)
GOOGLE_V6 = {
    'country': place('United States', 6252001, iso_code='US'),
    'continent': place('North America', 6255149, code='NA'),
    'traits': {'autonomous_system_number': 15169, 'autonomous_system_organization': 'Google LLC',
               'isp': 'Google LLC'},
}
# Sparse on purpose: every other field of the response is null.
CLOUDFLARE = {
    'country': place('Australia', 2077456, iso_code='AU'),
    'traits': {'autonomous_system_number': 13335},
}
QUAD9 = {
    'country': place('Switzerland', 2658434, iso_code='CH'),
    'traits': {'autonomous_system_number': 19281, 'autonomous_system_organization': 'Quad9'},
}

def networks(google_v4=GOOGLE_V4):
    """The main file's networks and records, in this order; google_v4 None leaves 8.8.8.8 out."""
    pairs = [('8.8.8.8/32', google_v4), ('2001:4860:4860::8888/128', GOOGLE_V6),
             ('1.1.1.1/32', CLOUDFLARE), ('9.9.9.9/32', QUAD9)]
    return [(network, record) for network, record in pairs if record is not None]

def without_asn(record):
    return {**record, 'traits': {k: v for k, v in record['traits'].items() if k != 'autonomous_system_number'}}

# A decode error at lookup time: latitude must be a double.
BAD_RECORD = {**GOOGLE_V4, 'location': {**GOOGLE_V4['location'], 'latitude': 'north'}}
FILES = {
    'ip-info-test.mmdb': (DBIP_TYPE, networks()),
    'ip-info-test-wrong-type.mmdb': ('GeoLite2-City', networks()),
    'ip-info-test-no-probe.mmdb': (DBIP_TYPE, networks(google_v4=None)),
    'ip-info-test-probe-no-asn.mmdb': (DBIP_TYPE, networks(google_v4=without_asn(GOOGLE_V4))),
    'ip-info-test-bad-record.mmdb': (DBIP_TYPE, networks() + [('8.8.4.4/32', BAD_RECORD)]),
}

def control(kind, size):
    """A field's control byte, its extended type byte (types over 7) and its size bytes."""
    head = (kind << 5) if kind <= 7 else 0
    extended = b'' if kind <= 7 else bytes([kind - 7])
    if size < 29:
        return bytes([head | size]) + extended
    if size < 285:
        return bytes([head | 29]) + extended + bytes([size - 29])
    if size < 65821:
        return bytes([head | 30]) + extended + (size - 285).to_bytes(2, 'big')
    return bytes([head | 31]) + extended + (size - 65821).to_bytes(3, 'big')

def unsigned(kind, value, width, key):
    if not 0 <= value < 256 ** width:
        raise ValueError(f'{key}: {value} does not fit in {width * 8} bits')
    payload = value.to_bytes((value.bit_length() + 7) // 8, 'big')
    return control(kind, len(payload)) + payload

def encode(value, key):
    """One data-section value; map keys are sorted, so the output is deterministic."""
    if isinstance(value, bool):
        return control(14, int(value))
    if isinstance(value, UInt16):
        return unsigned(5, value, 2, key)
    if isinstance(value, UInt64):
        return unsigned(9, value, 8, key)
    if isinstance(value, int):
        return unsigned(6, value, 4, key)
    if isinstance(value, float):
        return control(3, 8) + struct.pack('>d', value)
    if isinstance(value, str):
        data = value.encode('utf-8')
        return control(2, len(data)) + data
    if isinstance(value, dict):
        return control(7, len(value)) + b''.join(
            encode(name, key) + encode(value[name], name) for name in sorted(value))
    if isinstance(value, list):
        return control(11, len(value)) + b''.join(encode(item, key) for item in value)
    raise ValueError(f'{key}: unsupported value {value!r}')

def tree_key(network):
    """A network as (128-bit address, prefix) in the IPv6 tree; IPv4 sits at ::a.b.c.d/(96+prefix)."""
    net = ipaddress.ip_network(network)
    offset = 96 if net.version == 4 else 0
    return int(net.network_address), net.prefixlen + offset

def build_tree(leaves):
    """A binary trie: each node is [left, right]; a side is a node index, ('data', offset) or None."""
    nodes = [[None, None]]
    for (address, prefix), offset in leaves:
        node = 0
        for depth in range(prefix - 1):
            bit = (address >> (127 - depth)) & 1
            side = nodes[node][bit]
            if isinstance(side, tuple):
                raise ValueError(f'network {address:#x}/{prefix} overlaps another network')
            if side is None:
                side = nodes[node][bit] = len(nodes)
                nodes.append([None, None])
            node = side
        bit = (address >> (128 - prefix)) & 1
        if nodes[node][bit] is not None:
            raise ValueError(f'network {address:#x}/{prefix} overlaps another network')
        nodes[node][bit] = ('data', offset)
    return nodes

def record_value(side, node_count):
    if side is None:
        return node_count
    if isinstance(side, tuple):
        return node_count + 16 + side[1]
    return side

def database(database_type, records):
    data, leaves = b'', []
    for network, record in records:
        leaves.append((tree_key(network), len(data)))
        data += encode(record, network)
    nodes = build_tree(leaves)
    tree = b''.join(record_value(side, len(nodes)).to_bytes(RECORD_SIZE // 8, 'big')
                    for node in nodes for side in node)
    metadata = {
        'binary_format_major_version': UInt16(2), 'binary_format_minor_version': UInt16(0),
        'build_epoch': UInt64(BUILD_EPOCH), 'database_type': database_type,
        'description': {'en': DESCRIPTION}, 'ip_version': UInt16(6), 'languages': ['en'],
        'node_count': len(nodes), 'record_size': UInt16(RECORD_SIZE),
    }
    return tree + bytes(16) + data + METADATA_MARKER + encode(metadata, 'metadata')

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'tests/fixtures')
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, (database_type, records) in FILES.items():
        content = database(database_type, records)
        (args.out_dir / name).write_bytes(content)
        print(f'{name}: {len(content)} bytes')

if __name__ == '__main__':
    main()

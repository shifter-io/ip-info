"""Single source for the response type, OpenAPI, examples and field reference."""
FIELDS = [
    ("ip", "string", False, "8.8.8.8", "Normalized public IP address that was looked up."),
    ("city", "string", True, "Mountain View", "City name in English."),
    ("city_geoname_id", "integer", True, 5375480, "City GeoNames identifier."),
    ("region", "string", True, "California", "First administrative subdivision in English."),
    ("region_code", "string", True, "CA", "Subdivision code as stored in the database; not prefixed with country."),
    ("region_geoname_id", "integer", True, 5332921, "First subdivision GeoNames identifier."),
    ("district", "string", True, "Santa Clara", "Second administrative subdivision in English."),
    ("district_code", "string", True, None, "Second subdivision code, where available."),
    ("district_geoname_id", "integer", True, 5393021, "Second subdivision GeoNames identifier."),
    ("country", "string", True, "US", "Two-letter ISO country code."),
    ("country_name", "string", True, "United States", "Country name in English."),
    ("country_geoname_id", "integer", True, 6252001, "Country GeoNames identifier."),
    ("is_eu", "boolean", True, False, "European Union membership; null means unknown."),
    ("continent", "string", True, "NA", "Two-letter continent code."),
    ("continent_name", "string", True, "North America", "Continent name in English."),
    ("continent_geoname_id", "integer", True, 6255149, "Continent GeoNames identifier."),
    ("loc", "string", True, "37.422,-122.085", "Approximate latitude,longitude pair; null if either coordinate is missing."),
    ("latitude", "number", True, 37.422, "Approximate latitude in decimal degrees."),
    ("longitude", "number", True, -122.085, "Approximate longitude in decimal degrees."),
    ("postal", "string", True, "94043", "Postal code, where available."),
    ("timezone", "string", True, "America/Los_Angeles", "IANA time zone name."),
    ("weather_code", "string", True, "USCA0746", "Nearest weather station code supplied by the database."),
    ("asn", "integer", True, 15169, "Autonomous system number as a number, without AS prefix."),
    ("as_name", "string", True, "Google LLC", "Autonomous system organization name."),
    ("isp", "string", True, "Google LLC", "Internet service provider name."),
    ("org", "string", True, "Level 3", "Organization using the IP; separate from ASN and ISP."),
    ("connection_type", "string", True, "Corporate", "Network connection classification, such as Cable/DSL, Cellular, Corporate or Dialup."),
    ("user_type", "string", True, "hosting", "Network usage classification, such as business, residential, cellular or hosting."),
    ("is_anycast", "boolean", True, True, "Anycast classification; not a VPN or proxy detection flag."),
]
EXAMPLE = {name: sample for name, _, _, sample, _ in FIELDS}
ERRORS = {
    "400": ("invalid_ip", "Malformed, conflicting, non-public, or unsupported lookup input."),
    "404": ("ip_not_found", "No record in the active database."),
    "405": ("method_not_allowed", "Use GET for lookups."),
    "431": ("request_too_large", "Request headers exceed the configured limit."),
    "503": ("database_unavailable", "Database unavailable; retry later with backoff."),
    "504": ("timeout", "Request timed out; retry later with backoff."),
}

def openapi():
    props = {name: {"type": [kind, "null"] if nullable else kind, "description": desc, "examples": [value]} for name, kind, nullable, value, desc in FIELDS}
    def operation(op, path=False):
        params = [{"name":"ip", "in":"query", "required":False,"schema":{"type":"string"},"description":"Public IPv4 or IPv6 literal. Omit to detect caller. Must match path IP when both are supplied.","example":"8.8.8.8"}]
        if path:
            params.insert(0, {"name":"ip", "in":"path","required":True,"schema":{"type":"string"},"description":"Public IPv4 or IPv6 literal.","example":"8.8.8.8"})
        responses = {"200":{"description":"IP lookup result; missing attributes are null.","headers":{"Cache-Control":{"schema":{"type":"string"},"example":"no-store"}},"content":{"application/json":{"schema":{"$ref":"#/components/schemas/IpInfo"},"example":EXAMPLE}}}}
        for status,(code, desc) in ERRORS.items():
            responses[status] = {"description":desc,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/Error"},"example":{"error":{"code":code,"message":desc}}}}}
        return {"operationId":op,"summary":"Look up a supplied IP" if path else "Look up the caller or a supplied IP", "description":"Free, no API key. Caller detection returns the requesting machine or proxy exit, not necessarily the human user's IP.","security":[],"parameters":params,"responses":responses}
    myip = {
        "operationId": "getMyIp",
        "summary": "Return only the caller IP as plain text",
        "description": "Returns the normalized IPv4 or IPv6 address followed by a newline. Uses the same trusted-proxy and authenticated-ingress rules as /json. Query parameters are ignored. No database is required; local/private caller addresses are returned too. Errors use the standard JSON envelope.",
        "security": [],
        "responses": {
            "200": {
                "description": "Caller IP address followed by a newline; no JSON wrapper.",
                "headers": {"Cache-Control": {"schema": {"type": "string"}, "example": "no-store"}},
                "content": {"text/plain": {"schema": {"type": "string"}, "example": "8.8.8.8\n"}},
            },
            **{status: response for status, response in operation("lookupIp")["responses"].items() if status in ("400", "405", "431", "504")},
        },
    }
    myip["responses"]["400"]["description"] = "Unable to determine the caller IP, or invalid/missing trusted-ingress headers."
    return {"openapi":"3.1.0","info":{"title":"IP Info by Shifter","version":"1.0.0","description":"Free public IP geolocation and ASN API. Maintained and supported by Shifter. No signup or API key.","termsOfService":"https://ip-info.com/terms","contact":{"name":"Shifter","url":"https://shifter.io","email":"hi@shifter.io"}},"servers":[{"url":"https://ip-info.com"},{"url":"http://ip-info.com"}],"security":[],"paths":{"/myip":{"get":myip},"/json":{"get":operation("lookupIp")},"/{ip}/json":{"get":operation("lookupIpByPath",True)}},"components":{"schemas":{"IpInfo":{"type":"object","required":list(props),"additionalProperties":False,"properties":props},"Error":{"type":"object","required":["error"],"additionalProperties":False,"properties":{"error":{"type":"object","required":["code","message"],"additionalProperties":False,"properties":{"code":{"type":"string"},"message":{"type":"string"}}}}}}}}

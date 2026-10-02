LANGUAGES = {'curl':'cURL','javascript':'JavaScript / Node.js','python':'Python','php':'PHP','go':'Go','rust':'Rust','java':'Java','csharp':'C#','ruby':'Ruby'}
def example(language, mode):
    url = 'https://ip-info.com/json' + ('?ip=8.8.8.8' if mode == 'custom' else '')
    templates = {
      'curl': 'curl --fail --max-time 10 "URL"',
      'javascript': '''// Node.js 18+ or a modern browser
const response = await fetch("URL", {
  signal: AbortSignal.timeout(10000)
});
if (!response.ok) throw new Error(`HTTP ${response.status}`);
console.log(await response.json());''',
      'python': '''# Python 3; standard library only
import json
from urllib.request import urlopen

with urlopen("URL", timeout=10) as response:
    print(json.load(response))''',
      'php': '''<?php
$curl = curl_init('URL');
curl_setopt_array($curl, [CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 10, CURLOPT_FAILONERROR => true]);
$body = curl_exec($curl);
if ($body === false) { throw new RuntimeException(curl_error($curl)); }
curl_close($curl);
print_r(json_decode($body, true, 512, JSON_THROW_ON_ERROR));''',
      'go': '''package main

import ("encoding/json"; "fmt"; "net/http"; "time")

func main() {
    client := &http.Client{Timeout: 10 * time.Second}
    resp, err := client.Get("URL")
    if err != nil { panic(err) }
    defer resp.Body.Close()
    if resp.StatusCode != 200 { panic(resp.Status) }
    var data map[string]any
    if err := json.NewDecoder(resp.Body).Decode(&data); err != nil { panic(err) }
    fmt.Println(data)
}''',
      'rust': '''// Cargo.toml: reqwest = { version = "0.12", features = ["blocking", "json"] }
// serde_json = "1"
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10)).build()?;
    let data: serde_json::Value = client.get("URL")
        .send()?.error_for_status()?.json()?;
    println!("{data}");
    Ok(())
}''',
      'java': '''// Java 11+
import java.net.URI;
import java.net.http.*;
import java.time.Duration;

class Lookup {
    public static void main(String[] args) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("URL"))
            .timeout(Duration.ofSeconds(10)).GET().build();
        var response = HttpClient.newHttpClient()
            .send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) throw new RuntimeException("Lookup failed");
        System.out.println(response.body());
    }
}''',
      'csharp': '''// .NET 6+
using System;
using System.Net.Http;
using System.Text.Json;

using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
using var response = await client.GetAsync("URL");
response.EnsureSuccessStatusCode();
using var data = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
Console.WriteLine(data.RootElement);''',
      'ruby': '''require "net/http"
require "json"

uri = URI("URL")
response = Net::HTTP.start(uri.host, uri.port,
    use_ssl: uri.scheme == "https", open_timeout: 10, read_timeout: 10) do |http|
  http.get(uri.request_uri)
end
raise "HTTP #{response.code}" unless response.is_a?(Net::HTTPSuccess)
puts JSON.parse(response.body)'''
    }
    return templates[language].replace('URL',url)
EXAMPLES = {lang:{mode:example(lang,mode) for mode in ['self','custom']} for lang in LANGUAGES}

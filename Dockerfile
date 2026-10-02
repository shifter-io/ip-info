# syntax=docker/dockerfile:1
FROM rust:1.94-bookworm AS build
ARG TARGETARCH
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY web ./web
RUN --mount=type=cache,id=ip-info-registry,target=/usr/local/cargo/registry \
    --mount=type=cache,id=ip-info-target-${TARGETARCH},target=/app/target \
    cargo build --release --locked && cp /app/target/release/ip-info /ip-info

FROM debian:bookworm-slim AS database
WORKDIR /data
COPY data/dbip.mmdb ./dbip.mmdb
COPY data/source-manifest.json ./source-manifest.json
# Verify the local source checksum before the commercial file enters the image.
RUN expected=$(sed -n 's/.*"sha256": "\([a-f0-9]*\)".*/\1/p' source-manifest.json) && \
    test ${#expected} -eq 64 && echo "$expected  dbip.mmdb" | sha256sum -c - && chmod 0444 dbip.mmdb

FROM debian:bookworm-slim
RUN groupadd --gid 10001 ipinfo && useradd --uid 10001 --gid 10001 --no-create-home ipinfo
COPY --from=database /data /data
COPY --from=build /ip-info /usr/local/bin/ip-info
ENV BIND_ADDR=0.0.0.0:8080 MMDB_PATH=/data/dbip.mmdb SITE_INDEXABLE=false
USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/local/bin/ip-info"]

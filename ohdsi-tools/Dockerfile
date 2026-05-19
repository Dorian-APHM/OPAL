FROM rocker/r-ver:4.3.2

# Proxy passed at build-time via --build-arg (empty by default for clean networks).
# Behind a MITM corporate proxy (e.g. APHM), also set PROXY_CA_HOST so the CA can be extracted.
ARG HTTP_PROXY=
ARG HTTPS_PROXY=
ARG PROXY_CA_HOST=
ARG PROXY_CA_PORT=
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}

RUN apt-get update && apt-get install -y \
    libpq-dev libssl-dev libcurl4-openssl-dev libxml2-dev default-jdk \
    libfreetype6-dev libpng-dev libtiff5-dev libjpeg-dev libwebp-dev \
    libfontconfig1-dev libharfbuzz-dev libfribidi-dev \
    libpcre2-dev libbz2-dev zlib1g-dev liblzma-dev \
    pkg-config curl wget ca-certificates openssl \
    && apt-get clean && R CMD javareconf

# Optional MITM proxy CA extraction (only runs if PROXY_CA_HOST is set).
# Some corporate proxies intercept SSL — extract their CA from the proxy handshake
# and add it to the trust store so R/CRAN downloads work.
RUN if [ -n "$PROXY_CA_HOST" ] && [ -n "$PROXY_CA_PORT" ]; then \
      echo | openssl s_client -connect cloud.r-project.org:443 -proxy "${PROXY_CA_HOST}:${PROXY_CA_PORT}" -showcerts 2>/dev/null \
        | awk '/BEGIN CERTIFICATE/,/END CERTIFICATE/{print}' > /tmp/all_certs.pem && \
      csplit -z -f /tmp/cert_ /tmp/all_certs.pem '/BEGIN CERTIFICATE/' '{*}' 2>/dev/null && \
      cp "$(ls /tmp/cert_* | tail -1)" /usr/local/share/ca-certificates/proxy.crt && \
      update-ca-certificates && \
      rm -f /tmp/all_certs.pem /tmp/cert_* ; \
    fi

# CRAN: use a fast EU mirror + wget (libcurl can fail on big files through corporate proxies).
RUN echo 'options(repos = c(CRAN = "https://pbil.univ-lyon1.fr/CRAN"))' >> /usr/local/lib/R/etc/Rprofile.site && \
    echo 'options(download.file.method = "wget")' >> /usr/local/lib/R/etc/Rprofile.site && \
    echo 'options(timeout = 600)' >> /usr/local/lib/R/etc/Rprofile.site && \
    R -e "install.packages('remotes')" && \
    R -e "install.packages(c('rJava', 'systemfonts', 'data.table', 'RPostgres', 'officer'))"

# OHDSI packages vendored as tarballs (proxy-restricted networks can't reach GitHub).
COPY vendor/Achilles.tar.gz /tmp/
COPY vendor/DataQualityDashboard.tar.gz /tmp/
COPY vendor/CdmOnboarding.tar.gz /tmp/

# Achilles is pure R — extract directly into the library.
RUN tar xzf /tmp/Achilles.tar.gz -C /usr/local/lib/R/site-library/ && \
    R -e "remotes::install_local('/tmp/DataQualityDashboard.tar.gz')" && \
    R -e "remotes::install_local('/tmp/CdmOnboarding.tar.gz')" && \
    rm -f /tmp/*.tar.gz

WORKDIR /app

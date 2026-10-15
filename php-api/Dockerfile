FROM php:8.3.12-cli-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev \
    && docker-php-ext-install pdo pdo_pgsql \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 ccm \
    && mkdir -p /app /watched \
    && chown -R ccm:ccm /app /watched

WORKDIR /app
COPY autoload.php composer.json /app/
COPY src /app/src
COPY public /app/public
COPY tests /app/tests
USER ccm
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD php -r "exit(@file_get_contents('http://127.0.0.1:8080/health')===false?1:0);"
CMD ["php", "-S", "0.0.0.0:8080", "-t", "public"]

<?php
declare(strict_types=1);

use Ccm\App;
use Ccm\Auth;
use Ccm\PathPolicy;
use Ccm\PdoRepository;

$root = dirname(__DIR__);
if (is_file($root . '/vendor/autoload.php')) {
    require $root . '/vendor/autoload.php';
} else {
    require $root . '/autoload.php';
}

$pathOnly = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
if (($pathOnly === '/dashboard' || $pathOnly === '/dashboard.html') && ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'GET') {
    header('Content-Type: text/html; charset=utf-8');
    readfile(__DIR__ . '/dashboard.html');
    exit;
}

$dsn = getenv('DATABASE_URL') ?: 'pgsql:host=postgres;port=5432;dbname=ccm';
if (str_starts_with($dsn, 'postgresql://') || str_starts_with($dsn, 'postgres://')) {
    $parts = parse_url($dsn);
    $dsn = sprintf(
        'pgsql:host=%s;port=%s;dbname=%s',
        $parts['host'] ?? 'postgres',
        $parts['port'] ?? 5432,
        ltrim($parts['path'] ?? '/ccm', '/')
    );
    $user = $parts['user'] ?? getenv('POSTGRES_USER') ?: 'ccm';
    $pass = $parts['pass'] ?? getenv('POSTGRES_PASSWORD') ?: 'ccm';
} else {
    $user = getenv('POSTGRES_USER') ?: 'ccm';
    $pass = getenv('POSTGRES_PASSWORD') ?: 'ccm';
}

$pdo = new PDO($dsn, $user, $pass, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$allowlist = getenv('WATCH_ALLOWLIST') ?: '/watched';
$roots = array_filter(array_map('trim', explode(';', $allowlist)));
$app = new App(
    new PdoRepository($pdo),
    new Auth(getenv('API_KEYS') ?: '', (getenv('ALLOW_LOCAL_DEV_AUTH') ?: 'false') === 'true'),
    new PathPolicy($roots),
);

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$uri = $_SERVER['REQUEST_URI'] ?? '/';
$headers = [];
foreach ($_SERVER as $k => $v) {
    if (str_starts_with($k, 'HTTP_')) {
        $headers[str_replace('_', '-', strtolower(substr($k, 5)))] = $v;
    }
}
if (isset($_SERVER['CONTENT_TYPE'])) {
    $headers['content-type'] = $_SERVER['CONTENT_TYPE'];
}
$body = file_get_contents('php://input') ?: null;
$result = $app->handle($method, $uri, $headers, $body);
http_response_code($result['status']);
foreach ($result['headers'] as $name => $value) {
    header($name . ': ' . $value);
}
echo $result['body'];

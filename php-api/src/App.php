<?php
declare(strict_types=1);

namespace Ccm;

final class App
{
    private ?\Closure $queueProbe;
    private ?\Closure $workerProbe;

    public function __construct(
        private Repository $repo,
        private Auth $auth,
        private PathPolicy $paths,
        private string $serviceName = 'ccm-api',
        ?callable $queueProbe = null,
        ?callable $workerProbe = null,
    ) {
        $this->queueProbe = $queueProbe === null ? null : \Closure::fromCallable($queueProbe);
        $this->workerProbe = $workerProbe === null ? null : \Closure::fromCallable($workerProbe);
    }

    public function handle(string $method, string $uri, array $headers, ?string $body): array
    {
        $method = strtoupper($method);
        $path = parse_url($uri, PHP_URL_PATH) ?: '/';
        parse_str((string) parse_url($uri, PHP_URL_QUERY), $query);
        $headers = $this->normalizeHeaders($headers);
        try {
            if ($path === '/health' && $method === 'GET') {
                return $this->json(200, $this->health());
            }
            if ($path === '/metrics' && $method === 'GET') {
                return ['status' => 200, 'headers' => ['Content-Type' => 'text/plain'], 'body' => $this->metricsText()];
            }
            $auth = $this->auth->authenticate(
                $headers['x-api-key'] ?? null,
                $headers['x-tenant-id'] ?? null
            );
            return $this->dispatch($method, $path, $query, $headers, $body, $auth);
        } catch (UnauthorizedException $e) {
            return $this->error(401, 'unauthorized', $e->getMessage());
        } catch (ForbiddenException $e) {
            return $this->error(403, 'forbidden', $e->getMessage());
        } catch (\InvalidArgumentException $e) {
            return $this->error(400, 'validation_error', $e->getMessage());
        } catch (\Throwable $e) {
            return $this->error(500, 'internal_error', 'unexpected error');
        }
    }

    private function dispatch(string $method, string $path, array $query, array $headers, ?string $body, AuthContext $auth): array
    {
        if ($path === '/files' && $method === 'GET') {
            return $this->json(200, ['data' => $this->repo->listFiles($auth->tenantId)]);
        }
        if ($path === '/watch' && $method === 'POST') {
            $payload = $this->decode($body);
            if (empty($payload['path']) || !is_string($payload['path'])) {
                throw new \InvalidArgumentException('path is required');
            }
            $resolved = $this->paths->validate($payload['path']);
            $display = basename($resolved);
            $row = $this->repo->createFile($auth->tenantId, $resolved, $display);
            return $this->json(201, ['data' => $row]);
        }
        if (preg_match('#^/watch/([0-9a-fA-F-]{36})$#', $path, $m) && $method === 'DELETE') {
            $ok = $this->repo->deleteFile($auth->tenantId, $m[1]);
            if (!$ok) {
                return $this->error(404, 'not_found', 'monitored file not found');
            }
            return $this->json(200, ['deleted' => true, 'id' => $m[1]]);
        }
        if ($path === '/events' && $method === 'GET') {
            $limit = min(100, max(1, (int) ($query['limit'] ?? 20)));
            $offset = max(0, (int) ($query['offset'] ?? 0));
            $filters = [
                'file_id' => $query['file_id'] ?? $query['file'] ?? null,
                'operation' => $query['operation'] ?? null,
                'delivery_status' => $query['delivery_status'] ?? null,
                'from' => $query['from'] ?? null,
                'to' => $query['to'] ?? null,
            ];
            $data = $this->repo->listEvents($auth->tenantId, $filters, $limit, $offset);
            $total = $this->repo->countEvents($auth->tenantId, $filters);
            return $this->json(200, ['data' => $data, 'pagination' => ['limit' => $limit, 'offset' => $offset, 'total' => $total]]);
        }
        if (preg_match('#^/events/([0-9a-fA-F-]{36})$#', $path, $m) && $method === 'GET') {
            $event = $this->repo->getEvent($auth->tenantId, $m[1]);
            if (!$event) {
                return $this->error(404, 'not_found', 'event not found');
            }
            return $this->json(200, ['data' => $event]);
        }
        if (preg_match('#^/events/([0-9a-fA-F-]{36})/replay$#', $path, $m) && $method === 'POST') {
            if (!in_array($auth->role, ['admin', 'operator'], true)) {
                throw new ForbiddenException('replay not permitted');
            }
            $event = $this->repo->getEvent($auth->tenantId, $m[1]);
            if (!$event) {
                return $this->error(404, 'not_found', 'event not found');
            }
            $this->repo->enqueueReplay($auth->tenantId, $m[1], $auth->actor);
            return $this->json(202, ['replayed' => true, 'event_id' => $m[1]]);
        }
        if ($path === '/deliveries' && $method === 'GET') {
            $limit = min(100, max(1, (int) ($query['limit'] ?? 20)));
            $offset = max(0, (int) ($query['offset'] ?? 0));
            $data = $this->repo->listDeliveries($auth->tenantId, $query['event_id'] ?? null, $limit, $offset);
            return $this->json(200, ['data' => $data, 'pagination' => ['limit' => $limit, 'offset' => $offset]]);
        }
        if ($path === '/dead-letters' && $method === 'GET') {
            $limit = min(100, max(1, (int) ($query['limit'] ?? 20)));
            $offset = max(0, (int) ($query['offset'] ?? 0));
            return $this->json(200, ['data' => $this->repo->listDeadLetters($auth->tenantId, $limit, $offset)]);
        }
        if ($path === '/destinations' && $method === 'GET') {
            return $this->json(200, ['data' => $this->repo->listDestinations($auth->tenantId)]);
        }
        if ($path === '/status' && $method === 'GET') {
            return $this->json(200, ['data' => $this->repo->workerStatus(), 'tenant' => $auth->tenantId]);
        }
        return $this->error(404, 'not_found', 'unknown endpoint');
    }

    private function health(): array
    {
        try {
            $deps = $this->repo->health();
            $workers = $this->repo->workerStatus();
        } catch (\Throwable) {
            $deps = ['database' => false];
            $workers = [];
        }
        $active = 0;
        foreach ($workers['leases'] ?? [] as $lease) {
            if (!empty($lease['active'])) {
                $active++;
            }
        }
        $db = !empty($deps['database']);
        $queueOk = false;
        try {
            $queueOk = $this->queueProbe !== null
                ? (bool) ($this->queueProbe)()
                : $this->probeQueue();
        } catch (\Throwable) {
            $queueOk = false;
        }
        $queue = $queueOk ? 'ok' : 'error';
        $workerOk = false;
        try {
            $workerOk = $this->workerProbe !== null
                ? (bool) ($this->workerProbe)()
                : $this->probeWorker();
        } catch (\Throwable) {
            $workerOk = false;
        }
        $worker = $workerOk ? 'ok' : 'error';
        $healthy = $db && $queueOk && $workerOk;
        return [
            'status' => $healthy ? 'ok' : 'degraded',
            'service' => $this->serviceName,
            'dependencies' => [
                'database' => $db ? 'ok' : 'error',
                'queue' => $queue,
                'workers' => $worker,
            ],
            'active_leases' => $active,
        ];
    }

    private function probeQueue(): bool
    {
        $host = getenv('RABBITMQ_HOST') ?: 'rabbitmq';
        $port = (int) (getenv('RABBITMQ_MANAGEMENT_PORT') ?: 15672);
        $user = getenv('RABBITMQ_USER') ?: 'ccm';
        $password = getenv('RABBITMQ_PASSWORD') ?: '';
        $context = stream_context_create(['http' => [
            'method' => 'GET',
            'header' => 'Authorization: Basic ' . base64_encode($user . ':' . $password),
            'timeout' => 1.0,
            'ignore_errors' => true,
        ]]);
        $body = @file_get_contents("http://$host:$port/api/overview", false, $context);
        if ($body === false || !isset($http_response_header[0]) || !str_contains($http_response_header[0], ' 200 ')) {
            return false;
        }
        return is_array(json_decode($body, true));
    }

    private function probeWorker(): bool
    {
        $context = stream_context_create(['http' => ['timeout' => 1.0]]);
        $metrics = @file_get_contents('http://worker:9100/metrics', false, $context);
        if ($metrics === false) {
            return false;
        }
        foreach ([
            '/^ccm_worker_component_up\{component="outbox"\}\s+1(?:\.0)?$/m',
            '/^ccm_worker_component_up\{component="consumer"\}\s+1(?:\.0)?$/m',
            '/^ccm_rabbitmq_connected\s+1(?:\.0)?$/m',
            '/^ccm_rabbitmq_consumer_ready\s+1(?:\.0)?$/m',
        ] as $pattern) {
            if (!preg_match($pattern, $metrics)) {
                return false;
            }
        }
        return true;
    }

    private function metricsText(): string
    {
        return "# TYPE ccm_api_up gauge\nccm_api_up 1\n";
    }

    private function decode(?string $body): array
    {
        if ($body === null || $body === '') {
            return [];
        }
        $data = json_decode($body, true);
        if (!is_array($data)) {
            throw new \InvalidArgumentException('JSON body required');
        }
        return $data;
    }

    private function normalizeHeaders(array $headers): array
    {
        $out = [];
        foreach ($headers as $k => $v) {
            $out[strtolower((string) $k)] = is_array($v) ? ($v[0] ?? '') : (string) $v;
        }
        return $out;
    }

    private function json(int $status, array $payload): array
    {
        return [
            'status' => $status,
            'headers' => ['Content-Type' => 'application/json'],
            'body' => json_encode($payload, JSON_UNESCAPED_SLASHES),
        ];
    }

    private function error(int $status, string $code, string $message): array
    {
        return $this->json($status, ['error' => ['code' => $code, 'message' => $message]]);
    }
}

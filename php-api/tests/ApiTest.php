<?php
declare(strict_types=1);

namespace Ccm\Tests;

use Ccm\App;
use Ccm\Auth;
use Ccm\MemoryRepository;
use Ccm\PathPolicy;
use PHPUnit\Framework\TestCase;

final class ApiTest extends TestCase
{
    private string $root;
    private MemoryRepository $repo;
    private App $app;
    private bool $queueReachable = true;
    private bool $workerReachable = true;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/ccm-api-' . bin2hex(random_bytes(4));
        mkdir($this->root, 0777, true);
        file_put_contents($this->root . '/app.json', '{"a":1}');
        $this->repo = new MemoryRepository();
        $this->repo->workerState['leases'] = [['active' => true]];
        $this->app = new App(
            $this->repo,
            new Auth('admin-key:admin:default,tenant-a:operator:tenant-a,tenant-b:operator:tenant-b', false),
            new PathPolicy([$this->root]),
            queueProbe: fn (): bool => $this->queueReachable,
            workerProbe: fn (): bool => $this->workerReachable,
        );
    }

    protected function tearDown(): void
    {
        @unlink($this->root . '/app.json');
        @rmdir($this->root);
    }

    private function call(string $method, string $path, array $headers = [], ?array $json = null): array
    {
        $res = $this->app->handle($method, $path, $headers, $json ? json_encode($json) : null);
        $decoded = json_decode($res['body'], true);
        return [$res['status'], $decoded];
    }

    public function testHealthUnauthenticated(): void
    {
        [$status, $body] = $this->call('GET', '/health');
        $this->assertSame(200, $status);
        $this->assertSame('ok', $body['status']);
    }

    public function testHealthDegradesWhenQueueOrWorkerIsUnavailable(): void
    {
        $this->queueReachable = false;
        [$status, $body] = $this->call('GET', '/health');
        $this->assertSame(200, $status);
        $this->assertSame('degraded', $body['status']);
        $this->assertSame('error', $body['dependencies']['queue']);

        $this->queueReachable = true;
        $this->workerReachable = false;
        $this->repo->workerState['leases'] = [];
        [, $body] = $this->call('GET', '/health');
        $this->assertSame('degraded', $body['status']);
        $this->assertSame('error', $body['dependencies']['workers']);
    }

    public function testPdoRepositoryAutoloadsFromSharedRepositoryFile(): void
    {
        $this->assertTrue(class_exists(\Ccm\PdoRepository::class));
    }

    public function testAuthRequired(): void
    {
        [$status, $body] = $this->call('GET', '/files');
        $this->assertSame(401, $status);
        $this->assertSame('unauthorized', $body['error']['code']);
    }

    public function testWatchValidationAndAllowlist(): void
    {
        $h = ['x-api-key' => 'admin-key'];
        [$status] = $this->call('POST', '/watch', $h, []);
        $this->assertSame(400, $status);
        [$status] = $this->call('POST', '/watch', $h, ['path' => '/etc/passwd']);
        $this->assertSame(400, $status);
        [$status] = $this->call('POST', '/watch', $h, ['path' => $this->root . '/../x.json']);
        $this->assertSame(400, $status);
        [$status, $body] = $this->call('POST', '/watch', $h, ['path' => $this->root . '/app.json']);
        $this->assertSame(201, $status);
        $this->assertArrayHasKey('id', $body['data']);
        $id = $body['data']['id'];
        [$status, $files] = $this->call('GET', '/files', $h);
        $this->assertSame(200, $status);
        $this->assertCount(1, $files['data']);
        [$status] = $this->call('DELETE', '/watch/' . $id, $h);
        $this->assertSame(200, $status);
    }

    public function testEventPaginationAndFilters(): void
    {
        $this->repo->events = [
            ['id' => '11111111-1111-1111-1111-111111111111', 'tenant_id' => 'default', 'file_id' => 'f1', 'operation' => 'modified', 'delivery_status' => 'delivered', 'payload' => ['event_id' => '11111111-1111-1111-1111-111111111111']],
            ['id' => '22222222-2222-2222-2222-222222222222', 'tenant_id' => 'default', 'file_id' => 'f2', 'operation' => 'deleted', 'delivery_status' => 'failed', 'payload' => []],
            ['id' => '33333333-3333-3333-3333-333333333333', 'tenant_id' => 'tenant-a', 'file_id' => 'f3', 'operation' => 'modified', 'delivery_status' => 'delivered', 'payload' => []],
        ];
        $h = ['x-api-key' => 'admin-key'];
        [$status, $body] = $this->call('GET', '/events?limit=1&offset=0&operation=modified', $h);
        $this->assertSame(200, $status);
        $this->assertSame(1, count($body['data']));
        $this->assertSame(1, $body['pagination']['total']);
        [$status, $body] = $this->call('GET', '/events?delivery_status=failed', $h);
        $this->assertSame('failed', $body['data'][0]['delivery_status']);
    }

    public function testReplayAuthorizationAndTenantIsolation(): void
    {
        $this->repo->events[] = [
            'id' => 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            'tenant_id' => 'tenant-a',
            'file_id' => 'f1',
            'operation' => 'modified',
            'delivery_status' => 'dead_lettered',
            'payload' => ['event_id' => 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'],
        ];
        [$status] = $this->call('POST', '/events/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/replay', ['x-api-key' => 'tenant-b']);
        $this->assertSame(404, $status);
        [$status] = $this->call('POST', '/events/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/replay', ['x-api-key' => 'tenant-a']);
        $this->assertSame(202, $status);
        $this->assertCount(1, $this->repo->replays);
        [$status, $files] = $this->call('GET', '/files', ['x-api-key' => 'tenant-b']);
        $this->assertSame([], $files['data']);
    }

    public function testConsistentErrorShape(): void
    {
        [$status, $body] = $this->call('GET', '/nope', ['x-api-key' => 'admin-key']);
        $this->assertSame(404, $status);
        $this->assertSame('not_found', $body['error']['code']);
        $this->assertArrayHasKey('message', $body['error']);
    }
}

final class PathPolicyTest extends TestCase
{
    public function testRejectsRelativeAndBadExt(): void
    {
        $policy = new PathPolicy([sys_get_temp_dir()]);
        $this->expectException(\InvalidArgumentException::class);
        $policy->validate('relative.json');
    }
}

<?php
declare(strict_types=1);

namespace Ccm;

interface Repository
{
    public function health(): array;
    public function listFiles(string $tenantId): array;
    public function getFile(string $tenantId, string $id): ?array;
    public function createFile(string $tenantId, string $path, string $display): array;
    public function deleteFile(string $tenantId, string $id): bool;
    public function listEvents(string $tenantId, array $filters, int $limit, int $offset): array;
    public function countEvents(string $tenantId, array $filters): int;
    public function getEvent(string $tenantId, string $id): ?array;
    public function listDeliveries(string $tenantId, ?string $eventId, int $limit, int $offset): array;
    public function listDeadLetters(string $tenantId, int $limit, int $offset): array;
    public function listDestinations(string $tenantId): array;
    public function enqueueReplay(string $tenantId, string $eventId, string $actor): void;
    public function audit(string $tenantId, string $actor, string $action, string $target, array $meta = []): void;
    public function workerStatus(): array;
}

final class PdoRepository implements Repository
{
    public function __construct(private \PDO $pdo)
    {
        $this->pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
        $this->pdo->setAttribute(\PDO::ATTR_DEFAULT_FETCH_MODE, \PDO::FETCH_ASSOC);
    }

    public function health(): array
    {
        $ok = false;
        try {
            $this->pdo->query('SELECT 1');
            $ok = true;
        } catch (\Throwable) {
        }
        return ['database' => $ok];
    }

    public function listFiles(string $tenantId): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT f.id, f.path, f.display_name, f.enabled, f.last_scan_at, f.last_error, f.last_operation,
                    s.content_hash, s.valid AS snapshot_valid, s.updated_at AS snapshot_updated_at
             FROM monitored_files f
             LEFT JOIN file_snapshots s ON s.file_id = f.id
             WHERE f.tenant_id = :t
             ORDER BY f.created_at DESC'
        );
        $stmt->execute(['t' => $tenantId]);
        return $stmt->fetchAll();
    }

    public function getFile(string $tenantId, string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM monitored_files WHERE id = :id AND tenant_id = :t');
        $stmt->execute(['id' => $id, 't' => $tenantId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createFile(string $tenantId, string $path, string $display): array
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO monitored_files (tenant_id, path, display_name) VALUES (:t, :p, :d)
             RETURNING id, tenant_id, path, display_name, enabled, created_at'
        );
        $stmt->execute(['t' => $tenantId, 'p' => $path, 'd' => $display]);
        $row = $stmt->fetch();
        $this->audit($tenantId, 'api', 'watch.register', $row['id'], ['path' => $display]);
        return $row;
    }

    public function deleteFile(string $tenantId, string $id): bool
    {
        $stmt = $this->pdo->prepare('DELETE FROM monitored_files WHERE id = :id AND tenant_id = :t');
        $stmt->execute(['id' => $id, 't' => $tenantId]);
        $ok = $stmt->rowCount() > 0;
        if ($ok) {
            $this->audit($tenantId, 'api', 'watch.delete', $id);
        }
        return $ok;
    }

    public function listEvents(string $tenantId, array $filters, int $limit, int $offset): array
    {
        [$where, $params] = $this->eventWhere($tenantId, $filters);
        $sql = "SELECT id, tenant_id, file_id, operation, parse_status, delivery_status, schema_version,
                       correlation_id, created_at, payload
                FROM change_events $where
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off";
        $stmt = $this->pdo->prepare($sql);
        foreach ($params as $k => $v) {
            $stmt->bindValue($k, $v);
        }
        $stmt->bindValue(':lim', $limit, \PDO::PARAM_INT);
        $stmt->bindValue(':off', $offset, \PDO::PARAM_INT);
        $stmt->execute();
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['payload'] = json_decode((string) $row['payload'], true);
        }
        return $rows;
    }

    public function countEvents(string $tenantId, array $filters): int
    {
        [$where, $params] = $this->eventWhere($tenantId, $filters);
        $stmt = $this->pdo->prepare("SELECT COUNT(*) AS c FROM change_events $where");
        $stmt->execute($params);
        return (int) $stmt->fetch()['c'];
    }

    public function getEvent(string $tenantId, string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM change_events WHERE id = :id AND tenant_id = :t');
        $stmt->execute(['id' => $id, 't' => $tenantId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['payload'] = json_decode((string) $row['payload'], true);
        return $row;
    }

    public function listDeliveries(string $tenantId, ?string $eventId, int $limit, int $offset): array
    {
        $sql = 'SELECT id, event_id, destination_id, status, http_status, error, attempt, created_at
                FROM delivery_attempts WHERE tenant_id = :t';
        $params = ['t' => $tenantId];
        if ($eventId) {
            $sql .= ' AND event_id = :e';
            $params['e'] = $eventId;
        }
        $sql .= ' ORDER BY created_at DESC LIMIT :lim OFFSET :off';
        $stmt = $this->pdo->prepare($sql);
        foreach ($params as $k => $v) {
            $stmt->bindValue($k, $v);
        }
        $stmt->bindValue(':lim', $limit, \PDO::PARAM_INT);
        $stmt->bindValue(':off', $offset, \PDO::PARAM_INT);
        $stmt->execute();
        return $stmt->fetchAll();
    }

    public function listDeadLetters(string $tenantId, int $limit, int $offset): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT event_id, reason, created_at FROM dead_letter_events
             WHERE tenant_id = :t ORDER BY created_at DESC LIMIT :lim OFFSET :off'
        );
        $stmt->bindValue(':t', $tenantId);
        $stmt->bindValue(':lim', $limit, \PDO::PARAM_INT);
        $stmt->bindValue(':off', $offset, \PDO::PARAM_INT);
        $stmt->execute();
        return $stmt->fetchAll();
    }

    public function listDestinations(string $tenantId): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT id, url, enabled, auth_header_name, created_at FROM notification_destinations WHERE tenant_id = :t'
        );
        $stmt->execute(['t' => $tenantId]);
        return $stmt->fetchAll();
    }

    public function enqueueReplay(string $tenantId, string $eventId, string $actor): void
    {
        $event = $this->getEvent($tenantId, $eventId);
        if (!$event) {
            throw new \RuntimeException('event not found');
        }
        $payload = $event['payload'];
        $payload['_attempt'] = 1;
        $payload['correlation_id'] = $payload['correlation_id'] ?? $eventId;
        $this->pdo->beginTransaction();
        try {
            $ins = $this->pdo->prepare(
                'INSERT INTO outbox (id, event_id, tenant_id, payload, status, attempts, available_at, created_at)
                 VALUES (:id, :eid, :t, CAST(:p AS jsonb), \'pending\', 0, NOW(), NOW())'
            );
            $ins->execute([
                'id' => $this->uuid(),
                'eid' => $eventId,
                't' => $tenantId,
                'p' => json_encode($payload, JSON_THROW_ON_ERROR),
            ]);
            $this->pdo->prepare(
                "UPDATE change_events SET delivery_status = 'replaying', updated_at = NOW() WHERE id = :id AND tenant_id = :t"
            )->execute(['id' => $eventId, 't' => $tenantId]);
            $this->audit($tenantId, $actor, 'event.replay', $eventId);
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
    }

    public function audit(string $tenantId, string $actor, string $action, string $target, array $meta = []): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO audit_log (tenant_id, actor, action, target, metadata) VALUES (:t,:a,:ac,:tg, CAST(:m AS jsonb))'
        );
        $stmt->execute([
            't' => $tenantId,
            'a' => $actor,
            'ac' => $action,
            'tg' => $target,
            'm' => json_encode($meta, JSON_THROW_ON_ERROR),
        ]);
    }

    public function workerStatus(): array
    {
        $leases = $this->pdo->query(
            "SELECT directory, worker_id, expires_at, (expires_at > NOW()) AS active FROM watcher_leases"
        )->fetchAll();
        $outbox = $this->pdo->query(
            "SELECT status, COUNT(*) AS c FROM outbox GROUP BY status"
        )->fetchAll();
        return ['leases' => $leases, 'outbox' => $outbox];
    }

    private function eventWhere(string $tenantId, array $filters): array
    {
        $where = 'WHERE tenant_id = :t';
        $params = [':t' => $tenantId];
        if (!empty($filters['file_id'])) {
            $where .= ' AND file_id = :fid';
            $params[':fid'] = $filters['file_id'];
        }
        if (!empty($filters['operation'])) {
            $where .= ' AND operation = :op';
            $params[':op'] = $filters['operation'];
        }
        if (!empty($filters['delivery_status'])) {
            $where .= ' AND delivery_status = :ds';
            $params[':ds'] = $filters['delivery_status'];
        }
        if (!empty($filters['from'])) {
            $where .= ' AND created_at >= :from';
            $params[':from'] = $filters['from'];
        }
        if (!empty($filters['to'])) {
            $where .= ' AND created_at <= :to';
            $params[':to'] = $filters['to'];
        }
        return [$where, $params];
    }

    private function uuid(): string
    {
        $data = random_bytes(16);
        $data[6] = chr((ord($data[6]) & 0x0f) | 0x40);
        $data[8] = chr((ord($data[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
    }
}

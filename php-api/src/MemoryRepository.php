<?php
declare(strict_types=1);

namespace Ccm;

final class MemoryRepository implements Repository
{
    public array $files = [];
    public array $events = [];
    public array $deliveries = [];
    public array $dead = [];
    public array $destinations = [];
    public array $replays = [];
    public array $audits = [];
    public bool $dbOk = true;
    public array $workerState = ['leases' => [], 'outbox' => []];

    public function health(): array
    {
        return ['database' => $this->dbOk];
    }

    public function listFiles(string $tenantId): array
    {
        return array_values(array_filter($this->files, fn ($f) => $f['tenant_id'] === $tenantId));
    }

    public function getFile(string $tenantId, string $id): ?array
    {
        foreach ($this->files as $f) {
            if ($f['id'] === $id && $f['tenant_id'] === $tenantId) {
                return $f;
            }
        }
        return null;
    }

    public function createFile(string $tenantId, string $path, string $display): array
    {
        $row = [
            'id' => $this->uuid(),
            'tenant_id' => $tenantId,
            'path' => $path,
            'display_name' => $display,
            'enabled' => true,
            'created_at' => gmdate('c'),
            'last_scan_at' => null,
            'last_error' => null,
        ];
        $this->files[] = $row;
        $this->audit($tenantId, 'api', 'watch.register', $row['id']);
        return $row;
    }

    public function deleteFile(string $tenantId, string $id): bool
    {
        foreach ($this->files as $i => $f) {
            if ($f['id'] === $id && $f['tenant_id'] === $tenantId) {
                array_splice($this->files, $i, 1);
                $this->audit($tenantId, 'api', 'watch.delete', $id);
                return true;
            }
        }
        return false;
    }

    public function listEvents(string $tenantId, array $filters, int $limit, int $offset): array
    {
        $rows = array_values(array_filter($this->events, function ($e) use ($tenantId, $filters) {
            if ($e['tenant_id'] !== $tenantId) {
                return false;
            }
            if (!empty($filters['file_id']) && $e['file_id'] !== $filters['file_id']) {
                return false;
            }
            if (!empty($filters['operation']) && $e['operation'] !== $filters['operation']) {
                return false;
            }
            if (!empty($filters['delivery_status']) && $e['delivery_status'] !== $filters['delivery_status']) {
                return false;
            }
            return true;
        }));
        return array_slice($rows, $offset, $limit);
    }

    public function countEvents(string $tenantId, array $filters): int
    {
        return count($this->listEvents($tenantId, $filters, 100000, 0));
    }

    public function getEvent(string $tenantId, string $id): ?array
    {
        foreach ($this->events as $e) {
            if ($e['id'] === $id && $e['tenant_id'] === $tenantId) {
                return $e;
            }
        }
        return null;
    }

    public function listDeliveries(string $tenantId, ?string $eventId, int $limit, int $offset): array
    {
        $rows = array_values(array_filter($this->deliveries, function ($d) use ($tenantId, $eventId) {
            if ($d['tenant_id'] !== $tenantId) {
                return false;
            }
            if ($eventId && $d['event_id'] !== $eventId) {
                return false;
            }
            return true;
        }));
        return array_slice($rows, $offset, $limit);
    }

    public function listDeadLetters(string $tenantId, int $limit, int $offset): array
    {
        $rows = array_values(array_filter($this->dead, fn ($d) => $d['tenant_id'] === $tenantId));
        return array_slice($rows, $offset, $limit);
    }

    public function listDestinations(string $tenantId): array
    {
        return array_values(array_filter($this->destinations, fn ($d) => $d['tenant_id'] === $tenantId));
    }

    public function enqueueReplay(string $tenantId, string $eventId, string $actor): void
    {
        $event = $this->getEvent($tenantId, $eventId);
        if (!$event) {
            throw new \RuntimeException('event not found');
        }
        $this->replays[] = ['tenant_id' => $tenantId, 'event_id' => $eventId, 'actor' => $actor];
        $this->audit($tenantId, $actor, 'event.replay', $eventId);
    }

    public function audit(string $tenantId, string $actor, string $action, string $target, array $meta = []): void
    {
        $this->audits[] = compact('tenantId', 'actor', 'action', 'target', 'meta');
    }

    public function workerStatus(): array
    {
        return $this->workerState;
    }

    private function uuid(): string
    {
        return sprintf(
            '%04x%04x-%04x-%04x-%04x-%04x%04x%04x',
            random_int(0, 0xffff),
            random_int(0, 0xffff),
            random_int(0, 0xffff),
            random_int(0, 0x0fff) | 0x4000,
            random_int(0, 0x3fff) | 0x8000,
            random_int(0, 0xffff),
            random_int(0, 0xffff),
            random_int(0, 0xffff)
        );
    }
}

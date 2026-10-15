<?php
declare(strict_types=1);

namespace Ccm;

final class AuthContext
{
    public function __construct(
        public readonly string $actor,
        public readonly string $role,
        public readonly string $tenantId,
        public readonly bool $isAdmin,
    ) {
    }
}

final class Auth
{
    /** @var array<string, array{role:string,tenant:string}> */
    private array $keys;

    public function __construct(string $apiKeysCsv, private bool $allowLocalDev)
    {
        $this->keys = [];
        foreach (array_filter(explode(',', $apiKeysCsv)) as $item) {
            $parts = explode(':', trim($item));
            if (count($parts) >= 3) {
                $this->keys[$parts[0]] = ['role' => $parts[1], 'tenant' => $parts[2]];
            }
        }
    }

    public function authenticate(?string $apiKey, ?string $tenantOverride): AuthContext
    {
        if ($apiKey && isset($this->keys[$apiKey])) {
            $meta = $this->keys[$apiKey];
            $isAdmin = $meta['role'] === 'admin';
            $tenant = $isAdmin && $tenantOverride ? $tenantOverride : $meta['tenant'];
            return new AuthContext($apiKey, $meta['role'], $tenant, $isAdmin);
        }
        if ($this->allowLocalDev && ($apiKey === null || $apiKey === '')) {
            return new AuthContext('local-dev', 'admin', $tenantOverride ?: 'default', true);
        }
        throw new UnauthorizedException('authentication required');
    }
}

class UnauthorizedException extends \RuntimeException
{
}

class ForbiddenException extends \RuntimeException
{
}

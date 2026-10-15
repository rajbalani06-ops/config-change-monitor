<?php
declare(strict_types=1);

namespace Ccm;

final class PathPolicy
{
    public const EXTENSIONS = ['.env', '.json', '.yaml', '.yml', '.properties'];

    /** @param list<string> $roots */
    public function __construct(private array $roots)
    {
        if ($this->roots === []) {
            throw new \InvalidArgumentException('allowlist is required');
        }
        $this->roots = array_map(fn ($r) => $this->canonical($r), $this->roots);
    }

    public function validate(string $path): string
    {
        if ($path === '' || $path !== trim($path) || str_contains($path, "\0")) {
            throw new \InvalidArgumentException('invalid path');
        }
        if (!$this->isAbsolute($path)) {
            throw new \InvalidArgumentException('path must be absolute');
        }
        if (str_contains($path, '..')) {
            throw new \InvalidArgumentException('path traversal is not allowed');
        }
        $resolved = $this->canonical($path);
        $this->assertInside($resolved);
        $name = basename($resolved);
        $ext = strtolower(pathinfo($resolved, PATHINFO_EXTENSION));
        $suffix = $name === '.env' ? '.env' : ('.' . $ext);
        if (!in_array($suffix, self::EXTENSIONS, true)) {
            throw new \InvalidArgumentException('unsupported file extension');
        }
        return $resolved;
    }

    private function isAbsolute(string $path): bool
    {
        return str_starts_with($path, '/') || (bool) preg_match('/^[A-Za-z]:[\\\\\\/]/', $path);
    }

    private function canonical(string $path): string
    {
        $normalized = str_replace('\\', '/', $path);
        $real = realpath($normalized);
        if ($real !== false) {
            return str_replace('\\', '/', $real);
        }

        // realpath() fails for a new file. Resolve its nearest existing parent
        // so a symlinked directory cannot make an outside path appear allowlisted.
        $suffix = [];
        $parent = $normalized;
        while (!file_exists($parent) && !is_link($parent)) {
            $leaf = basename($parent);
            if ($leaf !== '' && $leaf !== '.' && $leaf !== '/') {
                array_unshift($suffix, $leaf);
            }
            $next = dirname($parent);
            if ($next === $parent) {
                return $normalized;
            }
            $parent = $next;
        }
        $resolvedParent = realpath($parent);
        if ($resolvedParent === false) {
            return $normalized;
        }
        return rtrim(str_replace('\\', '/', $resolvedParent), '/') . '/' . implode('/', $suffix);
    }

    private function assertInside(string $resolved): void
    {
        foreach ($this->roots as $root) {
            $root = rtrim($root, '/');
            if ($resolved === $root || str_starts_with($resolved, $root . '/')) {
                return;
            }
        }
        throw new \InvalidArgumentException('path is outside allowlisted directories');
    }
}

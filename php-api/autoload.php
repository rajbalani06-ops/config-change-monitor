<?php
declare(strict_types=1);

spl_autoload_register(static function (string $class): void {
    $prefix = 'Ccm\\';
    if (!str_starts_with($class, $prefix)) {
        return;
    }
    $rel = str_replace('\\', '/', substr($class, strlen($prefix)));
    $file = __DIR__ . '/src/' . $rel . '.php';
    if (is_file($file)) {
        require $file;
        return;
    }

    // These related classes intentionally share files; keep the lightweight
    // autoloader aligned with Composer's classmap for those declarations.
    $sharedFiles = [
        'PdoRepository' => 'Repository.php',
        'AuthContext' => 'Auth.php',
        'UnauthorizedException' => 'Auth.php',
        'ForbiddenException' => 'Auth.php',
    ];
    if (isset($sharedFiles[$rel])) {
        require_once __DIR__ . '/src/' . $sharedFiles[$rel];
    }
});

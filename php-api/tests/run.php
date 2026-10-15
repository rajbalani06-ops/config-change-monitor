<?php
declare(strict_types=1);

require dirname(__DIR__) . '/autoload.php';

$phpunit = dirname(__DIR__) . '/vendor/bin/phpunit';
if (is_file($phpunit)) {
    passthru(PHP_BINARY . ' ' . escapeshellarg($phpunit), $code);
    exit($code);
}

fwrite(STDERR, "phpunit not installed; running built-in runner\n");
require __DIR__ . '/phpunit_stub.php';
require __DIR__ . '/ApiTest.php';

function assert_true($cond, string $msg): void
{
    if (!$cond) {
        throw new RuntimeException($msg);
    }
}

$classes = [Ccm\Tests\ApiTest::class, Ccm\Tests\PathPolicyTest::class];
$failed = 0;
$passed = 0;
foreach ($classes as $class) {
    $ref = new ReflectionClass($class);
    foreach ($ref->getMethods(ReflectionMethod::IS_PUBLIC) as $method) {
        if (!str_starts_with($method->getName(), 'test')) {
            continue;
        }
        $test = $ref->newInstance($method->getName());
        $setup = $ref->getMethod('setUp');
        $setup->setAccessible(true);
        $teardown = $ref->getMethod('tearDown');
        $teardown->setAccessible(true);
        $error = null;
        try {
            $setup->invoke($test);
            $method->invoke($test);
            $expected = $test->expectedException();
            if ($expected !== null) {
                $error = new RuntimeException("Expected exception $expected was not thrown");
            }
        } catch (Throwable $e) {
            $actual = $e instanceof ReflectionException && $e->getPrevious() ? $e->getPrevious() : $e;
            $expected = $test->expectedException();
            if ($expected === null || !$actual instanceof $expected) {
                $error = $actual;
            }
        } finally {
            try {
                $teardown->invoke($test);
            } catch (Throwable $e) {
                $error ??= $e;
            }
        }
        if ($error === null) {
            $passed++;
            echo "PASS {$method->getName()}\n";
        } else {
            $failed++;
            echo "FAIL {$method->getName()}: " . $error->getMessage() . "\n";
        }
    }
}
echo "Results: $passed passed, $failed failed\n";
exit($failed === 0 ? 0 : 1);

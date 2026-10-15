<?php
declare(strict_types=1);

namespace PHPUnit\Framework;

class TestCase
{
    private ?string $expectedExceptionClass = null;

    public function __construct(string $name = "")
    {
    }

    protected function setUp(): void
    {
    }

    protected function tearDown(): void
    {
    }

    public static function assertSame($expected, $actual, string $message = ""): void
    {
        if ($expected !== $actual) {
            throw new \RuntimeException($message ?: "Failed asserting that " . var_export($actual, true) . " is identical to " . var_export($expected, true));
        }
    }

    public static function assertTrue(bool $actual, string $message = ""): void
    {
        if (!$actual) {
            throw new \RuntimeException($message ?: "Failed asserting that value is true");
        }
    }

    public static function assertCount(int $expected, $actual, string $message = ""): void
    {
        if (count($actual) !== $expected) {
            throw new \RuntimeException($message ?: "Failed asserting count $expected");
        }
    }

    public static function assertArrayHasKey($key, array $array, string $message = ""): void
    {
        if (!array_key_exists($key, $array)) {
            throw new \RuntimeException($message ?: "Missing key $key");
        }
    }

    public function expectException(string $class): void
    {
        $this->expectedExceptionClass = $class;
    }

    public function expectedException(): ?string
    {
        return $this->expectedExceptionClass;
    }
}

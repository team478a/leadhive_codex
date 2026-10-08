<?php
// CLI transport into this container's own Apache, never an arbitrary destination.
if (PHP_SAPI !== 'cli' || getenv('LEADHIVE_CF7_LAB') !== '1') { exit(2); }
$request = stream_get_contents(STDIN, 128001);
if (strlen($request) > 128000) { exit(3); }
$socket = fsockopen('127.0.0.1', 80, $errno, $message, 5);
if (!$socket) { exit(4); }
stream_set_timeout($socket, 10);
$offset = 0;
while ($offset < strlen($request)) {
    $written = fwrite($socket, substr($request, $offset));
    if (!$written) { fclose($socket); exit(5); }
    $offset += $written;
}
$response = stream_get_contents($socket, 2000001);
$metadata = stream_get_meta_data($socket);
fclose($socket);
if (strlen($response) > 2000000 || $metadata['timed_out']) { exit(6); }
fwrite(STDOUT, $response);

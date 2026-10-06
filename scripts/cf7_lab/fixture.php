<?php
// CLI only. No public control endpoint and no credentials in output.
if (PHP_SAPI !== 'cli' || getenv('LEADHIVE_CF7_LAB') !== '1') {
    exit(2);
}
$_SERVER['HTTP_HOST'] = '127.0.0.1';
if (($argv[1] ?? '') === 'install') {
    define('WP_INSTALLING', true);
}
require '/var/www/html/wp-load.php';
require_once ABSPATH . 'wp-admin/includes/upgrade.php';
require_once ABSPATH . 'wp-admin/includes/plugin.php';
$lab_action = $argv[1] ?? '';
if ($lab_action === 'install') {
    if (!is_blog_installed()) {
        wp_install('LeadHive isolated CF7 lab', 'lab_admin', 'lab-admin@example.invalid',
            false, '', bin2hex(random_bytes(32)));
    }
    update_option('blog_public', '0');
    update_option('home', getenv('LAB_ORIGIN'));
    update_option('siteurl', getenv('LAB_ORIGIN'));
    update_option('permalink_structure', '/%postname%/');
    $error = activate_plugin('contact-form-7/wp-contact-form-7.php');
    if (is_wp_error($error)) {
        throw new RuntimeException('CF7 activation failed');
    }
    flush_rewrite_rules(true);
    echo "installed\n";
    exit;
}
if (!defined('WPCF7_VERSION') || WPCF7_VERSION !== '6.1.4') {
    throw new RuntimeException('Unexpected CF7 source version');
}
if ($lab_action === 'create') {
    $forms = array();
    foreach (array('standard', 'optional', 'invert', 'demo') as $kind) {
        $form = WPCF7_ContactForm::get_template(array('title' => 'Lab ' . $kind));
        $options = $kind === 'optional' ? ' optional' : ($kind === 'invert' ? ' invert' : '');
        $props = $form->get_properties();
        $props['form'] = '<label>Name [text* your-name]</label>' . "\n"
            . '<label>Email [email* your-email]</label>' . "\n"
            . '<label>Message [textarea* your-message]</label>' . "\n"
            . '[acceptance consent' . $options . ']Lab-only privacy terms[/acceptance]' . "\n"
            . '[submit "Send lab fixture"]';
        $props['mail']['recipient'] = 'sink@example.invalid';
        $props['mail']['sender'] = 'Lab <sender@example.invalid>';
        $props['mail']['subject'] = 'LeadHive isolated fixture';
        $props['mail']['body'] = '[your-name]' . "\n" . '[your-email]' . "\n" . '[your-message]';
        $props['mail_2']['active'] = false;
        $props['additional_settings'] = $kind === 'demo' ? 'demo_mode: on' : '';
        $form->set_properties($props);
        $form->save();
        $forms[$kind] = $form->id();
    }
    $content = '';
    foreach ($forms as $id) {
        $content .= '[contact-form-7 id="' . $id . '"]' . "\n";
    }
    $page = wp_insert_post(array('post_type' => 'page', 'post_status' => 'publish',
        'post_title' => 'Lab contact forms', 'post_content' => $content));
    echo json_encode(array('forms' => $forms, 'page_id' => $page,
        'page_url' => get_permalink($page),
        'wp_version' => get_bloginfo('version'), 'cf7_version' => WPCF7_VERSION,
        'php_version' => PHP_VERSION)) . "\n";
} elseif ($lab_action === 'mode') {
    $mode = $argv[2] ?? '';
    if (!in_array($mode, array('capture', 'fail', 'skip', 'abort', 'spam'), true)) {
        exit(3);
    }
    update_option('leadhive_lab_mode', $mode, false);
    echo "mode set\n";
} elseif ($lab_action === 'query-root') {
    update_option('permalink_structure', '');
    flush_rewrite_rules(true);
    echo "query root enabled\n";
} elseif ($lab_action === 'evidence') {
    echo json_encode(array('mail_calls' => get_option('leadhive_lab_mail', array()),
        'submissions' => get_option('leadhive_lab_submissions', array()))) . "\n";
} elseif ($lab_action === 'isolation') {
    $request = wp_remote_get('https://example.invalid/');
    // Direct numeric socket tests cannot succeed due to Docker internal network.
    $targets = array(array('1.1.1.1', 443), array('8.8.8.8', 25), array('8.8.8.8', 587));
    $results = array();
    foreach ($targets as $target) {
        $socket = @fsockopen($target[0], $target[1], $error, $message, 1);
        $results[] = $socket === false;
        if ($socket) { fclose($socket); }
    }
    echo json_encode(array('wp_http_blocked' => is_wp_error($request)
        && $request->get_error_code() === 'lab_network_blocked',
        'external_socket_blocked' => $results)) . "\n";
} else {
    exit(4);
}

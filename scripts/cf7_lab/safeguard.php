<?php
/** Lab-only MU plugin: capture mail, block WP HTTP; never deploy with LeadHive. */
if (getenv('LEADHIVE_CF7_LAB') !== '1') {
    throw new RuntimeException('Explicit lab opt-in required');
}
add_filter('pre_http_request', static function () {
    return new WP_Error('lab_network_blocked', 'External WordPress HTTP is disabled');
}, PHP_INT_MAX);
add_filter('pre_wp_mail', static function ($return, $atts) {
    $records = get_option('leadhive_lab_mail', array());
    $records[] = array(
        'subject_sha256' => hash('sha256', $atts['subject']),
        'body_sha256' => hash('sha256', $atts['message']),
        'recipient_count' => count((array) $atts['to']),
    );
    update_option('leadhive_lab_mail', $records, false);
    return get_option('leadhive_lab_mode', 'capture') !== 'fail';
}, PHP_INT_MAX, 2);
// Defense in depth: no PHPMailer/sendmail execution even if capture fails.
add_action('phpmailer_init', static function () {
    throw new RuntimeException('Actual mail transport forbidden in lab');
}, PHP_INT_MAX);
add_filter('wpcf7_skip_mail', static function ($skip) {
    return $skip || get_option('leadhive_lab_mode') === 'skip';
});
add_filter('wpcf7_spam', static function ($spam) {
    return $spam || get_option('leadhive_lab_mode') === 'spam';
});
add_action('wpcf7_before_send_mail', static function ($form, &$abort) {
    if (get_option('leadhive_lab_mode') === 'abort') {
        $abort = true;
    }
}, 10, 2);
add_action('wpcf7_submit', static function ($form, $result) {
    $records = get_option('leadhive_lab_submissions', array());
    $records[] = array('form_id' => $form->id(), 'status' => $result['status']);
    update_option('leadhive_lab_submissions', $records, false);
}, 10, 2);

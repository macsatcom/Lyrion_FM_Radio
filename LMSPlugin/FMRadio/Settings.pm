package Plugins::FMRadio::Settings;

use strict;
use base qw(Slim::Web::Settings);

use Slim::Utils::Strings qw(string);
use Slim::Utils::Prefs;

my $prefs = preferences('plugin.fmradio');

sub name {
    return Slim::Web::HTTP::CSRF->protectName('PLUGIN_FMRADIO_MODULE_NAME');
}

sub page {
    return Slim::Web::HTTP::CSRF->protectURI('plugins/FMRadio/settings/basic.html');
}

sub prefs {
    return ($prefs, qw(daemon_url icecast_url stations));
}

sub handler {
    my ($class, $client, $params) = @_;

    if ($params->{'saveSettings'}) {
        $prefs->set('daemon_url',  $params->{daemon_url});
        $prefs->set('icecast_url', $params->{icecast_url});
        $prefs->set('stations',    $params->{stations});
    }

    $params->{daemon_url}  = $prefs->get('daemon_url');
    $params->{icecast_url} = $prefs->get('icecast_url');
    $params->{stations}    = $prefs->get('stations');

    return $class->SUPER::handler($client, $params);
}

1;

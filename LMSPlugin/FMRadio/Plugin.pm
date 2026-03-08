package Plugins::FMRadio::Plugin;

use strict;

use vars qw($VERSION);
use base qw(Slim::Plugin::OPMLBased);

use Plugins::FMRadio::Settings;

use Slim::Utils::Log;
use Slim::Utils::Prefs;
use Slim::Utils::Strings qw(string);

$VERSION = "1.0";

my $log = Slim::Utils::Log->addLogCategory({
    'category'     => 'plugin.fmradio',
    'defaultLevel' => 'WARN',
    'description'  => 'FM Radio Plugin',
});

my $prefs = preferences('plugin.fmradio');

my $DEFAULT_STATIONS = <<'END';
DR P1|90.8
DR P3|93.9
DR P4 København|96.5
NOVA|91.4
The Voice|96.1
Pop FM|97.2
Radio 100|100.0
myROCK|103.6
Radio4|102.3
Kanal Gladsaxe|100.9
END

$prefs->init({
    daemon_url  => 'http://your-daemon-host:8080',  # <-- set in LMS plugin settings
    icecast_url => 'http://your-icecast-host:8000/fm', # <-- set in LMS plugin settings
    stations    => $DEFAULT_STATIONS,
});

sub initPlugin {
    my $class = shift;

    Plugins::FMRadio::Settings->new();

    $class->SUPER::initPlugin(
        feed   => \&handleFeed,
        tag    => 'fmradio',
        menu   => 'radios',
        weight => 10,
    );
}

sub getDisplayName {
    return 'PLUGIN_FMRADIO_MODULE_NAME';
}

sub handleFeed {
    my ($client, $cb, $args) = @_;

    my $daemonUrl = $prefs->get('daemon_url');
    my @items;

    my $stationsText = $prefs->get('stations') || $DEFAULT_STATIONS;

    for my $line (split /\n/, $stationsText) {
        $line =~ s/^\s+|\s+$//g;
        next unless $line =~ /^(.+)\|(\d+(?:\.\d+)?)$/;
        my ($name, $freq_mhz) = ($1, $2 + 0);
        push @items, {
            name => sprintf("%s (%.1f MHz)", $name, $freq_mhz),
            type => 'audio',
            url  => sprintf("%s/listen/%.1f", $daemonUrl, $freq_mhz),
        };
    }

    push @items, { name => string('PLUGIN_FMRADIO_NO_STATIONS'), type => 'text' }
        unless @items;

    $cb->({ items => \@items });
}

1;

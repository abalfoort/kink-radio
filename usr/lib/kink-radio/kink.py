#! /usr/bin/env python3

"""_summary_
    show notification what song Kink is playing.

    Files:        $HOME/.kink-radio
    References:
    i18n:         http://docs.python.org/3/library/gettext.html
    notify:       https://lazka.github.io/pgi-docs/#Notify-0.7
    appindicator: https://lazka.github.io/pgi-docs/#AyatanaAppIndicator3-0.1
    requests:     https://requests.readthedocs.io/en/latest
    vlc:          https://www.olivieraubert.net/vlc/python-ctypes/doc/
    Author:       Arjen Balfoort, 17-06-2025
"""

import gettext
import os
import subprocess
import json
from enum import Enum
from shutil import copyfile
from pathlib import Path
from configparser import ConfigParser
from os.path import abspath, dirname, join, exists
from threading import Event, Thread
from utils import str_int, str_bool

import vlc
import requests
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Notify', '0.7')
from gi.repository import Gtk, Notify
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import AyatanaAppIndicator3 as AppIndicator3

APP_ID = 'kink-radio'
APP_NAME = 'ꓘINK Radio'
_ = gettext.translation(APP_ID, fallback=True).gettext

class MenuIcons(Enum):
    """ Enum with icon names or paths """
    PLAY = 'media-playback-start'
    STOP = 'media-playback-stop'
    SELECT = 'dialog-ok-apply'


class KinkRadio():
    """ Connect to Kink radio and show info in system tray. """
    def __init__(self):
        # Initiate variables
        self.scriptdir = abspath(dirname(__file__))
        self.home = str(Path.home())
        self.local = join(self.home, f".{APP_ID}")
        self.playlist = join(self.local, f"{APP_ID}.txt")
        self.default_settings = join(self.scriptdir, 'settings.ini')
        self.settings = join(self.local, 'settings.ini')
        self.tmp_thumb = join(self.local, 'album_art.jpg')
        self.grey_icon = join(self.scriptdir, f"{APP_ID}-grey.svg")
        self.instance = vlc.Instance('--intf dummy')
        self.list_player = self.instance.media_list_player_new()
        self.cur_playing = {'station': '', 'program': '',
                            'artist': '','title': '', 'album_art': ''}
        # Use dict to negate the mutability of self.cur_playing
        self.prev_playing = dict(self.cur_playing)

        # to keep comments, you have to trick configparser into believing that
        # lines starting with ";" are not comments, but they are keys without a value.
        # Set comment_prefixes to a string which you will not use in the config file
        self.conf_parser = ConfigParser(comment_prefixes='/', allow_no_value=True)

        # Create local directory
        os.makedirs(self.local, exist_ok=True)
        # Create conf file if it does not already exist
        if not exists(self.settings):
            copyfile(self.default_settings, self.settings)

        # Read the default and user ini into dictionaries
        self.kink_dict = self.read_ini(self.settings)
        self.kink_dict_default = self.read_ini(self.default_settings)

        # Save settings in variables
        self.wait = max(str_int(self.key_value('wait')), 1)

        # Create event to use when thread is done
        self.check_done_event = Event()
        # Create global indicator object
        self.indicator = AppIndicator3.Indicator.new(APP_ID,
                                                     APP_ID,
                                                     AppIndicator3.IndicatorCategory.OTHER)
        self.indicator.set_title(APP_NAME)
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self._build_menu())

        # Init notifier
        Notify.init(APP_NAME)

        # Reset log
        if exists(self.playlist):
            os.remove(self.playlist)

        # Load the configured playlist
        self._add_playlist()
        if str_bool(self.key_value('autoplay')):
            self.play_kink()
        else:
            self.stop_kink()

        # Start thread to check for connection changes
        Thread(target=self._run_check).start()

    def _run_check(self):
        """ Poll Kink for currently playing song. """
        was_connected = True

        while not self.check_done_event.is_set():
            # Check if kink server is online
            if not self._is_connected():
                # Show lost connection message
                if was_connected:
                    self.indicator.set_menu(self._build_menu())
                    self.indicator.set_icon_full(self.grey_icon, '')
                    unable_string = _('Unable to connect to:')
                    self.show_notification(summary=f"{unable_string} {self.key_value('station')}",
                                           thumb=APP_ID)
                    was_connected = False
            else:
                # In case we had lost our connection
                if not was_connected:
                    # Build menu and show normal icon
                    self.indicator.set_menu(self._build_menu())
                    self.indicator.set_icon_full(APP_ID, '')
                    was_connected = True

                # Check if there is new playing data
                self._fill_cur_playing()
                if self.cur_playing != self.prev_playing:
                    # Get album art
                    self._save_thumb(self.cur_playing['album_art'])

                    # Send notification
                    self.show_song_info()

                    # Keep a simple log
                    playing = (f"{self.key_value('station')}: "
                               f"{self.cur_playing['artist']} - {self.cur_playing['title']}")
                    print((playing))
                    with open(file=self.playlist, mode='a', encoding='utf-8') as log:
                        log.write(f"{playing}\n")

                    # Save playing data for the next loop
                    self.prev_playing = dict(self.cur_playing)

            # Wait until we continue with the loop
            self.check_done_event.wait(self.wait)

    # ===============================================
    # Kink functions
    # ===============================================

    def show_song_info(self):
        """ Show song information in notification. """
        if self.cur_playing and \
           str_int(self.key_value('notification_timeout')) > 0:
            # Show notification
            artist = _('Artist')
            title = _('Title')
            self.show_notification(summary=f"{self.key_value('station')}: "
                                           f"{self.cur_playing['program']}",
                                   body=(f"<b>{artist}</b>: {self.cur_playing['artist']}\n"
                                         f"<b>{title}</b>: {self.cur_playing['title']}"),
                                   thumb=self.tmp_thumb)

    def _save_thumb(self, url):
        """Retrieve image data from url and save to path

        Args:
            url (str): image url
        """
        if not url:
            if exists(self.tmp_thumb):
                os.remove(self.tmp_thumb)
            return
        res = requests.get(url, timeout=self.wait)
        if res.status_code == 200:
            with open(file=self.tmp_thumb, mode='wb') as file:
                file.write(res.content)

    def _json_request(self):
        """Get json data from KINK.

        Returns:
            json: now playing data from KINK
        """
        res = requests.get(self.key_value('json'), timeout=self.wait)
        if res.status_code == 200:
            return json.loads(res.text)
        return None

    def get_stations(self):
        """Get lists of Kink stations

        Returns:
            list: list with available KINK stations
        """
        obj = self._json_request()
        if obj:
            s_dict = obj['stations']
        else:
            return []
        stations = list(s_dict.keys())
        stations.sort()

        return stations

    def switch_station(self, key, value):
        """Switch KINK station.

        Args:
            station (str): KINK station name
        """
        if key != 'station' or value == self.key_value('station'):
            return
        self.save_key('station', value)
        print((f"Switch station: {self.key_value('station')}"))

        was_playing = False
        if self.list_player.is_playing():
            self.stop_kink()
            was_playing = True
        self._add_playlist()
        if was_playing:
            self.play_kink()

        self.indicator.set_menu(self._build_menu())

    def _fill_cur_playing(self):
        """Get what's playing data from Kink."""
        obj = self._json_request()
        program = ''
        artist = ''
        title = ''
        album_art = ''
        if obj:
            try:
                artist = obj['extended'][self.key_value('station')]['artist']
            except Exception:
                pass
            try:
                title = obj['extended'][self.key_value('station')]['title']
            except Exception:
                pass
            try:
                album_art = obj['extended'][self.key_value('station')]['album_art']['320']
            except Exception:
                pass
            try:
                program = obj['extended'][self.key_value('station')]['program']['title']
            except Exception:
                pass

        self.cur_playing['station'] = self.key_value('station')
        self.cur_playing['program'] = program
        self.cur_playing['artist'] = artist
        self.cur_playing['title'] = title
        self.cur_playing['album_art'] = album_art

    def _is_connected(self):
        """Check if Kink is online.

        Returns:
            bool: able to connect to KINK or not
        """
        res = requests.get(self.key_value('json'), timeout=self.wait)
        if res.status_code == 200:
            return True
        return False

    def _get_pls(self):
        """Get the station playlist url

        Returns:
            str: play list url for current station
        """
        if self.key_value('station') == 'kink':
            return self.key_value('stream_kink')
        if 'dna' in self.key_value('station'):
            return self.key_value('stream_dna')
        if 'distortion' in self.key_value('station'):
            return self.key_value('stream_distortion')
        return self.key_value('stream_indie')

    def _add_playlist(self):
        """ Add playlist to VLC """
        url = self._get_pls()
        print((f"Playlist: {url}"))
        media_list = self.instance.media_list_new()
        media_list.add_media(url)
        self.list_player.set_media_list(media_list)

    def play_kink(self):
        """ Play playlist """
        self.list_player.play()
        self.indicator.set_menu(self._build_menu())

    def stop_kink(self):
        """ Stop playlist """
        self.list_player.stop()
        self.indicator.set_menu(self._build_menu())

    # ===============================================
    # System Tray Icon
    # ===============================================
    def _get_image(self, icon):
        """Get GtkImage from icon name or path

        Args:
            icon (string): icon path

        Returns:
            Gtk.Image: image binary from path
        """
        if not icon:
            return None
        if exists(icon):
            img = Gtk.Image.new_from_file(icon, Gtk.IconSize.MENU)
        else:
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
        return img

    def _menu_item(self, label="", icon=None, function=None, key=None, value=None):
        """Create MenuItem with given arguments

        Args:
            label (str, optional): label. Defaults to "".
            icon (str, optional): icon name/path. Defaults to None.
            function (obj, optional): function to call when clicked. Defaults to None.
            argument (str, optional): function argument. Defaults to None.

        Returns:
            Gtk.MenuItem: menu item for Gtk.Menu
        """
        item = Gtk.MenuItem.new()
        item_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 6)

        if icon:
            item_box.pack_start(self._get_image(icon=icon), False, False, 0)
        if label:
            item_box.pack_start(Gtk.Label.new(label), False, False, 0)

        item.add(item_box)

        if function and key:
            item.connect('activate', lambda * a: function(key, value))
        elif function:
            item.connect('activate', lambda * a: function())
        return item

    def _build_menu(self):
        """Build menu for the tray icon.

        Returns:
            Gtk.Menu: indicator menu
        """
        menu = Gtk.Menu()

        # Kink menu
        item_kink = Gtk.MenuItem.new_with_label(APP_NAME)
        sub_menu_kink = Gtk.Menu()
        site = self.key_value('site')
        sub_menu_kink.append(self._menu_item(label=site[site.rfind('/') + 1:],
                                             function=self.show_site))
        sub_menu_kink.append(self._menu_item(label=_('Playlist'),
                                             function=self.show_log))
        item_kink.set_submenu(sub_menu_kink)
        menu.append(item_kink)

        # Settings
        menu.append(Gtk.SeparatorMenuItem())
        item_settings = Gtk.MenuItem.new_with_label(_('Settings'))
        sub_menu_settings = Gtk.Menu()
        select_icon = ""
        new_notification_value = 10
        if str_int(self.key_value('notification_timeout')) > 0:
            select_icon = MenuIcons.SELECT.value
            new_notification_value = 0
        sub_menu_settings.append(self._menu_item(label=_("Show what's playing"),
                                                 icon=select_icon,
                                                 function=self.save_key,
                                                 key='notification_timeout',
                                                 value=new_notification_value))

        select_icon = MenuIcons.SELECT.value if str_bool(self.key_value('autoplay')) else ''
        sub_menu_settings.append(self._menu_item(label=_("Autoplay when starting"),
                                                 icon=select_icon,
                                                 function=self.save_key,
                                                 key='autoplay',
                                                 value=str(not str_bool(self.key_value('autoplay')))
                                                       .lower()))

        select_icon = MenuIcons.SELECT.value if str_bool(self.key_value('autostart')) else ''
        sub_menu_settings.append(self._menu_item(label=_("Autostart after login"),
                                                 icon=select_icon,
                                                 function=self.save_key,
                                                 key='autostart',
                                                 value=str(not str_bool(self.key_value('autostart')))
                                                       .lower()))

        item_settings.set_submenu(sub_menu_settings)
        menu.append(item_settings)

        # Stations
        item_stations = Gtk.MenuItem.new_with_label(_('Stations'))
        stations = self.get_stations()
        if stations:
            sub_menu_stations = Gtk.Menu()
            for station in stations:
                select_icon = ""
                if station == self.key_value('station'):
                    select_icon = MenuIcons.SELECT.value
                sub_menu_stations.append(self._menu_item(label=station,
                                                         icon=select_icon,
                                                         function=self.switch_station,
                                                         key='station',
                                                         value=station))
            item_stations.set_submenu(sub_menu_stations)
        menu.append(item_stations)

        # Now playing menu
        item_now_playing = self._menu_item(label=_('Now playing'),
                                           function=self.show_current)
        menu.append(item_now_playing)

        # Play and Stop menus
        menu.append(Gtk.SeparatorMenuItem())
        item_play = self._menu_item(label=_('Play'),
                                            icon=MenuIcons.PLAY.value,
                                            function=self.play_kink)
        menu.append(item_play)
        item_stop = self._menu_item(label=_('Stop'),
                                            icon=MenuIcons.STOP.value,
                                            function=self.stop_kink)
        menu.append(item_stop)

        # Quit menu
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(self._menu_item(label=_('Quit'),
                                    function=self.quit))

        # Decide what can be used
        item_now_playing.set_sensitive(True)
        item_stations.set_sensitive(True)
        item_play.set_sensitive(True)
        item_stop.set_sensitive(True)
        if not self._is_connected():
            item_now_playing.set_sensitive(False)
            item_stations.set_sensitive(False)
            item_play.set_sensitive(False)
            item_stop.set_sensitive(False)

        if self.list_player.is_playing():
            item_play.set_sensitive(False)
        else:
            item_stop.set_sensitive(False)

        # Show the menu and return the menu object
        menu.show_all()
        return menu

    def show_current(self, widget=None):
        """ Show last played song. """
        self.show_song_info()

    def show_site(self, widget=None):
        """ Show site in default browser """
        subprocess.call(['xdg-open', self.key_value('site')])

    def show_log(self, widget=None):
        """ Show site in default browser """
        subprocess.call(['xdg-open', self.playlist])

    # ===============================================
    # General functions
    # ===============================================

    def quit(self, widget=None):
        """ Quit the application. """
        self.check_done_event.set()
        self.stop_kink()
        Notify.uninit()
        Gtk.main_quit()

    def read_ini(self, ini_path):
        """ Read user settings.ini into dictionary. """
        self.conf_parser.read(ini_path)
        return dict(self.conf_parser.items('kink'))
        #return {s:dict(self.conf_parser.items(s)) for
        #        s in self.conf_parser.sections()}

    def key_value(self, key):
        """Get key value from settings.ini and append to file if missing.

        Args:
            key (str): settings key.
            create_missing (bool): create key with default value if missing
            
        Returns:
            str: value of the key
        """
        try:
            value = self.kink_dict[key]
        except KeyError:
            # Get default value for missing key
            value = self.kink_dict_default[key]

            # Append key to settings.ini
            with open(file=self.settings, mode='a', encoding='utf-8') as settings_ini:
                settings_ini.write(f"\n{key} = {value}\n")

            # Reload the dictionary
            self.kink_dict = self.read_ini(self.settings)

            # Rebuild the menu
            self.indicator.set_menu(self._build_menu())
        return value

    def save_key(self, key, value):
        ''' Save settings.ini '''
        if 'kink' not in self.conf_parser.sections():
            self.conf_parser.add_section('kink')

        # Make sure value is a string
        self.conf_parser.set('kink', key, str(value))

        # Save the current config object to file
        with open(file=self.settings, mode='w', encoding='utf-8') as settings_ini:
            self.conf_parser.write(settings_ini)

        # Reload the dictionary
        self.kink_dict = self.read_ini(self.settings)

        # Rebuild the menu
        self.indicator.set_menu(self._build_menu())

        # Check if autostart is set
        self.check_autostart()

    def check_autostart(self):
        """ Check if configured for autostart """
        autostart = join(self.home, f".config/autostart/{APP_ID}-autostart.desktop")
        if str_bool(self.key_value('autostart')):
            if not exists(autostart):
                copyfile(join(self.scriptdir, f"{APP_ID}-autostart.desktop"), autostart)
        else:
            if exists(autostart):
                os.remove(autostart)

    def show_notification(self, summary, body=None, thumb=None):
        """Show the notification.

        Args:
            summary (str): notification summary.
            body (str, optional): notification body text. Defaults to None.
            thumb (str, optional): icon path. Defaults to None.
        """
        notification = Notify.Notification.new(summary, body, thumb)
        notification.set_timeout(str_int(self.key_value('notification_timeout')) * 1000)
        notification.set_urgency(Notify.Urgency.LOW)
        notification.show()

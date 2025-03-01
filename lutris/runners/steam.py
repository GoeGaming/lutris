import os
import time
import subprocess
from lutris.runners.runner import Runner
from lutris.gui.dialogs import NoticeDialog
from lutris.thread import LutrisThread
from lutris.util.log import logger
from lutris.util import system
from lutris.util.steam import (get_path_from_appmanifest, read_config,
                               get_default_acf, to_vdf)


def shutdown():
    """Cleanly quit Steam"""
    logger.debug("Shutting down Steam")
    if is_running():
        subprocess.call(['steam', '-shutdown'])


def get_steam_pid():
    """Return pid of Steam process"""
    return system.get_pid('steam$')


def kill():
    """Force quit Steam"""
    system.kill_pid(get_steam_pid())


def is_running():
    """Checks if Steam is running"""
    return bool(get_steam_pid())


class steam(Runner):
    """ Runs Steam for Linux games """
    human_name = "Steam"
    platform = "Steam for Linux"
    game_options = [
        {
            "option": 'appid',
            'label': "Application ID",
            "type": "string",
            'help': ("The application ID can be retrieved from the game's "
                     "page at steampowered.com. Example: 235320 is the "
                     "app ID for <i>Original War</i> in: \n"
                     "http://store.steampowered.com/app/<b>235320</b>/")
        }
    ]
    runner_options = [
        {
            'option': 'quit_steam_on_exit',
            'label': "Stop Steam after game exits",
            'type': 'bool',
            'default': False,
            'help': ("Quit Steam after the game has quit\n"
                     "(only if it was started by Lutris)")
        }
    ]
    system_options_override = [
        {
            'option': 'disable_runtime',
            'default': True,
        }
    ]

    def __init__(self, config=None):
        super(steam, self).__init__(config)
        self.own_game_remove_method = "Remove game data (through Steam)"
        self.no_game_remove_warning = True
        self.original_steampid = None

    @property
    def browse_dir(self):
        """Return the path to open with the Browse Files action."""
        if not self.is_installed():
            installed = self.install_dialog()
            if not installed:
                return False
        return self.game_path

    @property
    def steam_config(self):
        """Return the "Steam" part of Steam's config.vdf as a dict"""
        if not self.steam_data_dir:
            return
        return read_config(self.steam_data_dir)

    @property
    def game_path(self):
        appid = self.game_config.get('appid')
        for apps_path in self.get_steamapps_dirs():
            game_path = get_path_from_appmanifest(apps_path, appid)
            if game_path:
                return game_path
        logger.warning("Data path for SteamApp %s not found.", appid)

    @property
    def steam_exe(self):
        """Return Steam exe's path"""
        return 'steam'

    @property
    def steam_data_dir(self):
        """Return dir where Steam files lie"""
        candidates = (
            "~/.local/share/Steam/",
            "~/.local/share/steam/",
            "~/.steam/",
            "~/.Steam/",
        )
        for candidate in candidates:
            path = os.path.expanduser(candidate)
            if os.path.exists(path):
                return path

    def get_game_path_from_appid(self, appid):
        """Return the game directory"""
        for apps_path in self.get_steamapps_dirs():
            game_path = get_path_from_appmanifest(apps_path, appid)
            if game_path:
                return game_path
        logger.warning("Data path for SteamApp %s not found.", appid)

    def get_steamapps_dirs(self):
        """Return a list of the Steam library main + custom folders."""
        dirs = []
        # Main steamapps dir
        if self.steam_data_dir:
            main_dir = os.path.join(self.steam_data_dir, 'SteamApps')
            main_dir = system.fix_path_case(main_dir)
            if main_dir:
                dirs.append(main_dir)
        # Custom dirs
        steam_config = self.steam_config
        if steam_config:
            i = 1
            while ('BaseInstallFolder_%s' % i) in steam_config:
                path = steam_config['BaseInstallFolder_%s' % i] + '/SteamApps'
                path = system.fix_path_case(path)
                if path:
                    dirs.append(path)
                i += 1
        return dirs

    def install(self):
        message = "Steam for Linux installation is not handled by Lutris.\n" \
            "Please go to " \
            "<a href='http://steampowered.com'>http://steampowered.com</a>" \
            " or install Steam with the package provided by your distribution."
        NoticeDialog(message)

    def is_installed(self):
        return bool(system.find_executable(self.steam_exe))

    def install_game(self, appid):
        logger.debug("Installing steam game %s", appid)
        acf_data = get_default_acf(appid, appid)
        acf_content = to_vdf(acf_data)
        steamapps_dirs = self.get_steamapps_dirs()
        acf_path = os.path.join(steamapps_dirs[0], "appmanifest_%s.acf" % appid)
        with open(acf_path, "w") as acf_file:
            acf_file.write(acf_content)
        if is_running():
            shutdown()
            time.sleep(5)
        else:
            logger.debug("Steam not running")
        subprocess.Popen(["steam", "steam://preload/%s" % appid])

    def prelaunch(self):
        from lutris.runners import winesteam
        if winesteam.is_running():
            if winesteam.is_running():
                logger.info("Steam does not shutdown, killing it...")
                winesteam.kill()
                time.sleep(2)
                if winesteam.is_running():
                    logger.error("Failed to shutdown Steam for Windows :(")
                    return False
        else:
            logger.debug("winesteam not running")
        return True

    def play(self):

        # Get current steam pid to act as the root pid instead of lutris
        self.original_steampid = get_steam_pid()
        appid = self.game_config.get('appid')
        return {
            'command': [self.steam_exe, 'steam://rungameid/%s' % appid],
            'rootpid': self.original_steampid
        }

    def stop(self):
        if self.runner_config.get('quit_steam_on_exit') \
           and not self.original_steampid:
            shutdown()

    def remove_game_data(self, **kwargs):
        if not self.is_installed():
            installed = self.install_dialog()
            if not installed:
                return False
        appid = self.game_config.get('appid')
        logger.debug("Launching Wine Steam uninstall of game %s" % appid)
        command = [self.steam_exe, 'steam://uninstall/%s' % appid]
        thread = LutrisThread(command, runner=self)
        thread.start()
